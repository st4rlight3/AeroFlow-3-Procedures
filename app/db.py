import re
from contextlib import contextmanager
import pyodbc
from flask import g, has_request_context
from .config import connection_string
from .errors import ApiError, SQL_ERRORS

# Mutations of seats, fares and flight schedules use this transaction-owned lock.
LOCK_INVENTORY_SQL = """
DECLARE @inventory_lock_result int;
EXEC @inventory_lock_result = sys.sp_getapplock
 @Resource='AeroFlow:inventory', @LockMode='Exclusive',
 @LockOwner='Transaction', @LockTimeout=10000;
IF @inventory_lock_result<0 THROW 51001,N'Đặt chỗ đang được xử lý. Vui lòng thử lại.',1;
"""

@contextmanager
def connection(database=None, autocommit=False):
    conn = pyodbc.connect(connection_string(database), timeout=5, autocommit=autocommit)
    conn.timeout = 15
    try:
        conn.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
        actor = getattr(g, 'user', None) if has_request_context() else None
        conn.execute("EXEC sys.sp_set_session_context @key=N'ActorID',@value=?", actor['UserID'] if actor else None)
        yield conn
        if not autocommit:
            conn.commit()
    except Exception:
        if not autocommit:
            conn.rollback()
        raise
    finally:
        conn.close()

def query(sql, params=(), one=False):
    with connection() as conn:
        cursor = conn.cursor().execute(sql, tuple(params))
        rows = []
        while True:
            if cursor.description:
                names = [c[0] for c in cursor.description]
                rows = [dict(zip(names, row)) for row in cursor.fetchall()]
            if not cursor.nextset():
                break
    return (rows[0] if rows else None) if one else rows

def translate_error(error):
    text = str(error)
    for number, (message, status) in SQL_ERRORS.items():
        if re.search(r'\b' + str(number) + r'\b', text):
            return ApiError(message, status, f'SQL_{number}')
    if any(re.search(r'\b' + str(n) + r'\b', text) for n in (2601, 2627)):
        return ApiError('Dữ liệu bị trùng. Ghế, email, mã hoặc giao dịch có thể đã tồn tại.', 409, 'DUPLICATE')
    if re.search(r'\b(547|515|245|8114|8115|2628)\b', text):
        return ApiError('Dữ liệu vi phạm ràng buộc. Kiểm tra các trường và bản ghi liên quan.', 400, 'CONSTRAINT')
    if re.search(r'\b1205\b', text):
        return ApiError('Giao dịch đồng thời cần thử lại.', 409, 'RETRY_TRANSACTION')
    return ApiError('Không thể truy cập cơ sở dữ liệu. Vui lòng thử lại sau.', 503, 'DATABASE_UNAVAILABLE')
