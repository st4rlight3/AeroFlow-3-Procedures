from datetime import timezone
from flask import Blueprint, jsonify, request
from ..db import query
from ..errors import ApiError
from ..validation import iso_date, integer
from ..services.booking_commands import get_available_seats
from ..services.flight_service import airport_metadata, civil_day, decorate_flights, zone

bp = Blueprint('flights', __name__, url_prefix='/api')


@bp.get('/health')
def health():
    query('SELECT 1 Ready')
    return jsonify(status='ok', database='Microsoft SQL Server')


@bp.get('/airports')
def airports():
    rows = [a for a in airport_metadata().values() if a['IsActive']]
    return jsonify(items=sorted(rows, key=lambda a: (a['CountryName'], a['City'])))


@bp.get('/discovery')
def discovery():
    airports = airport_metadata()
    rows = query("WITH routes AS (SELECT *,ROW_NUMBER() OVER(PARTITION BY OriginID,DestinationID ORDER BY DepartureTime,FromPrice,FlightID) RowNumber,COUNT(*) OVER(PARTITION BY OriginID,DestinationID) FlightCount FROM dbo.vw_FlightAvailability WHERE Status='SCHEDULED' AND AircraftID IN(SELECT AircraftID FROM dbo.Aircraft WHERE IsActive=1) AND OriginID IN(SELECT AirportID FROM dbo.Airports WHERE IsActive=1) AND DestinationID IN(SELECT AirportID FROM dbo.Airports WHERE IsActive=1) AND DepartureTime>DATEADD(hour,2,SYSUTCDATETIME()) AND AvailableSeats>0 AND FromPrice IS NOT NULL) SELECT OriginID,DestinationID,OriginCode,DestinationCode,OriginCity,DestinationCity,FromPrice,DepartureTime NextDeparture,FlightCount FROM routes WHERE RowNumber=1 ORDER BY FlightCount DESC,OriginCode,DestinationCode")
    for row in rows:
        row['DepartureTime'] = row['NextDeparture']
    decorate_flights(rows, airports)
    # The hero uses one actual flight, keeping its departure date and price together.
    featured = query("SELECT TOP(1) * FROM dbo.vw_FlightAvailability WHERE Status='SCHEDULED' AND AircraftID IN(SELECT AircraftID FROM dbo.Aircraft WHERE IsActive=1) AND OriginID IN(SELECT AirportID FROM dbo.Airports WHERE IsActive=1) AND DestinationID IN(SELECT AirportID FROM dbo.Airports WHERE IsActive=1) AND DepartureTime>DATEADD(hour,2,SYSUTCDATETIME()) AND AvailableSeats>0 AND FromPrice IS NOT NULL ORDER BY CASE WHEN OriginCode='HAN' AND DestinationCode='SGN' THEN 0 ELSE 1 END,DepartureTime,FromPrice,FlightID", one=True)
    if featured:
        decorate_flights([featured], airports)
        featured['NextDeparture'] = featured['DepartureTime']
    next_date = min((r['DepartureDate'] for r in rows), default=None)
    window = query('SELECT OriginID,MIN(DepartureTime) FirstDeparture,MAX(DepartureTime) LastDeparture FROM dbo.Flights GROUP BY OriginID')
    first_dates = [r['FirstDeparture'].replace(tzinfo=timezone.utc).astimezone(zone(airports[r['OriginID']]['IanaTimeZone'])).date().isoformat() for r in window]
    last_dates = [r['LastDeparture'].replace(tzinfo=timezone.utc).astimezone(zone(airports[r['OriginID']]['IanaTimeZone'])).date().isoformat() for r in window]
    return jsonify(items=rows, featured=featured, NextAvailableDate=next_date,
                   DemoDateStart=min(first_dates, default=None), DemoDateEnd=max(last_dates, default=None))


@bp.get('/flights')
def search():
    d = request.args
    origin, dest = integer(d, 'origin'), integer(d, 'destination')
    count = integer(d, 'passengers', 1, 9)
    airports = airport_metadata()
    if origin == dest:
        raise ApiError('Điểm đi và điểm đến phải khác nhau.')
    if any(i not in airports or not airports[i]['IsActive'] for i in (origin, dest)):
        raise ApiError('Sân bay không hoạt động hoặc không tồn tại.')
    start, end = civil_day(iso_date(d.get('date')), airports[origin]['IanaTimeZone'])
    rows = query("SELECT * FROM dbo.vw_FlightAvailability WHERE OriginID=? AND DestinationID=? AND DepartureTime>=? AND DepartureTime<? AND DepartureTime>DATEADD(hour,2,SYSUTCDATETIME()) AND Status='SCHEDULED' AND AircraftID IN(SELECT AircraftID FROM dbo.Aircraft WHERE IsActive=1) AND AvailableSeats>=? AND FromPrice IS NOT NULL ORDER BY DepartureTime", (origin, dest, start, end, count))
    return jsonify(items=decorate_flights(rows, airports))


@bp.get('/flights/<int:flight_id>')
def details(flight_id):
    flight = query('SELECT * FROM dbo.vw_FlightAvailability WHERE FlightID=?', (flight_id,), one=True)
    if not flight:
        raise ApiError('Không tìm thấy chuyến bay.', 404)
    decorate_flights([flight])
    fares = query('SELECT c.*,ff.BasePrice,ff.TaxRate,dbo.fn_CalculateTicketPrice(ff.BasePrice,ff.TaxRate) Price FROM dbo.FlightFares ff JOIN dbo.FareClasses c ON c.FareClassID=ff.FareClassID WHERE ff.FlightID=? AND EXISTS(SELECT 1 FROM dbo.AircraftSeats s WHERE s.AircraftID=? AND s.IsActive=1 AND s.Cabin=c.Cabin) ORDER BY Price', (flight_id, flight['AircraftID']))
    return jsonify(flight=flight, fares=fares)


@bp.get('/flights/<int:flight_id>/seats')
def seats(flight_id):
    if not query('SELECT FlightID FROM dbo.Flights WHERE FlightID=?', (flight_id,), one=True):
        raise ApiError('Không tìm thấy chuyến bay.', 404)
    return jsonify(items=get_available_seats(flight_id))


@bp.get('/flight-status')
def flight_status():
    number = request.args.get('number', '').strip().upper()
    if not 2 <= len(number) <= 8:
        raise ApiError('Nhập mã chuyến bay từ 2 đến 8 ký tự.')
    rows = query('SELECT TOP(100) * FROM dbo.vw_FlightAvailability WHERE FlightNumber=? ORDER BY DepartureTime', (number,))
    return jsonify(items=decorate_flights(rows))
