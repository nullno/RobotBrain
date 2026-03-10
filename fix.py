import re

with open('d:\\github\\RobotBrain\\widgets\\remote_panel.py', 'r', encoding='utf-8') as f:
    code = f.read()

target = '''    def _on_key_down(self, window, keycode, scancode, codepoint, modifiers):
        key_name = str(keycode[1]).lower() if isinstance(keycode, tuple) else str(keycode).lower()'''

replacement = '''    def _get_key_name(self, keycode):
        if isinstance(keycode, tuple):
            return str(keycode[1]).lower()
        if isinstance(keycode, int):
            for name, code in Keyboard.keycodes.items():
                if code == keycode:
                    return name.lower()
        return str(keycode).lower()

    def _on_key_down(self, window, keycode, scancode, codepoint, modifiers):
        key_name = self._get_key_name(keycode)'''

code = code.replace(target, replacement)

target2 = '''    def _on_key_up(self, window, keycode, scancode):
        key_name = str(keycode[1]).lower() if isinstance(keycode, tuple) else str(keycode).lower()'''

replacement2 = '''    def _on_key_up(self, window, keycode, scancode):
        key_name = self._get_key_name(keycode)'''

code = code.replace(target2, replacement2)

with open('d:\\github\\RobotBrain\\widgets\\remote_panel.py', 'w', encoding='utf-8') as f:
    f.write(code)

print("done")
