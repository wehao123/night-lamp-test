from inspect_data import read_data, TZ
from unified_analysis import integral
from datetime import datetime
import numpy as np

d=next(z for z in read_data() if z['tag']=='环境1')
y=integral(d['x'],d['w'],420,700)
peaks=d['x'].max(axis=1)
for i,(ts,total,peak) in enumerate(zip(d['t'],y,peaks),1):
    print(f'{i:02d}\t{datetime.fromtimestamp(ts,TZ).strftime("%H:%M:%S.%f")[:-3]}\t积分={total:.1f}\t峰值DN={peak:.0f}')
print('median',np.median(y),'mean',y.mean(),'std',y.std(ddof=1),'min',y.min(),'max',y.max())
for width in [5,10,15,20]:
    best=None
    for a in range(len(y)-width+1):
        z=y[a:a+width];cv=100*z.std(ddof=1)/z.mean()
        if best is None or cv<best[0]:best=(cv,a,z.mean(),z.min(),z.max())
    print('best',width,'frames','start',best[1]+1,'end',best[1]+width,'cv_pct',best[0],'mean',best[2],'min',best[3],'max',best[4])
