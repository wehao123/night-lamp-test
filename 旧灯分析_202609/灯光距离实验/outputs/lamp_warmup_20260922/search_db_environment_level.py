import sqlite3,json
from datetime import datetime,timezone,timedelta
from pathlib import Path
import numpy as np

DB=Path(r'C:\Users\haowei\Desktop\夜间水质资料\夜间水质资料\标定上位机V3\标定上位机V3\data\2026-09-20.db')
TZ=timezone(timedelta(hours=8))
con=sqlite3.connect(f'file:{DB}?mode=ro',uri=True)
wmap=json.loads(con.execute('select wavelengths from calibrations where calibration_id=2').fetchone()[0])
keys=sorted(wmap,key=lambda k:int(k));w=np.array([wmap[k] for k in keys]);mask=(w>=420)&(w<=700)
rows=con.execute('''select c.capture_id,c.timestamp,d.dn_values from captures c
 join spectra_dn d on d.spectra_dn_id=c.spectra_dn_id where c.probe_id=2 order by c.timestamp''').fetchall()
items=[]
for cid,stamp,payload in rows:
    vals=json.loads(payload);x=np.array([vals[k] for k in keys],float)
    items.append((cid,datetime.fromisoformat(stamp),float(np.trapezoid(x[mask],w[mask]))))

print('ENV1_NEIGHBORHOOD')
for cid,t,y in items:
    local=t.astimezone(TZ)
    if datetime(2026,9,20,14,30,0,tzinfo=TZ)<=local<=datetime(2026,9,20,14,31,0,tzinfo=TZ):
        print(cid,local.strftime('%H:%M:%S.%f')[:-3],f'{y:.1f}')

# Environment 2/3 total integral center is about 0.99 million. Search runs within +/-5%.
lo,hi=939000,1039000
runs=[];cur=[];prev=None
for row in items:
    cid,t,y=row
    good=lo<=y<=hi
    if good and (prev is None or (t-prev).total_seconds()<=2):cur.append(row)
    elif good:cur=[row]
    else:
        if len(cur)>=3:runs.append(cur)
        cur=[]
    prev=t
if len(cur)>=3:runs.append(cur)
print('MATCHING_RUNS')
for run in runs:
    print(len(run),run[0][1].astimezone(TZ).strftime('%H:%M:%S.%f')[:-3],
          run[-1][1].astimezone(TZ).strftime('%H:%M:%S.%f')[:-3],
          f'mean={np.mean([r[2] for r in run]):.1f}',f'min={min(r[2] for r in run):.1f}',f'max={max(r[2] for r in run):.1f}')
