import subprocess
import threading
import time
import uuid
import pytest
import os

def stream_output(pipe, label, buffer):
    for line in iter(pipe.readline, ''):
        print(f"[{label}] {line}", end='')
        buffer.append(line)

def start_logged_process(cmd, label):
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    out_buf, err_buf = [], []
    threading.Thread(target=stream_output, args=(proc.stdout, f"{label}-out", out_buf), daemon=True).start()
    threading.Thread(target=stream_output, args=(proc.stderr, f"{label}-err", err_buf), daemon=True).start()
    return proc, out_buf, err_buf

@pytest.fixture
def dhcp_test_env_with_tcpdump():
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

    # Resolve client interface name
    iface_out = subprocess.check_output([
        "sudo", "ip", "netns", "exec", ns_client, "ip", "-o", "link"
    ], text=True)
    iface_name = next(line.split(": ")[1].split("@")[0]
                      for line in iface_out.splitlines() if "veth" in line)

    # Start tcpdump
    pcap_file = f"/tmp/dhcp-test-{ns_id}.pcap"
    tcpdump_proc = subprocess.Popen([
        "sudo", "ip", "netns", "exec", ns_client,
        "tcpdump", "-i", iface_name, "-w", pcap_file, "-n", "-U"
    ])

    time.sleep(1)  # Let tcpdump warm up

    yield ns_server, ns_client, veth0, veth1, server_ip, offered_ip, pcap_file

    time.sleep(1)

    # Teardown
    tcpdump_proc.terminate()
    tcpdump_proc.wait()

    subprocess.run(f"sudo ip netns del {ns_server}", shell=True, stderr=subprocess.DEVNULL)
    subprocess.run(f"sudo ip netns del {ns_client}", shell=True, stderr=subprocess.DEVNULL)
    subprocess.run(f"sudo ip link del {veth0}", shell=True, stderr=subprocess.DEVNULL)

    print(f"🐾 pcap saved to {pcap_file}")

def test_dhcp_dora(dhcp_test_env_with_tcpdump):
    ns_server, ns_client, veth0, veth1, server_ip, offered_ip, pcap_file = dhcp_test_env_with_tcpdump

    print(f"🕵️ Inspect traffic with: sudo tcpdump -r {pcap_file}")

    print("🚀 Starting DHCP server subprocess")
    server_cmd = [
        "sudo", "ip", "netns", "exec", ns_server,
        f"{os.getcwd()}/venv/bin/python", "scripts/dhcp_server.py", veth0, server_ip, offered_ip
    ]
    server_proc, server_out, server_err = start_logged_process(server_cmd, "scapy")

    time.sleep(2)

    print("🔄 Running dhclient...")
    client_cmd = ["sudo", "ip", "netns", "exec", ns_client, "dhclient", "-v", veth1]

    try:
        client_proc, client_out, client_err = start_logged_process(client_cmd, "dhclient")
        client_proc.wait(timeout=15)

        print("📥 dhclient finished, checking output...")
        combined_out = ''.join(client_out + client_err)
        assert "bound to 10.0.0.100" in combined_out

    except subprocess.TimeoutExpired:
        print("⏰ dhclient timed out!")
        raise

    finally:
        server_proc.terminate()
        client_proc.terminate()
        try:
            server_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            server_proc.kill()

        try:
            client_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            client_proc.kill()
