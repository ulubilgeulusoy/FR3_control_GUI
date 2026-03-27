#!/usr/bin/env python3
"""
robot_state_api.py

Small local HTTP API for explicit robot-state updates on the robot computer.

This is intended to run alongside the actual robot-control applications so they
can publish the four binary LSL flags directly, without relying on ROS topic
availability:

    - visual_servo_active
    - kt_active
    - arm_moving
    - gripper_moving

Endpoints:
    GET  /health
    GET  /state
    POST /state

POST /state body example:
{
  "visual_servo_active": 1,
  "arm_moving": 1,
  "ttl_sec": 0.5
}

If ttl_sec is provided, updated fields automatically fall back to 0 after the
TTL expires unless refreshed again by the application.
"""

from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Optional


HOST = os.environ.get("FR3_STATE_API_HOST", "127.0.0.1")
PORT = int(os.environ.get("FR3_STATE_API_PORT", "8765"))
STATE_FIELDS = (
    "visual_servo_active",
    "kt_active",
    "arm_moving",
    "gripper_moving",
)


class StateStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: Dict[str, int] = {field: 0 for field in STATE_FIELDS}
        self._expires_at: Dict[str, Optional[float]] = {field: None for field in STATE_FIELDS}
        self._updated_at = time.time()

    def snapshot(self) -> Dict[str, object]:
        now = time.time()
        with self._lock:
            values = {}
            for field in STATE_FIELDS:
                expires_at = self._expires_at[field]
                if expires_at is not None and now >= expires_at:
                    self._values[field] = 0
                    self._expires_at[field] = None
                values[field] = int(self._values[field])

            return {
                "state": values,
                "updated_at": self._updated_at,
                "now": now,
            }

    def update(self, payload: Dict[str, object]) -> Dict[str, object]:
        ttl_value = payload.get("ttl_sec")
        ttl_sec: Optional[float]
        if ttl_value is None:
            ttl_sec = None
        else:
            ttl_sec = max(0.0, float(ttl_value))

        now = time.time()
        with self._lock:
            for field in STATE_FIELDS:
                if field not in payload:
                    continue
                self._values[field] = 1 if bool(int(payload[field])) else 0
                self._expires_at[field] = (now + ttl_sec) if ttl_sec is not None else None
            self._updated_at = now

        return self.snapshot()


STORE = StateStore()


class RobotStateAPIHandler(BaseHTTPRequestHandler):
    server_version = "FR3RobotStateAPI/1.0"

    def _send_json(self, status: int, payload: Dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(200, {"ok": True})
            return
        if self.path == "/state":
            self._send_json(200, STORE.snapshot())
            return
        self._send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path != "/state":
            self._send_json(404, {"error": "not_found"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length)
            payload = json.loads(raw_body.decode("utf-8") or "{}")
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object")
            snapshot = STORE.update(payload)
        except Exception as exc:
            self._send_json(400, {"error": "bad_request", "detail": str(exc)})
            return

        self._send_json(200, snapshot)

    def log_message(self, fmt: str, *args) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), RobotStateAPIHandler)
    print(f"robot_state_api listening on http://{HOST}:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
