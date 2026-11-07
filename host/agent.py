#!/usr/bin/env python3
"""Car Diagnostics host agent. Runs on the Mac with the stock /usr/bin/python3, stdlib only.

Started by double-clicking "Run Diagnostics.command". Nothing is installed.
Exposes two local-only endpoints the devcontainer reaches via host.docker.internal:

  control  http://127.0.0.1:35001   GET /ports   GET /status   POST /open {"port": "/dev/cu.X"}   POST /close
  data     tcp://127.0.0.1:35000    raw ELM327 bytes bridged to the opened serial port
"""
import glob
import json
import os
import select
import socket
import termios
import threading
import tty
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CONTROL_PORT = 35001
DATA_PORT = 35000
SKIP = ("Bluetooth-Incoming-Port", "debug-console", "wlan-debug")
HINT = "Is the dongle paired in Bluetooth settings, plugged into the car, and the ignition on?"

state = {"fd": None, "port": None, "client": False, "error": None}
lock = threading.Lock()


def log(msg: str) -> None:
    print(msg, flush=True)


def list_ports() -> list[dict]:
    ports = [p for p in sorted(glob.glob("/dev/cu.*")) if not any(s in p for s in SKIP)]
    return [{"path": p, "suggested": any(k in p.upper() for k in ("OBD", "ELM", "SPP"))} for p in ports]


def open_serial(path: str) -> int:
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    tty.setraw(fd)
    attrs = termios.tcgetattr(fd)
    attrs[2] |= termios.CLOCAL | termios.CREAD
    attrs[4] = attrs[5] = termios.B38400  # ponytail: ignored by Bluetooth SPP, matters for USB ELM327
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    return fd


def close_serial() -> None:
    with lock:
        if state["fd"] is not None:
            try:
                os.close(state["fd"])
            except OSError:
                pass
        state["fd"] = None
        state["port"] = None


def set_port(path: str) -> None:
    close_serial()
    fd = open_serial(path)  # raises OSError with a readable strerror
    with lock:
        state["fd"] = fd
        state["port"] = path
        state["error"] = None
    log(f"✓ opened {path}")


def pump(conn: socket.socket) -> str:
    conn.setblocking(False)
    while True:
        fd = state["fd"]
        if fd is None:
            return "no serial port open"
        ready, _, _ = select.select([fd, conn], [], [], 1.0)
        if fd in ready:
            data = os.read(fd, 4096)
            if not data:
                close_serial()
                return "serial port closed by device"
            conn.sendall(data)
        if conn in ready:
            data = conn.recv(4096)
            if not data:
                return "client disconnected"
            os.write(fd, data)


def data_server() -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", DATA_PORT))
    srv.listen(1)
    while True:
        conn, _ = srv.accept()
        state["client"] = True
        try:
            reason = pump(conn)
        except (OSError, ValueError) as exc:
            reason = f"{exc}. {HINT}"
            state["error"] = reason
            close_serial()
        finally:
            conn.close()
            state["client"] = False
        log(f"  data link ended: {reason}")


class Control(BaseHTTPRequestHandler):
    def _json(self, payload: dict, code: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/ports":
            return self._json({"ports": list_ports()})
        if self.path == "/status":
            return self._json({"port": state["port"], "client": state["client"], "error": state["error"]})
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/open":
            path = str(body.get("port", ""))
            if not path.startswith("/dev/"):
                return self._json({"ok": False, "error": "port must be a /dev/ path"}, 400)
            try:
                set_port(path)
            except OSError as exc:
                msg = f"Could not open {path}: {exc.strerror}. {HINT}"
                log(f"✗ {msg}")
                return self._json({"ok": False, "error": msg}, 400)
            return self._json({"ok": True, "port": path})
        if self.path == "/close":
            close_serial()
            log("  serial port closed")
            return self._json({"ok": True})
        self._json({"error": "not found"}, 404)

    def log_message(self, *args):  # keep the Terminal window readable
        pass


def main() -> None:
    threading.Thread(target=data_server, daemon=True).start()
    ports = list_ports()
    log("Car Diagnostics agent is running. Leave this window open while you use the browser page.")
    log("Serial ports visible now: " + (", ".join(p["path"] for p in ports) or "none"))
    if not any(p["suggested"] for p in ports):
        log("No OBDII port yet. Pair the dongle: System Settings → Bluetooth → OBDII, PIN 1234 (or 0000).")
    log("Next step: in the browser page, pick the OBDII device and press Connect.\n")
    try:
        ThreadingHTTPServer(("127.0.0.1", CONTROL_PORT), Control).serve_forever()
    except KeyboardInterrupt:
        close_serial()
        log("\nagent stopped")


if __name__ == "__main__":
    main()
