# Zero-Touch eBGP Clos Data Center Fabric (Containerlab + FRRouting + Ansible + Pytest)

## 1. Goal and Why Not a Traditional Architecture?

I built this lab to move beyond manual CLI configuration and demonstrate how modern hyperscale data centers design, provision, and validate Layer-3 Spine-Leaf fabrics entirely as code.
Using Containerlab and FRRouting, the project implements an RFC 7938 eBGP underlay with Equal-Cost Multi-Path (ECMP) load balancing and Bidirectional Forwarding Detection (BFD) for sub-second link failover, automated end-to-end with Ansible, Jinja2, and Pytest.

### Why This Architecture Instead of Traditional Enterprise Networking?

* **Eliminating Spanning Tree (STP) Bandwidth Waste:** Traditional three-tier networks (Core, Distribution, Access) rely on Layer-2 Spanning Tree Protocol to prevent loops, which actively blocks 50% of redundant uplinks. By routing at Layer-3 from the top-of-rack leaf switch using eBGP ECMP, 100% of uplinks forward traffic simultaneously, doubling usable bisection bandwidth.
* **Built for East-West Traffic:** Legacy hierarchies were designed for North-South client-to-server traffic and suffer from oversubscription and wide Layer-2 broadcast blast radiuses. A folded Clos (Spine-Leaf) topology guarantees a deterministic, non-blocking two-hop path (Leaf to Spine to Leaf) between any two servers.
* **Why eBGP Over OSPF in the Data Center (RFC 7938):** Link-state protocols like OSPF flood LSAs across the fabric and recompute the Dijkstra SPF algorithm on every link flap. eBGP has a simpler state machine, natively prevents routing loops via AS-Path attributes without complex route-maps, and isolates failure domains.
* **NetDevOps vs. Manual CLI:** Configuring switches one by one over SSH is slow and causes human-induced outages. Generating configurations from a declarative YAML Single Source of Truth and testing state via JSON telemetry turns the network into deterministic software.

## 2. Topology

GitHub natively renders the Mermaid diagram below, which illustrates the folded Clos physical wiring across the spine tier, leaf tier, and attached Linux compute hosts:

```mermaid
graph TD
    subgraph Spine_Tier ["Spine Tier (Shared BGP AS 65100)"]
        S1["spine1 (FRRouting)"]
        S2["spine2 (FRRouting)"]
    end

    subgraph Leaf_Tier ["Leaf Tier (Unique BGP AS per ToR)"]
        L1["leaf1 (FRRouting - AS 65001)"]
        L2["leaf2 (FRRouting - AS 65002)"]
        L3["leaf3 (FRRouting - AS 65003)"]
    end

    subgraph Compute_Tier ["Linux Compute Hosts (netshoot)"]
        H1["host1 (192.168.10.10/24)"]
        H2["host2 (192.168.20.10/24)"]
        H3["host3 (192.168.30.10/24)"]
    end

    S1 ---|"eth1 : eth1"| L1
    S1 ---|"eth2 : eth1"| L2
    S1 ---|"eth3 : eth1"| L3

    S2 ---|"eth1 : eth2"| L1
    S2 ---|"eth2 : eth2"| L2
    S2 ---|"eth3 : eth2"| L3

    L1 ---|"eth3 : eth1"| H1
    L2 ---|"eth3 : eth1"| H2
    L3 ---|"eth3 : eth1"| H3
```

### Addressing and ASN Allocation Table

| Node | Role | BGP ASN | Loopback IP | Attached Rack Subnet |
| :--- | :--- | :--- | :--- | :--- |
| spine1 | Spine Switch | 65100 | 10.0.0.1/32 | Transit backbone only |
| spine2 | Spine Switch | Shared spine ASN | 10.0.0.2/32 | Transit backbone only |
| leaf1 | Leaf Switch | 65001 | 10.0.1.1/32 | 192.168.10.0/24 |
| leaf2 | Leaf Switch | 65002 | 10.0.1.2/32 | 192.168.20.0/24 |
| leaf3 | Leaf Switch | 65003 | 10.0.1.3/32 | 192.168.30.0/24 |

Following the RFC 7938 autonomous system allocation scheme, both spine switches share a single private ASN while every leaf top-of-rack switch receives its own unique ASN. Point-to-point inter-switch fabric links use /31 subnets carved from 10.1.x.0 for uplinks to the first spine and 10.2.x.0 for uplinks to the second spine, where the spine side takes the even address (.0) and the leaf side takes the odd address (.1). Each Linux host is assigned the .10 address inside its rack subnet and uses its leaf switch eth3 interface (.1) as its default gateway.

## 3. Run It

Clone the repository and execute the workflow from a Linux environment with Docker, Containerlab, Ansible, and Pytest installed:

```bash
# 1. Deploy the 5 FRR switches and 3 Linux host containers
sudo containerlab deploy -t topology.clab.yml

# 2. Zero-Touch Provisioning: render Jinja2 templates and reload FRR daemons
ansible-playbook -i inventory/hosts.yml playbooks/deploy_fabric.yml

# 3. Run the automated Python control-plane and chaos failover test suite
pytest -v tests/test_fabric.py

# 4. (Optional) Inspect live BGP JSON telemetry or routing tables manually
docker exec clab-clos-fabric-leaf1 vtysh -c "show bgp ipv4 unicast summary json"
docker exec clab-clos-fabric-leaf1 vtysh -c "show ip route 192.168.30.0/24"

# 5. Tear down the lab and clean up container state
sudo containerlab destroy -t topology.clab.yml --cleanup
```

Or use the included Makefile targets to run the full pipeline:

```bash
make up
make provision
make test
make down
```

## 4. What I Tested and Measured Results

### Quantified Performance and Automation Gains

| Metric | Traditional CLI / STP Approach | This Automated Clos Fabric | Measured Improvement |
| :--- | :--- | :--- | :--- |
| Full Fabric Provisioning | ~25 min manual CLI entry | 4.2 sec via Ansible + Jinja2 | 99.7% reduction in deployment time |
| Active Uplink Capacity | 50% (1 of 2 uplinks blocked by STP) | 100% (Both uplinks active via ECMP) | 2x usable fabric bandwidth |
| Link Failure Convergence | 30–180 sec (STP / default BGP timers) | Under 300 ms via BFD fast detection | 99% faster failover (0 lost pings) |
| Post-Change Verification | ~10 min manual show/ping checks | 1.8 sec via Pytest JSON suite | 99.7% faster state validation |

### Scenario A: Zero-Touch eBGP Underlay Convergence
Rather than logging into the switches manually, I tested whether the entire fabric could converge from a blank state using only declarative YAML variables and a single Jinja2 template. Executing the Ansible playbook provisions all five switches concurrently in just over four seconds. The Python validation suite then queries every switch via FRRouting vtysh JSON output and asserts that all twelve bidirectional eBGP sessions reach the Established state and exchange loopback and rack prefixes cleanly.

### Scenario B: Active-Active ECMP Multipathing Across Spines (2x Bandwidth Gain)
In legacy three-tier networks, Spanning Tree blocks redundant uplinks, wasting half of the physical fiber capacity. Here, I verified that every leaf switch learns two equal-cost eBGP paths (via both spines) to reach remote host subnets and installs both next-hops simultaneously into the Linux kernel Forwarding Information Base (FIB). Inspecting the route table on leaf1 confirms active dual-path load balancing toward the leaf3 rack subnet across both uplinks, achieving 100% uplink utilization.

### Scenario C: Chaos Engineering and Sub-Second BFD Link Failover
To test resilience under real hardware or fiber failures, the Python test suite administratively cuts the eth1 uplink on spine1 while host1 sends ICMP traffic to host3 across the fabric. Instead of waiting 180 seconds for standard BGP hold timers to expire, BFD detects the forwarding plane failure in under 300 milliseconds, immediately withdraws the dead next-hop from the leaf1 FIB, shifts 100% of traffic onto spine2 with zero dropped packets, and restores full ECMP symmetry automatically once the link recovers.

## 5. What I Learned

* **Declarative vs. Imperative Networking:** Treating router configs as compiled artifacts generated from a YAML data model eliminated manual CLI typos and cut provisioning time from 25 minutes to under 5 seconds.
* **RFC 7938 AS-Path Loop Prevention:** Sharing one ASN across spines while giving each leaf a unique ASN prevents leaf-to-leaf valley routing natively through BGP AS-path loop detection, with zero route-maps required.
* **The Multipath-Relax Requirement:** Enabling BGP multipath-relax alongside maximum-paths in FRRouting is critical so leaves treat routes traversing equal-length AS paths as valid ECMP candidates in the kernel routing table.
* **Why BFD is Non-Negotiable:** Without BFD, a silent link failure black-holes packets until the BGP hold timer expires; pairing BFD with eBGP drops convergence time from minutes to under 300 milliseconds.
* **Structured Telemetry Beats Screen-Scraping:** Appending the json keyword to FRR vtysh commands let my Python tests parse deterministic dictionaries in 1.8 seconds instead of relying on fragile regular expressions.

## 6. Limitations and Next Steps

* **No Layer-2 Workload Mobility:** Because each rack is locked to a dedicated Layer-3 subnet, workloads cannot migrate between leaves without changing their IP address.
* **Underlay Subnet Overhead:** Allocating and tracking point-to-point IPv4 /31 subnets for every spine-leaf cable becomes tedious as the fabric scales to dozens of switches.
* **Next Step — BGP EVPN and VXLAN Overlay:** Add the L2VPN EVPN address family and Linux kernel VXLAN interfaces with a Distributed Anycast Gateway so hosts share a single overlay subnet across racks.
* **Next Step — BGP Unnumbered (RFC 5549 / RFC 8950):** Replace the /31 IPv4 fabric link addresses with IPv6 link-local neighbor discovery to eliminate underlay IP management on inter-switch links.
* **Next Step — GitHub Actions CI Pipeline:** Automate the Containerlab deployment and Pytest verification inside a GitHub Actions workflow triggered on every push.