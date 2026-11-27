"""Explicit Windows local-admin launcher; never grants or bypasses startup checks."""
from __future__ import annotations

import os
from pathlib import Path
import platform
import socket
import struct
import sys


ROOT = Path(__file__).resolve().parents[1]
PORTS = (843, 41843, 18083, 18443, 49119)


def check_runtime():
    if (sys.platform != 'win32' or platform.python_implementation() != 'CPython' or
            sys.version_info[:3] != (3, 13, 15) or struct.calcsize('P') != 8):
        raise RuntimeError('Can Windows CPython 3.13.15 64-bit da dung cho server. Khong doi moi truong de bo qua kiem tra.')
    target = Path(os.environ.get('BB_DATABASE', str(ROOT / 'data' / 'bangbang.sqlite3')))
    if not target.is_absolute():
        target = ROOT / target
    if not target.is_file():
        raise RuntimeError('Khong tim thay SQLite game hien tai. Dung dung SERVER_BB da cai M29; khong bootstrap DB moi.')
    # Read-only checks. A timeout/10035 or unexpected socket error is NOT
    # interpreted as proof that an existing server stopped. Never kill it.
    for port in PORTS:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.75)
            try:
                probe.connect(('127.0.0.1', port))
            except ConnectionRefusedError:
                continue
            except OSError as exc:
                raise RuntimeError('Khong xac nhan duoc cong ' + str(port) + ' da dong; dung de kiem tra.') from exc
            raise RuntimeError('Cong ' + str(port) + ' dang mo. Tat server cu truoc; khong chay hai server.')


def main():
    os.chdir(ROOT)
    check_runtime()
    print('Web buff local: http://127.0.0.1:18083/admin/buff/')
    print('Game cung server: http://127.0.0.1:18083/html5/')
    print('Khong gui qua tu dong. Chi gui thu sau khi ban xem truoc va bam xac nhan.')
    print('Khoa nam ngoai www tai data/admin_buff.key; khong chia se khoa.')
    import app
    sys.argv = [str(ROOT / 'server' / 'app.py'), '--bind', '127.0.0.1', '--enable-admin-buff']
    app.main()


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError) as exc:
        print('DUNG: ' + str(exc), file=sys.stderr)
        sys.exit(1)
