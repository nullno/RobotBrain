'''
JOHO串口总线舵机 Python SDK 
--------------------------------------------------
- 作者: 阿凯爱玩机器人@成都深感机器人
- Email: xingshunkai@qq.com
- update by joho
- 更新时间: 2024-04-26
- 2025-08
--------------------------------------------------
'''
import time
import logging
import serial
import struct
from .packet import Packet
from .packet_buffer import PacketBuffer
from .data_table import *

class UartServoInfo:
	'''串口舵机的信息'''
	SERVO_DEADBLOCK = 1 # 舵机死区
	
	def __init__(self, servo_id, lowerb=None, upperb=None):
		self.is_online = False 	 # 电机是否在线 
		self.servo_id = servo_id # 舵机的ID
		self.cur_position = None # 当前位置
		self.target_position = None # 目标位置
		# 位置与角度的变换关系
		self.position2angle_k = 360 / 4096.0
		self.position2angle_b = -180 #角度体系-180°~180°

		self.last_angle_error = None    # 上一次的角度误差
		self.last_sample_time = None    # 上一次的采样时间
		# 内存表数据
		self.data_table_raw_dict = {} # 原始数据 字典类型
		# 内存表写入标志位
		self.data_write_success = False
		# 舵机状态
		self.status = 0 # 舵机状态

	def is_stop(self):
		'''判断舵机是否已经停止'''
		# # 如果没有指定目标角度， 就将其设置为当前角度
		# if self.target_angle is None:
		# 	self.target_angle = self.cur_angle
		# 角度误差判断
		angle_error = self.target_angle - self.cur_angle
		if abs(angle_error) <= self.SERVO_DEADBLOCK:
			return True
		
		if self.last_angle_error is None:
			self.last_angle_error = angle_error
			self.last_sample_time = time.time()
		
		# 角度误差在死区范围以内则判断为已经到达目标点
		
		# 更新采样数据
		if abs(self.last_angle_error - angle_error) > 0.2:
			self.last_angle_error = angle_error
			self.last_sample_time = time.time() # 更新采样时间

		if (time.time() - self.last_sample_time) > 1:
			# 已经有1s没有更新误差了, 舵机卡住了
			self.last_angle_error = None
			self.last_sample_time = None
			return True
		
		return False

	def position2angle(self, position):
		'''位置转化为角度'''
		return self.position2angle_k * position + self.position2angle_b
	
	def angle2position(self, angle):
		'''角度转换为位置'''
		return (angle-self.position2angle_b)/self.position2angle_k
		#pass

	@property
	def cur_angle(self):
		return self.position2angle(self.cur_position)

	@property
	def target_angle(self):
		return self.position2angle(self.target_position)

	def move(self, target_position):
		'''设置舵机的目标角度'''
		# 设置目标角度
		self.target_position = target_position

	def update(self, cur_position):
		'''更新当前舵机的角度'''
		self.cur_position = cur_position
	
	def __str__(self):
		return "目标角度:{:.1f} 实际角度:{:.1f} 角度误差:{:.2f}".format(self.target_angle, self.cur_angle, self.target_angle-self.cur_angle)

class UartServoManager:
	'''串口总线舵机管理器'''
	# 数据帧接收Timeout
	RECEIVE_TIMEOUT = 0.02		# 接收超时延迟
	RETRY_NTIME = 10 			# 通信失败后，重试的次数
	DELAY_BETWEEN_CMD = 0.001	# 数据帧之间的延时时间
	# 命令类型定义
	CMD_TYPE_PING = 0x01		# 查询
	CMD_TYPE_READ_DATA = 0x02	# 读
	CMD_TYPE_WRITE_DATA = 0x03	# 写
	CMD_TYPE_REG_WRITE = 0x04	# 异步写
	CMD_TYPE_ACTION = 0x05		# 执行异步写
	CMD_TYPE_RESET = 0x06		# 回复出厂设置
	CMD_TYPE_SYNC_WRITE = 0x83	# 同步写
	# 电机控制
	POSITION_DEADAREA = 10		# 舵机位置控制 死区 	 
	def __init__(self, uart, servo_id_list=[1]):
		'''初始化舵机管理器'''
		self.uart = uart						# 串口
		self.pkt_buffer = PacketBuffer()		# 数据帧缓冲区
  		# 创建舵机信息字典
		self.servo_info_dict = {}				# 舵机信息字典
		# 诊断统计（默认关闭，可在上层按平台开启）
		self._diag_enabled = False
		self._diag_tag = 'uart-servo'
		self._diag_log_interval_sec = 5.0
		self._diag_last_log_ts = 0.0
		self._diag_stat = {
			'wait_req': 0,
			'wait_ok': 0,
			'wait_fail': 0,
			'read_req': 0,
			'read_ok': 0,
			'read_fail': 0,
			'ping_req': 0,
			'ping_ok': 0,
			'ping_fail': 0,
			'total_retry_used': 0,
			'last_rsp_len': 0,
			'last_error': '',
		}
		# 舵机扫描
		self.servo_scan(servo_id_list)

	def enable_diagnostics(self, enabled=True, tag='uart-servo', log_interval_sec=5.0):
		'''开启/关闭通信诊断统计与周期日志。'''
		self._diag_enabled = bool(enabled)
		self._diag_tag = str(tag or 'uart-servo')
		try:
			self._diag_log_interval_sec = max(1.0, float(log_interval_sec))
		except Exception:
			self._diag_log_interval_sec = 5.0

	def get_diagnostics_snapshot(self):
		'''获取当前诊断快照。'''
		try:
			return dict(self._diag_stat)
		except Exception:
			return {}

	def _diag_cmd_name(self, cmd_type):
		if cmd_type == self.CMD_TYPE_READ_DATA:
			return 'READ'
		if cmd_type == self.CMD_TYPE_PING:
			return 'PING'
		if cmd_type == self.CMD_TYPE_WRITE_DATA:
			return 'WRITE'
		return f'CMD{int(cmd_type)}'

	def _diag_record_wait_response(self, cmd_type, ok, retry_used, rsp_len=0, err=''):
		if not self._diag_enabled:
			return
		st = self._diag_stat
		st['wait_req'] += 1
		if ok:
			st['wait_ok'] += 1
		else:
			st['wait_fail'] += 1
		if cmd_type == self.CMD_TYPE_READ_DATA:
			st['read_req'] += 1
			if ok:
				st['read_ok'] += 1
			else:
				st['read_fail'] += 1
		elif cmd_type == self.CMD_TYPE_PING:
			st['ping_req'] += 1
			if ok:
				st['ping_ok'] += 1
			else:
				st['ping_fail'] += 1

		st['total_retry_used'] += int(max(0, retry_used))
		st['last_rsp_len'] = int(max(0, rsp_len))
		if err:
			st['last_error'] = str(err)

		now = time.time()
		if (now - float(self._diag_last_log_ts or 0.0)) < float(self._diag_log_interval_sec):
			return
		self._diag_last_log_ts = now

		wait_req = max(1, int(st.get('wait_req', 0) or 0))
		read_req = int(st.get('read_req', 0) or 0)
		read_fail = int(st.get('read_fail', 0) or 0)
		wait_fail = int(st.get('wait_fail', 0) or 0)
		avg_retry = float(st.get('total_retry_used', 0) or 0) / float(wait_req)
		read_fail_rate = (100.0 * float(read_fail) / float(read_req)) if read_req > 0 else 0.0
		wait_fail_rate = 100.0 * float(wait_fail) / float(wait_req)
		logging.info(
			"[%s] %s req=%d ok=%d fail=%d fail_rate=%.1f%% read_fail_rate=%.1f%% avg_retry=%.2f last_rsp_len=%d last_err=%s",
			self._diag_tag,
			self._diag_cmd_name(cmd_type),
			wait_req,
			int(st.get('wait_ok', 0) or 0),
			wait_fail,
			wait_fail_rate,
			read_fail_rate,
			avg_retry,
			int(st.get('last_rsp_len', 0) or 0),
			str(st.get('last_error', '') or '-'),
		)
	
	def receive_response(self):
		'''接收单个数据帧'''
  		# 清空缓冲区
		self.pkt_buffer.empty_buffer()
		# 开始计时
		t_start = time.time()
		while True:
			# 判断是否有新的数据读入
			buffer_bytes = self.uart.readall()
			if buffer_bytes is not None and len(buffer_bytes) > 0:
				for next_byte in buffer_bytes:
					self.pkt_buffer.update(next_byte)
			# 弹出接收的数据帧
			if self.pkt_buffer.has_valid_packet():
				# 获取数据帧
				packet_bytes = self.pkt_buffer.get_packet()
				# 提取数据帧参数
				result = Packet.unpack(packet_bytes)
				servo_id, data_size, servo_status, param_bytes = result
				# 舵机状态自动同步
				if servo_id in self.servo_info_dict.keys():
					self.servo_info_dict[servo_id].status = servo_status
				return packet_bytes
			# 超时判断
			if time.time() - t_start > self.RECEIVE_TIMEOUT:
				return None

	def send_request(self, servo_id, cmd_type, param_bytes, wait_response=False, retry_ntime=None):
		'''发送请求'''
		if wait_response:
			# 清空串口缓冲区
			self.uart.readall()

		packet_bytes = Packet.pack(servo_id, cmd_type, param_bytes)	

		if not wait_response:
			# 发送指令
			self.uart.write(packet_bytes)
			time.sleep(self.DELAY_BETWEEN_CMD)
			return True, None
		else:
			
			if retry_ntime is None:
				retry_ntime = self.RETRY_NTIME
			# 尝试多次
			for i in range(retry_ntime):
				self.uart.write(packet_bytes)
				time.sleep(self.DELAY_BETWEEN_CMD)
				response_packet =  self.receive_response()
				if response_packet is not None:
					self._diag_record_wait_response(
						cmd_type=cmd_type,
						ok=True,
						retry_used=(i + 1),
						rsp_len=len(response_packet),
					)
					return True, response_packet
			# 发送失败
			self._diag_record_wait_response(
				cmd_type=cmd_type,
				ok=False,
				retry_used=retry_ntime,
				rsp_len=0,
				err='response-timeout-or-invalid-packet',
			)
			return False, None

	def find_servo(self):
		'''搜索舵机'''
		ret, response_packet = self.send_request(
			254,
			self.CMD_TYPE_PING,
			b'',
			wait_response=True,
			retry_ntime=max(3, int(getattr(self, 'RETRY_NTIME', 3) or 3)),
		)
		if ret:
		# 提取读取到的数据位
			servo_id, data_size, servo_status, param_bytes = Packet.unpack(response_packet)
			return True, servo_id
		else:
			return False, None

	def ping(self, servo_id):
		'''舵机通讯检测'''
		ret, response_packet = self.send_request(
			servo_id,
			self.CMD_TYPE_PING,
			b'',
			wait_response=True,
			retry_ntime=max(3, int(getattr(self, 'RETRY_NTIME', 3) or 3)),
		)
		if ret and servo_id not in self.servo_info_dict.keys():
			# 创建舵机对象
			self.servo_info_dict[servo_id] = UartServoInfo(servo_id)
			# 舵机角度查询
			# TODO?
		return ret
	
	def read_data(self, servo_id, data_address, read_nbyte=1):
		'''读取数据'''
		param_bytes = struct.pack('>BB', data_address, read_nbyte)
		ret, response_packet = self.send_request(servo_id, self.CMD_TYPE_READ_DATA, param_bytes, wait_response=True)
		if ret:
			# 提取读取到的数据位
			servo_id, data_size, servo_status, param_bytes = Packet.unpack(response_packet)
			return True, param_bytes
		else:
			return False, None
	
	def write_data(self, servo_id, data_address, param_bytes):
		'''写入数据'''
		param_bytes = struct.pack('>B', data_address) + param_bytes
		self.send_request(servo_id, self.CMD_TYPE_WRITE_DATA, param_bytes)
		return True

	def read_data_by_name(self, servo_id, data_name):
		'''根据名字读取数据'''
		# 获取地址位与数据类型
		if data_name not in UART_SERVO_DATA_TABLE:
			return None
		data_address, dtype = UART_SERVO_DATA_TABLE[data_name]
		read_nbyte = 1
		if dtype in ['h', 'H']:
			read_nbyte = 2
		ret, param_bytes = self.read_data(servo_id, data_address, read_nbyte=read_nbyte)
		if not ret:
			return None
		# 数据解析
		value = struct.unpack(f">{dtype}", param_bytes)[0]
		return value

	def write_data_by_name(self, servo_id, data_name, value):
		'''根据名称写入数据'''
		if data_name not in UART_SERVO_DATA_TABLE:
			return None
		data_address, dtype = UART_SERVO_DATA_TABLE[data_name]
		param_bytes = struct.pack(f">{dtype}", value)
		self.write_data(servo_id, data_address, param_bytes)
	
	def get_legal_position(self, position):
		'''获取合法的位置'''
		position = int(position)
		if position > 4095:
			position = 4095
		elif position < 0:
			position = 0
		return position

	def async_set_position(self, servo_id, position, runtime_ms):
		'''异步写入位置控制信息'''
		# 参数规范化
		if servo_id in self.servo_info_dict.keys():
			self.servo_info_dict[servo_id].is_stop = False
		position = self.get_legal_position(position)
		runtime_ms = int(runtime_ms)

		address, _ = UART_SERVO_DATA_TABLE['TARGET_POSITION']
		param_bytes = struct.pack('>BHH', address,  position, runtime_ms)
		self.send_request(servo_id, self.CMD_TYPE_REG_WRITE, param_bytes)
		return True

	def async_action(self):
		'''执行异步位置控制信息'''
		self.send_request(SERVO_ID_BRODCAST, self.CMD_TYPE_ACTION, b'')
		return True

	def sync_set_position(self, servo_id_list, position_list, runtime_ms_list):
		'''同步写指令'''
		param_bytes = b'\x2A\x04'
		servo_num = len(servo_id_list) # 舵机个数
		for sidx in range(servo_num):
			servo_id = servo_id_list[sidx]
			if servo_id in self.servo_info_dict.keys():
				self.servo_info_dict[servo_id].is_stop = False
			position = position_list[sidx]
			position = self.get_legal_position(position)
			runtime_ms = runtime_ms_list[sidx]
			runtime_ms = int(runtime_ms)
			param_bytes += struct.pack('>BHH', servo_id, position, runtime_ms)
		self.send_request(SERVO_ID_BRODCAST, self.CMD_TYPE_SYNC_WRITE, param_bytes)
	
	def reset(self, servo_id):
		'''舵机恢复出厂设置'''
		self.send_request(servo_id, self.CMD_TYPE_RESET, b'')
	
	def set_position(self, servo_id, position, is_wait=False):
		'''设置舵机位置'''
		position = self.get_legal_position(position)
		self.write_data_by_name(servo_id, "TARGET_POSITION", position)
		if servo_id in self.servo_info_dict.keys():
			self.servo_info_dict[servo_id].move(position)
			self.servo_info_dict[servo_id].is_stop = False
		if is_wait:
			self.wait(servo_id)

	def set_position_time(self, servo_id, position, runtime_ms=None, time_ms=None):
		"""设置舵机位置及执行时间。
		支持两种关键字：`runtime_ms`（原名）和 `time_ms`（常见别名），并保持向后兼容。
		"""
		position = self.get_legal_position(position)
		# 兼容 time_ms 参数名
		if runtime_ms is None and time_ms is not None:
			runtime_ms = time_ms
		# 默认 300ms
		if runtime_ms is None:
			runtime_ms = 300
		runtime_ms = int(runtime_ms)
		address, _ = UART_SERVO_DATA_TABLE['TARGET_POSITION']
		param_bytes = struct.pack('>BHH', address,  position, runtime_ms)
		self.send_request(servo_id, self.CMD_TYPE_WRITE_DATA, param_bytes)
		return True


	def set_runtime_ms(self, servo_id, runtime_ms):
		'''设置运行时间ms'''
		self.write_data_by_name(servo_id, "RUNTIME_MS", runtime_ms)
	
	def get_target_position(self, servo_id):
		'''获取目标位置'''
		return self.read_data_by_name(servo_id, "TARGET_POSITION")

	def get_position(self, servo_id):
		'''查询舵机位置'''
		return self.read_data_by_name(servo_id, "CURRENT_POSITION")

	def get_velocity(self, servo_id):
		'''查询舵机速度'''
		return self.read_data_by_name(servo_id, "CURRENT_VELOCITY")

	def servo_scan(self, servo_id_list=[1]):
		'''舵机扫描'''
		for servo_id in servo_id_list:
			# Android USB 串口链路存在抖动时，命令间稍作间隔可显著降低回包丢失
			time.sleep(max(0.0, float(getattr(self, 'DELAY_BETWEEN_CMD', 0.001) or 0.001)))
			# 尝试ping一下舵机
			if self.ping(servo_id):
				print("发现舵机: {}".format(servo_id))
				# 设置为舵机模式
				self.set_motor_mode(servo_id, MOTOR_MODE_SERVO)
				# 创建舵机对象
				self.servo_info_dict[servo_id] = UartServoInfo(servo_id)
				self.servo_info_dict[servo_id].is_online = True
				# 查询角度并同步角度
				position = self.get_position(servo_id)
				self.servo_info_dict[servo_id].update(position)
				self.servo_info_dict[servo_id].move(position)
			else:
				if servo_id in self.servo_info_dict.keys():
					self.servo_info_dict[servo_id].is_online = False
		
	def wait(self, servo_id):
		'''等待单个舵机停止运动'''
		angle_error_dict = {}
		while True:
			target_position = self.servo_info_dict[servo_id].target_position
			cur_position = self.get_position(servo_id)
			angle_error = abs( cur_position - target_position)
			# print(f"target_position: {target_position}  cur_position:{cur_position}  angle_error:{angle_error}")
			# 小于死区
			if angle_error < self.POSITION_DEADAREA:
				self.servo_info_dict[servo_id].is_stop = True
				break
			# 判断是否卡住了
			if angle_error not in angle_error_dict:
				angle_error_dict[angle_error] = 1
			else:
				angle_error_dict[angle_error] += 1
			if angle_error_dict[angle_error] >= 100:
				self.servo_info_dict[servo_id].is_stop = True
				break
	
	def wait_all(self):
		'''等待所有舵机执行动作'''
		for servo_id in self.servo_info_dict.keys():
			if self.servo_info_dict[servo_id].is_online:
				self.wait(servo_id)

	def set_motor_mode(self, servo_id, mode):
		'''设置电机模式'''
		self.write_data_by_name(servo_id, "MOTOR_MODE", mode)
	
	def dc_rotate(self, servo_id, direction, pwm):
		'''直流电机旋转'''
		pwm = int(pwm)
		pwm = min(100, max(pwm, 0))
		# 设置方向 顺时针: DC_DIR_CW |  逆时针: DC_DIR_CCW
		self.write_data_by_name(servo_id, "MOTOR_DIR", direction)
		#加延迟10ms
		time.sleep(0.01)
		# 设置转速 [0, 100]
		self.write_data_by_name(servo_id, "MOTOR_SPEED", pwm)
	
	def dc_stop(self, servo_id):
		self.write_data_by_name(servo_id, "MOTOR_SPEED", 0)
  
	def torque_enable(self, servo_id, enable):
		'''扭力使能'''
		value = TORQUE_ENABLE if enable else TORQUE_DISABLE
		self.write_data_by_name(servo_id, "TORQUE_ENABLE", value)
	
	def torque_enable_all(self, enable):
		'''扭力使能(所有舵机)'''
		value = TORQUE_ENABLE if enable else TORQUE_DISABLE
		self.write_data_by_name(SERVO_ID_BRODCAST, "TORQUE_ENABLE", value)
	
	def set_torque_upperb(self, servo_id, torque_upperb):
		'''设置最大扭力
		@torque_upperb: 取值范围[0, 1000]
  		'''
		self.write_data_by_name(servo_id, "TORQUE_UPPERB", torque_upperb)
  
	def get_temperature(self, servo_id):
		'''获取当前温度'''
		return self.read_data_by_name(servo_id, "CURRENT_TEMPERATURE")

	def get_voltage(self, servo_id):
		'''获取当前电压'''
		return self.read_data_by_name(servo_id, "CURRENT_VOLTAGE")
	
	# def pos2ang(self, position):
	# 	'''位置转化为角度'''
	# 	return self.position2angle_k * position + self.position2angle_b
	
	def ang2pos(self, angle):
		'''角度转换为位置'''
		return (angle+180)/(360/4096)