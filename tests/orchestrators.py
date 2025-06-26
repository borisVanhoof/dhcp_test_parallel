import subprocess
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime
import paramiko
import socket
import ctypes
import os

class BaseProcessHandle(ABC):
    @abstractmethod
    def wait(self, timeout=None): pass

    @abstractmethod
    def terminate(self): pass

    @abstractmethod
    def kill(self): pass

    @abstractmethod
    def get_stdout(self): pass

    @abstractmethod
    def get_stderr(self): pass

class SubprocessHandle(BaseProcessHandle):
    def __init__(self, proc: subprocess.Popen, label: str):
        self.proc = proc
        self.label = label
        self.stdout_lines = []
        self.stderr_lines = []
        self.stdout_thread = threading.Thread(target=self._stream_output, args=(proc.stdout, "out", self.stdout_lines), daemon=True)
        self.stderr_thread = threading.Thread(target=self._stream_output, args=(proc.stderr, "err", self.stderr_lines), daemon=True)
        self.stdout_thread.start()
        self.stderr_thread.start()

    def _stream_output(self, pipe, stream_type, buffer):
        for line in iter(pipe.readline, ''):
            ts = datetime.utcnow().strftime('%H:%M:%S.%f')[:-3]
            formatted = f"{ts} [{self.label}-{stream_type}] {line.strip()}"
            print(formatted, flush=True)
            buffer.append(formatted)

    def wait(self, timeout=None):
        return self.proc.wait(timeout=timeout)

    def terminate(self):
        self.proc.terminate()

    def kill(self):
        self.proc.kill()

    def get_stdout(self):
        return "\n".join(self.stdout_lines)

    def get_stderr(self):
        return "\n".join(self.stderr_lines)

class SSHHandle(BaseProcessHandle):
    def __init__(self, channel, label: str):
        self.channel = channel
        self.label = label
        self.stdout_lines = []
        self.stderr_lines = []
        self.stdout_thread = threading.Thread(target=self._stream_output, daemon=True)
        self.stdout_thread.start()

    def _stream_output(self):
        while True:
            if self.channel.recv_ready():
                data = self.channel.recv(1024).decode('utf-8')
                for line in data.splitlines():
                    ts = datetime.utcnow().strftime('%H:%M:%S.%f')[:-3]
                    formatted = f"{ts} [{self.label}-out] {line}"
                    print(formatted, flush=True)
                    self.stdout_lines.append(formatted)
            if self.channel.recv_stderr_ready():
                err = self.channel.recv_stderr(1024).decode('utf-8')
                for line in err.splitlines():
                    ts = datetime.utcnow().strftime('%H:%M:%S.%f')[:-3]
                    formatted = f"{ts} [{self.label}-err] {line}"
                    print(formatted, flush=True)
                    self.stderr_lines.append(formatted)
            if self.channel.exit_status_ready():
                break
            time.sleep(0.1)

    def wait(self, timeout=None):
        start = time.time()
        while not self.channel.exit_status_ready():
            if timeout and (time.time() - start) > timeout:
                raise TimeoutError("SSH process timed out")
            time.sleep(0.1)
        return self.channel.recv_exit_status()

    def terminate(self):
        self.channel.close()

    def kill(self):
        self.channel.close()

    def get_stdout(self):
        return "\n".join(self.stdout_lines)

    def get_stderr(self):
        return "\n".join(self.stderr_lines)

class Orchestrator(ABC):
    @abstractmethod
    def start(self, cmd, label): pass

    @abstractmethod
    def terminate_all(self): pass

    @abstractmethod
    def stop(self): pass

class SubprocessOrchestrator(Orchestrator):
    def __init__(self, namespace=None):
        self.namespace = namespace
        self.handles = []

    def start(self, cmd, label):
        if self.namespace:
            cmd = ["sudo", "ip", "netns", "exec", self.namespace] + cmd
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        handle = SubprocessHandle(proc, label)
        self.handles.append(handle)
        return handle

    def terminate_all(self):
        for h in self.handles:
            h.terminate()
        for h in self.handles:
            try:
                h.wait(timeout=3)
            except subprocess.TimeoutExpired:
                h.kill()

    def stop(self):
        pass

class SSHOrchestrator(Orchestrator):
    def __init__(self, hostname, username, port=22, namespace=None):
        self.hostname = hostname
        self.username = username
        self.port = port
        self.namespace = namespace
        self.handles = []
        self.client = self._connect_via_namespace() if namespace else self._connect_direct()

    def _connect_direct(self):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(hostname=self.hostname, port=self.port, username=self.username)
        return client

    def _connect_via_namespace(self):
        ns_path = f"/var/run/netns/{self.namespace}"
        CLONE_NEWNET = 0x40000000
        fd = os.open(ns_path, os.O_RDONLY)
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        if libc.setns(fd, CLONE_NEWNET) != 0:
            errno = ctypes.get_errno()
            raise OSError(errno, os.strerror(errno))

        sock = socket.create_connection((self.hostname, self.port))
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(hostname=self.hostname, port=self.port, username=self.username, sock=sock)
        return client

    def start(self, cmd, label):
        ns_cmd = ' '.join(cmd)  # Do not prefix with ip netns
        stdin, stdout, stderr = self.client.exec_command(ns_cmd)
        channel = stdout.channel
        handle = SSHHandle(channel, label)
        self.handles.append(handle)
        return handle

    def terminate_all(self):
        for h in self.handles:
            h.terminate()

    def stop(self):
        self.client.close()