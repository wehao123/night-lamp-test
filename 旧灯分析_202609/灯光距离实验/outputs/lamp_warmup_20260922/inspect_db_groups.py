import sqlite3, json
from datetime import datetime
from pathlib import Path
import numpy as np

DB = Path(r"C:\Users\haowei\Desktop\夜间水质资料\夜间水质资料\标定上位机V3\标定上位机V3\data\2026-09-20.db")

def integral(x, w, lo=420, hi=700):
    m = (w >= lo) & (w <= hi)
    return np.trapezoid(x[m], w[m])

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
wmap = json.loads(con.execute("select wavelengths from calibrations where calibration_id=2").fetchone()[0])
keys = sorted(wmap, key=lambda s: int(s))
w = np.array([wmap[k] for k in keys])
rows = con.execute("""
select c.capture_id,c.timestamp,d.dn_values
from captures c join spectra_dn d on d.spectra_dn_id=c.spectra_dn_id
where c.timestamp>=? and c.timestamp<? order by c.timestamp
""", ("2026-09-20T06:29:00", "2026-09-20T07:34:00")).fetchall()

groups=[]; current=[]; prev=None
for capture_id, stamp, payload in rows:
    when=datetime.fromisoformat(stamp)
    if prev is not None and (when-prev).total_seconds()>2:
        groups.append(current); current=[]
    vals=json.loads(payload)
    x=np.array([vals[k] for k in keys], dtype=float)
    current.append((capture_id,when,integral(x,w)))
    prev=when
groups.append(current)

for i,g in enumerate(groups,1):
    y=np.array([r[2] for r in g])
    print(i, g[0][1].astimezone().isoformat(), g[-1][1].astimezone().isoformat(), len(g),
          f"mean={y.mean():.1f}", f"min={y.min():.1f}", f"max={y.max():.1f}")
