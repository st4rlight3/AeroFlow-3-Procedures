import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import timedelta
import pyodbc
import pytest
from app.db import query
from conftest import send,sign_in,book,pay,booking_data

pytestmark=pytest.mark.integration

def test_registration_login_logout(app,sql_ready):
    c=app.test_client();email=f'reg-{uuid.uuid4().hex}@aeroflow.example';password='Demo-'+uuid.uuid4().hex
    payload={'Email':email,'Password':password,'FullName':'Khách đăng ký'}
    assert send(c,'/api/auth/register',payload).status_code==201
    assert send(c,'/api/auth/register',payload).status_code==409
    assert send(c,'/api/auth/login',{'Email':email,'Password':'wrong'}).status_code==401
    assert send(c,'/api/auth/login',payload).status_code==200
    assert c.get('/api/me').get_json()['user']['Role']=='CUSTOMER'
    stored=query('SELECT PasswordHash FROM dbo.Users WHERE Email=?',(email,),one=True)['PasswordHash']
    assert stored.startswith('scrypt:') and stored!=password
    assert send(c,'/api/auth/logout').status_code==200
    assert c.get('/api/me').status_code==401

def test_roles_and_admin_views(app,users):
    c=sign_in(app,users[0]);a=sign_in(app,users[2])
    assert c.get('/api/admin/overview').status_code==403
    for endpoint in ('overview','flights','bookings','customers','payments','audit','reports/revenue'):
        assert a.get('/api/admin/'+endpoint).status_code==200

def test_search_and_details(app,flight):
    c=app.test_client();f=flight
    day=(f['DepartureTime']+timedelta(hours=7)).date().isoformat()
    r=c.get(f"/api/flights?origin={f['OriginID']}&destination={f['DestinationID']}&date={day}&passengers=2")
    assert r.status_code==200 and any(x['FlightID']==f['FlightID'] for x in r.get_json()['items'])
    assert c.get(f"/api/flights/{f['FlightID']}").get_json()['fares'][0]['Price']=='1100000.00'
    assert len(c.get(f"/api/flights/{f['FlightID']}/seats").get_json()['items'])==12

def test_booking_uses_database_price_and_seat_conflict(app,users,flight):
    c=sign_in(app,users[0]);payload=booking_data(flight);payload['TotalAmount']=1
    r=send(c,'/api/bookings',payload);assert r.status_code==201,r.get_json()
    assert r.get_json()['booking']['TotalAmount']=='1100000.00'
    other=sign_in(app,users[1]);conflict=send(other,'/api/bookings',payload)
    assert conflict.status_code==409 and conflict.get_json()['error']['code']=='SQL_51005'

def test_two_customers_same_seat_concurrently(app,users,flight):
    clients=[sign_in(app,u) for u in users[:2]];barrier=Barrier(2);data=booking_data(flight)
    def attempt(c):
        barrier.wait(timeout=10)
        r=send(c,'/api/bookings',data)
        return r.status_code,r.get_json()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(attempt,clients))
    assert sorted(x[0] for x in results)==[201,409],results
    count=query('SELECT COUNT(*) N FROM dbo.FlightSeatAssignments WHERE FlightID=? AND SeatID=? AND IsActive=1',(flight['FlightID'],flight['Seats'][0]['SeatID']),one=True)['N']
    assert count==1

def test_failed_duplicate_and_success_payment(app,users,flight):
    c=sign_in(app,users[0]);b=book(c,flight);bid=b['BookingID'];k=uuid.uuid4().hex
    failed=pay(c,bid,False,k);assert failed.status_code==200
    assert pay(c,bid,False,k).get_json()['payment']['PaymentID']==failed.get_json()['payment']['PaymentID']
    assert c.get(f'/api/bookings/{bid}').get_json()['booking']['Status']=='HELD'
    assert pay(c,bid,True,k).status_code==409
    key=uuid.uuid4().hex;success=pay(c,bid,True,key);assert success.status_code==200
    assert pay(c,bid,True,key).get_json()['payment']['PaymentID']==success.get_json()['payment']['PaymentID']
    assert pay(c,bid).status_code==409
    d=c.get(f'/api/bookings/{bid}').get_json();assert d['booking']['Status']=='CONFIRMED' and d['tickets'][0]['Status']=='VALID'
    assert query("SELECT COUNT(*) N FROM dbo.Payments WHERE BookingID=? AND Status='SUCCESS' AND Kind='CHARGE'",(bid,),one=True)['N']==1

def test_concurrent_payment_exactly_once(app,users,flight):
    c=sign_in(app,users[0]);b=book(c,flight);clients=[sign_in(app,users[0]),sign_in(app,users[0])];barrier=Barrier(2);key=uuid.uuid4().hex
    def attempt(client):barrier.wait(timeout=10);return pay(client,b['BookingID'],True,key)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(attempt,clients))
    assert all(r.status_code==200 for r in results)
    assert len({r.get_json()['payment']['PaymentID'] for r in results})==1

def test_expired_hold_releases_and_cannot_pay(app,users,flight):
    c=sign_in(app,users[0]);b=book(c,flight)
    query('UPDATE dbo.Bookings SET CreatedAt=DATEADD(minute,-11,SYSUTCDATETIME()),ExpiresAt=DATEADD(minute,-1,SYSUTCDATETIME()) WHERE BookingID=?',(b['BookingID'],))
    assert pay(c,b['BookingID']).status_code==409
    d=c.get(f"/api/bookings/{b['BookingID']}").get_json();assert d['booking']['Status']=='EXPIRED' and d['tickets'][0]['Status']=='VOID'
    assert book(sign_in(app,users[1]),flight)['Status']=='HELD'

def test_cancel_refund_and_idempotent_release(app,users,flight):
    c=sign_in(app,users[0]);b=book(c,flight);assert pay(c,b['BookingID']).status_code==200
    for _ in range(2):assert send(c,f"/api/bookings/{b['BookingID']}/cancel").status_code==200
    refund=query("SELECT Amount FROM dbo.Payments WHERE BookingID=? AND Kind='REFUND'",(b['BookingID'],))
    assert len(refund)==1 and str(refund[0]['Amount'])=='880000.00'
    assert book(sign_in(app,users[1]),flight)['Status']=='HELD'

def test_cancel_cutoff(app,users,flight):
    query('UPDATE dbo.Flights SET DepartureTime=DATEADD(hour,12,SYSUTCDATETIME()),ArrivalTime=DATEADD(hour,14,SYSUTCDATETIME()) WHERE FlightID=?',(flight['FlightID'],))
    c=sign_in(app,users[0]);b=book(c,flight);assert pay(c,b['BookingID']).status_code==200
    assert send(c,f"/api/bookings/{b['BookingID']}/cancel").status_code==409

def test_ownership_prevents_idor(app,users,flight):
    c=sign_in(app,users[0]);b=book(c,flight);other=sign_in(app,users[1]);bid=b['BookingID']
    assert other.get(f'/api/bookings/{bid}').status_code==404
    assert pay(other,bid).status_code==404
    assert send(other,f'/api/bookings/{bid}/cancel').status_code==404

def test_booking_validation(app,users,flight):
    c=sign_in(app,users[0]);assert send(c,'/api/bookings',{'FlightID':flight['FlightID'],'Passengers':[]}).status_code==400
    d=booking_data(flight);d['Passengers'][0]['DateOfBirth']='2099-01-01';assert send(c,'/api/bookings',d).status_code==400
    d=booking_data(flight);d['Passengers']*=2;assert send(c,'/api/bookings',d).status_code==400
    d=booking_data(flight);d['Passengers'][0]['SeatID']=2147483647;assert send(c,'/api/bookings',d).status_code==400

def test_sql_injection_is_data(app,users,flight):
    c=sign_in(app,users[0]);d=booking_data(flight);d['Passengers'][0]['FullName']="Test'); DROP TABLE dbo.Users;--"
    assert send(c,'/api/bookings',d).status_code==201
    assert query('SELECT COUNT(*) N FROM dbo.Users',one=True)['N']>0
    assert send(c,'/api/auth/login',{'Email':"x'OR'1'='1@example.com",'Password':'anything'}).status_code==401

def test_transaction_rollback_after_partial_writes(app,users,flight):
    before={t:query(f'SELECT COUNT(*) N FROM dbo.{t}',one=True)['N'] for t in ('Bookings','Passengers','BookingPassengers','Tickets','FlightSeatAssignments','AuditLogs')}
    # Fault after booking and passenger inserts, inside the same SQL transaction.
    query("""CREATE OR ALTER TRIGGER dbo.tr_TestFault ON dbo.Tickets AFTER INSERT AS
    BEGIN IF EXISTS(SELECT 1 FROM inserted i JOIN dbo.BookingPassengers bp ON bp.BookingPassengerID=i.BookingPassengerID JOIN dbo.Passengers p ON p.PassengerID=bp.PassengerID WHERE p.DocumentNumber=N'ROLLBACK_FAULT') THROW 51999,'Injected test failure',1; END""")
    try:
        c=sign_in(app,users[0]);d=booking_data(flight,document='ROLLBACK_FAULT');r=send(c,'/api/bookings',d)
        assert r.status_code==503
    finally:query('DROP TRIGGER dbo.tr_TestFault')
    after={t:query(f'SELECT COUNT(*) N FROM dbo.{t}',one=True)['N'] for t in before}
    assert before==after

def test_check_unique_fk_and_consistency(sql_ready):
    statements=[("INSERT dbo.Airports(Code,Name,City) VALUES('HAN',N'Duplicate',N'Test')",()),("INSERT dbo.Aircraft(AirlineID,Registration,Model) VALUES(-1,'INVALID','Test')",()),("UPDATE dbo.FlightFares SET BasePrice=-1 WHERE FlightID=(SELECT MIN(FlightID) FROM dbo.Flights)",())]
    for sql,params in statements:
        with pytest.raises(pyodbc.IntegrityError):query(sql,params)
    assert not query('SELECT FlightID,SeatID FROM dbo.FlightSeatAssignments WHERE IsActive=1 GROUP BY FlightID,SeatID HAVING COUNT(*)>1')
    assert not query("SELECT t.TicketID FROM dbo.Tickets t JOIN dbo.BookingPassengers p ON p.BookingPassengerID=t.BookingPassengerID JOIN dbo.Bookings b ON b.BookingID=p.BookingID JOIN dbo.FlightSeatAssignments a ON a.AssignmentID=t.AssignmentID WHERE t.Status='VALID' AND (b.Status<>'CONFIRMED' OR a.IsActive<>1)")

def test_admin_catalog_fares_and_status(app,users,flight):
    a=sign_in(app,users[2]);fid=flight['FlightID'];c=sign_in(app,users[0]);b=book(c,flight);assert pay(c,b['BookingID']).status_code==200
    assert send(a,f'/api/admin/flights/{fid}/fares/{flight["FareClassID"]}',{'BasePrice':2000000,'TaxRate':.1},'PUT').status_code==200
    assert c.get(f"/api/bookings/{b['BookingID']}").get_json()['tickets'][0]['Amount']=='1100000.00'
    assert send(a,f'/api/admin/flights/{fid}/status',{'Status':'CANCELLED'},'PUT').status_code==200
    d=c.get(f"/api/bookings/{b['BookingID']}").get_json();assert d['booking']['Status']=='CANCELLED'
    assert d['payments'][-1]['Amount']=='1100000.00'
    assert send(a,f'/api/admin/flights/{fid}/status',{'Status':'SCHEDULED'},'PUT').status_code==409
    seat=flight['Seats'][0];payload={k:seat[k] for k in ('RowNumber','ColumnLetter','Cabin')};payload.update(AircraftID=flight['AircraftID'],IsActive=True)
    assert send(a,f"/api/admin/catalog/seats/{seat['SeatID']}",payload,'PUT').status_code==409

def test_admin_creates_aircraft_flight_and_seat(app,users,flight):
    a=sign_in(app,users[2]);airline=query('SELECT TOP(1) AirlineID FROM dbo.Airlines',one=True)['AirlineID']
    r=send(a,'/api/admin/catalog/aircraft',{'AirlineID':airline,'Registration':'QA-'+uuid.uuid4().hex[:10],'Model':'QA 18','IsActive':True,'Rows':3,'BusinessRows':1})
    assert r.status_code==200,r.get_json();aircraft=r.get_json()['id']
    assert len(query('SELECT * FROM dbo.AircraftSeats WHERE AircraftID=?',(aircraft,)))==18
    d={'FlightNumber':'QA'+uuid.uuid4().hex[:6],'AircraftID':aircraft,'OriginID':flight['OriginID'],'DestinationID':flight['DestinationID'],'DepartureTime':(flight['DepartureTime']+timedelta(days=1)).isoformat()+'Z','ArrivalTime':(flight['DepartureTime']+timedelta(days=1,hours=2)).isoformat()+'Z'}
    r=send(a,'/api/admin/flights',d);assert r.status_code==201,r.get_json()
    d['FlightNumber']='QA'+uuid.uuid4().hex[:6];assert send(a,'/api/admin/flights',d).status_code==409

def test_customer_disable_invalidates_session(app,users):
    c=sign_in(app,users[0]);a=sign_in(app,users[2])
    assert send(a,f"/api/admin/customers/{users[0]['UserID']}",{'IsActive':False},'PUT').status_code==200
    assert c.get('/api/me').status_code==401

def test_filtered_unique_index_blocks_direct_double_assignment(app,users,flight):
    c=sign_in(app,users[0]);book(c,flight)
    with pytest.raises(pyodbc.IntegrityError):
        query('INSERT dbo.FlightSeatAssignments(FlightID,SeatID) VALUES(?,?)',(flight['FlightID'],flight['Seats'][0]['SeatID']))

def test_group_booking_atomic_total(app,users,flight):
    c=sign_in(app,users[0]);d=booking_data(flight);d['Passengers'].extend(booking_data(flight,1)['Passengers'])
    r=send(c,'/api/bookings',d);assert r.status_code==201,r.get_json()
    b=r.get_json()['booking'];assert b['PassengerCount']==2 and b['TotalAmount']=='2200000.00'
    assert pay(c,b['BookingID']).status_code==200
    detail=c.get(f"/api/bookings/{b['BookingID']}").get_json();assert len(detail['tickets'])==2 and all(t['Status']=='VALID' for t in detail['tickets'])

def test_payment_cancel_race_preserves_final_state(app,users,flight):
    c=sign_in(app,users[0]);b=book(c,flight);bid=b['BookingID'];clients=[sign_in(app,users[0]),sign_in(app,users[0])];barrier=Barrier(2)
    def charge():barrier.wait(timeout=10);return pay(clients[0],bid)
    def cancel():barrier.wait(timeout=10);return send(clients[1],f'/api/bookings/{bid}/cancel')
    with ThreadPoolExecutor(max_workers=2) as pool:
        p=pool.submit(charge);q=pool.submit(cancel);paid,cancelled=p.result(),q.result()
    assert paid.status_code in (200,409) and cancelled.status_code==200
    d=c.get(f'/api/bookings/{bid}').get_json();assert d['booking']['Status']=='CANCELLED' and d['tickets'][0]['Status']=='VOID'
    assert query('SELECT COUNT(*) N FROM dbo.FlightSeatAssignments WHERE FlightID=? AND IsActive=1',(flight['FlightID'],),one=True)['N']==0

def test_fare_cabin_change_is_blocked_when_used(app,users,flight):
    a=sign_in(app,users[2]);f=query('SELECT * FROM dbo.FareClasses WHERE FareClassID=?',(flight['FareClassID'],),one=True)
    f['Cabin']='BUSINESS';f['RefundPercent']=str(f['RefundPercent'])
    assert send(a,f"/api/admin/catalog/fare-classes/{flight['FareClassID']}",f,'PUT').status_code==409
