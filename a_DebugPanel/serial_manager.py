import threading
import time
import serial
import serial.tools.list_ports
from collections import namedtuple

PortInfo = namedtuple('PortInfo', ['device', 'description'])

class SerialWrapper:
    """Wrap pyserial.Serial to provide readall() and write() used by SDK."""
    def __init__(self, ser: serial.Serial):
        self.ser = ser
        self.lock = threading.Lock()

    def readall(self):
        try:
            n = self.ser.in_waiting
            if n and n > 0:
                return self.ser.read(n)
            return b''
        except Exception:
            return b''

    def write(self, data: bytes):
        with self.lock:
            try:
                self.ser.write(data)
            except Exception:
                pass

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass

class PortMonitor:
    """Monitor serial ports and support hotplug callbacks."""
    def __init__(self, poll_interval=1.0):
        self.poll_interval = poll_interval
        self._stop = False
        self._thread = None
        self._callbacks = []
        self._last_ports = set()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop = True
        if self._thread:
            self._thread.join(timeout=0.5)

    def register_callback(self, cb):
        if cb not in self._callbacks:
            self._callbacks.append(cb)

    def _run(self):
        while not self._stop:
            ports = set(p.device for p in serial.tools.list_ports.comports())
            if ports != self._last_ports:
                added = ports - self._last_ports
                removed = self._last_ports - ports
                self._last_ports = ports
                for cb in self._callbacks:
                    try:
                        cb(list(ports), list(added), list(removed))
                    except Exception:
                        pass
            time.sleep(self.poll_interval)

    @staticmethod
    def open_port(device, baudrate=115200, timeout=0.02):
        try:
            ser = serial.Serial(device, baudrate=baudrate, timeout=timeout)
            return SerialWrapper(ser)
        except Exception:
            return None
