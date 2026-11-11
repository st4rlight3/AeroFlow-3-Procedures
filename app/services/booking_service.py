import json
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from ..db import query
from ..errors import ApiError
from ..validation import text, integer, iso_date, decimal_value
from .booking_commands import create_booking_db, expire_flight_holds, get_available_seats


def owned_booking(booking_id, user):
    booking = query('SELECT * FROM dbo.vw_BookingDetails WHERE BookingID=? AND (UserID=? OR ?=1)', (booking_id, user['UserID'], int(user['Role'] == 'ADMIN')), one=True)
    if not booking:
        raise ApiError('Không tìm thấy đơn đặt vé.', 404, 'NOT_FOUND')
    expire_flight_holds(booking['FlightID'])
    return query('SELECT * FROM dbo.vw_BookingDetails WHERE BookingID=?', (booking_id,), one=True)


def booking_input(data):
    flight_id = integer(data, 'FlightID')
    return_id = integer(data, 'ReturnFlightID') if data.get('ReturnFlightID') is not None else None
    if return_id == flight_id:
        raise ApiError('Chuyến đi và chuyến về phải khác nhau.')
    passengers = data.get('Passengers')
    if not isinstance(passengers, list) or not 1 <= len(passengers) <= 9:
        raise ApiError('Cần từ 1 đến 9 hành khách.')
    clean = []
    for passenger in passengers:
        if not isinstance(passenger, dict):
            raise ApiError('Thông tin hành khách không hợp lệ.')
        dob = iso_date(passenger.get('DateOfBirth'))
        if not date(1900, 1, 1) <= dob <= date.today():
            raise ApiError('Ngày sinh không hợp lệ.')
        row = dict(SeatID=integer(passenger, 'SeatID'), FareClassID=integer(passenger, 'FareClassID'),
                   FullName=text(passenger, 'FullName', 2), DateOfBirth=dob.isoformat(),
                   DocumentNumber=text(passenger, 'DocumentNumber', 5, 30))
        if return_id:
            row.update(ReturnSeatID=integer(passenger, 'ReturnSeatID'),
                       ReturnFareClassID=integer(passenger, 'ReturnFareClassID'))
        clean.append(row)
    if len({p['DocumentNumber'].casefold() for p in clean}) != len(clean):
        raise ApiError('Giấy tờ hành khách trong một đơn không được trùng.')
    for field in ('SeatID', 'ReturnSeatID') if return_id else ('SeatID',):
        if len({p[field] for p in clean}) != len(clean):
            raise ApiError('Mỗi hành khách phải chọn một ghế khác nhau trên từng chuyến.')
    expected = decimal_value(data, 'ExpectedTotal', 0, 18000000000) if 'ExpectedTotal' in data else None
    return flight_id, return_id, clean, expected


def quote_booking(data):
    flight_id, return_id, passengers, _ = booking_input(data)
    flights = []
    for fid in (flight_id, return_id) if return_id else (flight_id,):
        flight = query("SELECT f.* FROM dbo.Flights f JOIN dbo.Aircraft a ON a.AircraftID=f.AircraftID JOIN dbo.Airports o ON o.AirportID=f.OriginID JOIN dbo.Airports d ON d.AirportID=f.DestinationID WHERE f.FlightID=? AND f.Status='SCHEDULED' AND f.DepartureTime>DATEADD(hour,2,SYSUTCDATETIME()) AND a.IsActive=1 AND o.IsActive=1 AND d.IsActive=1", (fid,), one=True)
        if not flight:
            raise ApiError('Chuyến bay không còn mở bán.', 409)
        flights.append(flight)
    if return_id:
        outbound, inbound = flights
        if (inbound['OriginID'], inbound['DestinationID']) != (outbound['DestinationID'], outbound['OriginID']) or inbound['DepartureTime'] < outbound['ArrivalTime'] + timedelta(minutes=60):
            raise ApiError('Chuyến về phải đi ngược tuyến và khởi hành sau khi chuyến đi hạ cánh ít nhất 60 phút.')
    lines = []
    for order, flight in enumerate(flights, 1):
        seats = {s['SeatID']: s for s in get_available_seats(flight['FlightID'])}
        fares = {f['FareClassID']: f for f in query('SELECT ff.*,c.Name FareName,c.Cabin FROM dbo.FlightFares ff JOIN dbo.FareClasses c ON c.FareClassID=ff.FareClassID WHERE ff.FlightID=?', (flight['FlightID'],))}
        for passenger in passengers:
            seat = seats.get(passenger['SeatID' if order == 1 else 'ReturnSeatID'])
            fare = fares.get(passenger['FareClassID' if order == 1 else 'ReturnFareClassID'])
            if not seat or not fare or seat['Cabin'] != fare['Cabin']:
                raise ApiError('Ghế hoặc hạng vé không phù hợp với chuyến bay.')
            if not seat['Available']:
                raise ApiError('Ghế vừa được người khác giữ. Vui lòng chọn ghế khác.', 409)
            base = Decimal(str(fare['BasePrice']))
            tax = (base * Decimal(str(fare['TaxRate']))).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
            fee = Decimal(str(seat['SeatFee']))
            lines.append(dict(FullName=passenger['FullName'], FlightID=flight['FlightID'],
                              FlightNumber=flight['FlightNumber'], SegmentOrder=order,
                              SeatNumber=seat['SeatNumber'], FareName=fare['FareName'],
                              BaseFare=base, TaxAmount=tax, SeatFee=fee, Amount=base + tax + fee))
    return dict(Total=sum((line['Amount'] for line in lines), Decimal('0.00')), Lines=lines)


def create_booking(data, uid):
    flight_id, return_id, passengers, expected = booking_input(data)
    return create_booking_db(uid, flight_id, json.dumps(passengers, ensure_ascii=False), return_id, expected)
