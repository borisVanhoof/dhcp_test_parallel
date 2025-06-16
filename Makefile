VENV := venv
ACTIVATE := source $(VENV)/bin/activate

setup:
	python3 -m venv $(VENV)
	. $(VENV)/bin/activate && pip install -r requirements.txt

system-deps:
	sudo apt-get update && sudo apt-get install -y isc-dhcp-client iproute2

test:
	sudo bash -c "source $(VENV)/bin/activate && pytest -n auto tests/"

clean:
	sudo ip netns list | awk '{print $$1}' | xargs -r -n1 sudo ip netns del
	find . -name "__pycache__" -exec rm -rf {} +

.PHONY: setup system-deps test clean
