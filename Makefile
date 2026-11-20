.PHONY: up provision test down

up:
	sudo containerlab deploy -t topology.clab.yml

provision:
	ansible-playbook -i inventory/hosts.yml playbooks/deploy_fabric.yml

test:
	pytest -v tests/test_fabric.py

down:
	sudo containerlab destroy -t topology.clab.yml --cleanup