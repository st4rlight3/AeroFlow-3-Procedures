from datetime import date, timedelta
from decimal import Decimal
from flask import Blueprint, g, jsonify, request
from ..db import connection, query
from ..errors import ApiError
from ..security import authenticated
from ..validation import body, text, integer, decimal_value, iso_date, utc_datetime
from ..services import flight_commands
from ..services.flight_service import zone

bp = Blueprint('admin', __name__, url_prefix='/api/admin')

# Identifiers come exclusively from this allowlist, never from client SQL fragments.
CATALOGS = {
 'airports': ('Airports', 'AirportID', {'Code': ('text', 3), 'Name': ('text', 120), 'City': ('text', 80), 'CountryName': ('text', 80), 'IanaTimeZone': ('text', 64), 'IsActive': ('bool', 0)}),
 'airlines': ('Airlines', 'AirlineID', {'Code': ('text', 2), 'Name': ('text', 100)}),
 'aircraft': ('Aircraft', 'AircraftID', {'AirlineID': ('int', 0), 'Registration': ('text', 20), 'Model': ('text', 80), 'IsActive': ('bool', 0)}),
 'seats': ('AircraftSeats', 'SeatID', {'AircraftID': ('int', 0), 'RowNumber': ('int', 80), 'ColumnLetter': ('text', 1), 'Cabin': ('text', 12), 'SeatFee': ('decimal', 10000000), 'IsPriority': ('bool', 0), 'IsActive': ('bool', 0)}),
 'fare-classes': ('FareClasses', 'FareClassID', {'Code': ('text', 10), 'Name': ('text', 60), 'Cabin': ('text', 12), 'BaggageKg': ('int0', 60), 'RefundPercent': ('decimal', 100)})
}

@bp.get('/overview')
@authenticated(admin=True)
def overview():
    totals = query("SELECT (SELECT COUNT(*) FROM dbo.Flights) Flights,(SELECT COUNT(*) FROM dbo.Bookings) Bookings,(SELECT COUNT(*) FROM dbo.Tickets WHERE Status='VALID') ValidTickets,(SELECT COALESCE(SUM(NetRevenue),0) FROM dbo.vw_MonthlyRevenue) NetRevenue,(SELECT CONVERT(decimal(5,2),COALESCE(100.0*SUM(SoldSeats)/NULLIF(SUM(TotalSeats),0),0)) FROM dbo.vw_FlightOccupancy) Occupancy", one=True)
    monthly = query('SELECT * FROM dbo.vw_MonthlyRevenue ORDER BY [Year],[Month]')
    occupancy = query('SELECT TOP(30) *,dbo.fn_GetFlightOccupancyRate(FlightID) OccupancyPercent FROM dbo.vw_FlightOccupancy ORDER BY DepartureTime')
    return jsonify(totals=totals, monthly=monthly, occupancy=occupancy)

@bp.get('/flights')
@authenticated(admin=True)
def flights():
    return jsonify(items=query('SELECT TOP(500) * FROM dbo.vw_FlightAvailability ORDER BY DepartureTime DESC'))

@bp.route('/flights', methods=['POST'])
@bp.route('/flights/<int:flight_id>', methods=['PUT'])
@authenticated(admin=True)
def save_flight(flight_id=None):
    d = body()
    result = flight_commands.save_flight(
        flight_id, text(d, 'FlightNumber', 3, 8), integer(d, 'AircraftID'),
        integer(d, 'OriginID'), integer(d, 'DestinationID'),
        utc_datetime(d.get('DepartureTime')), utc_datetime(d.get('ArrivalTime')),
    )
    return jsonify(result=result), 201 if flight_id is None else 200

@bp.put('/flights/<int:flight_id>/status')
@authenticated(admin=True)
def flight_status(flight_id):
    flight_commands.update_flight_status(flight_id, text(body(), 'Status', 1, 12))
    return jsonify(message='Đã cập nhật trạng thái chuyến bay.')

@bp.put('/flights/<int:flight_id>/fares/<int:class_id>')
@authenticated(admin=True)
def fare(flight_id, class_id):
    d = body()
    query('EXEC dbo.sp_SaveFare ?,?,?,?', (flight_id, class_id, decimal_value(d, 'BasePrice', 1), decimal_value(d, 'TaxRate', 0, 1)))
    return jsonify(message='Đã lưu giá vé. Vé đã đặt giữ nguyên giá cũ.')

@bp.get('/catalog/<entity>')
@authenticated(admin=True)
def catalog(entity):
    if entity not in CATALOGS:
        raise ApiError('Không tìm thấy danh mục.', 404)
    table, pk, fields = CATALOGS[entity]
    return jsonify(items=query(f'SELECT TOP(2000) * FROM dbo.{table} ORDER BY {pk}'), key=pk, fields=fields)

@bp.route('/catalog/<entity>', methods=['POST'])
@bp.route('/catalog/<entity>/<int:item_id>', methods=['PUT'])
@authenticated(admin=True)
def save_catalog(entity, item_id=None):
    if entity not in CATALOGS:
        raise ApiError('Không tìm thấy danh mục.', 404)
    table, pk, fields = CATALOGS[entity]
    d, values = body(), {}
    defaults = {'SeatFee': 0, 'IsPriority': False} if entity == 'seats' else {'CountryName': 'Việt Nam', 'IanaTimeZone': 'Asia/Ho_Chi_Minh'} if entity == 'airports' else {}
    for key, (kind, limit) in fields.items():
        if key in defaults and key not in d:
            if item_id:
                continue
            d[key] = defaults[key]
        if kind == 'text':
            values[key] = text(d, key, 1, limit)
        elif kind == 'bool':
            if type(d.get(key)) is not bool:
                raise ApiError(f'{key} cần là true hoặc false.')
            values[key] = d[key]
        elif kind in ('int', 'int0'):
            values[key] = integer(d, key, 0 if kind=='int0' else 1, limit or 2147483647)
        else:
            values[key] = decimal_value(d, key, 0, limit)
    if 'Code' in values:
        values['Code'] = values['Code'].upper()
    if 'Cabin' in values and values['Cabin'] not in ('ECONOMY', 'PREMIUM', 'BUSINESS', 'FIRST'):
        raise ApiError('Khoang cần là ECONOMY, PREMIUM, BUSINESS hoặc FIRST.')
    if 'IanaTimeZone' in values:
        zone(values['IanaTimeZone'], status=400)
    if entity == 'seats':
        values['ColumnLetter'] = values['ColumnLetter'].upper()
        values['SeatNumber'] = f"{values['ColumnLetter']}{values['RowNumber']}"
    with connection() as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE')
        if item_id:
            existing = conn.execute(f'SELECT {pk} FROM dbo.{table} WITH(UPDLOCK,HOLDLOCK) WHERE {pk}=?', item_id).fetchone()
            if not existing:
                raise ApiError('Không tìm thấy bản ghi.', 404)
            if entity=='aircraft' and conn.execute('SELECT 1 FROM dbo.Flights WHERE AircraftID=?', item_id).fetchone():
                raise ApiError('Máy bay đã có lịch sử chuyến bay. Hãy tạo máy bay mới.', 409)
            if entity=='fare-classes':
                current = conn.execute('SELECT Cabin FROM dbo.FareClasses WHERE FareClassID=?', item_id).fetchone()[0]
                if values['Cabin']!=current and conn.execute('SELECT 1 FROM dbo.FlightFares WHERE FareClassID=?', item_id).fetchone():
                    raise ApiError('Không đổi khoang của hạng vé đã được mở bán. Hãy tạo hạng vé mới.', 409)
            conn.execute(f"UPDATE dbo.{table} SET {','.join(k+'=?' for k in values)} WHERE {pk}=?", tuple(values.values())+(item_id,))
        else:
            cursor = conn.execute(f"SET NOCOUNT ON; INSERT dbo.{table}({','.join(values)}) VALUES({','.join('?' for _ in values)}); SELECT CONVERT(int,SCOPE_IDENTITY()) NewID;", tuple(values.values()))
            while cursor.description is None:
                cursor.nextset()
            item_id = cursor.fetchone()[0]
            if entity=='aircraft':
                rows = integer(d, 'Rows', 1, 40)
                biz = integer(d, 'BusinessRows', 0, rows)
                for r in range(1, rows+1):
                    for c in 'ABCDEF':
                        conn.execute('INSERT dbo.AircraftSeats(AircraftID,SeatNumber,RowNumber,ColumnLetter,Cabin) VALUES(?,?,?,?,?)', item_id, f'{c}{r}', r, c, 'BUSINESS' if r>rows-biz else 'ECONOMY')
        conn.execute('INSERT dbo.AuditLogs(ActorID,Entity,EntityID,Action) VALUES(?,?,?,?)', g.user['UserID'], table, item_id, 'CATALOG_SAVE')
    return jsonify(id=item_id, message='Đã lưu danh mục.')

@bp.get('/bookings')
@authenticated(admin=True)
def bookings():
    q = request.args.get('q', '').strip()[:80]
    return jsonify(items=query('SELECT TOP(300) * FROM dbo.vw_BookingDetails WHERE PNR LIKE ? OR Email LIKE ? ORDER BY CreatedAt DESC', ('%'+q+'%', '%'+q+'%')))

@bp.get('/customers')
@authenticated(admin=True)
def customers():
    return jsonify(items=query("SELECT TOP(300) u.UserID,u.FullName,u.Email,u.Phone,u.IsActive,u.CreatedAt FROM dbo.Users u JOIN dbo.Roles r ON r.RoleID=u.RoleID WHERE r.Name='CUSTOMER' ORDER BY u.UserID DESC"))

@bp.put('/customers/<int:user_id>')
@authenticated(admin=True)
def update_customer(user_id):
    d = body()
    if type(d.get('IsActive')) is not bool:
        raise ApiError('IsActive cần là true hoặc false.')
    with connection() as conn:
        row = conn.execute("UPDATE dbo.Users SET IsActive=?,SessionVersion=SessionVersion+1 OUTPUT inserted.UserID WHERE UserID=? AND RoleID=(SELECT RoleID FROM dbo.Roles WHERE Name='CUSTOMER')", d['IsActive'], user_id).fetchone()
        if not row:
            raise ApiError('Không tìm thấy khách hàng.', 404)
        conn.execute('INSERT dbo.AuditLogs(ActorID,Entity,EntityID,Action,Details) VALUES(?,?,?,?,?)', g.user['UserID'], 'Users', user_id, 'ACCOUNT_STATUS', str(d['IsActive']))
    return jsonify(message='Đã cập nhật trạng thái khách hàng.')

@bp.get('/reports/revenue')
@authenticated(admin=True)
def report():
    start = iso_date(request.args.get('from', (date.today()-timedelta(days=30)).isoformat()))
    end = iso_date(request.args.get('to', date.today().isoformat()))
    if start>end or (end-start).days>366:
        raise ApiError('Khoảng báo cáo tối đa 366 ngày và ngày bắt đầu không sau ngày kết thúc.')
    return jsonify(items=query('EXEC dbo.sp_GetRevenueReport ?,?', (start, end)))

@bp.get('/payments')
@authenticated(admin=True)
def payments():
    return jsonify(items=query('SELECT TOP(300) p.PaymentID,b.PNR,p.Amount,p.Kind,p.Status,p.CreatedAt FROM dbo.Payments p JOIN dbo.Bookings b ON b.BookingID=p.BookingID ORDER BY p.PaymentID DESC'))

@bp.get('/audit')
@authenticated(admin=True)
def audit():
    return jsonify(items=query('SELECT TOP(300) a.AuditID,u.FullName Actor,a.Entity,a.EntityID,a.Action,a.Details,a.CreatedAt FROM dbo.AuditLogs a LEFT JOIN dbo.Users u ON u.UserID=a.ActorID ORDER BY a.AuditID DESC'))
