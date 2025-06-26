import time
import os

def test_dhcp_dora(env):
    print("🚀 Starting DHCP server on WAN namespace")

    # Start the DHCP server subprocess
    server_cmd = [
        "sudo", "ip", "netns", "exec", env.ns_wan,
        f"{os.getcwd()}/venv/bin/python", "scripts/dhcp_server.py",
        env.server_iface, env.server_ip, "10.0.0.100"
    ]
    env.orch_wan.start(server_cmd, label="dhcp-server")

    print("🧪 Starting packet capture on WAN")
    tshark_cmd = [
        "sudo", "ip", "netns", "exec", env.ns_wan,
        "tshark", "-i", env.server_iface,
        "-l", "-f", "udp port 67 or udp port 68"
    ]
    env.orch_wan.start(tshark_cmd, label="tshark")

    time.sleep(1)  # Let tshark warm up

    if env.client_should_start:
        print("🔄 Starting DHCP client in DUT namespace")

        client_cmd = [
            "sudo", "ip", "netns", "exec", env.ns_dut_wan,
            "dhclient", "-v", env.iface_wan
        ]
        client_proc = env.orch_wan.start(client_cmd, label="dhclient")
        client_proc.wait(timeout=15)

        print("✅ DHCP client completed")
        assert "bound to 10.0.0.100" in ''.join(client_proc.get_stdout() + client_proc.get_stderr())
    else:
        print("🛑 Client should be preconfigured on target (hardware or QEMU)")