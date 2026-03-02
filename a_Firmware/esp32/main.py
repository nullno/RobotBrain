"""
RobotBrain ESP32 MicroPython 固件
- Wi-Fi + BLE 配网（BLE 名称 ESP32-PROV，UUID 与主控一致）
- UDP(5005) / HTTP(8080) / WebSocket(8765) 控制通道
- I2C IMU 采样（MPU6050/BNO055，可扩展），简单互补滤波占位
- UART 桥接 CH340 舵机板（25 路，同步写）
"""

import uasyncio as asyncio
import ujson as json
import socket
import struct
import time
from machine import UART, Pin, I2C
import machine
from servo_sdk_adapter import ServoSDKBridge

try:
    import network
    import ubinascii
    import os
except Exception:
    network = None
    ubinascii = None
    os = None

try:
    import bluetooth
except Exception:
    bluetooth = None

try:
    import uwebsockets.server as ws_server
except Exception:
    ws_server = None

CONFIG_PATH = "esp32_config.json"
DEVICE_NAME = "robotbrain-esp32"
BLE_NAME = "ESP32-PROV"
UDP_PORT = 5005
HTTP_PORT = 8080
WS_PORT = 8765
UART_ID = 1
UART_BAUD = 115200
UART_TX_PIN = 17
UART_RX_PIN = 16
I2C_SCL_PIN = 22
I2C_SDA_PIN = 21
IMU_ADDR = 0x68
SERVO_MIN = 0
SERVO_MAX = 1000
TELEMETRY_MS = 400

uart = UART(UART_ID, baudrate=UART_BAUD, tx=UART_TX_PIN, rx=UART_RX_PIN, timeout=0)
i2c = I2C(0, scl=Pin(I2C_SCL_PIN), sda=Pin(I2C_SDA_PIN))
servo = ServoSDKBridge(uart, servo_count=25)

state = {
    "imu": {"pitch": 0.0, "roll": 0.0, "yaw": 0.0, "accel": (0, 0, 0), "gyro": (0, 0, 0)},
    "servos": {},
}


# ---------------------------------------------------------------------------
def _adv_payload(name: str) -> bytes:
    try:
        nb = name.encode()
        return struct.pack("BB", len(nb) + 1, 0x09) + nb
    except Exception:
        return b"\x02\x01\x06"


def load_config():
    try:
        if os and CONFIG_PATH in os.listdir("/"):
            with open(CONFIG_PATH, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_config(cfg) -> bool:
    try:
        if os:
            with open(CONFIG_PATH, "w") as f:
                f.write(json.dumps(cfg))
            return True
    except Exception:
        pass
    return False


def clamp(val, lo, hi):
    if val < lo:
        return lo
    if val > hi:
        return hi
    return val


def checksum(servo_id, data_size, cmd_type, param_bytes):
    buf = struct.pack("<BBB", servo_id, data_size, cmd_type) + param_bytes
    s = 0
    for b in buf:
        s += b if isinstance(b, int) else ord(b)
    return (0xFF - (s & 0xFF)) & 0xFF


def pack_frame(servo_id, cmd_type, param_bytes=b""):
    data_size = len(param_bytes) + 2
    cs = checksum(servo_id, data_size, cmd_type, param_bytes)
    return b"\xff\xff" + struct.pack("<BBB", servo_id, data_size, cmd_type) + param_bytes + struct.pack("<B", cs)


def build_sync_param(pairs):
    out = bytearray()
    out.extend(b"\x2A\x04")
    for sid, pos, runtime in pairs:
        out.extend(struct.pack(">BHH", int(sid) & 0xFF, int(pos) & 0xFFFF, int(runtime) & 0xFFFF))
    return bytes(out)


def send_servo_targets(targets, duration_ms):
    safe_targets = {}
    for sid, val in targets.items():
        try:
            sid_i = int(sid)
            pos_i = clamp(int(val), SERVO_MIN, SERVO_MAX)
            safe_targets[sid_i] = pos_i
            state["servos"][sid_i] = pos_i
        except Exception:
            pass
    if not safe_targets:
        return
    servo.set_positions(safe_targets, duration_ms)


def read_mpu6050():
    try:
        i2c.writeto_mem(IMU_ADDR, 0x6B, b"\x00")
        data = i2c.readfrom_mem(IMU_ADDR, 0x3B, 14)

        def to_i16(h, l):
            v = (h << 8) | l
            return v - 65536 if v & 0x8000 else v

        ax = to_i16(data[0], data[1])
        ay = to_i16(data[2], data[3])
        az = to_i16(data[4], data[5])
        gx = to_i16(data[8], data[9])
        gy = to_i16(data[10], data[11])
        gz = to_i16(data[12], data[13])
        state["imu"].update({"accel": (ax, ay, az), "gyro": (gx, gy, gz)})
    except Exception:
        return None
    return state["imu"]


# ---------------------------------------------------------------------------
async def wifi_connect():
    if network is None:
        return
    cfg = load_config()
    sta = network.WLAN(network.STA_IF)
    if not sta.active():
        sta.active(True)
    wifi_cfg = cfg.get("wifi") or {}
    if wifi_cfg.get("ssid"):
        sta.connect(wifi_cfg.get("ssid"), wifi_cfg.get("password"))
        for _ in range(40):
            if sta.isconnected():
                break
            await asyncio.sleep_ms(250)
    if not sta.isconnected():
        ap = network.WLAN(network.AP_IF)
        ap.active(True)
        ap.config(essid=cfg.get("device_name", DEVICE_NAME))


async def http_server():
    async def handle(reader, writer):
        try:
            req_line = await reader.readline()
            if not req_line:
                await writer.wait_closed()
                return
            content_length = 0
            while True:
                line = await reader.readline()
                if line == b"\r\n" or not line:
                    break
                if line.lower().startswith(b"content-length"):
                    try:
                        content_length = int(line.decode().split(":")[1].strip())
                    except Exception:
                        content_length = 0
            body = b""
            if content_length:
                body = await reader.readexactly(content_length)
            try:
                payload = json.loads(body.decode()) if body else {}
            except Exception:
                payload = {}
            path = req_line.decode().split(" ")[1]
            if path == "/provision":
                ssid = payload.get("ssid")
                password = payload.get("password")
                cfg = load_config()
                cfg["wifi"] = {"ssid": ssid, "password": password}
                ok = save_config(cfg)
                resp = {"ok": bool(ok)}
            elif path == "/status":
                resp = telemetry_payload()
            else:
                resp = {"ok": True}
            raw = json.dumps(resp)
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: " + str(len(raw)).encode() + b"\r\n\r\n" + raw.encode())
            await writer.drain()
        except Exception:
            pass
        try:
            await writer.wait_closed()
        except Exception:
            pass

    srv = await asyncio.start_server(handle, "0.0.0.0", HTTP_PORT)
    while True:
        await asyncio.sleep_ms(1000)


def telemetry_payload():
    wifi_ip = None
    wifi_ok = False
    if network:
        try:
            sta = network.WLAN(network.STA_IF)
            wifi_ok = sta.isconnected()
            wifi_ip = sta.ifconfig()[0]
        except Exception:
            pass
    return {
        "type": "telemetry",
        "imu": state.get("imu"),
        "servos": state.get("servos"),
        "wifi": wifi_ip,
        "wifi_ok": wifi_ok,
        "uptime_ms": time.ticks_ms(),
    }


async def udp_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", UDP_PORT))
    sock.setblocking(False)
    while True:
        try:
            data, addr = sock.recvfrom(2048)
        except Exception:
            data = None
        if data:
            try:
                msg = json.loads(data.decode())
                await handle_command(msg, addr, sock)
            except Exception:
                pass
        await asyncio.sleep_ms(10)


async def handle_command(msg, addr, sock=None):
    mtype = msg.get("type") or msg.get("cmd") or "servo_targets"
    if mtype == "discover":
        resp = {"type": "discover_resp", "port": UDP_PORT, "device": DEVICE_NAME}
        if network:
            try:
                sta = network.WLAN(network.STA_IF)
                resp["ip"] = sta.ifconfig()[0]
                if ubinascii:
                    resp["mac"] = ubinascii.hexlify(sta.config("mac")).decode()
            except Exception:
                pass
        if sock:
            sock.sendto(json.dumps(resp).encode(), addr)
    elif mtype in ("servo_targets", "keyframe"):
        targets = msg.get("targets") or {}
        duration = int(msg.get("duration", 300))
        send_servo_targets(targets, duration)
    elif mtype == "torque":
        enable = bool(msg.get("enable", True))
        servo.torque(enable=enable)
    elif mtype == "motion":
        # 占位：根据需要映射动作到关键帧
        pass
    elif mtype == "status":
        if sock:
            sock.sendto(json.dumps(telemetry_payload()).encode(), addr)


async def telemetry_task():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    while True:
        cfg = load_config()
        host = cfg.get("host") or cfg.get("pair")
        if host:
            try:
                sock.sendto(json.dumps(telemetry_payload()).encode(), (host.get("ip"), int(host.get("port", UDP_PORT))))
            except Exception:
                pass
        await asyncio.sleep_ms(TELEMETRY_MS)


async def imu_task():
    while True:
        read_mpu6050()
        await asyncio.sleep_ms(50)


async def ws_task():
    if ws_server is None:
        return

    async def handler(reader, writer):
        ws = await ws_server.serve(reader, writer)
        while True:
            try:
                msg = await ws.recv()
                if msg is None:
                    break
                try:
                    obj = json.loads(msg)
                    await handle_command(obj, None)
                except Exception:
                    pass
            except Exception:
                break
        await ws.close()

    await asyncio.start_server(handler, "0.0.0.0", WS_PORT)
    while True:
        await asyncio.sleep_ms(1000)


def ble_setup():
    if bluetooth is None:
        return None
    ble = bluetooth.BLE()
    ble.active(True)
    SERVICE_UUID = bluetooth.UUID("0000ffaa-0000-1000-8000-00805f9b34fb")
    CHAR_UUID = bluetooth.UUID("0000ffab-0000-1000-8000-00805f9b34fb")
    WIFI_CHAR = (CHAR_UUID, bluetooth.FLAG_WRITE)
    service = (SERVICE_UUID, (WIFI_CHAR,))
    handles = ble.gatts_register_services((service,))
    wifi_handle = handles[0][1][0]

    def on_write(attr_handle, _data):
        if attr_handle != wifi_handle:
            return
        try:
            txt = ble.gatts_read(wifi_handle).decode().strip()
            ssid = ""
            pwd = ""
            if "\n" in txt:
                parts = txt.split("\n", 1)
                ssid, pwd = parts[0], parts[1] if len(parts) > 1 else ""
            else:
                try:
                    payload = json.loads(txt)
                    ssid = payload.get("ssid") or ""
                    pwd = payload.get("password") or ""
                except Exception:
                    pass
            if ssid:
                cfg = load_config()
                cfg["wifi"] = {"ssid": ssid, "password": pwd}
                save_config(cfg)
        except Exception:
            pass

    ble.gatts_set_buffer(wifi_handle, 128, True)
    ble.irq(lambda e, d: on_write(d[1], None) if e == 1 else None)
    adv_name = BLE_NAME or DEVICE_NAME
    ble.gap_advertise(100000, adv_data=_adv_payload(adv_name))
    return ble


async def main():
    await wifi_connect()
    asyncio.create_task(udp_server())
    asyncio.create_task(telemetry_task())
    asyncio.create_task(imu_task())
    asyncio.create_task(ws_task())
    asyncio.create_task(http_server())
    ble_setup()
    while True:
        await asyncio.sleep_ms(1000)


try:
    asyncio.run(main())
finally:
    asyncio.new_event_loop()
