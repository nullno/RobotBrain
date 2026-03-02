"""
Lightweight IMU abstraction for PC/mobile side.
- Tries to read pitch/roll/yaw from an I2C IMU (MPU6050/BNO055 style).
- Falls back to simulated data when no hardware is available.
- Provides a complementary filter for smoother attitude output.
"""
import math
import threading
import time
from typing import Tuple, Optional

try:
    from smbus2 import SMBus
except Exception:  # pragma: no cover - optional dependency
    SMBus = None


class IMUService:
    """Simple IMU reader with an optional complementary filter."""

    def __init__(
        self,
        bus_id: int = 1,
        address: int = 0x68,
        simulate: bool = False,
        alpha: float = 0.92,
        sample_hz: float = 50.0,
    ) -> None:
        self.bus_id = bus_id
        self.address = address
        self.alpha = max(0.0, min(1.0, float(alpha)))
        self.sample_hz = max(5.0, float(sample_hz))
        self._simulate = bool(simulate or (SMBus is None))
        self._bus: Optional[SMBus] = None
        self._last_orientation: Tuple[float, float, float] = (0.0, 0.0, 0.0)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._thread = None
        try:
            if self._bus is not None:
                self._bus.close()
        except Exception:
            pass
        self._bus = None

    def get_orientation(self) -> Tuple[float, float, float]:
        with self._lock:
            return tuple(self._last_orientation)

    # ------------------------------------------------------------------
    def _run(self) -> None:
        next_ts = 0.0
        sample_period = 1.0 / self.sample_hz
        while not self._stop.is_set():
            now = time.time()
            if now < next_ts:
                time.sleep(max(0.0, next_ts - now))
                continue
            next_ts = now + sample_period
            try:
                pitch, roll, yaw = self._read_orientation()
                with self._lock:
                    lp, lr, ly = self._last_orientation
                    pitch = self.alpha * lp + (1 - self.alpha) * pitch
                    roll = self.alpha * lr + (1 - self.alpha) * roll
                    yaw = self.alpha * ly + (1 - self.alpha) * yaw
                    self._last_orientation = (pitch, roll, yaw)
            except Exception:
                # Keep last orientation on error
                pass

    def _read_orientation(self) -> Tuple[float, float, float]:
        if self._simulate:
            t = time.time()
            return (
                math.sin(t * 0.6) * 10.0,
                math.sin(t * 0.4) * 8.0,
                math.sin(t * 0.2) * 35.0,
            )

        if self._bus is None:
            self._bus = SMBus(self.bus_id)
            self._init_mpu6050()

        # Minimal MPU6050 read (raw accel for pitch/roll approximation)
        accel_x = self._read_word_2c(0x3B)
        accel_y = self._read_word_2c(0x3D)
        accel_z = self._read_word_2c(0x3F)

        roll = math.degrees(math.atan2(accel_y, accel_z))
        pitch = math.degrees(math.atan2(-accel_x, math.sqrt(accel_y ** 2 + accel_z ** 2)))
        yaw = self._last_orientation[2]
        return pitch, roll, yaw

    # ------------------------------------------------------------------
    def _init_mpu6050(self) -> None:
        # Wake up the MPU6050 (exit sleep mode)
        try:
            self._bus.write_byte_data(self.address, 0x6B, 0)
        except Exception:
            self._simulate = True

    def _read_word_2c(self, reg: int) -> int:
        hi = self._bus.read_byte_data(self.address, reg)
        lo = self._bus.read_byte_data(self.address, reg + 1)
        val = (hi << 8) + lo
        if val >= 0x8000:
            return -((65535 - val) + 1)
        return val


__all__ = ["IMUService"]
