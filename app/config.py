import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')

def settings():
    secret = os.getenv('SECRET_KEY', '')
    if len(secret) < 32 or secret.startswith('REPLACE_'):
        raise RuntimeError('Run python scripts/configure.py to generate SECRET_KEY in .env.')
    return dict(SECRET_KEY=secret, SESSION_COOKIE_NAME=os.getenv('SESSION_COOKIE_NAME', 'aeroflow'), SESSION_COOKIE_HTTPONLY=True,
                SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.getenv('SESSION_COOKIE_SECURE', 'false').lower() == 'true',
                PERMANENT_SESSION_LIFETIME=3600, MAX_CONTENT_LENGTH=32768,
                JSON_SORT_KEYS=False, LOGIN_LIMIT=10)

def connection_string(database=None):
    # ODBC values must be escaped independently of SQL parameterization.
    def q(value):
        return '{' + str(value).replace('}', '}}') + '}'
    parts = {'DRIVER': os.getenv('SQL_DRIVER', 'ODBC Driver 18 for SQL Server'),
             'SERVER': os.getenv('SQL_SERVER', r'.\SQLEXPRESS'),
             'DATABASE': database or os.getenv('SQL_DATABASE', 'AeroFlow'),
             'Encrypt': os.getenv('SQL_ENCRYPT', 'no'),
             'TrustServerCertificate': os.getenv('SQL_TRUST_SERVER_CERTIFICATE', 'yes')}
    if os.getenv('SQL_TRUSTED_CONNECTION', 'yes').lower() == 'yes':
        parts['Trusted_Connection'] = 'yes'
    else:
        parts.update(UID=os.getenv('SQL_USERNAME', ''), PWD=os.getenv('SQL_PASSWORD', ''))
    return ';'.join(f'{k}={q(v)}' for k, v in parts.items())
