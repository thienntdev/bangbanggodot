"""Explicitly enabled, same-origin loopback-only offline gift-mail admin API.

There is no anonymous grant route, URL secret, direct inventory grant or CORS.
The random operator key is created outside www only by --enable-admin-buff.
Successful HTTP sends enqueue durable mail; a game GATE claim delivers it.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
from pathlib import Path
import posixpath
import re
import secrets
import ssl
import stat
import threading
import time
from urllib.parse import parse_qs, unquote, urlsplit

import storage
import offline_mail
import mail_rewards
from mail_rewards import RewardError

COOKIE = 'bb_admin_session'
PREFIX = '/api/admin/'
MAX_BODY = 32768
SESSION_SECONDS = 1800
PREVIEW_SECONDS = 300
_TOKEN = re.compile(r'^[0-9a-f]{64}$')
_REQUEST_ID = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
_access = None


class AdminError(RewardError):
    def __init__(self, status, code, message, details=None):
        super().__init__(code, message, details)
        self.status = status


class Access:
    def __init__(self, secret):
        if not isinstance(secret, str) or not _TOKEN.fullmatch(secret):
            raise ValueError('Admin key must be a random 256-bit hex key')
        self.secret_hash = hashlib.sha256(secret.encode('ascii')).digest()
        self.sessions = {}
        self.failures = []
        self.lock = threading.RLock()

    def unlock(self, secret):
        now = time.time()
        with self.lock:
            self.failures = [stamp for stamp in self.failures if now - stamp < 60]
            if len(self.failures) >= 5:
                raise AdminError(429, 'rate_limited', 'Đã nhập sai nhiều lần. Chờ một phút rồi thử lại.')
            valid = isinstance(secret, str) and _TOKEN.fullmatch(secret)
            hashed = hashlib.sha256(secret.encode('ascii')).digest() if valid else b''
            if not valid or not secrets.compare_digest(hashed, self.secret_hash):
                self.failures.append(now)
                raise AdminError(401, 'unlock_failed', 'Khóa quản trị không đúng.')
            self._prune(now)
            if len(self.sessions) >= 8:
                raise AdminError(429, 'session_limit', 'Đã mở đủ 8 phiên quản trị. Đăng xuất phiên cũ hoặc chờ hết hạn.')
            token = secrets.token_hex(32)
            entry = dict(csrf=secrets.token_hex(32), expires_at=int(now) + SESSION_SECONDS,
                         previews={}, session_id=secrets.token_hex(16))
            self.sessions[hashlib.sha256(token.encode('ascii')).digest()] = entry
            self.failures.clear()
            return token, entry

    def _prune(self, now):
        for key in list(self.sessions):
            if self.sessions[key]['expires_at'] <= now:
                del self.sessions[key]

    def session(self, token):
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            return None
        with self.lock:
            self._prune(time.time())
            return self.sessions.get(hashlib.sha256(token.encode('ascii')).digest())

    def logout(self, token):
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            return
        with self.lock:
            self.sessions.pop(hashlib.sha256(token.encode('ascii')).digest(), None)

    def prove(self, session, payload_hash):
        now = int(time.time())
        with self.lock:
            proofs = session['previews']
            for token in list(proofs):
                if proofs[token]['expires_at'] <= now:
                    del proofs[token]
            if len(proofs) >= 32:
                proofs.pop(next(iter(proofs)))
            token = secrets.token_hex(32)
            proofs[token] = dict(payload_hash=payload_hash, expires_at=now + PREVIEW_SECONDS)
            return token, now + PREVIEW_SECONDS

    def check_proof(self, session, token, payload_hash):
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            return False
        with self.lock:
            proof = session['previews'].get(token)
            return bool(proof and proof['expires_at'] > time.time() and
                        secrets.compare_digest(proof['payload_hash'], payload_hash))


def _safe_key_path(path):
    path = Path(path).absolute()
    # A key in any served directory is forbidden, including paths containing ..
    # or symlinks that would otherwise disguise the resolved location.
    if '..' in path.parts:
        raise ValueError('Admin key path must not contain parent traversal')
    served = (storage.ROOT / 'www').resolve()
    if path == served or served in path.parents:
        raise ValueError('Admin key must be outside www')
    for part in [*reversed(path.parents), path]:
        try:
            record = part.lstat()
        except FileNotFoundError:
            if part == path:
                break
            raise ValueError('Admin key parent must already exist')
        if stat.S_ISLNK(record.st_mode) or getattr(record, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Admin key path must not contain symlinks/reparse points')
    return path


def enable(key_path=None):
    """Only called by the explicit CLI flag. Never print or log key contents."""
    global _access
    path = _safe_key_path(key_path or storage.ROOT / 'data' / 'admin_buff.key')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        value = secrets.token_hex(32).encode('ascii') + b'\n'
        create = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
        fd = os.open(path, create, 0o600)
        try:
            os.write(fd, value)
            os.fsync(fd)
        finally:
            os.close(fd)
        fd = os.open(path, flags)
    with os.fdopen(fd, 'rb') as stream:
        record = os.fstat(stream.fileno())
        # Recheck both ancestry and final identity after opening. An attacker
        # replacing a name while it is being checked must never make us read a
        # different key through an unchecked symlink/reparse point.
        checked = _safe_key_path(path).lstat()
        if (record.st_dev, record.st_ino) != (checked.st_dev, checked.st_ino):
            raise ValueError('Admin key changed while opening')
        if not stat.S_ISREG(record.st_mode) or record.st_nlink != 1 or record.st_size > 128:
            raise ValueError('Admin key must be a small private regular file')
        if os.name != 'nt' and (record.st_mode & 0o077 or record.st_uid != os.getuid()):
            raise ValueError('Admin key must be owned by this account and chmod 600')
        secret = stream.read(129).strip().decode('ascii')
    _access = Access(secret)
    import admin_accounts
    admin_accounts.initialize()
    return path


def enabled():
    return _access is not None


def page_path(path):
    # Match SimpleHTTPRequestHandler's decoded/normalised served path too, so
    # percent-encoding or dot segments cannot bypass the local-only page guard.
    try:
        decoded = unquote(path, errors='surrogatepass')
    except UnicodeDecodeError:
        decoded = unquote(path)
    normalized = posixpath.normpath(decoded)
    return normalized == '/admin/buff' or normalized.startswith('/admin/buff/')


def _single(handler, name, required=False):
    values = handler.headers.get_all(name, [])
    if len(values) > 1 or required and not values:
        raise AdminError(400, 'header_invalid', 'Header quản trị không hợp lệ.')
    return values[0] if values else None


def guard(handler, *, mutation=False):
    """Check actual peer + exact loopback authority, never X-Forwarded-*.

    Host protects against DNS rebinding. All mutations require an exact Origin
    and JSON; an authenticated cookie also needs the separate CSRF header.
    """
    try:
        peer = ipaddress.ip_address(handler.client_address[0])
    except ValueError as exc:
        raise AdminError(403, 'local_only', 'Web quản trị chỉ mở trên máy chạy server.') from exc
    if not peer.is_loopback:
        raise AdminError(403, 'local_only', 'Web quản trị chỉ mở trên máy chạy server.')
    host = _single(handler, 'Host', True)
    port = int(handler.server.server_address[1])
    allowed = {f'127.0.0.1:{port}', f'localhost:{port}', f'[::1]:{port}'}
    secure = isinstance(handler.connection, ssl.SSLSocket)
    if port == (443 if secure else 80):
        allowed.update(('127.0.0.1', 'localhost', '[::1]'))
    if host not in allowed:
        raise AdminError(403, 'host_invalid', 'Dùng đúng địa chỉ localhost hoặc 127.0.0.1 và cổng server.')
    origin = _single(handler, 'Origin', mutation)
    expected = ('https://' if secure else 'http://') + host
    if origin is not None and origin != expected:
        raise AdminError(403, 'origin_invalid', 'Nguồn yêu cầu không khớp trang quản trị.')
    fetch_site = _single(handler, 'Sec-Fetch-Site')
    if fetch_site is not None and fetch_site not in ('none', 'same-origin'):
        raise AdminError(403, 'origin_invalid', 'Không cho phép website khác gọi quản trị local.')
    if _single(handler, 'Transfer-Encoding') is not None:
        raise AdminError(400, 'body_invalid', 'Không hỗ trợ Transfer-Encoding cho quản trị.')
    if mutation:
        ctype = _single(handler, 'Content-Type', True)
        if ctype.lower() not in ('application/json', 'application/json; charset=utf-8'):
            raise AdminError(415, 'content_type', 'Yêu cầu quản trị phải dùng JSON.')


def _cookie(handler):
    raw = _single(handler, 'Cookie') or ''
    if len(raw) > 8192:
        raise AdminError(400, 'cookie_invalid', 'Cookie quá dài.')
    found = []
    for part in raw.split(';'):
        key, sep, value = part.strip().partition('=')
        if sep and key == COOKIE:
            found.append(value)
    if len(found) > 1:
        raise AdminError(400, 'cookie_invalid', 'Cookie quản trị bị lặp.')
    return found[0] if found else None


def _json_body(handler):
    value = _single(handler, 'Content-Length', True)
    if not value.isdecimal() or not 2 <= int(value) <= MAX_BODY:
        raise AdminError(413, 'body_limit', 'Nội dung yêu cầu vượt giới hạn quản trị.')
    previous_timeout = handler.connection.gettimeout()
    try:
        handler.connection.settimeout(10)
        raw = handler.rfile.read(int(value))
    except TimeoutError as exc:
        raise AdminError(408, 'body_timeout', 'Yêu cầu quản trị gửi quá chậm; chưa thực hiện thao tác.') from exc
    finally:
        handler.connection.settimeout(previous_timeout)
    if len(raw) != int(value):
        raise AdminError(400, 'body_invalid', 'Nội dung yêu cầu chưa đầy đủ.')
    def pairs(values):
        result = {}
        for key, item in values:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = item
        return result
    try:
        body = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
    except (UnicodeError, ValueError) as exc:
        raise AdminError(400, 'json_invalid', 'JSON không hợp lệ.') from exc
    if not isinstance(body, dict):
        raise AdminError(400, 'json_invalid', 'Nội dung JSON phải là object.')
    return body


def _send(handler, status, value, *, cookie=None, clear=False):
    raw = offline_mail.json_text(value).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('X-Content-Type-Options', 'nosniff')
    handler.send_header('Referrer-Policy', 'no-referrer')
    handler.send_header('X-Frame-Options', 'DENY')
    handler.send_header('Content-Security-Policy', "default-src 'none'; frame-ancestors 'none'")
    handler.send_header('Content-Length', str(len(raw)))
    if cookie is not None or clear:
        suffix = '; Secure' if isinstance(handler.connection, ssl.SSLSocket) else ''
        handler.send_header('Set-Cookie', COOKIE + '=' + (cookie or '') +
                            '; Path=/api/admin/; HttpOnly; SameSite=Strict; Max-Age=' +
                            ('0' if clear else str(SESSION_SECONDS)) + suffix)
    handler.end_headers()
    if handler.command != 'HEAD':
        handler.wfile.write(raw)


def protect_page(handler):
    try:
        guard(handler)
        return True
    except AdminError as exc:
        _send(handler, exc.status, dict(ok=False, error=exc.envelope()))
        return False


def _query(query, allowed):
    values = parse_qs(query, keep_blank_values=True, max_num_fields=8)
    if set(values) - allowed or any(len(v) != 1 for v in values.values()):
        raise AdminError(400, 'query_invalid', 'Bộ lọc quản trị không hợp lệ.')
    return {k: v[0] for k, v in values.items()}


def _page(values, default=25, maximum=100):
    try:
        offset, limit = int(values.get('offset', '0')), int(values.get('limit', str(default)))
    except ValueError as exc:
        raise AdminError(400, 'query_invalid', 'Phân trang không hợp lệ.') from exc
    if not 0 <= offset <= 0x7fffffff or not 1 <= limit <= maximum:
        raise AdminError(400, 'query_invalid', 'Phân trang vượt giới hạn.')
    return offset, limit


def handle(handler):
    """Called only for /api/admin/*. Return one JSON response, never fallthrough."""
    try:
        mutation = handler.command == 'POST'
        guard(handler, mutation=mutation)
        if handler.command not in ('GET', 'POST'):
            raise AdminError(405, 'method_invalid', 'Phương thức không được hỗ trợ.')
        parsed = urlsplit(handler.path)
        path = parsed.path
        if mutation and parsed.query:
            raise AdminError(400, 'query_invalid', 'Không truyền dữ liệu quản trị trong URL.')
        if _access is None:
            if path == PREFIX + 'session' and not mutation:
                return _send(handler, 200, dict(ok=True, enabled=False, authenticated=False, version='m29'))
            raise AdminError(503, 'admin_disabled', 'Dừng server rồi mở bằng --enable-admin-buff để bật quản trị local.')
        token = _cookie(handler)
        session = _access.session(token)
        if path == PREFIX + 'session':
            if mutation:
                body = _json_body(handler)
                if set(body) != {'secret'}:
                    raise AdminError(400, 'payload_invalid', 'Nhập khóa quản trị local.')
                new_token, session = _access.unlock(body['secret'])
                if token:
                    _access.logout(token)
                return _send(handler, 200, dict(ok=True, enabled=True, authenticated=True, version='m29',
                                               csrf=session['csrf'], expires_at=session['expires_at']), cookie=new_token)
            if parsed.query:
                raise AdminError(400, 'query_invalid', 'Trạng thái quản trị không nhận tham số URL.')
            return _send(handler, 200, dict(ok=True, enabled=True, authenticated=session is not None, version='m29',
                                           **(dict(csrf=session['csrf'], expires_at=session['expires_at']) if session else {})))
        if session is None:
            raise AdminError(401, 'admin_required', 'Mở khóa quản trị trước khi tiếp tục.')
        if mutation:
            csrf = _single(handler, 'X-CSRF-Token', True)
            if not isinstance(csrf, str) or not _TOKEN.fullmatch(csrf) or not secrets.compare_digest(csrf, session['csrf']):
                raise AdminError(403, 'csrf_invalid', 'Phiên xác nhận đã đổi; tải lại trang quản trị.')
            body = _json_body(handler)
        if path == PREFIX + 'logging':
            import server_logging
            if parsed.query:
                raise AdminError(400, 'query_invalid', 'Log không nhận tham số URL.')
            if mutation:
                if set(body) != {'enabled'} or type(body['enabled']) is not bool:
                    raise AdminError(400, 'payload_invalid', 'Chọn bật hoặc tắt ghi log.')
                try:
                    result = server_logging.set_file_logging(body['enabled'])
                except OSError:
                    raise AdminError(500, 'log_unavailable', 'Không mở được file log. Kiểm tra quyền ghi thư mục game.')
            else:
                result = server_logging.status()
            return _send(handler, 200, dict(ok=True, **result))
        if path == PREFIX + 'logout' and mutation:
            if body:
                raise AdminError(400, 'payload_invalid', 'Yêu cầu đăng xuất không hợp lệ.')
            _access.logout(token)
            return _send(handler, 200, dict(ok=True, authenticated=False), clear=True)
        if path == PREFIX + 'accounts' and not mutation:
            import admin_accounts
            values = _query(parsed.query, {'q', 'status', 'offset', 'limit'})
            offset, limit = _page(values, maximum=100)
            query = values.get('q', '').strip()
            if len(query) > 128:
                raise AdminError(400, 'query_invalid', 'Từ khóa tài khoản quá dài.')
            with storage.connection() as db:
                result = admin_accounts.accounts(db, _access.secret_hash, query, values.get('status', 'active'), offset, limit)
            return _send(handler, 200, dict(ok=True, **result))
        if path == PREFIX + 'accounts/receipt' and not mutation:
            import admin_accounts
            values = _query(parsed.query, {'request_id'})
            return _send(handler, 200, dict(ok=True, **admin_accounts.receipt(values.get('request_id'))))
        if path == PREFIX + 'accounts/preview' and mutation:
            import admin_accounts
            result, payload_hash = admin_accounts.preview(body, _access.secret_hash)
            proof, expiry = _access.prove(session, payload_hash) if payload_hash else (None, None)
            return _send(handler, 200, dict(ok=True, preview_token=proof, expires_at=expiry, **result))
        if path == PREFIX + 'accounts/execute' and mutation:
            import admin_accounts
            result = admin_accounts.execute(body, _access.secret_hash,
                                            lambda proof, digest: _access.check_proof(session, proof, digest))
            return _send(handler, 200, dict(ok=True, **result))
        if path == PREFIX + 'accounts/cancel' and mutation:
            import admin_accounts
            if set(body) != {'request_id'}:
                raise AdminError(400, 'payload_invalid', 'Nội dung hủy thao tác tài khoản không hợp lệ.')
            return _send(handler, 200, dict(ok=True, **admin_accounts.cancel(body['request_id'])))
        if path == PREFIX + 'recipients' and not mutation:
            values = _query(parsed.query, {'q', 'offset', 'limit'})
            offset, limit = _page(values, maximum=100)
            query = values.get('q', '').strip()
            if len(query) > 128:
                raise AdminError(400, 'query_invalid', 'Từ khóa quá dài.')
            with storage.connection() as db:
                result = offline_mail.recipients(db, query, offset, limit)
            return _send(handler, 200, dict(ok=True, **result))
        if path == PREFIX + 'catalog' and not mutation:
            values = _query(parsed.query, {'q', 'category', 'offset', 'limit'})
            offset, limit = _page(values, 100, 200)
            category, query = values.get('category', 'all'), values.get('q', '').casefold()
            if category not in {'all', *(k for k, _ in mail_rewards.CATEGORIES)} or len(query) > 128:
                raise AdminError(400, 'query_invalid', 'Bộ lọc danh mục không hợp lệ.')
            with storage.connection() as db:
                available = mail_rewards.catalog(db)
            selected = sorted((r for r in available.values() if (category == 'all' or category == r['category']) and
                               (not query or query in r['name'].casefold() or query in str(r['id']).casefold())),
                              key=lambda r: (r['category'], r['name'].casefold(), str(r['id'])))
            return _send(handler, 200, dict(ok=True, rows=selected[offset:offset + limit], total=len(selected),
                                           offset=offset, limit=limit,
                                           categories=[dict(id=k, label=v) for k, v in mail_rewards.CATEGORIES]))
        if path == PREFIX + 'mail/preview' and mutation:
            payload = offline_mail.canonical(body)
            with storage.connection() as db:
                db.execute('BEGIN')
                result = offline_mail.preview(db, payload)
                db.commit()
            proof, expiry = _access.prove(session, offline_mail.digest(payload)) if result['can_send'] else (None, None)
            return _send(handler, 200, dict(ok=True, preview_token=proof, expires_at=expiry, **result))
        if path == PREFIX + 'mail/send' and mutation:
            if set(body) != {'recipient', 'subject', 'body', 'rewards', 'request_id', 'preview_token'}:
                raise AdminError(400, 'payload_invalid', 'Nội dung gửi thư không hợp lệ.')
            request_id = body['request_id']
            if not isinstance(request_id, str) or not _REQUEST_ID.fullmatch(request_id):
                raise AdminError(400, 'request_id_invalid', 'Mã yêu cầu không hợp lệ.')
            payload = offline_mail.canonical({k: body[k] for k in ('recipient', 'subject', 'body', 'rewards')})
            payload_hash = offline_mail.digest(payload)
            with storage.connection(write=True) as db:
                # The persisted idempotency lookup is always first, including
                # after re-auth/restart. Proof is required only for a NEW send.
                previous = offline_mail.send_receipt(db, request_id, payload_hash)
                if previous is not None:
                    result = previous
                else:
                    valid = _access.check_proof(session, body['preview_token'], payload_hash)
                    result = offline_mail.send(db, payload, request_id, proof_checked=valid)
            offline_mail.notify(result['recipient']['id'])
            return _send(handler, 200, dict(ok=True, **result))
        raise AdminError(404, 'route_missing', 'Không có chức năng quản trị này.')
    except RewardError as exc:
        status = getattr(exc, 'status', 409 if exc.code in ('idempotency_conflict', 'recipient_changed',
                                                          'already_owned', 'bag_full', 'wallet_overflow',
                                                          'preview_required') else 400)
        error = exc.envelope()
        not_created = getattr(exc, 'send_not_created_request_id', None)
        if (400 <= status < 500 and handler.command == 'POST' and
                urlsplit(handler.path).path == PREFIX + 'mail/send' and
                isinstance(not_created, str) and _REQUEST_ID.fullmatch(not_created)):
            error.update(not_created=True, request_id=not_created)
        return _send(handler, status, dict(ok=False, error=error))
    except (ValueError, UnicodeError):
        return _send(handler, 400, dict(ok=False, error=dict(code='request_invalid', message='Yêu cầu quản trị không hợp lệ.')))
    except Exception:
        # No body, cookie, secret or private database values in HTTP error text.
        return _send(handler, 500, dict(ok=False, error=dict(code='admin_error', message='Không hoàn tất thao tác. Giữ nguyên mã yêu cầu và thử lại để kiểm tra biên nhận.')))
