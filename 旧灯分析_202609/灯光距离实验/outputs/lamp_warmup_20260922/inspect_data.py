from pathlib import Path
import csv, json
from datetime import datetime, timezone, timedelta
import numpy as np

SOURCE = Path(r'C:\Users\haowei\Desktop\夜间水质资料\夜间水质资料\标定上位机V3\标定上位机V3\output')
OUT = Path(__file__).parent
TZ = timezone(timedelta(hours=8))

def read_data():
    data = []
    source = SOURCE if SOURCE.exists() else OUT / 'raw'
    if not source.exists():
        source = OUT.parent / 'raw'
    for p in source.glob('*.csv'):
        with p.open(encoding='utf-8-sig') as f:
            rows = list(csv.reader(line for line in f if not line.startswith('#')))
        times = np.array([datetime.fromisoformat(s).timestamp() for s in rows[0][2:]])
        waves = np.array([float(r[1]) for r in rows[3:]])
        x = np.array([[float(v) for v in r[2:]] for r in rows[3:]]).T
        tag = p.stem.split('_')[-1][10:]
        data.append(dict(path=p, tag=tag, t=times, w=waves, x=x,
                         integration=np.array([float(v) for v in rows[1][2:]]), modes=rows[2][2:]))
    return sorted(data, key=lambda d:d['t'][0])

if __name__ == '__main__':
    data = read_data()
    t0 = data[0]['t'][0]
    bg = [d for d in data if '环境' in d['tag']]
    for d in data:
        base = min(bg,key=lambda b:abs(np.mean(b['t'])-np.mean(d['t'])))['x'].mean(axis=0)
        mask = (d['w']>=420)&(d['w']<=700)
        y = (d['x'][:,mask]-base[mask]).sum(axis=1)
        print(json.dumps(dict(tag=d['tag'],n=len(y),start_min=(d['t'][0]-t0)/60,end_min=(d['t'][-1]-t0)/60,
          min_dn=d['x'].min(),max_dn=d['x'].max(), dt_max=np.diff(d['t']).max(),duplicates=len(y)-len(set(d['t'])),
          band_mean=y.mean(),band_cv_pct=100*y.std(ddof=1)/abs(y.mean()) if abs(y.mean())>1e-6 else None,
          first10_mean=y[:10].mean(),last10_mean=y[-10:].mean(),peak_nm=d['w'][np.argmax((d['x']-base).mean(axis=0))],
          max_raw_mean=d['x'].mean(axis=0).max()),ensure_ascii=False))
        if d['tag']=='第二段':
            for a in np.arange(0,26,1):
                m=((d['t']-t0)/60>=a)&((d['t']-t0)/60<a+1)
                if m.any(): print('minute',a,'n',m.sum(),'mean',round(y[m].mean(),1),'CV%',round(100*y[m].std()/y[m].mean(),3),'minmax',np.round([y[m].min(),y[m].max()],1))
