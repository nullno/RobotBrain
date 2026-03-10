from kivy.app import App
from kivy.core.window import Window
from kivy.uix.button import Button
class TestApp(App):
    def build(self):
        self.btn = Button(text='Press W')
        Window.bind(on_key_down=self.down)
        return self.btn
    def down(self, window, keycode, scancode, codepoint, modifiers):
        print('down:', keycode, scancode, codepoint, modifiers)
TestApp().run()
