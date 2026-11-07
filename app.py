#!/usr/bin/env python3
"""Car Diagnostics web app (runs in the devcontainer).

python-OBD does the protocol + trouble-code decoding, stdlib http.server serves it.
Talks to the host agent (host/agent.py on the Mac) for device discovery and the serial bridge.

GET  /                dashboard page (guides every step)
GET  /api/agent       host agent reachable? which serial ports exist? which one is open?
POST /api/connect     {"port": "/dev/cu.X"}  ask the agent to open that port
POST /api/disconnect  close the port
GET  /api/scan        MIL, trouble codes with descriptions, live values
POST /api/clear       clear stored codes and reset the Check Engine light
"""
import json
import os
import threading
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import obd

OBD_PORT = os.environ.get("OBD_PORT", "socket://host.docker.internal:35000")
AGENT_URL = os.environ.get("AGENT_URL", "http://host.docker.internal:35001")
HTTP_PORT = int(os.environ.get("HTTP_PORT", "8000"))
HERE = os.path.dirname(os.path.abspath(__file__))

LIVE = [
    obd.commands.RPM,
    obd.commands.SPEED,
    obd.commands.COOLANT_TEMP,
    obd.commands.ENGINE_LOAD,
    obd.commands.INTAKE_TEMP,
    obd.commands.THROTTLE_POS,
    obd.commands.FUEL_LEVEL,
    obd.commands.ELM_VOLTAGE,
]

_lock = threading.Lock()
_conn: obd.OBD | None = None


# ---------------------------------------------------------------- host agent
def agent(path: str, body: dict | None = None) -> tuple[dict, int]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(AGENT_URL + path, data=data, headers={"Content-Type": "application/json"},
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.load(r), 200
    except urllib.error.HTTPError as exc:
        return json.load(exc), exc.code
    except (urllib.error.URLError, OSError) as exc:
        return {"agent": False, "error": str(getattr(exc, "reason", exc))}, 503


def agent_state() -> dict:
    status, code = agent("/status")
    if code != 200:
        return {"agent": False, "error": status.get("error")}
    ports, _ = agent("/ports")
    return {"agent": True, **status, "ports": ports.get("ports", [])}


# ------------------------------------------------------------------- python-OBD
def drop_connection() -> None:
    global _conn
    if _conn is not None:
        try:
            _conn.close()
        except Exception:
            pass
    _conn = None


def connection() -> obd.OBD:
    global _conn
    if _conn is None or not _conn.is_connected():
        # ponytail: fast=False for V2.1 clones; fixed baud because auto-baud probing fails over socket://
        _conn = obd.OBD(OBD_PORT, baudrate=38400, fast=False, timeout=5)
    return _conn


def query(conn: obd.OBD, cmd):
    r = conn.query(cmd)
    return None if r.is_null() else r.value


def codes(conn: obd.OBD, cmd) -> list[dict]:
    v = query(conn, cmd) or []
    return [{"code": c, "description": d or "Manufacturer-specific code (no generic description)"} for c, d in v]


def scan() -> dict:
    with _lock:
        conn = connection()
        if not conn.is_connected():
            return {"connected": False, "status": conn.status()}
        status = query(conn, obd.commands.STATUS)
        live = {}
        for cmd in LIVE:
            v = query(conn, cmd)
            if v is not None:
                live[cmd.name] = {"value": round(float(v.magnitude), 1), "unit": f"{v.units:~P}", "desc": cmd.desc}
        return {
            "connected": True,
            "protocol": conn.protocol_name(),
            "mil": bool(status.MIL) if status else None,
            "dtc_count": status.DTC_count if status else None,
            "stored": codes(conn, obd.commands.GET_DTC),
            "pending": codes(conn, obd.commands.GET_CURRENT_DTC),
            "live": live,
        }


def clear() -> dict:
    with _lock:
        conn = connection()
        if not conn.is_connected():
            return {"ok": False, "error": "not connected"}
        conn.query(obd.commands.CLEAR_DTC)
        return {"ok": True}


# ------------------------------------------------------------------------ HTTP
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=HERE, **kw)

    def _json(self, payload: dict, code: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if self.path == "/":
            self.path = "/index.html"
        if self.path == "/api/agent":
            return self._json(agent_state())
        if self.path == "/api/scan":
            try:
                return self._json(scan())
            except Exception as exc:  # adapter dropped mid-scan etc.
                drop_connection()
                return self._json({"connected": False, "error": str(exc)}, 500)
        return super().do_GET()

    def do_POST(self):
        if self.path == "/api/connect":
            with _lock:
                drop_connection()
                res, code = agent("/open", {"port": self._body().get("port", "")})
            return self._json(res, code)
        if self.path == "/api/disconnect":
            with _lock:
                drop_connection()
                res, code = agent("/close", {})
            return self._json(res, code)
        if self.path == "/api/clear":
            return self._json(clear())
        self._json({"error": "not found"}, 404)

    def log_message(self, fmt, *args):
        if "/api/agent" not in str(args[0] if args else ""):  # polled every few seconds, keep log quiet
            super().log_message(fmt, *args)


if __name__ == "__main__":
    print(
        "\nCar Diagnostics\n"
        f"  Web page:  http://localhost:{HTTP_PORT}   (VS Code opens it automatically; if not, click the link)\n"
        "  The page shows what to do next: start the Mac agent, pick the OBDII device, press Connect.\n"
        f"  Host agent expected at {AGENT_URL}, data bridge at {OBD_PORT}\n",
        flush=True,
    )
    ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), Handler).serve_forever()
