from pathlib import Path
import sqlite3,zipfile,re,json,subprocess
b=Path(r'C:\Users\haowei\Desktop\夜间水质资料\夜间水质资料'); a=b/'标定上位机V3/标定上位机V3'
for p in (a/'doc').rglob('*.md'):
 s=p.read_text(encoding='utf-8-sig'); print('DOC',p.name,len(s),' | '.join(re.findall(r'^#{1,2} (.+)',s,re.M)[:7]))
for p in (a/'data').glob('*.db'):
 c=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True)
 print('DB',p.name)
 for t in ['raw_data','captures','spectra_dn']:
  print(t,c.execute('select count(*) from '+t).fetchone()[0])
 print('RAW_SCHEMA',c.execute('pragma table_info(raw_data)').fetchall())
 print('MATCH_PROBES',c.execute("select * from probes where serial_number like '%0382' or serial_number like '%2100'").fetchall())
 print('RAW_SAMPLE',str(c.execute('select * from raw_data limit 1').fetchone())[:350]);c.close()
for p in (a/'cal').rglob('*'):
 if p.is_file() and ('0382' in p.name or '2100' in p.name):
  print('CAL_MATCH',p.relative_to(a))
  if p.suffix=='.json':
   d=json.loads(p.read_text(encoding='utf-8-sig'));print('CAL_KEYS',list(d) if isinstance(d,dict) else type(d).__name__); print(str(d)[:500])
for p in [b/'标定上位机V3.zip',b/'多参数软件.A1.5.2(2)/多参数软件/lib/wqa_dev_modbus.jar',b/'多参数软件.A1.5.2(2)/多参数软件/mwqa_windows2.jar']:
 with zipfile.ZipFile(p) as z:
  names=z.namelist();print('ARCHIVE',p.name,'entries',len(names))
  selected=[n for n in names if not n.endswith('/') and ('_internal/' not in n) and (n.endswith(('.md','.pdf','.docx','.java','.py','.xml','.properties','.json')) or ('modbus' in n.lower() and n.endswith('.class')))]
  print('\n'.join(selected[:90]))
