#!/usr/bin/env python3
"""Controller client for a Red-X PC Control agent running on a Windows PC.

The agent runs on the PC (see agent.py). This client runs on the
controller's machine -- e.g. another Muse instance -- and talks to the
agent over the PC's Tailscale network.

Setup:
  1. Copy client-config.example.json to client-config.json and fill in
     the PC's Tailscale IP (host), port (8765) and token (shown in the
     agent's window on the PC).
  2. Make sure this machine can reach the PC's Tailscale IP: join the
     same Tailscale network as the PC, or use your environment's
     Tailscale tunnel/proxy (this client honours the HTTPS_PROXY
     environment variable).
  3. python3 redx-client.py status

Usage: redx-client.py <command> [args...]
  status                      agent status + screen size
  shot <file>                 save a screenshot PNG
  pos                         current mouse position
  move <x> <y>                move mouse
  click <x> <y> [btn] [n]     click (btn: left/right/middle, n: clicks)
  drag <x1> <y1> <x2> <y2>     drag
  scroll <n> [x y]            scroll (n>0 up, n<0 down)
  type <text>                 type ASCII text
  paste <text>                paste text via clipboard (unicode-safe)
  press <key>                 press one key (enter, esc, tab, ...)
  hotkey <k1> <k2> ...         key combination (ctrl s, alt tab, ...)
  shutdown                    stop the agent on the PC
"""
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "client-config.json")


def _config():
    if not os.path.exists(CONFIG):
        print("Copy client-config.example.json to client-config.json "
              "and fill in the PC's host and token first.")
        sys.exit(2)
    with open(CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["host"] = os.environ.get("REDX_PC_HOST", cfg.get("host", ""))
    cfg["port"] = int(os.environ.get("REDX_PC_PORT", cfg.get("port", 8765)))
    cfg["token"] = os.environ.get("REDX_PC_TOKEN", cfg.get("token", ""))
    if not cfg["host"] or not cfg["token"]:
        print("Set the PC's host and token in client-config.json "
              "(or REDX_PC_HOST / REDX_PC_TOKEN env vars).")
        sys.exit(2)
    return cfg


def call(method, path, payload=None, out_file=None):
    cfg = _config()
    url = "http://%s:%d%s" % (cfg["host"], cfg["port"], path)
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("X-Auth-Token", cfg["token"])
    if data:
        req.add_header("Content-Type", "application/json")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler())
    with opener.open(req, timeout=100) as resp:
        body = resp.read()
    if out_file:
        with open(out_file, "wb") as f:
            f.write(body)
        return {"ok": True, "saved": out_file, "bytes": len(body)}
    try:
        return json.loads(body.decode("utf-8"))
    except ValueError:
        return {"ok": True, "raw": body[:200].decode("utf-8", "replace")}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd, a = sys.argv[1], sys.argv[2:]
    if cmd == "status":
        print(call("GET", "/status"))
    elif cmd == "shot":
        print(call("GET", "/screenshot", out_file=a[0]))
    elif cmd == "pos":
        print(call("GET", "/mouse/position"))
    elif cmd == "move":
        print(call("POST", "/mouse/move", {"x": int(a[0]), "y": int(a[1])}))
    elif cmd == "click":
        p = {"x": int(a[0]), "y": int(a[1])}
        if len(a) > 2:
            p["button"] = a[2]
        if len(a) > 3:
            p["clicks"] = int(a[3])
        print(call("POST", "/mouse/click", p))
    elif cmd == "drag":
        print(call("POST", "/mouse/drag",
                   {"x1": int(a[0]), "y1": int(a[1]),
                    "x2": int(a[2]), "y2": int(a[3])}))
    elif cmd == "scroll":
        p = {"clicks": int(a[0])}
        if len(a) > 2:
            p["x"], p["y"] = int(a[1]), int(a[2])
        print(call("POST", "/mouse/scroll", p))
    elif cmd == "type":
        print(call("POST", "/key/type", {"text": " ".join(a)}))
    elif cmd == "typefile":
        with open(a[0], "r", encoding="utf-8") as f:
            print(call("POST", "/key/type", {"text": f.read()}))
    elif cmd == "paste":
        print(call("POST", "/key/paste", {"text": " ".join(a)}))
    elif cmd == "pastefile":
        with open(a[0], "r", encoding="utf-8") as f:
            print(call("POST", "/key/paste", {"text": f.read()}))
    elif cmd == "press":
        print(call("POST", "/key/press", {"key": a[0]}))
    elif cmd == "hotkey":
        print(call("POST", "/key/hotkey", {"keys": a}))
    elif cmd == "shutdown":
        print(call("POST", "/shutdown"))
    else:
        print("unknown command:", cmd)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
