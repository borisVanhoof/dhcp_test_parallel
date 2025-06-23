import time
import uuid
import pytest
import subprocess
import os
from orchestrator import SubprocessOrchestrator

@pytest.fixture
def dhcp_test_env():
    ns_id = uuid.uuid4().hex[:8]
    ns_server = f"ns_srv_{ns_id}"
    ns_client = f"ns_cli_{ns_id}"
    veth0 = f"veth_{ns_id[:4]}"
    veth1 = f"veth_{ns_id[4:]}"
    server_ip = "10.0.0.1"
    offered_ip = "10.0.0.100"

    # Setup veth and namespaces
    subprocess.run(f"sudo ip link add {veth0} type veth peer name {veth1}", shell=True, check=True)
    subprocess.run(f"sudo ip netns add {ns_server}", shell=True, check=True)
    subprocess.run(f"sudo ip netns add {ns_client}", shell=True, check=True)
    subprocess.run(f"sudo ip link set {veth0} netns {ns_server}", shell=True, check=True)
    subprocess.run(f"sudo ip link set {veth1} netns {ns_client}", shell=True, check=True)
    subprocess.run(f"sudo ip netns exec {ns_server} ip addr add {server_ip}/24 dev {veth0}", shell=True, check=True)
    subprocess.run(f"sudo ip netns exec {ns_server} ip link set {veth0} up", shell=True, check=True)
    subprocess.run(f"sudo ip netns exec {ns_client} ip link set {veth1} up", shell=True, check=True)

    orch = SubprocessOrchestrator()

    # Start tshark logger
    tshark_cmd = [
        "sudo", "ip", "netns", "exec", ns_client,
        "tshark", "-i", veth1,
        "-l", "-f", "udp port 67 or 68"
    ]
    orch.start(tshark_cmd, "tshark")

    # Start DHCP server
    dhcp_server_cmd = [
        "sudo", "ip", "netns", "exec", ns_server,
        f"{os.getcwd()}/venv/bin/python", "scripts/dhcp_server.py", veth0, server_ip, offered_ip
    ]
    orch.start(dhcp_server_cmd, "scapy")

    time.sleep(1)  # let them settle

    yield ns_server, ns_client, veth1, orch

    # Clean up all namespace-related resources
    for name in [ns_server, ns_client]:
        subprocess.run(f"sudo ip netns del {name}", shell=True, stderr=subprocess.DEVNULL)
    subprocess.run(f"sudo ip link del {veth0}", shell=True, stderr=subprocess.DEVNULL)

    # Stop orchestrator
    orch.terminate_all()
    orch.stop()

def test_dhcp_dora(dhcp_test_env):
    ns_server, ns_client, veth1, orch = dhcp_test_env

    print("🔄 Running dhclient...")

    client_cmd = ["sudo", "ip", "netns", "exec", ns_client, "dhclient", "-v", veth1]
    handle = orch.start(client_cmd, "dhclient")

    try:
        handle.wait(timeout=15)

        assert "bound to 10.0.0.100" in ''.join(handle.stdout + handle.stderr)
    except subprocess.TimeoutExpired:
        handle.terminate()
        pytest.fail("⏰ dhclient timed out")

    print("✅ dhclient completed")
