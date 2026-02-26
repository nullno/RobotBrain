"""
ESP32 主机端测试脚本
用法示例：
  python firmware/esp32/esp32_test.py discover
  python firmware/esp32/esp32_test.py provision --ip 192.168.1.50 --ssid MySSID --password MyPass
  python firmware/esp32/esp32_test.py send --ip 192.168.1.50 --targets 1:1500,2:1500 --duration 500

此脚本在局域网通过 UDP 与固件示例交互（默认端口 5005）。
"""

import socket
import json
import time
import argparse

PORT = 5005
BCAST_ADDR = '<broadcast>'


def discover(timeout=3.0):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.settimeout(timeout)
    msg = json.dumps({'type': 'discover'}).encode('utf-8')
    s.sendto(msg, (BCAST_ADDR, PORT))
    results = []
    start = time.time()
    while True:
        try:
            data, addr = s.recvfrom(4096)
            try:
                obj = json.loads(data.decode('utf-8'))
            except Exception:
                obj = {'raw': data.decode('utf-8', errors='ignore')}
            obj['_addr'] = addr
            results.append(obj)
        except socket.timeout:
            break
        if time.time() - start > timeout:
            break
    s.close()
    return results


def provision(ip, ssid, password, timeout=15.0):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    msg = json.dumps({'type': 'provision', 'ssid': ssid, 'password': password}).encode('utf-8')
    s.sendto(msg, (ip, PORT))
    try:
        data, addr = s.recvfrom(4096)
        obj = json.loads(data.decode('utf-8'))
    except Exception as e:
        return {'error': 'timeout_or_parse', 'detail': str(e)}
    finally:
        s.close()
    return obj


def pair(ip, port=PORT, timeout=5.0, host=None):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    payload = {'type': 'pair'}
    if host:
        payload['host'] = host
        payload['port'] = port
    msg = json.dumps(payload).encode('utf-8')
    s.sendto(msg, (ip, PORT))
    try:
        data, addr = s.recvfrom(4096)
        return json.loads(data.decode('utf-8'))
    except Exception as e:
        return {'error': 'timeout_or_parse', 'detail': str(e)}
    finally:
        s.close()


def status(ip, timeout=2.0):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    s.sendto(json.dumps({'type': 'status'}).encode('utf-8'), (ip, PORT))
    try:
        data, addr = s.recvfrom(4096)
        return json.loads(data.decode('utf-8'))
    except Exception as e:
        return {'error': 'timeout_or_parse', 'detail': str(e)}
    finally:
        s.close()


def send_cmd(ip, cmd_type, timeout=2.0):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    s.sendto(json.dumps({'type': cmd_type}).encode('utf-8'), (ip, PORT))
    try:
        data, addr = s.recvfrom(4096)
        return json.loads(data.decode('utf-8'))
    except Exception as e:
        return {'error': 'timeout_or_parse', 'detail': str(e)}
    finally:
        s.close()


def listen(port=PORT, duration=30):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('', port))
    s.settimeout(1.0)
    end = time.time() + float(duration)
    print('Listening for telemetry on port', port)
    try:
        while time.time() < end:
            try:
                data, addr = s.recvfrom(4096)
                try:
                    obj = json.loads(data.decode('utf-8'))
                except Exception:
                    obj = {'raw': data}
                print(time.strftime('%Y-%m-%d %H:%M:%S'), addr, obj)
            except socket.timeout:
                continue
    finally:
        s.close()
    return True


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '0.0.0.0'


def ping(ip, timeout=2.0):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    msg = json.dumps({'type': 'ping'}).encode('utf-8')
    s.sendto(msg, (ip, PORT))
    try:
        data, addr = s.recvfrom(4096)
        obj = json.loads(data.decode('utf-8'))
    except Exception as e:
        return {'error': 'timeout_or_parse', 'detail': str(e)}
    finally:
        s.close()
    return obj


def send_keyframe(ip, targets, duration=300):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    msg = json.dumps({'targets': targets, 'duration': int(duration)}).encode('utf-8')
    s.sendto(msg, (ip, PORT))
    s.close()
    return {'sent': True}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='cmd')
    sub.add_parser('discover')
    prov = sub.add_parser('provision')
    prov.add_argument('--ip', required=True)
    prov.add_argument('--ssid', required=True)
    prov.add_argument('--password', required=True)
    pingp = sub.add_parser('ping')
    pingp.add_argument('--ip', required=True)
    sendp = sub.add_parser('send')
    sendp.add_argument('--ip', required=True)
    sendp.add_argument('--targets', required=True, help='格式: 1:1500,2:1500')
    sendp.add_argument('--duration', type=int, default=300)

    args = p.parse_args()
    if args.cmd == 'discover':
        res = discover(timeout=3.0)
        if not res:
            print('No devices found')
        else:
            for i, r in enumerate(res):
                print(i, r)
    elif args.cmd == 'provision':
        r = provision(args.ip, args.ssid, args.password)
        print('provision result:', r)
    elif args.cmd == 'ping':
        r = ping(args.ip)
        print('ping result:', r)
    elif args.cmd == 'send':
        # parse targets
        pairs = args.targets.split(',')
        tdict = {}
        for pstr in pairs:
            if not pstr:
                continue
            sid, pos = pstr.split(':')
            tdict[int(sid.strip())] = int(pos.strip())
        r = send_keyframe(args.ip, tdict, args.duration)
        print('sent:', r)
    else:
        p.print_help()
