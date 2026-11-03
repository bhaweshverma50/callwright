"""A webhook receiver that fails a set number of times, then succeeds (003 T087, quickstart 7).

Library use (tests): ``FlakyReceiver(fail=2).start()`` runs it on 127.0.0.1 in a thread and
records every request. Command line::

    uv run python tests/integration/tools/flaky_receiver.py --fail 2 --port 9009 [--status 500]

Every request is printed with its ``Callwright-Signature`` header; pass ``--secret`` to verify it.
``--reply JSON`` answers successful requests with that JSON body instead of ``ok``, for example
the ``call_inbound`` reply of 010 quickstart section 9 (``--fail 0 --port 9010 --reply ...``).
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@dataclass
class Received:
    path: str
    headers: dict[str, str]
    body: bytes


@dataclass
class FlakyReceiver:
    fail: int = 2
    fail_status: int = 500
    delay_s: float = 0.0
    port: int = 0
    reply: bytes | None = None
    received: list[Received] = field(default_factory=list)
    _server: ThreadingHTTPServer | None = None

    @property
    def url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_address[1]}/hook"

    def start(self) -> FlakyReceiver:
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                receiver.received.append(Received(self.path, dict(self.headers.items()), body))
                if receiver.delay_s:
                    time.sleep(receiver.delay_s)
                failing = len(receiver.received) <= receiver.fail
                status = receiver.fail_status if failing else 200
                payload = b"nope" if failing else (receiver.reply or b"ok")
                try:
                    self.send_response(status)
                    if receiver.reply is not None and not failing:
                        self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, format: str, *args: object) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


def verify(secret: str, header: str, body: bytes, tolerance: int = 300) -> bool:
    """The receiver-side check from quickstart.md section 7."""
    parts = [p.split("=", 1) for p in header.split(",")]
    t = int(next(v for k, v in parts if k == "t"))
    if abs(time.time() - t) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, v) for k, v in parts if k == "v1")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fail", type=int, default=2)
    parser.add_argument("--status", type=int, default=500)
    parser.add_argument("--port", type=int, default=9009)
    parser.add_argument("--secret")
    parser.add_argument("--reply", help="JSON body for successful replies (default: ok)")
    args = parser.parse_args()
    reply = json.dumps(json.loads(args.reply)).encode() if args.reply else None
    receiver = FlakyReceiver(fail=args.fail, fail_status=args.status, port=args.port, reply=reply).start()
    print(
        f"listening on {receiver.url}; failing the first {args.fail} requests with {args.status}",
        flush=True,
    )
    seen = 0
    try:
        while True:
            time.sleep(0.2)
            for item in receiver.received[seen:]:
                signature = item.headers.get("Callwright-Signature", "")
                ok = verify(args.secret, signature, item.body) if args.secret else None
                print(
                    f"{item.headers.get('Callwright-Event')} "
                    f"{item.headers.get('Callwright-Delivery')} verified={ok}",
                    flush=True,
                )
            seen = len(receiver.received)
    except KeyboardInterrupt:
        receiver.stop()


if __name__ == "__main__":
    main()
