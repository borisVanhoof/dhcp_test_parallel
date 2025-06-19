import subprocess
import threading
import time
import uuid
import pytest
import os
import queue

def log_consumer(log_queue):
    while True:
        entry = log_queue.get()
        if entry is None:
            break
        print(entry)

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

def start_dhcp_log_stream(ns_name, iface, label="tshark"):
    """
    Runs tshark in a network namespace and streams DHCP packet summaries.
    Returns the subprocess and a background thread.
    """
    cmd = [
        "sudo", "ip", "netns", "exec", ns_name,
        "tshark", "-i", iface,
        "-l",
        "-f", "udp port 67 or udp port 68"
    ]
    return start_logged_process(cmd, label)

@pytest.fixture
def dhcp_test_env():
    ns_id = uuid.uuid4().hex[:8]
    ns_server = f"ns_srv_{ns_id}"
    ns_client = f"ns_cli_{ns_id}"
    veth0 = f"veth_{ns_id[:4]}"
    veth1 = f"veth_{ns_id[4:]}"
    server_ip = "10.0.0.1"
    offered_ip = "10.0.0.100"

    log_queue = queue.Queue()
    log_thread = threading.Thread(target=log_consumer, args=(log_queue,), daemon=True)
    log_thread.start()

    # Setup veth and namespaces
    subprocess.run(f"sudo ip link add {veth0} type veth peer name {veth1}", shell=True, check=True)
    subprocess.run(f"sudo ip netns add {ns_server}", shell=True, check=True)
    subprocess.run(f"sudo ip netns add {ns_client}", shell=True, check=True)
    subprocess.run(f"sudo ip link set {veth0} netns {ns_server}", shell=True, check=True)
    subprocess.run(f"sudo ip link set {veth1} netns {ns_client}", shell=True, check=True)
    subprocess.run(f"sudo ip netns exec {ns_server} ip addr add {server_ip}/24 dev {veth0}", shell=True, check=True)
    subprocess.run(f"sudo ip netns exec {ns_server} ip link set {veth0} up", shell=True, check=True)
    subprocess.run(f"sudo ip netns exec {ns_client} ip link set {veth1} up", shell=True, check=True)

    # Start tshark logger
    tshark_proc, tshark_out, tshark_err = start_dhcp_log_stream(ns_client, veth1)

    time.sleep(1)  # Let tshark warm up

    yield ns_server, ns_client, veth0, veth1, server_ip, offered_ip

    # Teardown

    time.sleep(1)

    tshark_proc.terminate()
    try:
        tshark_proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        tshark_proc.kill()

    subprocess.run(f"sudo ip netns del {ns_server}", shell=True, stderr=subprocess.DEVNULL)
    subprocess.run(f"sudo ip netns del {ns_client}", shell=True, stderr=subprocess.DEVNULL)
    subprocess.run(f"sudo ip link del {veth0}", shell=True, stderr=subprocess.DEVNULL)

    log_queue.put(None)   # 🔚 sentinel to stop consumer
    log_thread.join()

def test_dhcp_dora(dhcp_test_env):
    ns_server, ns_client, veth0, veth1, server_ip, offered_ip = dhcp_test_env

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
