"""Read-only inventory plus rollback-only SQL constraint tests. Save truthful evidence."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.db import query,connection

root=Path(__file__).resolve().parents[1]
tables=query("SELECT name FROM sys.tables WHERE schema_id=SCHEMA_ID('dbo') ORDER BY name")
snapshot={'checked_at_utc':datetime.now(timezone.utc).isoformat(),
          'server':query("SELECT CONVERT(varchar(50),SERVERPROPERTY('Edition')) Edition,CONVERT(varchar(30),SERVERPROPERTY('ProductVersion')) Version",one=True),
          'tables':{t['name']:query('SELECT COUNT(*) [RowCount] FROM dbo.['+t['name']+']',one=True)['RowCount'] for t in tables},
          'objects':query("SELECT type_desc,COUNT(*) N FROM sys.objects WHERE is_ms_shipped=0 AND type IN ('U','V','P','FN','TR','PK','F','UQ','C','D') GROUP BY type_desc ORDER BY type_desc"),
          'columns':query("SELECT t.name TableName,c.column_id Ordinal,c.name ColumnName,ty.name DataType,c.max_length MaxLength,c.precision Precision,c.scale Scale,c.is_nullable Nullable,c.is_identity IsIdentity FROM sys.tables t JOIN sys.columns c ON c.object_id=t.object_id JOIN sys.types ty ON ty.user_type_id=c.user_type_id WHERE t.schema_id=SCHEMA_ID('dbo') ORDER BY t.name,c.column_id"),
          'foreign_keys':query("SELECT fk.name ConstraintName,OBJECT_NAME(fkc.parent_object_id) ParentTable,COL_NAME(fkc.parent_object_id,fkc.parent_column_id) ParentColumn,OBJECT_NAME(fkc.referenced_object_id) ReferencedTable,COL_NAME(fkc.referenced_object_id,fkc.referenced_column_id) ReferencedColumn FROM sys.foreign_keys fk JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id=fk.object_id ORDER BY fk.name,fkc.constraint_column_id"),
          'constraints':query("SELECT OBJECT_NAME(parent_object_id) TableName,name,type_desc FROM sys.objects WHERE type IN ('PK','UQ','C','D') AND is_ms_shipped=0 ORDER BY TableName,name"),
          'indexes':query("SELECT OBJECT_NAME(object_id) TableName,name,is_unique,filter_definition FROM sys.indexes WHERE object_id IN(SELECT object_id FROM sys.tables WHERE schema_id=SCHEMA_ID('dbo')) AND name IS NOT NULL ORDER BY TableName,name")}
checks=[]
for filename in ('09_business_queries.sql','10_test_cases.sql'):
    text=(root/'sql'/filename).read_text(encoding='utf-8').replace('USE AeroFlow;','')
    rowsets=[]
    with connection() as conn:
        for batch in re.split(r'^\s*GO\s*$',text,flags=re.MULTILINE|re.IGNORECASE):
            if not batch.strip():continue
            c=conn.cursor().execute(batch)
            while True:
                if c.description:rowsets.append({'columns':[x[0] for x in c.description],'rows':len(c.fetchall())})
                if not c.nextset():break
    checks.append({'script':filename,'result':'executed_without_error','result_sets':rowsets})
(root/'evidence').mkdir(exist_ok=True)
(root/'evidence/database-inventory.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
(root/'evidence/sql-checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'tables':snapshot['tables'],'objects':snapshot['objects'],'checks':[(x['script'],x['result']) for x in checks]},ensure_ascii=False,indent=2))
