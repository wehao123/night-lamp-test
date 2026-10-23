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
 join spectra_dn d on d.spectra_dn_id=c.spectra_dn_id
 where c.probe_id=2 order by c.timestamp''').fetchall()
items=[]
for cid,stamp,payload in rows:
    vals=json.loads(payload);x=np.array([vals[k] for k in keys],float)
    items.append((cid,datetime.fromisoformat(stamp),float(np.trapezoid(x[mask],w[mask]))))

groups=[];cur=[];prev=None
for row in items:
    if prev is not None and (row[1]-prev).total_seconds()>2:
        groups.append(cur);cur=[]
    cur.append(row);prev=row[1]
groups.append(cur)

for gi,g in enumerate(groups,1):
    yy=np.array([r[2] for r in g]);mean=yy.mean()
    if mean>3_000_000:continue
    print(f'GROUP {gi} {g[0][1].astimezone(TZ).strftime("%H:%M:%S.%f")[:-3]}--{g[-1][1].astimezone(TZ).strftime("%H:%M:%S.%f")[:-3]} n={len(g)} mean={mean:.1f} min={yy.min():.1f} max={yy.max():.1f}')
    for width in [5,10]:
        if len(g)<width:continue
        candidates=[]
        for a in range(len(g)-width+1):
            z=yy[a:a+width];cv=100*z.std(ddof=1)/z.mean()
            candidates.append((cv,a,z.mean(),z.min(),z.max()))
        cv,a,mn,mn0,mx=min(candidates)
        print(f' BEST{width} frames {a+1}-{a+width} {g[a][1].astimezone(TZ).strftime("%H:%M:%S.%f")[:-3]}--{g[a+width-1][1].astimezone(TZ).strftime("%H:%M:%S.%f")[:-3]} mean={mn:.1f} cv={cv:.3f}% min={mn0:.1f} max={mx:.1f}')
