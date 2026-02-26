"""
ESP32 客户端（宿主侧）

提供简单函数将关键帧（targets + duration）发送到 ESP32 固件（UDP）。
"""
import os
import socket
import json
import time

DEFAULT_PORT = 5005

class ESP32Client:
    def __init__(self, host=None, port=None, timeout=0.5):
        self.host = host or os.environ.get('ESP32_HOST')
        self.port = int(port or os.environ.get('ESP32_PORT') or DEFAULT_PORT)
        self.timeout = float(timeout)
        self._sock = None
        if self.host:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.settimeout(self.timeout)

    def set_host(self, host, port=None):
        self.host = host
        if port:
            self.port = int(port)
        if self._sock is None:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.settimeout(self.timeout)

    def send_raw(self, obj: dict, expect_reply: bool=False, reply_timeout: float=None):
        if not self.host or not self._sock:
            return None
        try:
            data = json.dumps(obj).encode('utf-8')
            self._sock.sendto(data, (self.host, int(self.port)))
            if expect_reply:
                old_to = self._sock.gettimeout()
                self._sock.settimeout(reply_timeout or self.timeout)
                try:
                    data, addr = self._sock.recvfrom(4096)
                    return json.loads(data.decode('utf-8'))
                except Exception:
                    return None
                finally:
                    self._sock.settimeout(old_to)
            return True
        except Exception:
            return None

    def send_command(self, cmd_type: str, expect_reply: bool=False, reply_timeout: float=None):
        return self.send_raw({'type': cmd_type}, expect_reply=expect_reply, reply_timeout=reply_timeout)

    def status(self):
        return self.send_raw({'type': 'status'}, expect_reply=True, reply_timeout=1.0)

    def pair(self, host=None, port=None):
        payload = {'type': 'pair'}
        if host:
            payload['host'] = host
        if port:
            payload['port'] = int(port)
        return self.send_raw(payload, expect_reply=True, reply_timeout=2.0)

    def stop(self):
        return self.send_command('stop', expect_reply=True)

    def reboot(self):
        return self.send_command('reboot', expect_reply=True)

    def factory_reset(self):
        return self.send_command('factory_reset', expect_reply=True)

    def send_keyframe(self, targets: dict, duration_ms: int=300):
        """Send targets (dict of id->position) and duration to ESP32."""
        if not self.host or not self._sock:
            return False
        try:
            payload = {'targets': {str(k): int(v) for k, v in (targets or {}).items()}, 'duration': int(duration_ms)}
            data = json.dumps(payload).encode('utf-8')
            self._sock.sendto(data, (self.host, int(self.port)))
            return True
        except Exception:
            return False

    def test_ping(self):
        """Optional ping: send a simple ping message. ESP32 firmware may reply if implemented."""
        if not self.host or not self._sock:
            return False
        try:
            payload = {'ping': True, 'ts': int(time.time())}
            data = json.dumps(payload).encode('utf-8')
            self._sock.sendto(data, (self.host, int(self.port)))
            return True
        except Exception:
            return False

# Convenience module-level client
_client = None

def get_client():
    global _client
    if _client is None:
        _client = ESP32Client()
    return _client

def send_keyframe(targets, duration_ms=300):
    return get_client().send_keyframe(targets, duration_ms)

def set_host(host, port=None):
    get_client().set_host(host, port)

def send_command(cmd_type, expect_reply=False, reply_timeout=None):
    return get_client().send_command(cmd_type, expect_reply=expect_reply, reply_timeout=reply_timeout)

def status():
    return get_client().status()

def pair(host=None, port=None):
    return get_client().pair(host=host, port=port)

def stop():
    return get_client().stop()

def reboot():
    return get_client().reboot()

def factory_reset():
    return get_client().factory_reset()
