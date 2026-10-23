from pathlib import Path
import sqlite3,struct,json,collections,zipfile
b=Path(r'C:\Users\haowei\Desktop\夜间水质资料\夜间水质资料');a=b/'标定上位机V3/标定上位机V3'
c=sqlite3.connect((a/'data/2026-09-08.db').as_uri()+'?mode=ro',uri=True)
rows=c.execute('select r.raw_content,d.integration_time_ms,d.dn_values from captures c join raw_data r on c.raw_data_id=r.raw_data_id join spectra_dn d on c.spectra_dn_id=d.spectra_dn_id where c.probe_id=2').fetchall()
stats=collections.Counter();example=None
for raw,t,dn in rows:
 stats['rows']+=1;stats['length_'+str(len(raw))]+=1
 if len(raw)==596:
  stats['header_match']+=raw[:11]==b'WHSRHSE0382'
  stats['integration_match']+=struct.unpack_from('<I',raw,16)[0]/1000==t
  values=json.loads(dn);nums=struct.unpack_from('<288H',raw,20)
  if isinstance(values,dict): vals=[values[str(i)] for i in range(1,289)]
  else: vals=values
  stats['dn_match']+=list(nums)==vals
  stats['nonzero_reserved']+=raw[13:16]!=b'\x00\x00\x00'
  if example is None:example={'source':'2026-09-08.db, probe_id=2','device':'HSE0382 / database SN 25K00382','raw_body_hex':raw.hex(' '),'integration_ms':t,'dn':values,'note':'596-byte stored body, not a full wire frame; CRC/tail absent'}
c.close();print(dict(stats))
out=Path('outputs/上位机开发方案');(out/'OCR0382_历史数据回放样例.json').write_text(json.dumps(example,ensure_ascii=False,indent=2),encoding='utf-8')
with zipfile.ZipFile(b/'标定上位机V3.zip') as z:
 docs=[n for n in z.namelist() if '/doc/' in n and not n.endswith('/')]
 mismatches=[]
 for n in docs:
  rel=n.split('/',1)[1];p=a/rel
  if not p.exists() or p.read_bytes()!=z.read(n):mismatches.append(rel)
 print('ZIP_DOCS',len(docs),'DIFFERENCES',mismatches)
