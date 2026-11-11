import argparse
from getpass import getpass
from pathlib import Path
import re
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from werkzeug.security import generate_password_hash
from app.db import query

parser=argparse.ArgumentParser(description='Create a local AeroFlow account; password is never printed.')
parser.add_argument('--role', choices=['ADMIN','CUSTOMER'], default='ADMIN')
parser.add_argument('--email', required=True)
parser.add_argument('--name', default='Quản trị AeroFlow')
args=parser.parse_args()
if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',args.email) or len(args.email)>254 or not 2<=len(args.name)<=120:
    raise SystemExit('Invalid email or name.')
password=getpass('Password (12+ characters): ')
if len(password)<12 or len(password)>128 or password!=getpass('Confirm password: '):
    raise SystemExit('Password invalid or confirmation differs.')
role=query('SELECT RoleID FROM dbo.Roles WHERE Name=?',(args.role,),one=True)
query('INSERT dbo.Users(RoleID,Email,FullName,PasswordHash) VALUES(?,?,?,?)',(role['RoleID'],args.email.lower(),args.name,generate_password_hash(password,method='scrypt')))
print('Account created.')
