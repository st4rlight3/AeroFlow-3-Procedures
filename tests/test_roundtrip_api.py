"""Two direct flights share one booking, one payment and one cancellation."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
import uuid

import pytest

from app.db import query
from app.services.flight_commands import save_flight
from conftest import book, pay, send, sign_in


pytestmark = pytest.mark.integration


def returning_flight(flight):
    departure = flight['DepartureTime'] + timedelta(days=2)
    fid = save_flight(
        None, 'R'+uuid.uuid4().hex[:7], flight['AircraftID'],
        flight['DestinationID'], flight['OriginID'], departure,
        departure+timedelta(hours=2))['FlightID']
    query('EXEC dbo.sp_SaveFare ?,?,?,?', (fid, flight['FareClassID'], 1000000, '.1'))
    return {**flight, 'FlightID': fid, 'OriginID': flight['DestinationID'],
            'DestinationID': flight['OriginID'], 'DepartureTime': departure}


def roundtrip_data(outbound, returning):
    return {'FlightID': outbound['FlightID'], 'ReturnFlightID': returning['FlightID'],
            'Passengers': [{'FullName': 'Khách khứ hồi', 'DateOfBirth': '1995-01-01',
                'DocumentNumber': 'RT-'+uuid.uuid4().hex[:12],
                'SeatID': outbound['Seats'][0]['SeatID'], 'FareClassID': outbound['FareClassID'],
                'ReturnSeatID': returning['Seats'][0]['SeatID'], 'ReturnFareClassID': returning['FareClassID']}]}


def test_roundtrip_quote_payment_and_full_cancellation(app, users, flight):
    customer = sign_in(app, users[0])
    returning = returning_flight(flight)
    payload = roundtrip_data(flight, returning)
    quoted = send(customer, '/api/bookings/quote', payload)
    assert quoted.status_code == 200, quoted.json
    quote = quoted.json['quote']
    assert Decimal(quote['Total']) == 2200000 and len(quote['Lines']) == 2
    created = send(customer, '/api/bookings', {**payload, 'ExpectedTotal': quote['Total']})
    assert created.status_code == 201, created.json
    booking_id = created.json['booking']['BookingID']
    detail = customer.get(f'/api/bookings/{booking_id}').json
    assert len(detail['segments']) == len(detail['tickets']) == 2
    assert detail['booking']['SegmentCount'] == 2
    assert detail['booking']['PassengerCount'] == 1
    assert [s['SegmentOrder'] for s in detail['segments']] == [1, 2]
    assert pay(customer, booking_id).status_code == 200
    for _ in range(2):
        result = send(customer, f'/api/bookings/{booking_id}/cancel')
        assert result.status_code == 200, result.json
    payments = query('SELECT Kind,Amount FROM dbo.Payments WHERE BookingID=? ORDER BY PaymentID', (booking_id,))
    assert payments == [{'Kind': 'CHARGE', 'Amount': Decimal('2200000')},
                        {'Kind': 'REFUND', 'Amount': Decimal('1760000')}]
    assert not query('''SELECT a.AssignmentID FROM dbo.FlightSeatAssignments a
        JOIN dbo.Tickets t ON t.AssignmentID=a.AssignmentID
        JOIN dbo.BookingPassengers bp ON bp.BookingPassengerID=t.BookingPassengerID
        WHERE bp.BookingID=? AND a.IsActive=1''', (booking_id,))


def test_second_leg_conflict_rolls_back_every_first_leg_write(app, users, flight):
    returning = returning_flight(flight)
    other = sign_in(app, users[1])
    book(other, returning)
    tables = ('Bookings', 'BookingSegments', 'Passengers', 'BookingPassengers',
              'FlightSeatAssignments', 'Tickets', 'AuditLogs')
    before = {t: query('SELECT COUNT(*) N FROM dbo.'+t, one=True)['N'] for t in tables}
    customer = sign_in(app, users[0])
    result = send(customer, '/api/bookings', roundtrip_data(flight, returning))
    assert result.status_code == 409, result.json
    assert result.json['error']['code'] == 'SQL_51005'
    after = {t: query('SELECT COUNT(*) N FROM dbo.'+t, one=True)['N'] for t in tables}
    assert before == after


def test_return_leg_read_releases_expired_seats_in_both_directions(app, users, flight):
    returning = returning_flight(flight)
    customer = sign_in(app, users[0])
    result = send(customer, '/api/bookings', roundtrip_data(flight, returning))
    assert result.status_code == 201, result.json
    bid = result.json['booking']['BookingID']
    query('''UPDATE dbo.Bookings SET CreatedAt=DATEADD(minute,-11,SYSUTCDATETIME()),
        ExpiresAt=DATEADD(minute,-1,SYSUTCDATETIME()) WHERE BookingID=?''', (bid,))
    assert customer.get(f"/api/flights/{returning['FlightID']}/seats").status_code == 200
    detail = customer.get(f'/api/bookings/{bid}').json
    assert detail['booking']['Status'] == 'EXPIRED'
    assert all(t['Status'] == 'VOID' for t in detail['tickets'])
    assert pay(customer, bid).status_code == 409
    for leg in (flight, returning):
        assert query('SELECT COUNT(*) N FROM dbo.FlightSeatAssignments WHERE FlightID=? AND IsActive=1',
                     (leg['FlightID'],), one=True)['N'] == 0


def test_changed_fare_invalidates_quote_and_existing_tickets_keep_their_price(app, users, flight):
    returning = returning_flight(flight)
    customer = sign_in(app, users[0])
    payload = roundtrip_data(flight, returning)
    quote = send(customer, '/api/bookings/quote', payload)
    assert quote.status_code == 200, quote.json
    query('EXEC dbo.sp_SaveFare ?,?,?,?', (flight['FlightID'], flight['FareClassID'], 1100000, '.1'))
    result = send(customer, '/api/bookings', {**payload, 'ExpectedTotal': quote.json['quote']['Total']})
    assert result.status_code == 409 and result.json['error']['code'] == 'SQL_51013', result.json
    assert not query('SELECT BookingID FROM dbo.Bookings WHERE UserID=?', (users[0]['UserID'],))
    current_quote = send(customer, '/api/bookings/quote', payload).json['quote']
    assert Decimal(current_quote['Total']) == 2310000
    created = send(customer, '/api/bookings', {**payload, 'ExpectedTotal': current_quote['Total']})
    assert created.status_code == 201, created.json
    query('EXEC dbo.sp_SaveFare ?,?,?,?', (flight['FlightID'], flight['FareClassID'], 1200000, '.1'))
    assert Decimal(customer.get(f"/api/bookings/{created.json['booking']['BookingID']}").json['booking']['TotalAmount']) == 2310000


def test_two_roundtrips_cannot_share_the_last_return_seat(app, users, flight):
    returning = returning_flight(flight)
    airline = query('SELECT AirlineID FROM dbo.Aircraft WHERE AircraftID=?', (flight['AircraftID'],), one=True)['AirlineID']
    aircraft = query('''SET NOCOUNT ON; INSERT dbo.Aircraft(AirlineID,Registration,Model)
        VALUES(?,?,N'Test aircraft'); SELECT CONVERT(int,SCOPE_IDENTITY()) ID''',
        (airline, 'C-'+uuid.uuid4().hex[:14]), one=True)['ID']
    query("INSERT dbo.AircraftSeats(AircraftID,SeatNumber,RowNumber,ColumnLetter,Cabin) VALUES(?,'A1',1,'A','ECONOMY')", (aircraft,))
    depart = flight['DepartureTime']+timedelta(hours=1)
    fid = save_flight(None, 'C'+uuid.uuid4().hex[:7], aircraft,
                      flight['OriginID'], flight['DestinationID'], depart,
                      depart+timedelta(hours=2))['FlightID']
    query('EXEC dbo.sp_SaveFare ?,?,?,?', (fid, flight['FareClassID'], 1000000, '.1'))
    seats = query('EXEC dbo.sp_GetAvailableSeats ?', (fid,))
    second = {**flight, 'FlightID': fid, 'AircraftID': aircraft, 'Seats': seats}
    clients = [sign_in(app, u) for u in users[:2]]
    payloads = [roundtrip_data(flight, returning), roundtrip_data(second, returning)]
    barrier = Barrier(2)

    def attempt(index):
        barrier.wait(timeout=10)
        response = send(clients[index], '/api/bookings', payloads[index])
        return index, response.status_code, response.json

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sorted(status for _, status, _ in results) == [201, 409], results
    loser = next(index for index, status, _ in results if status == 409)
    assert not query('SELECT BookingID FROM dbo.Bookings WHERE UserID=?', (users[loser]['UserID'],))
    assert query('SELECT COUNT(*) N FROM dbo.FlightSeatAssignments WHERE FlightID=? AND IsActive=1',
                 (returning['FlightID'],), one=True)['N'] == 1


def test_database_stays_within_the_agreed_inventory(sql_ready):
    types = {row['type'].strip(): row['N'] for row in query('''SELECT type,COUNT(*) N
        FROM sys.objects WHERE schema_id=SCHEMA_ID('dbo') AND type IN ('U','V','FN','P','TR')
        AND is_ms_shipped=0 GROUP BY type''')}
    assert types == {'U': 17, 'V': 4, 'FN': 2, 'P': 3, 'TR': 6}
    procedures = query("""SELECT name FROM sys.procedures
        WHERE schema_id=SCHEMA_ID('dbo') AND is_ms_shipped=0""")
    assert {row['name'] for row in procedures} == {
        'sp_GetAvailableSeats', 'sp_GetRevenueReport', 'sp_SaveFare',
    }
