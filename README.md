# Red-X PC Control

Let your AI assistant see your screen and drive your mouse and keyboard — while you watch everything it does, and only while the app is open.

I built this because I wanted help on my own PC without handing it over to a stranger on the internet. The agent runs on your Windows PC, listens only on your private Tailscale network (never the public internet), and every command needs a secret token that is generated on your machine on first run. Close the window or hit STOP and the control ends instantly. Move the mouse to the top-left corner and whatever it is doing aborts on the spot.

## What it can do

- Move the mouse, click, type, press keys
- Take screenshots so the assistant can see what is happening
- Nothing else: no file access, no shell commands, no background service, no autostart

## Setup (Windows)

1. Download the latest zip from [Releases](../../releases) and unzip it anywhere, e.g. Desktop.
2. Double-click **`Red-X-PC-Control.bat`**. That's it.

On first run it installs Python and Tailscale by itself if they are missing (needs internet, takes 2–3 minutes). Windows may ask you to click "Yes" once, and Tailscale will ask you to sign in with Google in the browser once. After that, a small window appears saying `Red-X PC Control — RUNNING`, with a Tailscale address like `100.64.x.x:8765` and a token. Send that address and token to your assistant — that is how it connects and checks the screen.

From the second run on, just double-click the same file.

## How it works

- A tiny HTTP server listens on the PC's Tailscale IP, port 8765.
- Every request must carry the token in the `X-Auth-Token` header. No token, no control.
- The agent executes commands with PyAutoGUI. The failsafe is on: slam the mouse into the top-left corner to abort.
- The token lives in `config.json` next to `agent.py`. It is created on first run if the file has an empty token — don't share it with anyone except the assistant you want to control the PC.

## Requirements

- Windows 10/11
- Python 3.10+ and `pip install pyautogui pillow` — the one-click file handles this for you
- A Tailscale account (free) — same network as the machine controlling it

## Files

| File | What it is |
| --- | --- |
| `agent.py` | The agent: HTTP server + status window (runs on the PC) |
| `Red-X-PC-Control.bat` | One-click start (installs Python/Tailscale if missing) |
| `config.json` | Port + token (token is generated on first run) |
| `requirements.txt` | `pyautogui`, `pillow` |
| `SETUP-BANGLA.md` | Setup guide in Bengali |
| `redx-client.py` | Controller client (runs on the assistant's machine) |
| `client-config.example.json` | Template for the client's host + token |

## Control the PC from another assistant

The agent on the PC doesn't care which assistant talks to it — anyone on
the same Tailscale network with the token can control it. To use a
different assistant (e.g. a new Muse account):

1. On the PC: run the agent as above. The window shows the Tailscale
   address (like `100.64.x.x:8765`) and a token.
2. On the assistant's machine: copy `client-config.example.json` to
   `client-config.json` and fill in the PC's address (`host`), port
   (`8765`) and token. Or set the `REDX_PC_HOST` / `REDX_PC_TOKEN`
   environment variables instead.
3. Make sure the assistant's machine can reach the PC's Tailscale IP —
   join the same Tailscale network as the PC (first connection needs
   the network owner's approval once).
4. Check it: `python3 redx-client.py status` — then `python3
   redx-client.py shot screen.png` to see the screen.

After that the assistant works step by step: screenshot, one click or
keystroke, screenshot again. Close the agent window (or hit STOP) on the
PC and the control ends — no matter which assistant was connected.

## License

MIT — do what you want with it, just don't blame me if you give your token to the wrong person.
