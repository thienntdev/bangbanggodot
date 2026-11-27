"""Flash socket policy — ports 843 and 41843 (xmlsocket://host:41843)."""
from __future__ import annotations

import socket
import threading
from server_logging import get_logger

log = get_logger('policy')

# Wildcard, no Adobe DTD (PepperFlash 26 hangs if the DTD fetch fails).
POLICY = (
    b'<?xml version="1.0"?>'
    b"<cross-domain-policy>"
    b'<allow-access-from domain="*" to-ports="*" secure="false"/>'
    b"</cross-domain-policy>\x00"
)


def _serve(port: int) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", port))
    except OSError as exc:
        log.exception("[policy] port %s bind failed", port)
        return
    sock.listen(32)
    log.info(f"[policy] listening :{port}")
    while True:
        conn, addr = sock.accept()
        threading.Thread(target=_one, args=(conn, addr, port), daemon=True).start()


def _one(conn: socket.socket, addr, port: int) -> None:
    try:
        conn.settimeout(5)
        data = conn.recv(256)
        log.debug("[policy:%s] %s %r", port, addr, data)
        conn.sendall(POLICY)
    except Exception as exc:
        log.warning("[policy:%s] %s error: %s", port, addr, exc)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def start_policy_servers() -> None:
    # 843 must answer instantly with the SAME XML as 41843 so Flash
    # does not wait 3s, connect :49119 too early, then FIN.
    for port in (843, 41843):
        threading.Thread(target=_serve, args=(port,), daemon=True).start()
