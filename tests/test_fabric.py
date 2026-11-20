import json
import subprocess
import time
import pytest

SWITCHES = ["spine1", "spine2", "leaf1", "leaf2", "leaf3"]

def run_vtysh_json(node: str, command: str) -> dict:
    """Execute a vtysh JSON command inside a Containerlab FRR container."""
    container = f"clab-clos-fabric-{node}"
    cmd = ["docker", "exec", container, "vtysh", "-c", f"{command} json"]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)

def test_all_bgp_sessions_established():
    """Verify every configured eBGP neighbor across the fabric is Established."""
    for node in SWITCHES:
        bgp_data = run_vtysh_json(node, "show bgp ipv4 unicast summary")
        peers = bgp_data.get("ipv4Unicast", {}).get("peers", {})
        assert len(peers) >= 2, f"{node} has fewer peers than expected"
        for peer_ip, attrs in peers.items():
            state = attrs.get("state")
            assert state == "Established", f"{node} peer {peer_ip} is in state {state}"

def test_leaf_ecmp_multipath_to_remote_hosts():
    """Verify leaf1 installs 2 Equal-Cost Multi-Path (ECMP) routes to host3 subnet."""
    routes = run_vtysh_json("leaf1", "show ip route 192.168.30.0/24")
    prefix_entries = routes.get("192.168.30.0/24", [])
    assert len(prefix_entries) > 0, "Route 192.168.30.0/24 missing on leaf1"
    nexthops = [nh for nh in prefix_entries[0].get("nexthops", []) if nh.get("active")]
    assert len(nexthops) == 2, f"Expected 2 active ECMP next-hops on leaf1, found {len(nexthops)}"

def test_link_failure_and_bfd_failover():
    """Simulate a link failure on spine1:eth1 and verify host1 can still reach host3."""
    # 1. Cut link between spine1 and leaf1
    subprocess.run(
        ["docker", "exec", "clab-clos-fabric-spine1", "ip", "link", "set", "eth1", "down"],
        check=True
    )
    try:
        # Allow BFD / BGP fast convergence
        time.sleep(2)
        # 2. Verify host1 (192.168.10.10) can still ping host3 (192.168.30.10) via spine2
        ping = subprocess.run(
            ["docker", "exec", "clab-clos-fabric-host1", "ping", "-c", "3", "-W", "1", "192.168.30.10"],
            capture_output=True, text=True
        )
        assert ping.returncode == 0, "Host1 lost connectivity to Host3 during spine1 link failure!"
    finally:
        # 3. Restore link and wait for recovery
        subprocess.run(
            ["docker", "exec", "clab-clos-fabric-spine1", "ip", "link", "set", "eth1", "up"],
            check=True
        )
        time.sleep(5)