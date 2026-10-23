from pathlib import Path
import sys,os,json,csv,hashlib,base64,zipfile,shutil
import numpy as np
import pandas as pd
ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT/'python_packages'))
os.environ['MPLCONFIGDIR']=str(ROOT/'mplconfig')
sys.stdout.reconfigure(encoding='utf-8')
from inspect_data import read_data,TZ
from datetime import datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
font_manager.fontManager.addfont(r'C:\Windows\Fonts\msyh.ttc')
plt.rcParams.update({'font.family':'Microsoft YaHei','axes.unicode_minus':False,'font.size':10})
OUT=ROOT/'背景不确定性复核';OUT.mkdir(exist_ok=True)
def integral(x,w,lo,hi):
    inside=(w>lo)&(w<hi)
    def edge(v):
        j=np.searchsorted(w,v);return x[...,j-1]+(x[...,j]-x[...,j-1])*(v-w[j-1])/(w[j]-w[j-1])
    return np.trapezoid(np.concatenate([edge(lo)[...,None],x[...,inside],edge(hi)[...,None]],axis=-1),np.r_[lo,w[inside],hi],axis=-1)
BOUNDS=[(420,700),(420,500),(500,600),(600,700)]
NAMES=['总量','蓝','绿','红']
def bands(x):return np.column_stack([integral(x,w,*b) for b in BOUNDS])
def clock(t):return datetime.fromtimestamp(float(t),TZ).isoformat(timespec='milliseconds')
def savecsv(name,rows):pd.DataFrame(rows).to_csv(OUT/(name+'.csv'),index=False,encoding='utf-8-sig')
data=read_data();bright=[d for d in data if '环境' not in d['path'].name];env=[d for d in data if '环境' in d['path'].name]
w=bright[0]['w'];assert len(env)==3
for d in data:
    assert np.array_equal(w,d['w']) and np.isfinite(d['x']).all()
    assert np.all(d['integration']==32) and set(d['modes'])=={'N'}
t=np.concatenate([d['t'] for d in bright]);x=np.concatenate([d['x'] for d in bright]);assert np.all(np.diff(t)>0)
sec=t-t[0];raw=bands(x);assert np.allclose(raw[:,0],raw[:,1:].sum(axis=1))
savecsv('数据来源',[{'文件':d['path'].name,'帧数':len(d['t']),'开始':clock(d['t'][0]),'结束':clock(d['t'][-1]),'SHA256':hashlib.sha256(d['path'].read_bytes()).hexdigest()} for d in data])
bg=np.array([bands(d['x']).mean(axis=0) for d in env]);bt=np.array([d['t'].mean() for d in env])
bgmed=np.array([bands(np.median(d['x'],axis=0)[None,:])[0] for d in env])
def interpolate(background):return np.column_stack([np.interp(t,bt,background[:,j]) for j in range(4)])
bg23=(bg[1]+bg[2])/2
scenarios={'原始亮场':raw,'环境2与3平均':raw-bg23,**{f'固定环境{i+1}':raw-bg[i] for i in range(3)},'三点线性插值':raw-interpolate(bg),'三点中位光谱插值':raw-interpolate(bgmed)}
assert all(np.all(v>0) for v in scenarios.values())
envstats=[];candidates=[];envframes=[]
fig,axs=plt.subplots(2,3,figsize=(14,7))
for ei,d in enumerate(env):
    y=bands(d['x']);tt=d['t']-d['t'][0]
    for j,n in enumerate(NAMES):
        envstats.append({'环境':ei+1,'波段':n,'均值':y[:,j].mean(),'CV_pct':100*y[:,j].std(ddof=1)/y[:,j].mean(),'全段拟合变化_pct':100*np.polyfit(tt,y[:,j],1)[0]*np.ptp(tt)/y[:,j].mean()})
    # Same rule for each record: >=5 seconds, >=10 frames, all bands CV<=1%, fitted change<=1%.
    good=[]
    for a in range(len(tt)):
        for b in range(a+10,len(tt)+1):
            z=y[a:b];dt=np.ptp(tt[a:b])
            if dt<5:continue
            cv=100*z.std(axis=0,ddof=1)/z.mean(axis=0)
            drift=100*np.polyfit(tt[a:b],z,1)[0]*dt/z.mean(axis=0)
            if cv.max()<=1 and np.abs(drift).max()<=1:good.append((dt,a,b,float(cv.max()),float(np.abs(drift).max())))
    best=max(good,default=None)
    candidates.append({'环境':ei+1,'稳定候选':bool(best),'首帧':best[1]+1 if best else None,'末帧':best[2] if best else None,'跨度秒':best[0] if best else None,'最大CV_pct':best[3] if best else None})
    for k in range(len(tt)):envframes.append({'环境':ei+1,'帧':k+1,'时间':clock(d['t'][k]),**dict(zip(NAMES,y[k]))})
    axs[0,ei].plot(tt,y[:,0]/1e6,'o-',ms=3);axs[0,ei].set(title=f'环境{ei+1}：逐帧总量',xlabel='本次采集秒数',ylabel='DN·nm / 百万')
    axs[1,ei].plot(w,d['x'].mean(axis=0),label='全帧均值');axs[1,ei].plot(w,np.median(d['x'],axis=0),label='逐波长中位数');axs[1,ei].set(xlim=(420,700),xlabel='波长 / nm',ylabel='DN');axs[1,ei].legend()
fig.tight_layout();fig.savefig(OUT/'01_环境光检查.png',dpi=150);plt.close(fig)
savecsv('环境光统计',envstats);savecsv('环境光稳定候选',candidates);savecsv('环境光逐帧',envframes)
# Global 10-second blocks with actual coverage; never join across acquisition pauses.
ids=[];means={k:[] for k in scenarios}
for bid in range(int(sec[-1]//10)+1):
    m=(sec>=bid*10)&(sec<(bid+1)*10);tt=sec[m]
    if len(tt)<10 or tt[0]-bid*10>1 or (bid+1)*10-tt[-1]>1 or np.diff(tt).max()>2:continue
    ids.append(bid)
    for name,v in scenarios.items():means[name].append(v[m].mean(axis=0))
ids=np.array(ids);means={k:np.array(v) for k,v in means.items()};idx={int(b):i for i,b in enumerate(ids)}
endpoints=[];blockrows=[];slopes=[]
fig,axs=plt.subplots(2,2,figsize=(13,8));cuts=np.flatnonzero(np.diff(ids)>1)+1
for name,v in scenarios.items():
    start=v[sec<10].mean(axis=0);end=v[sec>sec[-1]-10].mean(axis=0)
    endpoints.append({'方法':name,**{n:100*(end[j]/start[j]-1) for j,n in enumerate(NAMES)}})
    for i,bid in enumerate(ids):blockrows.append({'方法':name,'开始分钟':bid/6,**dict(zip(NAMES,means[name][i]))})
    for j,ax in enumerate(axs.flat):
        ax.plot(np.insert((ids+.5)/6,cuts,np.nan),np.insert(100*(means[name][:,j]/start[j]-1),cuts,np.nan),label=name,lw=1)
        ax.set(title=NAMES[j],xlabel='累计点亮 / 分钟',ylabel='相对最初10秒 / %');ax.grid(alpha=.2)
    for minute in range(int(sec[-1]//60)):
        bids=list(range(minute*6,(minute+1)*6))
        if not all(b in idx for b in bids):continue
        yy=means[name][[idx[b] for b in bids]]
        slope=100*np.polyfit(np.arange(6)/6,yy,1)[0]/yy.mean(axis=0)
        for j,n in enumerate(NAMES):slopes.append({'方法':name,'分钟':minute,'波段':n,'变化率_pct每分钟':slope[j]})
axs[0,0].legend(fontsize=8);fig.tight_layout();fig.savefig(OUT/'02_全程曲线对比.png',dpi=150);plt.close(fig)
savecsv('全程变化',endpoints);savecsv('十秒均值',blockrows);savecsv('每分钟变化率',slopes)
# Measurement window uses its own first 10s as reference. No late reference or heat equilibrium assumption.
windowrows=[];capacity=[]
for i,bid in enumerate(ids):
    stop=i+1
    while stop<len(ids) and ids[stop]==ids[stop-1]+1:stop+=1
    for name,arr in means.items():
        yy=arr[i:stop];dev=np.max(np.abs(100*(yy/yy[0]-1))[:,1:],axis=1);cum=np.maximum.accumulate(dev)
        for tol in [1,2,5]:
            bad=np.flatnonzero(cum>tol);nb=int(bad[0]) if len(bad) else len(yy)
            capacity.append({'方法':name,'起点分钟':bid/6,'容差_pct':tol,'连续合格分钟':nb/6,'结束分钟':(bid+nb)/6,'停止原因':'观测越界' if len(bad) else '采样覆盖结束'})
        for duration in [1,3,5,10,15,20]:
            count=duration*6
            if len(yy)<count:continue
            value=float(cum[count-1])
            windowrows.append({'方法':name,'起点分钟':bid/6,'时长分钟':duration,'最大偏移_pct':value})
savecsv('全部测量窗口',windowrows);savecsv('起点与已验证时长',capacity)
netnames=['环境2与3平均']
lookup={(r['方法'],r['起点分钟'],r['时长分钟']):r['最大偏移_pct'] for r in windowrows}
summary=[]
for tol in [1,2,5]:
    for duration in [1,3,5,10,15,20]:
        eligible=[]
        for bid in ids:
            start=bid/6
            vals=[lookup.get((n,start,duration)) for n in netnames]
            if any(v is None for v in vals):continue
            if max(vals)<=tol:eligible.append((start,max(vals)))
        first=eligible[0] if eligible else None
        summary.append({'容差_pct':tol,'测量分钟':duration,'最早合格起点分钟':first[0] if first else None,'环境2与3平均背景_最大偏移_pct':first[1] if first else None})
savecsv('跨背景假设合格窗口',summary)
fig,axs=plt.subplots(1,2,figsize=(13,4.8))
for name in scenarios:
    for ax,tol in zip(axs,[1,2]):
        rr=[r for r in capacity if r['方法']==name and r['容差_pct']==tol]
        ax.scatter([r['起点分钟'] for r in rr],[r['连续合格分钟'] for r in rr],s=7,label=name)
        ax.set(title=f'±{tol}%：不同起点的已验证时长',xlabel='累计点亮 / 分钟',ylabel='连续合格 / 分钟');ax.grid(alpha=.2)
axs[0].legend(fontsize=8);fig.tight_layout();fig.savefig(OUT/'03_连续工作时长.png',dpi=150);plt.close(fig)
# Local residual flags are per-band events, not proof of absent flicker at all frequencies.
anomalies=[];noise=[]
fig,axs=plt.subplots(2,1,figsize=(12,7))
for j,n in enumerate(NAMES):
    v=scenarios['环境2与3平均'][:,j]
    med=pd.Series(v,index=pd.to_datetime(t,unit='s',utc=True)).rolling('10s',center=True,min_periods=5).median().to_numpy()
    residual=100*(v-med)/med;center=np.nanmedian(residual);sigma=1.4826*np.nanmedian(np.abs(residual-center));limit=max(.5,6*sigma)
    noise.append({'波段':n,'稳健标准差_pct':sigma,'阈值_pct':limit})
    for i in np.flatnonzero(np.abs(residual-center)>limit):anomalies.append({'时间':clock(t[i]),'分钟':sec[i]/60,'波段':n,'残差_pct':residual[i],'阈值_pct':limit})
    cc=np.flatnonzero(np.diff(sec)>2)+1
    axs[0].plot(np.insert(sec/60,cc,np.nan),np.insert(residual,cc,np.nan),lw=.4,label=n)
    rr=[r for r in slopes if r['方法']=='原始亮场' and r['波段']==n]
    axs[1].scatter([r['分钟']+.5 for r in rr],[r['变化率_pct每分钟'] for r in rr],s=12,label=n)
axs[0].set(title='局部残差：环境2与3平均背景，仅用于短时突波筛查',ylabel='局部偏移 / %');axs[1].set(title='原始亮场每分钟变化率',xlabel='累计点亮 / 分钟',ylabel='% / 分钟')
for ax in axs:ax.legend(ncol=4);ax.grid(alpha=.2)
fig.tight_layout();fig.savefig(OUT/'04_变化率与异常.png',dpi=150);plt.close(fig)
savecsv('异常记录',anomalies or [{'结果':'所设判据下无突波标记'}]);savecsv('异常判据',noise)
# Independent representative window calculation from raw frame averages.
checked=0
for name in scenarios:
    for start,duration in [(3,5),(15,10),(35,10),(49,5)]:
        key=(name,start,duration)
        if key not in lookup:continue
        yy=np.array([scenarios[name][(sec>=start*60+k*10)&(sec<start*60+(k+1)*10)].mean(axis=0) for k in range(duration*6)])
        independent=np.abs(100*(yy/yy[0]-1))[:,1:].max()
        assert abs(independent-lookup[key])<1e-9;checked+=1
savecsv('亮场原始积分',[{'时间':clock(t[i]),'累计分钟':sec[i]/60,**dict(zip(NAMES,raw[i]))} for i in range(len(t))])
def table(rows):return pd.DataFrame(rows).to_html(index=False,border=0,float_format=lambda v:f'{v:.3f}',na_rep='无完整合格窗口')
def pic(name):return '<img src="data:image/png;base64,'+base64.b64encode((OUT/name).read_bytes()).decode()+'">'
parts=['<h1>灯1：全程变化与连续测量稳定性复核</h1>',f'<p>仅使用最新7个CSV，{len(t)}帧亮场。亮场从{clock(t[0])}至{clock(t[-1])}，跨度{sec[-1]/60:.2f}分钟。灯按一次连续点亮计时。</p>',
'<h2>结论</h2><p><b>主分析采用环境2与环境3的平均光谱作为固定背景。</b>环境2为15:16:48.716～15:16:57.826，环境3为15:32:50.806～15:33:05.650。两段平均总积分相差约2.1%，折算到扣背景后的灯光信号约0.6%。环境1不参与背景扣除。</p>',
'<p>能够评估已采样时段的曲线、局部波动和指定窗口内变化；本次仍不能证明某一时刻以后永久达到热平衡，也不能把采样覆盖结束解释成灯的最大寿命或极限工作时长。</p>',table(summary),
'<p>“最早合格起点”指本次数据中首次找到的完整合格测量窗口，后面的窗口可能再次越界，不能解释成此时起永久稳定。1%、2%、5%为比较用的示例要求，尚未代表水质测量的精度预算。</p>',
'<h2>环境光质量</h2>',pic('01_环境光检查.png'),table([r for r in envstats if r['波段']=='总量']),table(candidates),
'<p>统一稳定候选规则：连续跨度至少5秒、至少10帧，且总量和蓝绿红各自CV≤1%、拟合首末变化≤1%。只列最长合格候选，作为诊断；不据此删帧或替换背景。主对照保留所有指定帧的均值，额外用逐波长中位数检查代表值敏感性。数值低不能证明测错，相互接近也不能证明测准。</p>',
'<h2>完整预热变化曲线</h2>',pic('02_全程曲线对比.png'),table(endpoints),
'<p>表为末10秒相对最初10秒变化（%）。主结果使用环境2与3平均背景；其他固定背景和插值曲线仅用于敏感性对照，不作为最终环境光处理方法。</p>',
'<h2>稳定等待与单次工作时长</h2>',pic('03_连续工作时长.png'),
'<p>每10秒扫描一个起点，基准为该测量窗口的首个10秒均值。蓝、绿、红三波段均须满足相对该基准的最大绝对偏移要求。每块至少10帧、块两端距采样≤1秒、内部间隔≤2秒；任何缺块均终止连续验证，不跨采集空档补值。</p>',
'<p>时长直到首次越界或完整采样覆盖结束；两者在CSV中分别标注。图中时长变短可能只是剩余记录变短。未观测到越界只能报告已验证时长，不能当作灯的最大工作时长。该窗口指标和“相对后期均值的偏移”含义不同，不能相互替代。</p>',
'<h2>变化率与异常</h2>',pic('04_变化率与异常.png'),table(noise),f'<p>环境2与3平均背景下检出{len(anomalies)}条波段突波标记。阈值为局部10秒中位数残差的max(0.5%, 6×稳健标准差)。这仅表示采样带宽及所设阈值内的结果；不等同于证明没有任何频率的闪烁。每分钟变化率用于观察漂移是否减缓，未设任意斜率门槛来宣布热平衡。</p>',
'<h2>数据与核对</h2><p>数据来源、各方法十秒均值、所有连续窗口、每分钟斜率及异常明细均随数据包提供。数据库没有参与本次分析。</p>',table([{'文件':d['path'].name,'帧数':len(d['t']),'开始':clock(d['t'][0]),'结束':clock(d['t'][-1])} for d in data])]
doc='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>灯1稳定性复核</title><style>body{font-family:Microsoft YaHei,sans-serif;margin:0;background:#f2f5f8;color:#23324a;line-height:1.8}main{max-width:1100px;margin:20px auto;background:white;padding:30px}h2{margin-top:32px}img{width:100%}table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:8px;border:1px solid #d6dde5;text-align:left}th{background:#e5eef5}p{font-size:15px}</style><main>'+''.join(parts)+'</main></html>'
(OUT/'分析报告.html').write_text(doc,encoding='utf-8');(ROOT/'分析报告.html').write_text(doc,encoding='utf-8')
(ROOT/'统一时间轴分析'/'分析报告.html').write_text(doc,encoding='utf-8')
md='# 灯1稳定性复核\n\n唯一热平衡时间与最大工作时长尚不能确定。旧的15分钟或45分钟操作建议已撤回。\n\n'+pd.DataFrame(summary).to_string(index=False)+'\n\n完整方法和图表见同目录分析报告.html。'
for p in [ROOT/'分析报告.md',OUT/'分析报告.md',ROOT/'统一时间轴分析'/'分析报告.md']:p.write_text(md,encoding='utf-8')
(OUT/'核对记录.txt').write_text(f'亮场{len(t)}帧，时间唯一，波长/32ms/N模式一致。总积分与三分波段之和一致。独立核对{checked}个窗口通过。所有背景净信号为正。\n',encoding='utf-8')
with zipfile.ZipFile(ROOT/'灯1冷启动分析_报告曲线与数据.zip','w',zipfile.ZIP_DEFLATED) as z:
    for p in OUT.iterdir():
        if p.is_file():z.write(p,p.name)
    for d in data:z.write(d['path'],'raw/'+d['path'].name)
    for p in [Path(__file__),ROOT/'inspect_data.py']:z.write(p,'代码/'+p.name)
print(json.dumps({'frames':len(t),'environment_candidates':candidates,'windows':summary,'endpoint':endpoints,'anomalies':len(anomalies),'checks':checked},ensure_ascii=False,indent=2))
