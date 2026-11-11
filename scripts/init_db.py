"""Create a fresh SQL Server database from the eight installation scripts."""
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import connection_string
import pyodbc

ORDER = [
    '02_create_tables.sql', '03_constraints_indexes.sql', '04_seed_data.sql',
    '06_functions.sql', '05_views.sql', '07_stored_procedures.sql', '08_triggers.sql',
]


def batches(text):
    for batch in re.split(r'^\s*GO\s*$', text, flags=re.MULTILINE | re.IGNORECASE):
        if batch.strip():
            yield batch


def main():
    name = os.getenv('SQL_DATABASE', 'AeroFlow')
    if not re.fullmatch(r'AeroFlow(?:_[A-Za-z0-9_]+)?', name):
        raise SystemExit('SQL_DATABASE must be AeroFlow or AeroFlow_<suffix>.')
    root = Path(__file__).resolve().parents[1]
    with pyodbc.connect(connection_string('master'), autocommit=True, timeout=10) as master:
        # A session lock also prevents two installers from initializing the same name.
        lock = master.execute("DECLARE @r int; EXEC @r=sys.sp_getapplock "
                              "@Resource=?,@LockMode='Exclusive',@LockOwner='Session',@LockTimeout=0; SELECT @r;",
                              'AeroFlow:install:' + name).fetchone()[0]
        if lock < 0:
            raise SystemExit('Another installer is using this database. Please try again.')
        if master.execute('SELECT DB_ID(?)', name).fetchone()[0] is not None:
            with pyodbc.connect(connection_string(name), autocommit=True, timeout=10) as existing:
                if existing.execute('SELECT COUNT(*) FROM sys.tables WHERE is_ms_shipped=0').fetchone()[0]:
                    raise SystemExit('Database already contains tables. Nothing changed. '
                                     'Run run.py to open the project, or choose a new SQL_DATABASE in .env.')
        script = (root / 'sql' / '01_create_database.sql').read_text(encoding='utf-8-sig')
        script = re.sub(r'\bAeroFlow\b', name, script)
        for batch in batches(script):
            cursor = master.execute(batch)
            while cursor.nextset():
                pass
        with pyodbc.connect(connection_string(name), autocommit=False, timeout=10) as conn:
            conn.timeout = 120
            try:
                conn.execute('SET XACT_ABORT ON;')
                if conn.execute('SELECT COUNT(*) FROM sys.tables WHERE is_ms_shipped=0').fetchone()[0]:
                    raise RuntimeError('Database is no longer empty. No tables were changed.')
                for filename in ORDER:
                    sql = (root / 'sql' / filename).read_text(encoding='utf-8-sig')
                    sql = sql.replace('USE AeroFlow;', f'USE [{name}];')
                    for batch in batches(sql):
                        cursor = conn.execute(batch)
                        while cursor.nextset():
                            pass
                    print('READ', filename, flush=True)
                count = conn.execute('SELECT COUNT(*) FROM dbo.Flights').fetchone()[0]
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        print(f'Database {name} ready: {count} flights. Sample accounts are disabled.')


if __name__ == '__main__':
    main()
