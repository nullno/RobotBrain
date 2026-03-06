from kivy.uix.modalview import ModalView
from kivy.lang import Builder
from app.theme import COLORS
from services.wifi_servo import get_controller
import logging

logger = logging.getLogger(__name__)

Builder.load_file("kv/remote_panel.kv")

class RemotePanel(ModalView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
    def send_motion(self, action_name):
        ctrl = get_controller()
        if ctrl and ctrl.is_connected:
            ctrl.send_motion(action_name)
            logger.info(f"Sent motion: {action_name}")
        else:
            logger.warning("Cannot send motion, ESP32 not connected.")
