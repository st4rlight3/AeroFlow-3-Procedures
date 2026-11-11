import secrets
import time
from collections import defaultdict, deque
from functools import wraps
from threading import Lock
from flask import current_app, g, request, session
from .db import query
from .errors import ApiError

attempts = defaultdict(deque)
attempt_lock = Lock()

def csrf_token():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_urlsafe(32)
    return session['csrf']

def protect_request():
    if request.path.startswith('/api/') and request.method not in ('GET', 'HEAD', 'OPTIONS'):
        token = request.headers.get('X-CSRF-Token', '')
        if not token or not secrets.compare_digest(token, session.get('csrf', '')):
            raise ApiError('Phiên bảo mật đã thay đổi. Vui lòng tải lại trang.', 403, 'CSRF')

def authenticated(admin=False):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            uid = session.get('uid')
            if not uid:
                raise ApiError('Vui lòng đăng nhập để tiếp tục.', 401, 'LOGIN_REQUIRED')
            user = query('SELECT u.UserID,u.FullName,u.Email,u.Phone,u.IsActive,u.SessionVersion,r.Name Role FROM dbo.Users u JOIN dbo.Roles r ON r.RoleID=u.RoleID WHERE u.UserID=?', (uid,), one=True)
            if not user or not user['IsActive'] or user['SessionVersion'] != session.get('version'):
                session.clear()
                raise ApiError('Phiên đăng nhập hết hạn.', 401, 'SESSION_EXPIRED')
            g.user = user
            if admin and user['Role'] != 'ADMIN':
                raise ApiError('Bạn không có quyền quản trị.', 403, 'FORBIDDEN')
            return fn(*args, **kwargs)
        return wrapped
    return decorate

def throttle_login():
    key, now = request.remote_addr or 'local', time.monotonic()
    with attempt_lock:
        # Expire keys to bound memory, independent of successful login.
        for old in list(attempts):
            while attempts[old] and attempts[old][0] < now-600:
                attempts[old].popleft()
            if not attempts[old]:
                del attempts[old]
        bucket = attempts[key]
        if len(bucket) >= current_app.config['LOGIN_LIMIT']:
            raise ApiError('Quá nhiều lần thử. Vui lòng thử lại sau 10 phút.', 429, 'RATE_LIMIT')
        bucket.append(now)
