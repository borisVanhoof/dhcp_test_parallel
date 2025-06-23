import threading
import subprocess
import datetime
import queue

"""
Separation of concerns:
- what command to run (local, netns, qemu, remote setup) belongs to fixture/test
- how to log and track it belongs here

By design:
- keep the class simple and flat to not confuse the c-developers (including myself)
- Liskov substitution principle (LSP) should be followed for classes derived from Orchestrator
"""

class ProcessHandle:
    """ For LSP
    """
    def __init__(self, wait_fn, terminate_fn=None, kill_fn=None):
        self.wait = wait_fn
        self.terminate = terminate_fn or (lambda: None)
        self.kill = kill_fn or (lambda: None)
        self.stdout = []
        self.stderr = []

class Orchestrator:
    def __init__(self):
        self.handles = []
        self.queue = queue.Queue()
        self._log_thread = threading.Thread(target=self._log_consumer, daemon=True)
        self._log_thread.start()

    def register(self, handle):
        self.handles.append(handle)
        return handle

    def _log_consumer(self):
        while True:
            line = self.queue.get()
            if line is None:
                break
            print(line)

    def log_line(self, label, line):
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.queue.put(f"{ts} [{label}] {line.rstrip()}")

    def stop(self):
        self.queue.put(None)
        self._log_thread.join(timeout=2)

    def terminate_all(self):
        for handle in self.handles:
            try:
                handle.terminate()
                handle.wait(timeout=3)
            except Exception:
                handle.kill()

class SubprocessOrchestrator(Orchestrator):
    def start(self, cmd, label):
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        handle = ProcessHandle(
            wait_fn=lambda timeout=None: proc.wait(timeout=timeout),
            terminate_fn=proc.terminate,
            kill_fn=proc.kill
        )

        def stream(pipe, stream_label, store):
            for line in iter(pipe.readline, ''):
                store.append(line)
                self.log_line(stream_label, line)

        threading.Thread(target=stream, args=(proc.stdout, f"{label}-out", handle.stdout), daemon=True).start()
        threading.Thread(target=stream, args=(proc.stderr, f"{label}-err", handle.stderr), daemon=True).start()

        return self.register(handle)
    
class SSHOrchestrator(Orchestrator):
    """
    how the connection is created is not of this class' concern, an example:
        import paramiko
    
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect("10.0.0.42", username="root", key_filename="~/.ssh/id_rsa")
    
        orch = SSHOrchestrator(ssh)
    """
    def __init__(self, ssh_client):
        super().__init__()
        self.ssh = ssh_client

    def start(self, cmd, label):
        stdin, stdout, stderr = self.ssh.exec_command(" ".join(cmd))

        # Paramiko has no wait, so simulate it
        channel = stdout.channel
        handle = ProcessHandle(
            wait_fn=lambda timeout=None: channel.recv_exit_status(),
            terminate_fn=channel.close,
            kill_fn=channel.close
        )

        def stream(stream_obj, stream_label, store):
            for line in iter(stream_obj.readline, ''):
                store.append(line)
                self.log_line(stream_label, line)

        threading.Thread(target=stream, args=(stdout, f"{label}-out", handle.stdout), daemon=True).start()
        threading.Thread(target=stream, args=(stderr, f"{label}-err", handle.stderr), daemon=True).start()

        return self.register(handle)