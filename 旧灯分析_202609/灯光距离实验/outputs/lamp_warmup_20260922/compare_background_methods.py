from pathlib import Path
import json
import numpy as np
from unified_analysis import load, integral, NAMES

t, sec, x, raw, bg, env, w, files, rows, meta = load()
late_ranges=[(46.17,47.17),(56.41,57.41)]

def summarize(net):
    late=np.array([net[(sec/60>=a)&(sec/60<=b)].mean(axis=0) for a,b in late_ranges])
    ref=late.mean(axis=0)
    blocks=[]
    for bid in range(int(sec[-1]//10)+1):
        a=bid*10;b=a+10;m=(sec>=a)&(sec<b);tt=sec[m]
        if len(tt)>=10 and tt[0]-a<=1 and b-tt[-1]<=1 and np.diff(tt).max()<=2:
            blocks.append({'start':a/60,'end':b/60,'dev':100*(net[m].mean(axis=0)/ref-1)})
    out=[]
    for tol in [5,2,1]:
        passed=np.array([np.abs(z['dev'][1:4]).max()<=tol for z in blocks])
        tail=np.logical_and.accumulate(passed[::-1])[::-1]
        ids=np.flatnonzero(tail)
        if not len(ids):
            out.append({'tol_pct':tol,'stable_start_min':None,'longest_continuous_min':None});continue
        start=blocks[int(ids[0])]['start']; eligible=[z for z in blocks if z['start']>=start]
        runs=[];rs=eligible[0]['start'];end=eligible[0]['end']
        for z in eligible[1:]:
            if abs(z['start']-end)>1e-8:runs.append((rs,end));rs=z['start']
            end=z['end']
        runs.append((rs,end));best=max(runs,key=lambda q:q[1]-q[0])
        out.append({'tol_pct':tol,'stable_start_min':start,'longest_continuous_min':best[1]-best[0],
                    'continuous_range_min':best})
    initial=net[sec<10].mean(axis=0);last=net[sec>sec[-1]-10].mean(axis=0)
    return {'stable':out,'endpoint_change_pct':dict(zip(NAMES,(100*(last/initial-1)).tolist()))}

fixed=raw-bg[0]
bt=np.array([d['t'].mean() for d in env]);bs=np.array([d['x'].mean(axis=0) for d in env])
interp=np.column_stack([np.interp(t,bt,bs[:,j]) for j in range(len(w))])
varying=np.column_stack([integral(x-interp,w,*bounds) for bounds in [(420,700),(420,500),(500,600),(600,700)]])
fixed2=raw-bg[1]
late_bg=(bg[1]+bg[2])/2
fixed23=raw-late_bg
bt23=bt[1:];bs23=bs[1:]
interp23=np.column_stack([np.interp(t,bt23,bs23[:,j]) for j in range(len(w))])
varying23=np.column_stack([integral(x-interp23,w,*bounds) for bounds in [(420,700),(420,500),(500,600),(600,700)]])
result={'fixed_environment_1':summarize(fixed),
        'time_interpolated_environment_1_2_3':summarize(varying),
        'fixed_environment_2':summarize(fixed2),
        'fixed_mean_environment_2_3':summarize(fixed23),
        'time_interpolated_environment_2_3_only':summarize(varying23)}
dest=Path(__file__).parent/'统一时间轴分析'/'环境光处理对比.json'
dest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
