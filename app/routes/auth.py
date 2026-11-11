from flask import Blueprint, g, jsonify, session
from werkzeug.security import check_password_hash, generate_password_hash
from ..db import query
from ..errors import ApiError
from ..security import authenticated, csrf_token, throttle_login
from ..validation import body, email, text

bp = Blueprint('auth', __name__, url_prefix='/api')

@bp.get('/csrf')
def csrf():
    return jsonify(token=csrf_token())

@bp.post('/auth/register')
def register():
    throttle_login()
    d = body()
    address, name = email(d), text(d, 'FullName', 2)
    password = text(d, 'Password', 12, 128)
    role = query("SELECT RoleID FROM dbo.Roles WHERE Name='CUSTOMER'", one=True)
    if not role:
        raise ApiError('Cơ sở dữ liệu chưa được khởi tạo.', 503)
    query('INSERT dbo.Users(RoleID,Email,FullName,PasswordHash) VALUES(?,?,?,?)',
          (role['RoleID'], address, name, generate_password_hash(password, method='scrypt')))
    return jsonify(message='Đăng ký thành công. Bạn có thể đăng nhập.'), 201

@bp.post('/auth/login')
def login():
    throttle_login()
    d = body()
    address, password = email(d), text(d, 'Password', 1, 128)
    u = query('SELECT UserID,PasswordHash,SessionVersion,IsActive FROM dbo.Users WHERE Email=?', (address,), one=True)
    if not u or not u['IsActive'] or not check_password_hash(u['PasswordHash'], password):
        raise ApiError('Email hoặc mật khẩu không đúng.', 401, 'INVALID_CREDENTIALS')
    session.clear()
    session.update(uid=u['UserID'], version=u['SessionVersion'])
    session.permanent = True
    return jsonify(message='Đăng nhập thành công.', csrf=csrf_token())

@bp.post('/auth/logout')
@authenticated()
def logout():
    query('UPDATE dbo.Users SET SessionVersion=SessionVersion+1 WHERE UserID=?', (g.user['UserID'],))
    session.clear()
    return jsonify(message='Đã đăng xuất.', csrf=csrf_token())

@bp.get('/me')
@authenticated()
def me():
    return jsonify(user={k: g.user[k] for k in ('UserID', 'FullName', 'Email', 'Phone', 'Role')})

@bp.put('/me')
@authenticated()
def update_me():
    d = body()
    name = text(d, 'FullName', 2)
    phone = str(d.get('Phone', '')).strip()
    if len(phone)>20 or (phone and not all(c in '+0123456789 ()-' for c in phone)):
        raise ApiError('Số điện thoại không hợp lệ.')
    query('UPDATE dbo.Users SET FullName=?,Phone=? WHERE UserID=?', (name, phone, g.user['UserID']))
    return jsonify(message='Đã cập nhật hồ sơ.')
