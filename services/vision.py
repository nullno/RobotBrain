"""
简单颜色目标跟踪器

用法示例：
    from services.vision import ColorTracker
    tracker = ColorTracker(hsv_lower=(35, 80, 60), hsv_upper=(85, 255, 255))
    # 将 tracker.process_frame(frame) 在 CameraView.frame_callback 中调用
    tracker.process_frame(frame)
    cx, cy, area = tracker.get_last()

返回：
    cx, cy: 相对于帧宽高的像素坐标（None 表示无目标）
    area: 目标面积像素数
"""

import threading
import time

try:
    import cv2
    import numpy as np
except Exception:
    cv2 = None
    np = None

class ColorTracker:
    def __init__(self, hsv_lower=(35, 80, 60), hsv_upper=(85, 255, 255), min_area=200):
        self.hsv_lower = hsv_lower
        self.hsv_upper = hsv_upper
        self.min_area = min_area

        self._lock = threading.Lock()
        self._last_cx = None
        self._last_cy = None
        self._last_area = 0

    def process_frame(self, frame):
        """处理一帧（BGR numpy array）并更新内部状态"""
        if cv2 is None:
            return
        try:
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            lower = np.array(self.hsv_lower, dtype=np.uint8)
            upper = np.array(self.hsv_upper, dtype=np.uint8)
            mask = cv2.inRange(hsv, lower, upper)
            # 去噪
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5,5))
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)

            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                with self._lock:
                    self._last_cx = None
                    self._last_cy = None
                    self._last_area = 0
                return

            # 找到最大轮廓
            c = max(contours, key=lambda x: cv2.contourArea(x))
            area = cv2.contourArea(c)
            if area < self.min_area:
                with self._lock:
                    self._last_cx = None
                    self._last_cy = None
                    self._last_area = area
                return

            M = cv2.moments(c)
            if M['m00'] == 0:
                return
            cx = int(M['m10'] / M['m00'])
            cy = int(M['m01'] / M['m00'])
            with self._lock:
                self._last_cx = cx
                self._last_cy = cy
                self._last_area = area
        except Exception:
            return

    def get_last(self):
        with self._lock:
            return (self._last_cx, self._last_cy, self._last_area)


if __name__ == '__main__':
    print('ColorTracker module - no demo here.')
