import os
import uuid
from datetime import datetime, timedelta, timezone
import pytest
from werkzeug.security import generate_password_hash
from app import create_app
from app.db import query
from app.services.flight_commands import save_flight

@pytest.fixture
def app():
    os.environ.setdefault('SECRET_KEY','unit-test-only-key-that-is-not-for-deployment')
    return create_app({'TESTING':True,'LOGIN_LIMIT':10000})

@pytest.fixture
def client(app):
    return app.test_client()

def token(client):
    return client.get('/api/csrf').get_json()['token']

def send(client,path,data=None,method='POST'):
    return client.open(path,method=method,json=data or {},headers={'X-CSRF-Token':token(client)})

def sign_in(app,user):
    client=app.test_client()
    r=send(client,'/api/auth/login',{'Email':user['Email'],'Password':user['Password']})
    assert r.status_code==200,r.get_json()
    return client

@pytest.fixture
def sql_ready():
    if os.getenv('RUN_SQL_TESTS')!='1':
        pytest.skip('RUN_SQL_TESTS=1 and isolated SQL Server database required')
    if not os.getenv('SQL_DATABASE','').startswith('AeroFlow_Test_'):
        pytest.fail('Integration suite requires SQL_DATABASE=AeroFlow_Test_<suffix>')
    assert query('SELECT 1 Ready',one=True)['Ready']==1

@pytest.fixture
def users(sql_ready):
    result=[]
    for role in ('CUSTOMER','CUSTOMER','ADMIN'):
        email=f'test-{uuid.uuid4().hex}@aeroflow.example'
        password='Test-'+uuid.uuid4().hex
        r=query('SET NOCOUNT ON; INSERT dbo.Users(RoleID,Email,FullName,PasswordHash) VALUES((SELECT RoleID FROM dbo.Roles WHERE Name=?),?,?,?); SELECT CONVERT(int,SCOPE_IDENTITY()) UserID;',
                (role,email,'Khách kiểm thử',generate_password_hash(password,method='scrypt')),one=True)
        result.append(dict(UserID=r['UserID'],Email=email,Password=password,Role=role))
    return result

@pytest.fixture
def flight(sql_ready):
    # Independent new aircraft per test, avoiding collisions with the seed timetable.
    airline=query('SELECT TOP(1) AirlineID FROM dbo.Airlines ORDER BY AirlineID',one=True)['AirlineID']
    aircraft=query('SET NOCOUNT ON; INSERT dbo.Aircraft(AirlineID,Registration,Model) VALUES(?,?,?); SELECT CONVERT(int,SCOPE_IDENTITY()) ID;',
                   (airline,'T-'+uuid.uuid4().hex[:14],'Test aircraft'),one=True)['ID']
    for row in (1,2):
        for col in 'ABCDEF':
            query('INSERT dbo.AircraftSeats(AircraftID,SeatNumber,RowNumber,ColumnLetter,Cabin) VALUES(?,?,?,?,?)',(aircraft,f'{col}{row}',row,col,'ECONOMY'))
    origin=query("SELECT AirportID FROM dbo.Airports WHERE Code='HAN'",one=True)['AirportID']
    dest=query("SELECT AirportID FROM dbo.Airports WHERE Code='SGN'",one=True)['AirportID']
    departure=datetime.now(timezone.utc).replace(tzinfo=None,microsecond=0)+timedelta(days=5)
    f=save_flight(None, 'T'+uuid.uuid4().hex[:7], aircraft, origin, dest,
                  departure, departure+timedelta(hours=2))['FlightID']
    cls=query("SELECT FareClassID FROM dbo.FareClasses WHERE Code='FLEX'",one=True)['FareClassID']
    query('EXEC dbo.sp_SaveFare ?,?,?,?',(f,cls,1000000,.1))
    seats=query('EXEC dbo.sp_GetAvailableSeats ?',(f,))
    return dict(FlightID=f,AircraftID=aircraft,OriginID=origin,DestinationID=dest,DepartureTime=departure,FareClassID=cls,Seats=seats)

def booking_data(flight,index=0,document=None):
    return {'FlightID':flight['FlightID'],'Passengers':[{'SeatID':flight['Seats'][index]['SeatID'],'FareClassID':flight['FareClassID'],'FullName':'Nguyễn Kiểm Thử','DateOfBirth':'1995-04-20','DocumentNumber':document or 'DEMO-'+uuid.uuid4().hex[:12]}]}

def book(client,flight,index=0):
    r=send(client,'/api/bookings',booking_data(flight,index))
    assert r.status_code==201,r.get_json()
    return r.get_json()['booking']

def pay(client,bid,success=True,key=None):
    return send(client,f'/api/bookings/{bid}/payments',{'Success':success,'IdempotencyKey':key or uuid.uuid4().hex})
