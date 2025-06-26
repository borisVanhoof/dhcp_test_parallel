import pytest
import subprocess
import os
import uuid
import time
from dataclasses import dataclass
from orchestrators import SubprocessOrchestrator, SSHOrchestrator

def connect_to_qemu():
    """TODO"""

def connect_to_board():
    """TODO"""

import pytest
import subprocess
import uuid
from dataclasses import dataclass

from orchestrators import SubprocessOrchestrator, SSHOrchestrator

@dataclass
class EnvFixture:
    orch_wan: object
    orch_lan: object | None
    iface_wan: str
    iface_lan: str | None
    server_iface: str
    server_ip: str
    client_should_start: bool
    ns_wan: str
    ns_lan: str | None
    ns_dut_wan: str

def pytest_addoption(parser):
    parser.addoption(
        "--env",
        action="store",
        default="subprocess",
        choices=["subprocess", "hardware", "qemu"],
        help="Target environment"
    )

@pytest.fixture
def dhcp_netns(request):
    env_type = request.config.getoption("--env")
    ns_id = uuid.uuid4().hex[:8]

    # WAN veth pair
    veth0 = f"veth_wan_{ns_id[:4]}"
    veth1 = f"veth_wan_{ns_id[4:]}"
    ns_wan = f"ns_wan_{ns_id}"
    ns_dut_wan = f"ns_dut_wan_{ns_id}"

    # LAN veth pair
    veth_l0 = f"veth_lan_{ns_id[:4]}"
    veth_l1 = f"veth_lan_{ns_id[4:]}"
    ns_lan = f"ns_lan_{ns_id}"
    ns_dut_lan = f"ns_dut_lan_{ns_id}"

    server_ip = "10.0.0.1"

    try:
        # WAN namespace setup
        subprocess.run(f"sudo ip link add {veth0} type veth peer name {veth1}", shell=True, check=True)
        subprocess.run(f"sudo ip netns add {ns_wan}", shell=True, check=True)
        subprocess.run(f"sudo ip netns add {ns_dut_wan}", shell=True, check=True)
        subprocess.run(f"sudo ip link set {veth0} netns {ns_wan}", shell=True, check=True)
        subprocess.run(f"sudo ip link set {veth1} netns {ns_dut_wan}", shell=True, check=True)
        subprocess.run(f"sudo ip netns exec {ns_wan} ip addr add {server_ip}/24 dev {veth0}", shell=True, check=True)
        subprocess.run(f"sudo ip netns exec {ns_wan} ip link set {veth0} up", shell=True, check=True)
        subprocess.run(f"sudo ip netns exec {ns_dut_wan} ip link set {veth1} up", shell=True, check=True)

        # LAN namespace setup
        subprocess.run(f"sudo ip link add {veth_l0} type veth peer name {veth_l1}", shell=True, check=True)
        subprocess.run(f"sudo ip netns add {ns_lan}", shell=True, check=True)
        subprocess.run(f"sudo ip netns add {ns_dut_lan}", shell=True, check=True)
        subprocess.run(f"sudo ip link set {veth_l0} netns {ns_lan}", shell=True, check=True)
        subprocess.run(f"sudo ip link set {veth_l1} netns {ns_dut_lan}", shell=True, check=True)
        subprocess.run(f"sudo ip netns exec {ns_lan} ip link set {veth_l0} up", shell=True, check=True)
        subprocess.run(f"sudo ip netns exec {ns_dut_lan} ip link set {veth_l1} up", shell=True, check=True)

        yield {
            "ns_wan": ns_wan,
            "ns_lan": ns_lan,
            "ns_dut_wan": ns_dut_wan,
            "ns_dut_lan": ns_dut_lan,
            "veth_wan_host": veth0,
            "veth_wan_dut": veth1,
            "veth_lan_host": veth_l0,
            "veth_lan_dut": veth_l1,
            "server_ip": server_ip,
        }

    finally:
        for ns in ["ns_wan", "ns_lan", "ns_dut_wan", "ns_dut_lan"]:
            subprocess.run(f"sudo ip netns del {ns}_{ns_id}", shell=True, stderr=subprocess.DEVNULL)

@pytest.fixture
def env(request, dhcp_netns):
    env_type = request.config.getoption("--env")
    server_ip = dhcp_netns["server_ip"]

    if env_type == "subprocess":
        orch_wan = SubprocessOrchestrator(namespace=dhcp_netns["ns_wan"])
        orch_lan = SubprocessOrchestrator(namespace=dhcp_netns["ns_lan"])
        client_should_start = True
        iface_wan = dhcp_netns["veth_wan_dut"]
        iface_lan = dhcp_netns["veth_lan_dut"]
        server_iface = dhcp_netns["veth_wan_host"]

    elif env_type in ("hardware", "qemu"):
        ssh = connect_to_board() if env_type == "hardware" else connect_to_qemu()
        orch_wan = SSHOrchestrator(ssh)
        orch_lan = None  # Optionally SSH to another port/IP if split
        client_should_start = False
        iface_wan = "eth0"
        iface_lan = "eth1"
        server_iface = "eth0"

    else:
        pytest.skip(f"Unknown env type: {env_type}")

    fixture = EnvFixture(
        orch_wan=orch_wan,
        orch_lan=orch_lan,
        iface_wan=iface_wan,
        iface_lan=iface_lan,
        server_iface=server_iface,
        server_ip=server_ip,
        client_should_start=client_should_start,
        ns_wan=dhcp_netns["ns_wan"],
        ns_lan=dhcp_netns["ns_lan"],
        ns_dut_wan=dhcp_netns["ns_dut_wan"],
    )

    yield fixture

    time.sleep(1)  # Ensure all logs are flushed

    orch_wan.terminate_all()
    if orch_lan:
        orch_lan.terminate_all()

    orch_wan.stop()
    if orch_lan:
        orch_lan.stop()
