"""Portable entry point. Run with the bundled interpreter; no global Python/pip."""
from __future__ import annotations
import argparse
import contextlib
import json
import os
from pathlib import Path
import platform
import socket
import sqlite3
import sys
import threading
import time
import uuid
import webbrowser
from urllib.request import urlopen, build_opener, ProxyHandler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))

def available_port(start):
    for port in range(start, start + 30):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if os.name == 'nt':
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                probe.bind(('127.0.0.1', port))
            except OSError:
                continue
            return port
    raise RuntimeError('Không tìm được cổng local còn trống. Đóng server cũ rồi thử lại.')

def health(url, instance):
    if not url.startswith('http://127.0.0.1:'):
        return False
    try:
        with build_opener(ProxyHandler({})).open(url + '/health', timeout=1) as response:
            data = json.load(response)
        return data.get('ok') is True and data.get('instance') == instance
    except (OSError, ValueError):
        return False

def open_pages(url):
    for route in ('/html5/', '/admin/buff/'):
        try:
            webbrowser.open(url + route, new=2)
        except OSError:
            print('Mở trình duyệt tại:', url + route, flush=True)

@contextlib.contextmanager
def project_lock(directory):
    import msvcrt
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / 'server.lock', 'a+b') as handle:
        if handle.tell() == 0:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

def main():
    parser = argparse.ArgumentParser(description='BangBang portable')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--check', action='store_true')
    # Development checks use a copied DB and separate state/key; never reset saves.
    parser.add_argument('--database', type=Path, default=ROOT / 'data/bangbang.sqlite3')
    parser.add_argument('--state-dir', type=Path, default=ROOT / 'runtime/state')
    parser.add_argument('--admin-key', type=Path, default=ROOT / 'data/admin_buff.key')
    args = parser.parse_args()
    os.chdir(ROOT)
    if os.name != 'nt' or sys.maxsize < 2**32:
        raise RuntimeError('Gói portable này dành cho Windows 64-bit.')
    if sys.version_info[:3] != (3, 13, 15):
        raise RuntimeError('Hãy chạy Choi_Ngay.bat để dùng đúng Python đi kèm.')
    database = args.database.resolve()
    if not database.is_file():
        raise RuntimeError('Thiếu database mẫu. Giải nén đầy đủ gói game; không tự tạo hoặc ghi đè save.')
    os.environ['BB_DATABASE'] = str(database)
    os.environ['BB_ACCELERATION'] = 'auto'
    from cpp_backend import initialize, status
    initialize()
    if args.check:
        with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise RuntimeError('Database không vượt qua kiểm tra toàn vẹn.')
        print(json.dumps({'python': platform.python_version(), 'database': 'ok', 'combat': status()}, ensure_ascii=False))
        return 0
    args.state_dir = args.state_dir.resolve()
    ready_file = args.state_dir / 'ready.json'
    with project_lock(args.state_dir) as acquired:
        if not acquired:
            try:
                existing = json.loads(ready_file.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                raise RuntimeError('Server đang khởi động. Chờ một lát, không cần bấm nhiều lần.')
            if health(existing['url'], existing['instance']):
                print('Server đã chạy:', existing['url'])
                if not args.no_browser:
                    open_pages(existing['url'])
                return 0
            raise RuntimeError('Bản game này đang chạy hoặc đang khởi động. Xem cửa sổ server đã mở.')
        http_port, native_port = available_port(19083), available_port(49119)
        instance = uuid.uuid4().hex
        os.environ['BB_LAUNCH_ID'] = instance
        base = f'http://127.0.0.1:{http_port}'
        ready = threading.Event(); stopping = threading.Event()
        print('BANG BANG — M45 portable + xác nhận EXP dư', flush=True)
        print('Đang khởi động. Giữ cửa sổ này trong khi chơi.', flush=True)
        print('Game:', base + '/html5/', flush=True)
        print('Web buff:', base + '/admin/buff/', flush=True)
        print('Khóa mở web buff:', args.admin_key.resolve(), flush=True)
        print('Ghi log mặc định TẮT. Có thể bật/tắt trong web buff.', flush=True)
        print('Thoát game về sảnh rồi nhấn Ctrl+C tại đây để dừng.', flush=True)
        def when_ready():
            for _ in range(180):
                if stopping.wait(.5):
                    return
                if not health(base, instance):
                    continue
                ready_file.write_text(json.dumps(dict(url=base, instance=instance, pid=os.getpid(), native_port=native_port)), encoding='utf-8')
                ready.set()
                print('SẴN SÀNG — đóng cửa sổ này sẽ dừng server.', flush=True)
                if not args.no_browser:
                    open_pages(base)
                return
            print('Chưa sẵn sàng sau 90 giây. Xem lỗi ở cửa sổ này; chưa tự mở trình duyệt.', flush=True)
        worker = threading.Thread(target=when_ready, daemon=True)
        worker.start()
        import app
        sys.argv = [str(ROOT / 'server/app.py'), '--bind', '127.0.0.1', '--port', str(http_port),
                    '--html5-local', '--native-port', str(native_port), '--enable-admin-buff',
                    '--admin-key-file', str(args.admin_key.resolve()), '--log-level', 'WARNING']
        try:
            app.main()
        finally:
            stopping.set();worker.join(timeout=2)
            ready_file.unlink(missing_ok=True)
        return 0 if ready.is_set() else 1

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('\nĐã dừng server.')
    except Exception as exc:
        print('\nKHÔNG KHỞI ĐỘNG ĐƯỢC:', exc, file=sys.stderr)
        raise SystemExit(1)
