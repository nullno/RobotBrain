import os
import threading
import time
import queue
import asyncio
import tempfile

from kivy.clock import Clock


def on_ai_action(app, instance, action, emotion):
    if "face" in app.root_widget.ids:
        try:
            app.root_widget.ids.face.set_emotion(emotion)
        except Exception:
            pass
    print(f"AI action received: {action}, emotion: {emotion}")

    action = str(action or "none").strip().lower()
    if action in ("", "none"):
        return

    motion = getattr(app, "motion_controller", None)
    if not motion:
        print("AI action skipped: motion_controller is not ready")
        return

    def _run_motion():
        try:
            if hasattr(motion, "run_action"):
                motion.run_action(action)
                return

            if action == "walk" and hasattr(motion, "walk"):
                motion.walk(steps=2)
            elif action == "stop" and hasattr(motion, "stop"):
                motion.stop()
            elif action == "nod" and hasattr(motion, "nod"):
                motion.nod(times=1)
            elif action == "shake_head" and hasattr(motion, "shake_head"):
                motion.shake_head(times=1)
            elif action == "wave" and hasattr(motion, "wave"):
                motion.wave(side="right", times=1)
            elif action == "sit" and hasattr(motion, "sit"):
                motion.sit()
            elif action == "stand" and hasattr(motion, "stand"):
                motion.stand()
            elif action == "twist" and hasattr(motion, "twist"):
                motion.twist(angle_deg=25)
            else:
                print(f"AI action not supported by motion controller: {action}")
        except Exception as e:
            print(f"AI action execution failed: {action}, err={e}")

    threading.Thread(target=_run_motion, daemon=True).start()


def on_ai_speech(app, instance, text):
    text = str(text or "")
    face = app.root_widget.ids.get("face")
    if face:
        try:
            if text.startswith("[我]") or text.startswith("[系统]"):
                face.show_speaking_text(text, timeout=2.0)
            else:
                face.show_speaking_text(text)
        except Exception:
            pass

    # [我]/[系统] 仅用于屏幕显示，不进入 TTS，避免麦克风回声自激
    if text.startswith("[我]") or text.startswith("[系统]"):
        return

    try:
        app._ai_speech_buf += text
        if app._ai_speech_clear_ev:
            app._ai_speech_clear_ev.cancel()
        app._ai_speech_clear_ev = Clock.schedule_once(app._ai_speak_final, 0.9)
    except Exception:
        pass


def ai_speak_final(app, dt):
    txt = app._ai_speech_buf.strip()
    app._ai_speech_buf = ""
    app._ai_speech_clear_ev = None
    if not txt:
        return

    _enqueue_tts(app, txt)


def speak_text(app, text):
    txt = str(text or "").strip()
    if not txt:
        return False
    _enqueue_tts(app, txt)
    return True


def _enqueue_tts(app, txt):
    try:
        if not hasattr(app, "_tts_queue") or app._tts_queue is None:
            app._tts_queue = queue.Queue()
        txt = str(txt or "").strip()
        if not txt:
            return

        now = time.time()
        last_text = str(getattr(app, "_tts_last_text", "") or "")
        last_ts = float(getattr(app, "_tts_last_ts", 0.0) or 0.0)
        if txt == last_text and (now - last_ts) < 20.0:
            return

        pending = set(getattr(app, "_tts_pending", set()) or set())
        if txt in pending:
            return

        while app._tts_queue.qsize() >= 3:
            try:
                dropped = app._tts_queue.get_nowait()
                try:
                    pending.discard(str(dropped))
                except Exception:
                    pass
            except Exception:
                break

        app._tts_queue.put(txt)
        pending.add(txt)
        app._tts_pending = pending
        app._tts_last_text = txt
        app._tts_last_ts = now

        worker = getattr(app, "_tts_worker", None)
        if not worker or (not worker.is_alive()):
            app._tts_worker = threading.Thread(target=_tts_worker_loop, args=(app,), daemon=True)
            app._tts_worker.start()
    except Exception as e:
        print(f"TTS enqueue failed: {e}")


def _tts_worker_loop(app):
    while True:
        try:
            txt = app._tts_queue.get()
        except Exception:
            return

        try:
            _speak_once(app, txt)
        except Exception as e:
            print(f"TTS worker speak failed: {e}")
        finally:
            try:
                pending = set(getattr(app, "_tts_pending", set()) or set())
                pending.discard(str(txt))
                app._tts_pending = pending
            except Exception:
                pass
            try:
                app._tts_queue.task_done()
            except Exception:
                pass


def _speak_once(app, txt):
    txt = str(txt or "").strip()
    if not txt:
        return

    try:
        ai_core = getattr(app, "ai_core", None)
        if ai_core is not None:
            estimate = min(7.0, max(1.6, len(txt) / 5.0))
            ai_core._stt_ignore_until = time.time() + estimate + 0.4
    except Exception:
        pass
    if _try_edge_tts(app, txt):
        return

    app._tts_channel = "edge-tts-failed"
    print(f"AI says: {txt}")


def _try_edge_tts(app, txt):
    try:
        tts_start = time.time()
        import edge_tts
        import pygame

        out_path = ""
        synth_start = time.time()

        async def _gen_audio(path):
            voice = os.environ.get("ROBOTBRAIN_TTS_VOICE", "zh-CN-XiaoxiaoNeural")
            rate = os.environ.get("ROBOTBRAIN_TTS_RATE", "+35%")
            communicate = edge_tts.Communicate(txt, voice=voice, rate=rate)
            await communicate.save(path)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as fp:
            out_path = fp.name

        asyncio.run(_gen_audio(out_path))
        synth_ms = int((time.time() - synth_start) * 1000)

        try:
            play_start = time.time()
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.music.load(out_path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.05)
            pygame.mixer.music.unload()
            play_ms = int((time.time() - play_start) * 1000)
        finally:
            try:
                if out_path and os.path.exists(out_path):
                    os.remove(out_path)
            except Exception:
                pass
        app._tts_channel = "edge-tts"
        app._tts_last_error = ""
        app._tts_last_ms = int((time.time() - tts_start) * 1000)
        try:
            print(
                f"[TTS] edge-tts total={app._tts_last_ms}ms synth={synth_ms}ms play={play_ms}ms"
            )
        except Exception:
            pass
        return True
    except Exception as e:
        print(f"TTS (edge-tts) play failed: {e}")
        try:
            app._tts_last_error = f"edge-tts: {e}"
            app._tts_last_ms = -1
        except Exception:
            pass
        return False

    print(f"AI says: {txt}")
