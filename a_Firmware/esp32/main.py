"""
ESP32 MicroPython 固件示例
功能：
- UDP 接收关键帧（目标位置和 duration），格式详见 README
- 对关键帧做线性插值（默认 20ms 步长）
- 使用 JOHO 串口总线舵机协议（与主仓库兼容）通过 UART 发送 `sync_set_position` 指令

备注：将 UART TX/RX 引脚与 CH340/舵机驱动板连通（TTL 3.3V）。
"""

import ujson as json
import socket
import struct
import time
from machine import UART, Pin, I2C, reset
import machine
try:
    import network
    import ubinascii
    import os
except Exception:
    network = None
    ubinascii = None
    os = None

# 配置
UDP_PORT = 5005
UART_ID = 1
UART_BAUD = 115200
UART_TX_PIN = 17  # 根据硬件调整
UART_RX_PIN = 16  # 可选
STEP_MS = 20      # 插值步长（ms）
BROADCAST_ID = 0xFE
CMD_SYNC_WRITE = 0x83
HEADER = b'\xff\xff'

# 初始化 UART
uart = UART(UART_ID, baudrate=UART_BAUD, tx=UART_TX_PIN, rx=UART_RX_PIN, timeout=0)

# 配置持久化文件
CONFIG_PATH = 'esp32_config.json'


def load_config():
    try:
        if os is None:
            return {}
        if CONFIG_PATH in os.listdir('/'):
            with open(CONFIG_PATH, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_config(cfg):
    try:
        if os is None:
            return False
        with open(CONFIG_PATH, 'w') as f:
            f.write(json.dumps(cfg))
        return True
    except Exception:
        return False


# IMU 支持（尝试初始化 MPU6050）
imu_available = False
imu_i2c = None
IMU_ADDR = 0x68


def init_imu(scl_pin=22, sda_pin=21):
    global imu_available, imu_i2c
    try:
        imu_i2c = I2C(0, scl=Pin(scl_pin), sda=Pin(sda_pin))
        # wake up
        imu_i2c.writeto_mem(IMU_ADDR, 0x6B, b'\x00')
        imu_available = True
    except Exception:
        imu_available = False


# 运行控制
stop_requested = False


def request_stop():
    global stop_requested
    stop_requested = True


def clear_stop():
    global stop_requested
    stop_requested = False


def read_imu():
    # 返回简单字典: accel{x,y,z}, gyro{x,y,z}
    try:
        if not imu_available:
            return None
        data = imu_i2c.readfrom_mem(IMU_ADDR, 0x3B, 14)
        def to_int16(bh, bl):
            v = (bh << 8) | bl
            if v & 0x8000:
                v = -((v ^ 0xFFFF) + 1)
            return v
        ax = to_int16(data[0], data[1])
        ay = to_int16(data[2], data[3])
        az = to_int16(data[4], data[5])
        gx = to_int16(data[8], data[9])
        gy = to_int16(data[10], data[11])
        gz = to_int16(data[12], data[13])
        return {'accel': {'x': ax, 'y': ay, 'z': az}, 'gyro': {'x': gx, 'y': gy, 'z': gz}}
    except Exception:
        return None



def calc_checksum_request(servo_id, data_size, cmd_type, param_bytes):
    buf = struct.pack('<BBB', servo_id, data_size, cmd_type) + param_bytes
    s = 0
    for b in buf:
        if isinstance(b, int):
            s += b
        else:
            s += ord(b)
    return (0xFF - (s & 0xFF)) & 0xFF


def pack_request(servo_id, cmd_type, param_bytes=b''):
    data_size = len(param_bytes) + 2
    checksum = calc_checksum_request(servo_id, data_size, cmd_type, param_bytes)
    frame = HEADER + struct.pack('<BBB', servo_id, data_size, cmd_type) + param_bytes + struct.pack('<B', checksum)
    return frame


# 构建 sync_write 参数体，格式与主仓库一致：0x2A 0x04 + [sid, pos(H), runtime_ms(H)]*
def build_sync_param(pairs):
    # pairs: list of (sid:int, pos:int, runtime_ms:int)
    out = bytearray()
    out.extend(b'\x2A\x04')
    for sid, pos, runtime in pairs:
        # >BHH
        out.extend(struct.pack('>BHH', int(sid) & 0xFF, int(pos) & 0xFFFF, int(runtime) & 0xFFFF))
    return bytes(out)


# 将一个关键帧（targets dict 与 duration ms）执行插值并发送
def execute_keyframe(targets, duration_ms):
    # targets: {sid: position}
    # duration_ms: integer
    if not targets:
        return
    # 读取当前 positions: 在本示例中我们没有读取回传，假设起点为目标（即时跳转）
    # 为简单起见，起点全部设为当前目标（导致直接执行），实际部署可添加 read-back 支持
    steps = max(1, int(duration_ms) // STEP_MS)
    step_ms = max(1, int(duration_ms) // steps)

    # Convert targets to int positions
    t_targets = {int(k): int(v) for k, v in targets.items()}

    # For simplicity assume current positions equal to targets (no smoothing) if steps == 1
    # If steps > 1, we linearly interpolate from current (assumed same) -> target (effectively single write)
    # To implement real interpolation, firmware should track last_sent positions. We'll maintain a small cache.
    global last_positions
    try:
        lp = last_positions
    except NameError:
        lp = {}

    # Ensure all SIDs present in last_positions
    for sid in t_targets:
        if sid not in lp:
            lp[sid] = t_targets[sid]

    # Interpolate per step
    for step in range(1, steps + 1):
        pairs = []
        for sid, tgt in t_targets.items():
            start = int(lp.get(sid, tgt))
            if steps <= 1:
                cur = tgt
            else:
                cur = int(round(start + (tgt - start) * (step / float(steps))))
            pairs.append((sid, cur, step_ms))
            # update last_positions to last step later
        # 构造 sync_write 帧并发送
        param = build_sync_param(pairs)
        frame = pack_request(BROADCAST_ID, CMD_SYNC_WRITE, param)
        try:
            uart.write(frame)
        except Exception:
            pass
        # 等待下一步
        # 可被 stop_requested 打断
        for _ in range(max(1, int(step_ms // 20))):
            if stop_requested:
                return
            time.sleep_ms(20)

    # 更新缓存为目标
    for sid, tgt in t_targets.items():
        lp[sid] = int(tgt)
    globals()['last_positions'] = lp


# UDP 接收循环（阻塞）
def udp_server():
    ai = socket.getaddrinfo('0.0.0.0', UDP_PORT)[0]
    s = socket.socket(ai[0], socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.setblocking(False)
    except Exception:
        # settimeout fallback
        try:
            s.settimeout(0.2)
        except Exception:
            pass
    s.bind(('0.0.0.0', UDP_PORT))
    print('UDP listen on', UDP_PORT)

    cfg = load_config()
    last_telemetry = time.ticks_ms()
    telemetry_interval = cfg.get('telemetry_interval_ms', 500)
    last_reconnect = time.ticks_ms()
    reconnect_interval = 5000

    # 启动时尝试连接已保存 Wi-Fi
    if network is not None:
        try:
            sta = network.WLAN(network.STA_IF)
            if not sta.active():
                sta.active(True)
            wcfg = cfg.get('wifi')
            if wcfg and isinstance(wcfg, dict):
                ssid = wcfg.get('ssid')
                pwd = wcfg.get('password')
                if ssid:
                    try:
                        sta.connect(ssid, pwd)
                        deadline = time.ticks_add(time.ticks_ms(), 10000)
                        while not sta.isconnected() and time.ticks_diff(deadline, time.ticks_ms()) > 0:
                            time.sleep_ms(200)
                    except Exception:
                        pass
            # 若仍未连接，则启动 AP 以便配网
            if not sta.isconnected():
                try:
                    ap = network.WLAN(network.AP_IF)
                    if not ap.active():
                        ap.active(True)
                        ap.config(essid=cfg.get('device_name', 'esp32-servo-bridge'))
                except Exception:
                    pass
        except Exception:
            pass

    while True:
        # 非阻塞接收
        try:
            data, addr = s.recvfrom(4096)
        except Exception:
            data = None
            addr = None

        if data:
            try:
                msg = data.decode('utf-8')
                obj = json.loads(msg)
            except Exception:
                obj = None
            if obj:
                # 支持多种消息类型：discover, provision, ping, pair, keyframe
                mtype = obj.get('type') or obj.get('cmd') or 'keyframe'
                if mtype in ('discover', 'probe'):
                    resp = {'type': 'discover_resp', 'device': 'esp32', 'port': UDP_PORT}
                    if network is not None:
                        try:
                            sta = network.WLAN(network.STA_IF)
                            resp['ip'] = sta.ifconfig()[0] if sta.active() else '0.0.0.0'
                            if ubinascii is not None:
                                try:
                                    resp['mac'] = ubinascii.hexlify(sta.config('mac')).decode()
                                except Exception:
                                    pass
                        except Exception:
                            pass
                    try:
                        s.sendto(json.dumps(resp).encode('utf-8'), addr)
                    except Exception:
                        pass
                elif mtype == 'ping':
                    try:
                        s.sendto(json.dumps({'type': 'pong'}).encode('utf-8'), addr)
                    except Exception:
                        pass
                elif mtype in ('provision', 'provisioning'):
                    ssid = obj.get('ssid')
                    password = obj.get('password')
                    result = {'type': 'provision_resp', 'ok': False}
                    if network is None:
                        result['error'] = 'network_module_missing'
                    else:
                        try:
                            sta = network.WLAN(network.STA_IF)
                            if not sta.active():
                                sta.active(True)
                            sta.connect(ssid, password)
                            deadline = time.ticks_add(time.ticks_ms(), 12000)
                            while not sta.isconnected() and time.ticks_diff(deadline, time.ticks_ms()) > 0:
                                time.sleep_ms(200)
                            if sta.isconnected():
                                result['ok'] = True
                                result['ip'] = sta.ifconfig()[0]
                                # persist
                                cfg = load_config()
                                cfg['wifi'] = {'ssid': ssid, 'password': password}
                                save_config(cfg)
                            else:
                                result['error'] = 'connect_timeout'
                        except Exception as e:
                            result['error'] = 'exception'
                            try:
                                result['detail'] = str(e)
                            except Exception:
                                pass
                    try:
                        s.sendto(json.dumps(result).encode('utf-8'), addr)
                    except Exception:
                        pass
                elif mtype in ('pair', 'set_host'):
                    # 保存主控信息
                    host = obj.get('host') or addr[0]
                    port = int(obj.get('port', UDP_PORT))
                    cfg = load_config()
                    cfg['host'] = {'ip': host, 'port': port}
                    ok = save_config(cfg)
                    try:
                        s.sendto(json.dumps({'type': 'pair_resp', 'ok': bool(ok)}).encode('utf-8'), addr)
                    except Exception:
                        pass
                elif mtype == 'status':
                    # 返回设备状态
                    resp = {'type': 'status_resp', 'device': cfg.get('device_name', 'esp32')}
                    try:
                        if network is not None:
                            sta = network.WLAN(network.STA_IF)
                            resp['wifi_connected'] = bool(sta.isconnected()) if hasattr(sta, 'isconnected') else bool(sta.active())
                            resp['ip'] = sta.ifconfig()[0] if sta.active() else '0.0.0.0'
                    except Exception:
                        pass
                    resp['last_positions'] = globals().get('last_positions', {})
                    resp['imu'] = read_imu()
                    resp['uptime_ms'] = time.ticks_ms()
                    try:
                        s.sendto(json.dumps(resp).encode('utf-8'), addr)
                    except Exception:
                        pass
                elif mtype == 'stop':
                    # 紧急停止
                    request_stop()
                    try:
                        s.sendto(json.dumps({'type': 'stop_resp', 'ok': True}).encode('utf-8'), addr)
                    except Exception:
                        pass
                elif mtype == 'reboot':
                    try:
                        s.sendto(json.dumps({'type': 'reboot_resp', 'ok': True}).encode('utf-8'), addr)
                    except Exception:
                        pass
                    time.sleep_ms(100)
                    machine.reset()
                elif mtype == 'factory_reset':
                    # 删除配置并重启
                    ok = False
                    try:
                        if os is not None:
                            try:
                                os.remove(CONFIG_PATH)
                                ok = True
                            except Exception:
                                ok = False
                    except Exception:
                        ok = False
                    try:
                        s.sendto(json.dumps({'type': 'factory_reset_resp', 'ok': ok}).encode('utf-8'), addr)
                    except Exception:
                        pass
                    time.sleep_ms(200)
                    machine.reset()
                else:
                    # 视作关键帧消息
                    targets = obj.get('targets') or obj.get('targets_positions') or {}
                    duration = int(obj.get('duration', obj.get('dur', 300) or 300))
                    execute_keyframe(targets, duration)

        # 周期性发送 telemetry 到已配对主机
        try:
            now = time.ticks_ms()
            if time.ticks_diff(now, last_telemetry) >= telemetry_interval:
                last_telemetry = now
                cfg = load_config()
                host = cfg.get('host')
                if host:
                    imu = read_imu()
                    payload = {'type': 'telemetry', 'uptime_ms': now, 'imu': imu}
                    try:
                        s.sendto(json.dumps(payload).encode('utf-8'), (host.get('ip'), int(host.get('port', UDP_PORT))))
                    except Exception:
                        pass
        except Exception:
            pass


if __name__ == '__main__':
    udp_server()
