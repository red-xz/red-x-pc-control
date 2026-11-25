# -*- coding: utf-8 -*-
"""
Red-X PC Control Agent — runs on the user's own Windows PC.

Lets Red-X (the user's AI assistant) control this PC's mouse and keyboard
and see the screen, over the user's private Tailscale network only.

HOW IT WORKS
- A small HTTP server listens on this PC's Tailscale IP (100.x.x.x), port 8765.
- Every request must carry the secret token from config.json
  (header: X-Auth-Token). No token = no control.
- Red-X sends commands (move mouse, click, type, screenshot) and this
  agent executes them with PyAutoGUI.
- NOTHING runs in the background or at startup: the agent only works while
  this window is open. Press STOP (or close the window) and control ends
  immediately. Every command is printed in the console and shown in the
  window, so the user always sees what Red-X is doing.

REQUIREMENTS: Python 3.10+ with `pip install pyautogui pillow`
  (Red-X-PC-Control.bat does this automatically on Windows).

SAFETY
- Binds to the Tailscale IP only (never the public internet).
- Token auth on every endpoint.
- PyAutoGUI failsafe is ON: slamming the mouse into the top-left corner
  of the screen aborts the current action instantly.
- No file access, no shell commands, no persistence. Mouse, keyboard and
  screenshots only.
"""

import io
import json
import os
import secrets
import socket
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "1.0.0"
DEFAULT_PORT = 8765
MAX_BODY = 1 * 1024 * 1024  # 1 MB

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")

# Shared state (server thread -> status window)
STATE = {"last_command": "Waiting for Red-X...", "requests": 0, "started": ""}


# ---------------------------------------------------------------- config
def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if cfg.get("token"):
            return cfg
    # First run without a config: create one with a fresh random token.
    cfg = {"port": DEFAULT_PORT, "token": secrets.token_urlsafe(32)}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    print("[agent] created new config.json with a fresh token")
    return cfg


# ------------------------------------------------------- network helpers
def tailscale_ip():
    """Return this machine's Tailscale address (100.64-127.x.x), or None.

    UDP 'connect' sends no packets; it just asks the OS which local
    address it would use to reach Tailscale's reserved IP.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("100.100.100.100", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        if ip.startswith("100."):
            return ip
    except OSError:
        pass
    return None


# ------------------------------------------------------------ input layer
try:
    import pyautogui
except Exception as exc:  # noqa: BLE001 - show a clear error instead of a traceback
    print("[agent] ERROR: could not import pyautogui:", exc)
    print("[agent] Run Red-X-PC-Control.bat (it installs the requirements), then try again.")
    sys.exit(1)

pyautogui.FAILSAFE = True   # mouse to top-left corner aborts the action
pyautogui.PAUSE = 0.1


def take_screenshot():
    """Capture the screen as a PIL image.

    PyAutoGUI first (uses ImageGrab on Windows/macOS). On Linux newer
    pyscreeze needs gnome-screenshot, so fall back to scrot, then
    gnome-screenshot directly, so the agent works on any Linux box too.
    """
    try:
        return pyautogui.screenshot()
    except Exception:
        pass
    if not sys.platform.startswith("win"):
        import subprocess
        import tempfile

        from PIL import Image

        for cmd in (["scrot", "{f}"], ["gnome-screenshot", "-f", "{f}"]):
            try:
                with tempfile.NamedTemporaryFile(suffix=".png",
                                                 delete=False) as tmp:
                    path = tmp.name
                os.unlink(path)  # scrot writes nothing if the file exists
                subprocess.run([c.format(f=path) for c in cmd],
                               check=True, capture_output=True, timeout=15)
                img = Image.open(path)
                img.load()
                os.unlink(path)
                return img
            except Exception:
                continue
    raise RuntimeError("screenshot failed: no working capture method")


def screen_size():
    w, h = pyautogui.size()
    return {"width": int(w), "height": int(h)}


def clamp(x, y):
    w, h = pyautogui.size()
    return max(0, min(int(x), w - 1)), max(0, min(int(y), h - 1))


def set_clipboard_windows(text):
    """Put unicode text on the Windows clipboard (no extra dependency)."""
    import ctypes

    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    # 64-bit: ctypes defaults to c_int returns, which truncates handles.
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    data = text.encode("utf-16-le") + b"\x00\x00"
    for _ in range(10):  # another app may briefly hold the clipboard
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("could not open clipboard")
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            raise RuntimeError("GlobalAlloc failed")
        ptr = kernel32.GlobalLock(handle)
        ctypes.memmove(ptr, data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            raise RuntimeError("SetClipboardData failed")
    finally:
        user32.CloseClipboard()


def do_paste(text):
    """Type unicode text reliably: clipboard + Ctrl+V (Windows)."""
    if sys.platform.startswith("win"):
        set_clipboard_windows(text)
        time.sleep(0.1)
        pyautogui.hotkey("ctrl", "v")
    else:
        pyautogui.write(text, interval=0.02)


# -------------------------------------------------------------- HTTP API
class Handler(BaseHTTPRequestHandler):
    token = ""
    protocol_version = "HTTP/1.1"

    # -- plumbing ------------------------------------------------------
    def log_message(self, fmt, *args):  # keep the console clean; we log ourselves
        pass

    def _auth_ok(self):
        return self.headers.get("X-Auth-Token") == self.token

    def _json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def _note(self, text):
        STATE["requests"] += 1
        STATE["last_command"] = f"{datetime.now():%H:%M:%S}  {text}"
        print(f"[{datetime.now():%H:%M:%S}] {text}", flush=True)

    def _guard(self):
        if not self._auth_ok():
            self._json(401, {"ok": False, "error": "bad or missing token"})
            return False
        return True

    # -- GET -----------------------------------------------------------
    def do_GET(self):
        if not self._guard():
            return
        try:
            if self.path == "/status":
                self._json(200, {"ok": True, "version": VERSION,
                                 "screen": screen_size(),
                                 "requests": STATE["requests"]})
            elif self.path == "/mouse/position":
                x, y = pyautogui.position()
                self._json(200, {"ok": True, "x": int(x), "y": int(y)})
            elif self.path == "/screenshot":
                self._note("screenshot")
                img = take_screenshot()
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                data = buf.getvalue()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self._json(404, {"ok": False, "error": "unknown endpoint"})
        except Exception as exc:  # noqa: BLE001 - report failures as JSON, keep serving
            self._note(f"ERROR: {exc}")
            try:
                self._json(500, {"ok": False, "error": str(exc)})
            except Exception:
                pass

    # -- POST ----------------------------------------------------------
    def do_POST(self):
        if not self._guard():
            return
        try:
            body = self._read_json()
            p = self.path
            if p == "/mouse/move":
                x, y = clamp(body.get("x", 0), body.get("y", 0))
                pyautogui.moveTo(x, y, duration=float(body.get("duration", 0.2)))
                self._note(f"mouse move -> ({x}, {y})")
                self._json(200, {"ok": True, "x": x, "y": y})
            elif p == "/mouse/click":
                x, y = clamp(body.get("x", 0), body.get("y", 0))
                button = str(body.get("button", "left"))
                clicks = int(body.get("clicks", 1))
                pyautogui.click(x, y, button=button, clicks=clicks)
                self._note(f"mouse {button} click x{clicks} at ({x}, {y})")
                self._json(200, {"ok": True, "x": x, "y": y})
            elif p == "/mouse/drag":
                x1, y1 = clamp(body.get("x1", 0), body.get("y1", 0))
                x2, y2 = clamp(body.get("x2", 0), body.get("y2", 0))
                pyautogui.moveTo(x1, y1, duration=0.2)
                pyautogui.dragTo(x2, y2, duration=float(body.get("duration", 0.5)))
                self._note(f"mouse drag ({x1}, {y1}) -> ({x2}, {y2})")
                self._json(200, {"ok": True})
            elif p == "/mouse/scroll":
                clicks = int(body.get("clicks", 3))
                if "x" in body and "y" in body:
                    x, y = clamp(body["x"], body["y"])
                    pyautogui.moveTo(x, y, duration=0.1)
                pyautogui.scroll(clicks)
                self._note(f"mouse scroll {clicks}")
                self._json(200, {"ok": True})
            elif p == "/key/type":
                text = str(body.get("text", ""))
                pyautogui.write(text, interval=float(body.get("interval", 0.02)))
                self._note(f"type {len(text)} chars")
                self._json(200, {"ok": True, "chars": len(text)})
            elif p == "/key/paste":
                text = str(body.get("text", ""))
                do_paste(text)
                self._note(f"paste {len(text)} chars")
                self._json(200, {"ok": True, "chars": len(text)})
            elif p == "/key/press":
                key = str(body.get("key", ""))
                pyautogui.press(key)
                self._note(f"key press {key}")
                self._json(200, {"ok": True, "key": key})
            elif p == "/key/hotkey":
                keys = [str(k) for k in body.get("keys", [])]
                pyautogui.hotkey(*keys)
                self._note(f"hotkey {'+'.join(keys)}")
                self._json(200, {"ok": True, "keys": keys})
            elif p == "/shutdown":
                self._note("shutdown requested by Red-X")
                self._json(200, {"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                self._json(404, {"ok": False, "error": "unknown endpoint"})
        except Exception as exc:  # noqa: BLE001 - report failures as JSON, keep serving
            self._note(f"ERROR: {exc}")
            self._json(500, {"ok": False, "error": str(exc)})


# ------------------------------------------------------------ status window
def run_window(server, bind_ip, port, token=""):
    """Small always-on-top window: shows status + a STOP button."""
    try:
        import tkinter as tk
    except Exception:  # noqa: BLE001 - no GUI available: console mode
        print("[agent] tkinter not available — console mode (Ctrl+C to stop).")
        server.serve_forever()
        return

    root = tk.Tk()
    root.title("Red-X PC Control")
    root.attributes("-topmost", True)
    root.resizable(False, False)

    tk.Label(root, text="Red-X PC Control — RUNNING",
             font=("Segoe UI", 12, "bold"), fg="#0d9488").pack(padx=16, pady=(12, 2))
    tk.Label(root, text=f"Listening on {bind_ip}:{port}  (Tailscale only)",
             font=("Segoe UI", 10)).pack(padx=16)
    tk.Label(root, text="Red-X can move the mouse, type and see the screen.",
             font=("Segoe UI", 10)).pack(padx=16)
    if token:
        tk.Label(root, text="Token (Red-X-ke pathao):", font=("Segoe UI", 9, "bold"),
                 fg="#0f172a").pack(padx=16, pady=(8, 0))
        tk.Label(root, text=token, font=("Consolas", 9), fg="#0f172a",
                 wraplength=360, justify="left").pack(padx=16)
    last_var = tk.StringVar(value=STATE["last_command"])
    tk.Label(root, textvariable=last_var, font=("Consolas", 9),
             fg="#334155", wraplength=360, justify="left").pack(padx=16, pady=(8, 4))

    def stop():
        print("[agent] stopped by user (STOP button).", flush=True)
        threading.Thread(target=server.shutdown, daemon=True).start()
        root.destroy()

    tk.Button(root, text="STOP — বন্ধ করুন", command=stop, bg="#dc2626",
              fg="white", font=("Segoe UI", 11, "bold"),
              padx=20, pady=6).pack(pady=(6, 12))
    root.protocol("WM_DELETE_WINDOW", stop)

    def poll():
        last_var.set(STATE["last_command"])
        root.after(500, poll)

    root.after(500, poll)
    root.mainloop()


# ------------------------------------------------------------------- main
def main():
    cfg = load_config()
    port = int(cfg.get("port", DEFAULT_PORT))
    Handler.token = cfg["token"]

    bind_ip = tailscale_ip()
    if bind_ip is None:
        bind_ip = "127.0.0.1"
        print("[agent] WARNING: no Tailscale address found — listening on "
              "127.0.0.1 only. Start Tailscale and restart the agent.")
    STATE["started"] = datetime.now().strftime("%H:%M:%S")

    server = ThreadingHTTPServer((bind_ip, port), Handler)
    print(f"[agent] Red-X PC Control Agent v{VERSION}")
    print(f"[agent] Listening on http://{bind_ip}:{port}  (token auth ON)")
    print(f"[agent] Screen: {screen_size()}")
    print("[agent] Failsafe ON: move the mouse to the top-left corner to abort.")
    print("[agent] Press STOP in the window (or Ctrl+C here) to end control.")

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        run_window(server, bind_ip, port, cfg["token"])
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        print("[agent] stopped.")


if __name__ == "__main__":
    main()
