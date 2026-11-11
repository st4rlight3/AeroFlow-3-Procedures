"""Generate a private local .env, without overwriting existing configuration."""
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
target = root / '.env'
if target.exists():
    print('.env already exists; preserved.')
else:
    data = (root/'.env.example').read_text(encoding='utf-8')
    target.write_text(data.replace('REPLACE_WITH_RANDOM_64_HEX_CHARACTERS', secrets.token_hex(32)), encoding='utf-8')
    print('Created .env. Check SQL_SERVER and SQL_DATABASE before initializing.')
