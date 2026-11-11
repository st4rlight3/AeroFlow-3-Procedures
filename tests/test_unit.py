import pyodbc
import pytest
from app.validation import integer,decimal_value,utc_datetime
from app.errors import ApiError
from app.db import translate_error
from conftest import send

def test_frontend_and_security_headers(client):
    r=client.get('/')
    assert r.status_code==200 and 'AeroFlow' in r.text
    assert "script-src 'self'" in r.headers['Content-Security-Policy']
    assert r.headers['X-Frame-Options']=='DENY'
    assert client.get('/static/app.js').status_code==200
    assert client.get('/static/style.css').status_code==200

def test_csrf_rejects_missing_token(client):
    assert client.post('/api/auth/login',json={'Email':'a@b.c','Password':'x'}).status_code==403

def test_unauthenticated_endpoints(client):
    for path in ('/api/me','/api/bookings','/api/admin/overview'):
        assert client.get(path).status_code==401

def test_json_and_required_validation(client):
    assert send(client,'/api/auth/register',{}).status_code==400
    assert send(client,'/api/auth/login',{'Email':'not-email','Password':'x'}).status_code==400
    assert client.get('/api/flights?origin=1%20OR%201=1&destination=2&date=2026-10-20&passengers=1').status_code==400

@pytest.mark.parametrize('value',['1 OR 1=1',True,'-1',None,3.5,'²','9'*4500])
def test_integer_rejects_invalid(value):
    with pytest.raises(ApiError):integer({'x':value},'x')

@pytest.mark.parametrize('value',['NaN','Infinity','-1','100000001'])
def test_decimal_rejects_invalid(value):
    with pytest.raises(ApiError):decimal_value({'x':value},'x')

def test_timestamp_requires_timezone():
    with pytest.raises(ApiError):utc_datetime('2026-10-20T10:00:00')
    assert utc_datetime('2026-10-20T10:00:00+07:00').hour==3

def test_unavailable_database_safe_response(client,monkeypatch):
    def fail(*args,**kwargs):raise pyodbc.OperationalError('08001','server=private;pwd=DO_NOT_EXPOSE')
    monkeypatch.setattr('app.db.pyodbc.connect',fail)
    r=client.get('/api/health')
    assert r.status_code==503
    assert r.get_json()['error']['code']=='DATABASE_UNAVAILABLE'
    assert 'DO_NOT_EXPOSE' not in r.text and 'Traceback' not in r.text

def test_constraint_error_sanitized():
    e=translate_error(pyodbc.IntegrityError('23000','duplicate (2627) secret details'))
    assert e.status==409 and 'secret' not in e.message

def test_payload_limit(client):
    r=send(client,'/api/auth/register',{'FullName':'x'*40000})
    assert r.status_code==413
