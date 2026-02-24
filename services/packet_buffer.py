'''
数据帧缓冲队列 - JOHO串口总线舵机 Python SDK 
--------------------------------------------------
- 作者: 阿凯爱玩机器人@成都深感机器人
- Email: xingshunkai@qq.com
- 更新时间: 2021-12-19
--------------------------------------------------
'''
import logging
import struct
from .packet import Packet

class PacketBuffer:
	'''Packet中转站'''
	def __init__(self, is_debug=False):
		self.is_debug = is_debug
		self.packet_bytes_list = []
		self._stream = bytearray()
		# 清空缓存区域
		self.empty_buffer()

	def _find_first_header_idx(self):
		try:
			buf = bytes(self._stream)
			headers = Packet.response_headers()
			best = None
			for hdr in headers:
				idx = buf.find(hdr)
				if idx >= 0 and (best is None or idx < best):
					best = idx
			return best
		except Exception:
			return None

	def _try_parse_headerless_from_start(self):
		'''兼容手机端偶发丢帧头场景：尝试将 [id,size,...,checksum] 还原为完整响应包。'''
		try:
			if len(self._stream) < 5:
				return False

			data_size = int(self._stream[1])
			if data_size < 2 or data_size > 64:
				return False

			payload_len = data_size + 2  # id + size + status + param + checksum
			if len(self._stream) < payload_len:
				return False

			payload = bytes(self._stream[:payload_len])
			for hdr in Packet.response_headers():
				frame = hdr + payload
				ret, _ = Packet.is_response_legal(frame)
				if ret:
					self.packet_bytes_list.append(frame)
					del self._stream[:payload_len]
					return True
			return False
		except Exception:
			return False

	def _extract_packets(self):
		'''从流缓存中尽可能提取有效数据帧（含错位/丢帧头容错）。'''
		while True:
			if len(self._stream) < 5:
				return

			hdr_idx = self._find_first_header_idx()

			if hdr_idx is None:
				if self._try_parse_headerless_from_start():
					continue
				# 无法识别则滑动丢弃 1 字节，避免死锁
				del self._stream[0]
				continue

			if hdr_idx > 0:
				# 头前缀若能还原为无头有效帧，优先恢复；否则丢弃噪声前缀
				if self._try_parse_headerless_from_start():
					continue
				del self._stream[:hdr_idx]
				if len(self._stream) < 5:
					return

			# 现在默认头在 0 位置
			if len(self._stream) < 4:
				return
			data_size = int(self._stream[3])
			if data_size < 2 or data_size > 64:
				del self._stream[0]
				continue

			total_len = data_size + 4
			if len(self._stream) < total_len:
				return

			frame = bytes(self._stream[:total_len])
			ret, _ = Packet.is_response_legal(frame)
			if ret:
				self.packet_bytes_list.append(frame)
				del self._stream[:total_len]
				continue

			# 当前头疑似伪头，滑动一字节继续找
			del self._stream[0]
	
	def update(self, next_byte):
		'''将新的字节添加到Packet中转站'''
		try:
			# < int > 转换为 bytearray
			next_b = struct.pack(">B", next_byte)
		except Exception:
			return

		self._stream.extend(next_b)
		# 限制流缓存大小，防止异常情况下无限增长
		if len(self._stream) > 512:
			del self._stream[:-256]
		self._extract_packets()
		
	def empty_buffer(self):
		# 数据帧是否准备好
		self.param_len = None
		# 帧头
		self.header = b''
		self.header_flag = False
		# 舵机ID
		self.servo_id = b''
		self.servo_id_flag = False
		# 数据长度
		self.data_size = b''
		self.data_size_flag = False
		# 舵机状态
		self.servo_status = b''
		self.servo_status_flag = False
		# 参数
		self.param_bytes = b''
		self.param_bytes_flag = False
		# 流缓存
		self._stream = bytearray()
	
	def has_valid_packet(self):
		'''是否有有效的包'''
		return len(self.packet_bytes_list) > 0
	
	def get_packet(self):
		'''获取队首的Bytes'''
		return self.packet_bytes_list.pop(0)

