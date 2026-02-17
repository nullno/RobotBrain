import json
import os
import subprocess
import sys

from kivy.clock import Clock


def on_ai_action(app, instance, action, emotion):
    if "face" in app.root_widget.ids:
        try:
            app.root_widget.ids.face.set_emotion(emotion)
        except Exception:
            pass
    print(f"AI action received: {action}, emotion: {emotion}")


def on_ai_speech(app, instance, text):
    face = app.root_widget.ids.get("face")
    if face:
        try:
            face.show_speaking_text(text)
        except Exception:
            pass
    try:
        app._ai_speech_buf += str(text)
        if app._ai_speech_clear_ev:
            app._ai_speech_clear_ev.cancel()
        app._ai_speech_clear_ev = Clock.schedule_once(app._ai_speak_final, 0.6)
    except Exception:
        pass


def ai_speak_final(app, dt):
    txt = app._ai_speech_buf.strip()
    app._ai_speech_buf = ""
    app._ai_speech_clear_ev = None
    if not txt:
        return

    try:
        from plyer import tts

        try:
            tts.speak(txt)
            return
        except Exception as e:
            print(f"TTS (plyer) play failed: {e}")
    except Exception as e:
        print(f"plyer.tts not available: {e}")

    try:
        try:
            cache_dir = os.environ.get("COMTYPES_CACHE_DIR") or os.path.join(
                os.path.expanduser("~"), ".comtypes_cache"
            )
            os.makedirs(cache_dir, exist_ok=True)
            os.environ["COMTYPES_CACHE_DIR"] = cache_dir
        except Exception as _e:
            print(f"Warning: cannot create comtypes cache dir: {_e}")

        import pyttsx3

        try:
            engine = pyttsx3.init()
            try:
                engine.setProperty("rate", 150)
            except Exception:
                pass
            engine.say(txt)
            engine.runAndWait()
            return
        except Exception as e:
            print(f"TTS (pyttsx3) play failed: {e}")
            try:
                import platform as _plat

                if _plat.system().lower().startswith("win"):
                    try:
                        import win32com.client

                        sapi = win32com.client.Dispatch("SAPI.SpVoice")
                        sapi.Speak(txt)
                        return
                    except Exception as e2:
                        print(f"TTS (win32com SAPI) play failed: {e2}")
                        try:
                            if sys.platform.startswith("win"):
                                ps_cmd = f"Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak({json.dumps(txt)})"
                                subprocess.run(
                                    [
                                        "powershell",
                                        "-NoProfile",
                                        "-Command",
                                        ps_cmd,
                                    ],
                                    check=True,
                                )
                                return
                        except Exception as e3:
                            print(f"TTS (PowerShell) play failed: {e3}")
            except Exception:
                pass
    except Exception as e:
        print(f"pyttsx3 not available: {e}")

    print(f"AI says: {txt}")
