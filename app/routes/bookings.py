from flask import Blueprint, g, jsonify
from ..db import query
from ..security import authenticated
from ..validation import body, text
from ..errors import ApiError
from ..services.booking_commands import cancel_booking, confirm_payment, expire_flight_holds
from ..services.booking_service import create_booking, owned_booking, quote_booking
from ..services.flight_service import decorate_flights

bp = Blueprint('bookings', __name__, url_prefix='/api/bookings')


@bp.post('/quote')
@authenticated()
def quote():
    return jsonify(quote=quote_booking(body()))


@bp.post('')
@authenticated()
def create():
    return jsonify(booking=create_booking(body(), g.user['UserID'])), 201


@bp.get('')
@authenticated()
def history():
    ids = query("SELECT DISTINCT s.FlightID FROM dbo.Bookings b JOIN dbo.BookingSegments s ON s.BookingID=b.BookingID WHERE b.UserID=? AND b.Status='HELD' AND b.ExpiresAt<=SYSUTCDATETIME()", (g.user['UserID'],))
    for row in ids:
        expire_flight_holds(row['FlightID'])
    return jsonify(items=decorate_flights(query('SELECT * FROM dbo.vw_BookingDetails WHERE UserID=? ORDER BY CreatedAt DESC', (g.user['UserID'],))))


@bp.get('/<int:booking_id>')
@authenticated()
def detail(booking_id):
    booking = owned_booking(booking_id, g.user)
    segments = query('SELECT s.BookingSegmentID,s.SegmentOrder,f.* FROM dbo.BookingSegments s JOIN dbo.vw_FlightAvailability f ON f.FlightID=s.FlightID WHERE s.BookingID=? ORDER BY s.SegmentOrder', (booking_id,))
    decorate_flights(segments)
    tickets = query('SELECT t.TicketID,t.TicketNumber,CAST(t.BaseFare+t.TaxAmount+t.SeatFee AS decimal(14,2)) AS Amount,t.Status,t.RefundPercent,t.BaseFare,t.TaxAmount,t.SeatFee,t.BaggageKg,t.FareClassID,p.FullName,p.DateOfBirth,RIGHT(p.DocumentNumber,4) DocumentLast4,c.Name FareName,a.SeatID,se.SeatNumber,bs.BookingSegmentID,bs.SegmentOrder,f.FlightID,f.FlightNumber,f.OriginID,f.DestinationID,o.Code OriginCode,d.Code DestinationCode,o.City OriginCity,d.City DestinationCity,f.DepartureTime,f.ArrivalTime,o.IanaTimeZone OriginTimeZone,d.IanaTimeZone DestinationTimeZone FROM dbo.BookingPassengers bp JOIN dbo.Passengers p ON p.PassengerID=bp.PassengerID JOIN dbo.Tickets t ON t.BookingPassengerID=bp.BookingPassengerID JOIN dbo.FareClasses c ON c.FareClassID=t.FareClassID JOIN dbo.FlightSeatAssignments a ON a.AssignmentID=t.AssignmentID JOIN dbo.AircraftSeats se ON se.SeatID=a.SeatID JOIN dbo.BookingSegments bs ON bs.BookingSegmentID=t.BookingSegmentID JOIN dbo.Flights f ON f.FlightID=bs.FlightID JOIN dbo.Airports o ON o.AirportID=f.OriginID JOIN dbo.Airports d ON d.AirportID=f.DestinationID WHERE bp.BookingID=? ORDER BY bs.SegmentOrder,t.TicketID', (booking_id,))
    decorate_flights(tickets)
    decorate_flights([booking])
    payments = query('SELECT PaymentID,Amount,Kind,Status,CreatedAt FROM dbo.Payments WHERE BookingID=? ORDER BY PaymentID', (booking_id,))
    return jsonify(booking=booking, tickets=tickets, payments=payments, segments=segments)


@bp.post('/<int:booking_id>/payments')
@authenticated()
def pay(booking_id):
    owned_booking(booking_id, g.user)
    data = body()
    if type(data.get('Success')) is not bool:
        raise ApiError('Success phải là true hoặc false cho thanh toán giả lập.')
    key = text(data, 'IdempotencyKey', 16, 80)
    return jsonify(payment=confirm_payment(g.user['UserID'], booking_id, key, data['Success']))


@bp.post('/<int:booking_id>/cancel')
@authenticated()
def cancel(booking_id):
    owned_booking(booking_id, g.user)
    return jsonify(result=cancel_booking(g.user['UserID'], booking_id))
