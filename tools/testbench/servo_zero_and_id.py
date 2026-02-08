#!/usr/bin/env python3
"""
servo_zero_and_id.py

用于舵机归零（记录当前位置为中位）并写入新的舵机 ID，以便组装调试。

操作流程：
1. 扫描在线舵机
2. 对每个选择的舵机执行归零：移动到中位，或在扭矩关闭时物理归位后读取当前位置并保存
3. 可选择写入新的 SERVO_ID（会写入到舵机内存）

注意：写 ID 有风险，请确保目标 ID 不与其他舵机冲突，写入后会改变通信 ID。
"""
import os
import sys
import time
import json

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if ROOT not in sys.path:
    sys.path.append(ROOT)

from services.uart_servo import UartServoManager
import serial

try:
    from services.neutral import load_neutral, save_neutral
    _HAS_NEUTRAL_SERVICE = True
except Exception:
    _HAS_NEUTRAL_SERVICE = False

NEUTRAL_FILE = os.path.join(os.path.dirname(__file__), 'neutral_positions.json')


def scan_online(us, ids=range(1,26)):
    online = []
    print('Scanning ids...')
    for i in ids:
        try:
            if us.ping(i):
                online.append(i)
                print(f'  found {i}')
        except Exception:
            pass
    return online


def save_neutral(mapping):
    with open(NEUTRAL_FILE, 'w', encoding='utf8') as f:
        json.dump(mapping, f, indent=2)
    print('Saved neutral positions to', NEUTRAL_FILE)


def load_neutral():
    if os.path.exists(NEUTRAL_FILE):
        return json.load(open(NEUTRAL_FILE, 'r', encoding='utf8'))
    return {}


def zero_servo(us, sid):
    print(f'-> 将舵机 {sid} 移到中位 (2048)')
    try:
        us.set_position_time(sid, 2048, 800)
    except Exception as e:
        print('set_position_time failed:', e)
    time.sleep(1.0)
    ans = input('需要手动调整位置并保存当前读取位置作为中位吗？(y=手动调整后按回车记录 / n=使用2048) [n]: ') or 'n'
    if ans.lower() == 'y':
        print('请现在关闭扭矩或手动调整舵机到目标中位，然后按回车继续')
        input()
    pos = None
    try:
        pos = us.read_data_by_name(sid, 'CURRENT_POSITION')
    except Exception as e:
        print('读取当前位置失败:', e)
    if pos is None:
        pos = 2048
    print(f'记录中位位置: {pos}')
    try:
        # 写入 MIDDLE_POSI_ADJUST (偏移值 signed short)
        offset = int(pos) - 2048
        us.write_data_by_name(sid, 'MIDDLE_POSI_ADJUST', offset)
        print('已写入 MIDDLE_POSI_ADJUST (偏移):', offset)
    except Exception as e:
        print('写入 MIDDLE_POSI_ADJUST 失败:', e)
    return int(pos)


def write_servo_id(us, current_id, new_id):
    print(f'尝试将舵机 {current_id} 的 ID 写为 {new_id} (请确认无 ID 冲突)')
    ok = False
    try:
        us.write_data_by_name(current_id, 'SERVO_ID', int(new_id))
        time.sleep(0.2)
        ok = us.ping(int(new_id))
    except Exception as e:
        print('写入 ID 失败:', e)
    print('写入后 ping 新 ID', '成功' if ok else '失败')
    return ok


def main():
    port = input('Serial port (e.g. COM6) [COM6]: ') or 'COM6'
    baud = int(input('Baudrate [115200]: ') or 115200)
    try:
        uart = serial.Serial(port, baud, timeout=0.02)
    except Exception as e:
        print('打开串口失败:', e)
        return

    us = UartServoManager(uart, servo_id_list=list(range(1,26)))
    online = scan_online(us)
    if not online:
        print('未发现任何舵机，退出')
        return

    neutral_map = {}
    if _HAS_NEUTRAL_SERVICE:
        try:
            neutral_map = load_neutral()
        except Exception:
            neutral_map = {}
    else:
        if os.path.exists(NEUTRAL_FILE):
            neutral_map = json.load(open(NEUTRAL_FILE, 'r', encoding='utf8'))

    print('\n在线舵机:', online)
    secs = input('输入要归零的舵机 ID 列表(例如 1,2,3 或 1-6)，或回车全部: ') or ''
    def parse(s):
        s = s.strip()
        if not s:
            return online
        out = []
        for part in s.split(','):
            part = part.strip()
            if not part:
                continue
            if '-' in part:
                a,b = part.split('-',1)
                out += list(range(int(a), int(b)+1))
            else:
                out.append(int(part))
        return out

    todo = parse(secs)
    for sid in todo:
        if sid not in online:
            print('跳过不在线或不可达 ID', sid)
            continue
        pos = zero_servo(us, sid)
        neutral_map[str(sid)] = pos
        if _HAS_NEUTRAL_SERVICE:
            try:
                # convert keys to int for service
                save_map = {int(k): int(v) for k, v in neutral_map.items()}
                save_neutral(save_map)
            except Exception:
                # fallback: save local file
                json.dump(neutral_map, open(NEUTRAL_FILE, 'w', encoding='utf8'), indent=2)
        else:
            json.dump(neutral_map, open(NEUTRAL_FILE, 'w', encoding='utf8'), indent=2)

    # 写 ID
    do_id = input('是否需要写入新 ID? (y/n) [n]: ') or 'n'
    if do_id.lower() == 'y':
        cur = int(input('输入当前 ID: '))
        new = int(input('输入新 ID: '))
        confirm = input(f'确认将 {cur} -> {new} ? (y/n): ') or 'n'
        if confirm.lower() == 'y':
            write_servo_id(us, cur, new)
    print('完成')


if __name__ == '__main__':
    main()
