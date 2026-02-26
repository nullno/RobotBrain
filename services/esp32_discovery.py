"""
ESP32 设备发现与配对辅助库

功能:
- 在局域网内通过 UDP 广播发现运行固件的 ESP32（期望固件对发现包做出响应）
- 向指定 ESP32 发送配对/配置（SSID/password）请求

注意: ESP32 固件需要实现对 discovery/pairing JSON 的响应和处理。
"""
import socket
import json
import time
import threading

DISCOVER_PORT = 5005
DISCOVER_TIMEOUT = 2.0
PROVISION_PORT = 5005


def discover(timeout=DISCOVER_TIMEOUT, broadcast_msg=None):
    """在局域网广播发现 ESP32 设备。返回列表 [(ip, data_dict), ...]"""
    results = {}
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.4)
        msg = broadcast_msg or json.dumps({'discover': True}).encode('utf-8')
        if isinstance(msg, str):
            msg = msg.encode('utf-8')

        # 发送几次以提高发现率
        end = time.time() + float(timeout or 2.0)
        while time.time() < end:
            try:
                sock.sendto(msg, ('<broadcast>', DISCOVER_PORT))
            except Exception:
                pass
            # 读取回复（短时多次读取）
            t_dead = time.time() + 0.4
            while time.time() < t_dead:
                try:
                    data, addr = sock.recvfrom(2048)
                    ip = addr[0]
                    try:
                        txt = data.decode('utf-8')
                        obj = json.loads(txt)
                    except Exception:
                        obj = {'raw': data.hex()}
                    results[ip] = obj
                except Exception:
                    break
        sock.close()
    except Exception:
        pass
    return list(results.items())


def provision_device(ip, ssid, password, port=PROVISION_PORT, timeout=1.0):
    """向设备发送 WiFi 配置信息（简单 JSON），返回 True/False 表示发送成功。
    设备固件需响应并应用此配对流程。
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(float(timeout or 1.0))
        payload = {'provision': {'ssid': ssid or '', 'password': password or ''}}
        data = json.dumps(payload).encode('utf-8')
        sock.sendto(data, (ip, int(port)))
        # 可选等待设备回复确认
        try:
            resp, addr = sock.recvfrom(1024)
            try:
                obj = json.loads(resp.decode('utf-8'))
                if obj.get('provision_ack'):
                    sock.close()
                    return True
            except Exception:
                pass
        except Exception:
            pass
        sock.close()
        return True
    except Exception:
        return False
