from pathlib import Path
import sqlite3,zipfile
b=Path(r'C:\Users\haowei\Desktop\夜间水质资料\夜间水质资料');a=b/'标定上位机V3/标定上位机V3'
c=sqlite3.connect((a/'data/2026-09-08.db').as_uri()+'?mode=ro',uri=True)
print('CAPTURE_SCHEMA',c.execute('pragma table_info(captures)').fetchall())
print('DN_SCHEMA',c.execute('pragma table_info(spectra_dn)').fetchall())
rows=c.execute('select r.raw_content from captures c join raw_data r on c.raw_data_id=r.raw_data_id where c.probe_id=2 limit 5').fetchall()
for (raw,) in rows:
 print('OCR_RAW',len(raw),raw[:24].hex(' '),raw[-6:].hex(' '))
 if len(raw) in (599,1171): print('CHECKSUM',sum(raw[:-3])&255==raw[-3])
print('OCR_COUNT',c.execute('select count(*),count(raw_data_id) from captures where probe_id=2').fetchone());c.close()
p=b/'多参数软件.A1.5.2(2)/多参数软件/lib/wqa_dev_modbus.jar'
with zipfile.ZipFile(p) as z:
 print('WATER_DRIVER_ENTRIES','\n'.join(z.namelist()))
 for n in ['mod_messages.properties','mod_messages_zh_CN.properties']:
  s=z.read(n).decode('utf-8',errors='replace');print(n,s[:5000])
