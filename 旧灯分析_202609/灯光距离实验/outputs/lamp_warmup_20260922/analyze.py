from pathlib import Path
import sys, os, csv, json, hashlib, shutil, html, base64
from datetime import datetime

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / 'python_packages'))
os.environ['MPLCONFIGDIR'] = str(ROOT / 'mplconfig')
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np
import pandas as pd
from inspect_data import read_data, SOURCE, TZ

BANDS = {'主波段420–700':(420,700),'蓝420–500':(420,500),'绿500–600':(500,600),'红600–700':(600,700),'扩展400–700':(400,700)}
COLORS = ['#202f46','#3478bc','#269278','#c45951','#8167a9']

def save_csv(name, rows):
    pd.DataFrame(rows).to_csv(ROOT/name,index=False,encoding='utf-8-sig',float_format='%.8f')

def clock(t):
    return datetime.fromtimestamp(float(t),TZ).isoformat(timespec='milliseconds')

def duration(seconds):
    return f'{int(seconds//60)}分{seconds%60:04.1f}秒'

def band_integral(x,w,lo,hi):
    # Exact requested boundaries via linear interpolation, then trapezoid weights.
    inside=(w>lo)&(w<hi)
    ww=np.r_[lo,w[inside],hi]
    def edge(v):
        j=np.searchsorted(w,v)
        return x[...,j-1]+(x[...,j]-x[...,j-1])*(v-w[j-1])/(w[j]-w[j-1])
    xx=np.concatenate([edge(lo)[...,None],x[...,inside],edge(hi)[...,None]],axis=-1)
    return np.trapezoid(xx,ww,axis=-1)

def run():
    data=read_data()
    lamps=[d for d in data if '环境' not in d['tag']]
    env=[d for d in data if '环境' in d['tag']]
    t0=lamps[0]['t'][0]
    w=lamps[0]['w']
    bt=np.array([d['t'].mean() for d in env])
    bs=np.array([d['x'].mean(axis=0) for d in env])
    (ROOT/'raw').mkdir(exist_ok=True)
    manifest=[]
    for d in data:
        raw=d['path'].read_bytes()
        (ROOT/'raw'/d['path'].name).write_bytes(raw)
        assert np.array_equal(d['w'],w)
        assert np.isfinite(d['x']).all()
        assert np.all(np.diff(d['t'])>0)
        assert np.all(d['integration']==32)
        assert set(d['modes'])=={'N'}
        d['elapsed']=(d['t']-t0)/60
        d['raw_band']=np.column_stack([band_integral(d['x'],w,*b) for b in BANDS.values()])
        manifest.append({'文件名':d['path'].name,'标签':d['tag'],'SHA256':hashlib.sha256(raw).hexdigest(),
             '采集开始北京时间':clock(d['t'][0]),'采集结束北京时间':clock(d['t'][-1]),'起始开灯分钟':d['elapsed'][0],
             '终止开灯分钟':d['elapsed'][-1],'帧数':len(d['t']),'记录跨度秒':np.ptp(d['t']),
             '帧间隔中位秒':np.median(np.diff(d['t'])),'最大帧间隔秒':np.diff(d['t']).max(),
             '最小原始DN':d['x'].min(),'最大原始DN':d['x'].max(),'积分时间ms':32,'模式':'N'})
    save_csv('01_文件与数据质量.csv',manifest)
    assert len(set(np.concatenate([d['t'] for d in data])))==sum(len(d['t']) for d in data)
    bgband=np.column_stack([band_integral(bs,w,*b) for b in BANDS.values()])
    for d in lamps:
        d['background']=np.column_stack([np.interp(d['t'],bt,bs[:,j]) for j in range(len(w))])
        d['net']=d['x']-d['background']
        d['net_band']=np.column_stack([band_integral(d['net'],w,*b) for b in BANDS.values()])
        d['fixed_band']=d['raw_band']-bgband[0]
        nearest=np.abs(d['t'][:,None]-bt[None,:]).argmin(axis=1)
        d['nearest_band']=d['raw_band']-bgband[nearest]
        d['spectrum_mean']=d['net'].mean(axis=0)
    # Equal weight to three late acquisitions rather than number of frames.
    refs={k:np.mean([d[k].mean(axis=0) for d in lamps[-3:]],axis=0) for k in ['net_band','fixed_band','raw_band','nearest_band']}
    ref=refs['net_band']
    refspec=np.mean([d['spectrum_mean'] for d in lamps[-3:]],axis=0)
    summary=[]
    for d in lamps:
        for j,b in enumerate(BANDS):
            y=d['net_band'][:,j]
            fit=np.polyfit(d['elapsed']-d['elapsed'][0],y,1)
            summary.append({'分段':d['tag'],'波段':b,'帧数':len(y),'开始开灯分钟':d['elapsed'][0],'结束开灯分钟':d['elapsed'][-1],
                '净DN积分均值_DNnm':y.mean(),'均值相对后期基准偏差_pct':100*(y.mean()/ref[j]-1),
                '单帧CV_pct':100*y.std(ddof=1)/y.mean(),'相对基准最小偏差_pct':100*(y.min()/ref[j]-1),
                '相对基准最大偏差_pct':100*(y.max()/ref[j]-1),'拟合漂移_pct每min':100*fit[0]/y.mean(),
                '段内拟合变化_pct':100*fit[0]*np.ptp(d['elapsed'])/y.mean(),
                '首10帧均值_DNnm':y[:10].mean(),'末10帧均值_DNnm':y[-10:].mean(),
                '固定环境1_均值相对后期基准偏差_pct':100*(d['fixed_band'][:,j].mean()/refs['fixed_band'][j]-1)})
    save_csv('02_分段与分波段统计.csv',summary)
    # Non-overlapping ten-second bins anchored to each acquisition, no fill across gaps.
    blocks=[]
    for d in lamps:
        bid=np.floor((d['t']-d['t'][0])/10).astype(int)
        for b in np.unique(bid):
            m=bid==b
            rec={'分段':d['tag'],'块号':int(b),'开始开灯分钟':d['elapsed'][m][0],'结束开灯分钟':d['elapsed'][m][-1],
                 '块中点分钟':d['elapsed'][m].mean(),'实际覆盖秒':np.ptp(d['t'][m]),'帧数':int(m.sum()),
                 '用于判定':bool(np.ptp(d['t'][m])>=8 and m.sum()>=10)}
            for j,k in enumerate(BANDS):
                rec[k+'_偏差_pct']=100*(d['net_band'][m,j].mean()/ref[j]-1)
                rec[k+'_单帧CV_pct']=100*d['net_band'][m,j].std(ddof=1)/d['net_band'][m,j].mean() if m.sum()>1 else None
            blocks.append(rec)
    save_csv('03_十秒块趋势.csv',blocks)
    valid=[b for b in blocks if b['用于判定']]
    waits=[]
    for target,js in [('主波段积分',[0]),('蓝绿红三个分波段同时',[1,2,3])]:
        for threshold in [1,2,5]:
            dev=np.array([[b[list(BANDS)[j]+'_偏差_pct'] for j in js] for b in valid])
            passed=(np.abs(dev)<=threshold).all(axis=1)
            remain=np.logical_and.accumulate(passed[::-1])[::-1]
            ix=np.flatnonzero(remain)
            if len(ix):
                i=ix[0]; b=valid[i]
                prev=valid[i-1] if i else None
                seg=next(d for d in lamps if d['tag']==b['分段'])
                covered=seg['elapsed'][-1]-b['开始开灯分钟']
                waits.append({'指标':target,'允许误差_pct':threshold,'首次后续实测块均合格分钟':b['开始开灯分钟'],
                  '前一不合格块结束分钟':prev['结束开灯分钟'] if prev else None,
                  '首个合格点所在分段':b['分段'],'所在连续记录剩余分钟':covered,'连续确认至少2分钟':bool(covered>=2),
                  '截至最后亮场分钟':lamps[-1]['elapsed'][-1],'后续观测跨度分钟':lamps[-1]['elapsed'][-1]-b['开始开灯分钟'],
                  '备注':'后续仅实测块合格，采集空档未验证；±误差相对后期实测基准，非热平衡证明'})
            else:
                waits.append({'指标':target,'允许误差_pct':threshold,'首次后续实测块均合格分钟':None,'备注':'未找到'})
    save_csv('04_等待时间与验证边界.csv',waits)
    # Cumulative run drift relative to initial 10-second mean: a separate working-session definition.
    work=[]
    second=lamps[1]
    starts=[second['elapsed'][0],5,10,15,20]
    for start in starts:
        m=second['elapsed']>=start
        ix=np.flatnonzero(m)
        tt=second['elapsed'][ix]
        xx=second['net_band'][ix]
        if not len(ix): continue
        initial=xx[tt<tt[0]+10/60].mean(axis=0)
        bvalid=[b for b in valid if b['分段']=='第二段' and b['开始开灯分钟']>=tt[0]+10/60]
        for target,js in [('主波段积分',[0]),('蓝绿红三个分波段同时',[1,2,3])]:
            for th in [1,2,5]:
                firstbad=None
                for b in bvalid:
                    mean=np.array([(b[k+'_偏差_pct']/100+1)*ref[j] for j,k in enumerate(BANDS)])
                    if np.max(np.abs(100*(mean[js]/initial[js]-1)))>th:
                        firstbad=b; break
                end=firstbad['开始开灯分钟'] if firstbad else tt[-1]
                work.append({'指标':target,'允许误差_pct':th,'会话起点开灯分钟':tt[0],
                    '首次越界块开始分钟':end if firstbad else None,'越界前观测跨度分钟':end-tt[0],
                    '状态':'观测到首次越界，非保证时长' if firstbad else '本连续记录内未越界，只给验证下限',
                    '定义':'相对会话开始10秒均值，后续合格10秒块；不跨采集空档'})
    save_csv('05_连续测量漂移窗口.csv',work)
    envrows=[]
    for d in env:
        for j,k in enumerate(BANDS):
            y=d['raw_band'][:,j]
            envrows.append({'环境记录':d['tag'],'波段':k,'帧数':len(y),'开灯分钟':d['elapsed'].mean(),
                '背景积分均值_DNnm':y.mean(),'背景单帧标准差_DNnm':y.std(ddof=1),
                '背景均值相对后期净信号_pct':100*y.mean()/ref[j],
                '背景标准差相对后期净信号_pct':100*y.std(ddof=1)/ref[j],
                '背景极差相对后期净信号_pct':100*np.ptp(y)/ref[j],
                '背景均值标准误相对后期净信号_pct':100*y.std(ddof=1)/np.sqrt(len(y))/ref[j]})
    save_csv('06_环境光统计.csv',envrows)
    # Robust local residual flags. Retain all data; diagnosis is not a hardware attribution.
    anomalies=[]; flagged=[]
    for d in lamps:
        idx=pd.to_datetime(d['t'],unit='s',utc=True)
        residual=np.zeros((len(idx),4)); local=np.zeros_like(residual)
        for j in range(4):
            yy=pd.Series(d['net_band'][:,j],index=idx)
            med=yy.rolling('10s',center=True,min_periods=5).median().to_numpy()
            local[:,j]=med
            residual[:,j]=100*(yy.to_numpy()-med)/med
        scale=1.4826*np.median(np.abs(residual-np.median(residual,axis=0)),axis=0)
        limits=np.maximum(6*scale,0.5)
        flags=(np.abs(residual)>limits).any(axis=1)
        d['residual']=residual; d['flags']=flags
        for i in np.flatnonzero(flags):
            affected=[list(BANDS)[j] for j in range(4) if abs(residual[i,j])>limits[j]]
            flagged.append({'分段':d['tag'],'分段内帧序号_1起':i+1,'时间北京时间':clock(d['t'][i]),'开灯分钟':d['elapsed'][i],
               '涉及波段':'、'.join(affected),'最大局部偏差_pct':np.max(np.abs(residual[i])),
               **{list(BANDS)[j]+'_局部偏差_pct':residual[i,j] for j in range(4)}})
        anomalies.append({'类别':'短时突波筛查','分段':d['tag'],'开始开灯分钟':d['elapsed'][0],'结束开灯分钟':d['elapsed'][-1],
            '结果':f'{int(flags.sum())}帧被标记 / {len(flags)}帧','依据':'任一波段偏离局部10秒中位数超过max(6×MAD稳健标准差,0.5%)，原始帧全部保留',
            '主波段实际阈值_pct':limits[0],'蓝波段实际阈值_pct':limits[1],'绿波段实际阈值_pct':limits[2],'红波段实际阈值_pct':limits[3]})
    for prev,cur in zip(lamps[:-1],lamps[1:]):
        before=prev['net_band'][-10:].mean(axis=0); after=cur['net_band'][:10].mean(axis=0)
        anomalies.append({'类别':'采集空档与跨段差异','分段':prev['tag']+'→'+cur['tag'],
          '开始开灯分钟':prev['elapsed'][-1],'结束开灯分钟':cur['elapsed'][0],
          '空档分钟':cur['elapsed'][0]-prev['elapsed'][-1],
          '主波段两端变化_pct':100*(after[0]/before[0]-1),
          '结果':'两端实测变化','依据':'前段末10帧均值与后段首10帧均值'})
    for d in env:
        anomalies.append({'类别':'背景波动','分段':d['tag'],'开始开灯分钟':d['elapsed'][0],'结束开灯分钟':d['elapsed'][-1],
             '结果':'背景不恒定，给净信号比较引入不确定性','主波段背景极差占后期净信号_pct':100*np.ptp(d['raw_band'][:,0])/ref[0],
             '主波段背景标准差占后期净信号_pct':100*d['raw_band'][:,0].std(ddof=1)/ref[0],
             '依据':'原始环境记录全部保留，不因偏离而删除帧'})
    exceed=[]; exceed_frames=[]
    for d in lamps[-3:]:
        for j in range(4):
            dev=100*(d['net_band'][:,j]/ref[j]-1)
            exceed.append({'分段':d['tag'],'波段':list(BANDS)[j],'帧数':len(dev),
                **{f'单帧超出正负{th}pct帧数':int((np.abs(dev)>th).sum()) for th in [1,2,5]},
                '最大绝对偏差_pct':float(np.max(np.abs(dev)))})
            for i in np.flatnonzero(np.abs(dev)>1):
                exceed_frames.append({'分段':d['tag'],'分段内帧序号_1起':int(i+1),'波段':list(BANDS)[j],
                    '时间北京时间':clock(d['t'][i]),'开灯分钟':d['elapsed'][i],'相对后期基准偏差_pct':dev[i],
                    '备注':'超出±1%的单帧精度记录，非稳健突波或故障判定'})
    save_csv('13_后期单帧误差检查.csv',exceed)
    save_csv('14_后期单帧越界时间记录.csv',exceed_frames)
    save_csv('07_异常与操作记录.csv',anomalies)
    if flagged: save_csv('08_疑似突波逐帧明细.csv',flagged)
    else: save_csv('08_疑似突波逐帧明细.csv',[{'结果':'按所述阈值未检出疑似突波；不代表排除所有波动'}])
    # Per wavelength coverage and final spectrum deviations (no clipping weak channels).
    sn=np.column_stack([d['spectrum_mean']/d['net'].std(axis=0,ddof=1) for d in lamps[-3:]])
    evaluable=(w>=420)&(w<=700)&(refspec>0)&(sn.min(axis=1)>=50)
    spectra=[]
    for j,wl in enumerate(w):
        row={'通道':j+1,'波长nm':wl,'后期参考净DN':refspec[j],'后期各段最小均值标准差比':sn[j].min(),
             '核心通道且后期各段SNR至少50':bool(evaluable[j])}
        for d in lamps:
            row[d['tag']+'_净DN均值']=d['spectrum_mean'][j]
            row[d['tag']+'_相对后期基准_pct']=100*(d['spectrum_mean'][j]/refspec[j]-1) if refspec[j]!=0 else None
        for i,d in enumerate(env): row[d['tag']+'_背景DN均值']=bs[i,j]
        spectra.append(row)
    save_csv('09_逐波长均值与评价范围.csv',spectra)
    frame_rows=[]
    for d in lamps:
        for i in range(len(d['t'])):
            row={'分段':d['tag'],'分段内帧序号_1起':i+1,'时间北京时间':clock(d['t'][i]),'开灯分钟':d['elapsed'][i],'疑似突波':bool(d['flags'][i])}
            for j,k in enumerate(BANDS):
                row[k+'_原始积分_DNnm']=d['raw_band'][i,j]
                row[k+'_估计背景积分_DNnm']=d['raw_band'][i,j]-d['net_band'][i,j]
                row[k+'_净积分_DNnm']=d['net_band'][i,j]
                row[k+'_相对后期基准_pct']=100*(d['net_band'][i,j]/ref[j]-1)
            frame_rows.append(row)
    save_csv('10_逐帧预热曲线数据.csv',frame_rows)
    # Background subtraction sensitivity at the same late reference definition.
    sensitivity=[]
    for d in lamps:
        for j,k in enumerate(BANDS):
            sensitivity.append({'分段':d['tag'],'波段':k,
              **{name:100*(d[key][:,j].mean()/refs[key][j]-1) for name,key in [
                  ('时变背景_相对后期偏差_pct','net_band'),('固定环境1_相对后期偏差_pct','fixed_band'),
                  ('最近环境_相对后期偏差_pct','nearest_band'),('未扣背景_相对后期偏差_pct','raw_band')]}})
    save_csv('11_背景处理敏感性.csv',sensitivity)
    sensitivity_wait=[]
    for key,name in [('net_band','时变背景'),('fixed_band','固定环境1'),('nearest_band','最近环境'),('raw_band','未扣背景')]:
        for target,js in [('主波段积分',[0]),('蓝绿红三个分波段同时',[1,2,3])]:
            trial=[]
            for b in valid:
                d=next(d for d in lamps if d['tag']==b['分段'])
                m=(d['elapsed']>=b['开始开灯分钟'])&(d['elapsed']<=b['结束开灯分钟'])
                trial.append(100*(d[key][m].mean(axis=0)/refs[key]-1))
            for th in [1,2,5]:
                passed=(np.abs(np.array(trial)[:,js])<=th).all(axis=1)
                ix=np.flatnonzero(np.logical_and.accumulate(passed[::-1])[::-1])
                sensitivity_wait.append({'背景方法':name,'指标':target,'允许误差_pct':th,
                    '首次后续实测块均合格分钟':valid[ix[0]]['开始开灯分钟'] if len(ix) else None})
    save_csv('12_等待时间背景敏感性.csv',sensitivity_wait)
    statistics={'bands':list(BANDS),'reference':ref.tolist(),'files':manifest,'summary':summary,'waits':waits,'work':work,
       'env':envrows,'anomalies':anomalies,'flagged':flagged,'sensitivity':sensitivity,'exceed':exceed,
       't0':clock(t0),'last_lamp_min':lamps[-1]['elapsed'][-1],
       'observed_lamp_minutes':sum(np.ptp(d['elapsed']) for d in lamps),
       'net_change_first10_to_last10_pct':(100*(lamps[-1]['net_band'][-10:].mean(axis=0)/lamps[0]['net_band'][:10].mean(axis=0)-1)).tolist(),
       'fixed_change_first10_to_last10_pct':(100*(lamps[-1]['fixed_band'][-10:].mean(axis=0)/lamps[0]['fixed_band'][:10].mean(axis=0)-1)).tolist(),
       'evaluable_channels':int(evaluable.sum()),'core_channels':int(((w>=420)&(w<=700)).sum()),'sensitivity_wait':sensitivity_wait}
    (ROOT/'statistics.json').write_text(json.dumps(statistics,ensure_ascii=False,indent=2),encoding='utf-8')
    print('完成统计：亮场帧数',sum(len(d['t']) for d in lamps),'疑似突波',len(flagged))
    return data,lamps,env,w,bt,bs,ref,refs,blocks,statistics

def plot_figures(data,lamps,env,w,bt,bs,ref,refs,blocks,s):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    font_manager.fontManager.addfont(r'C:\Windows\Fonts\msyh.ttc')
    plt.rcParams.update({'font.family':'Microsoft YaHei','axes.unicode_minus':False,'font.size':10,
      'axes.spines.top':False,'axes.spines.right':False,'axes.titleweight':'bold','axes.labelcolor':'#334155',
      'text.color':'#17243a','xtick.color':'#536175','ytick.color':'#536175','figure.facecolor':'white','savefig.facecolor':'white'})
    out=ROOT/'figures'; out.mkdir(exist_ok=True)
    def finish(fig,name):
        fig.savefig(out/(name+'.png'),dpi=180,bbox_inches='tight')
        fig.savefig(out/(name+'.svg'),bbox_inches='tight')
        plt.close(fig)
    def grid(ax): ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
    def gaps(ax):
        for a,b in zip(lamps[:-1],lamps[1:]): ax.axvspan(a['elapsed'][-1],b['elapsed'][0],color='#e7eaf0',alpha=.7,lw=0)
    fig,axs=plt.subplots(3,1,figsize=(11.5,10.4),gridspec_kw={'height_ratios':[1.2,1,1]})
    fig.suptitle('灯 1  冷启动与连续点亮观测',x=.075,ha='left',fontsize=19,y=.995)
    axs[0].set_title('完整时间轴：逐帧净信号与后期实测基准的偏差',loc='left',pad=12)
    gaps(axs[0]); axs[0].axhspan(-1,1,color='#d9efe6',alpha=.8)
    axs[0].axhline(5,color='#c38b27',ls='--',lw=1,label='+5% 参考线')
    for j in range(4):
        for k,d in enumerate(lamps):
            axs[0].plot(d['elapsed'],100*(d['net_band'][:,j]/ref[j]-1),color=COLORS[j],alpha=.75,lw=.65,
                 label=list(BANDS)[j]+' nm' if k==0 else None)
    for d in env:
        axs[0].axvline(d['elapsed'].mean(),color='#8b5ca1',ls=':',lw=1)
    axs[0].set(xlim=(-.5,65),ylabel='相对后期基准 / %',xlabel='从通电起算 / 分钟')
    axs[0].legend(loc='upper right',ncol=2,fontsize=9)
    axs[0].text(.02,.05,'灰色区间：无亮场数据\n紫色虚线：环境光采样时刻',transform=axs[0].transAxes,fontsize=9)
    for j in range(4):
        for k,d in enumerate(lamps[:2]):
            axs[1].plot(d['elapsed'],100*(d['net_band'][:,j]/ref[j]-1),color=COLORS[j],alpha=.7,lw=.65)
    axs[1].axvspan(lamps[0]['elapsed'][-1],lamps[1]['elapsed'][0],color='#e7eaf0',alpha=.7)
    axs[1].axhline(5,color='#c38b27',ls='--',lw=1)
    axs[1].axvline(17.2503865,color='#202f46',ls=':',lw=1)
    axs[1].set(title='早期仍有缓慢下降：主波段约 17.3 分钟进入 ±5%，蓝波段尚未同时满足',
       xlim=(-.3,26),ylabel='相对后期基准 / %',xlabel='从通电起算 / 分钟')
    gaps(axs[2]); axs[2].axhspan(-1,1,color='#d9efe6',alpha=.8)
    for j in range(4):
        for d in lamps[-3:]:axs[2].plot(d['elapsed'],100*(d['net_band'][:,j]/ref[j]-1),color=COLORS[j],alpha=.7,lw=.8)
    axs[2].axhline(0,color='#8c97a7',lw=.8)
    axs[2].set(title='后期三个短窗较一致：蓝波段仍有个别单帧超出 ±1%',xlim=(45.5,64),ylim=(-1.6,1.6),
               ylabel='相对后期基准 / %',xlabel='从通电起算 / 分钟')
    for ax in axs:grid(ax)
    fig.tight_layout(rect=[0,0.035,1,.975],h_pad=2)
    fig.text(.075,.01,'背景：三次环境平均光谱按时间线性插值；后期基准：第三、四、五段均值等权平均。DN 积分不是绝对光功率。',fontsize=9)
    finish(fig,'01_预热曲线')

    fig,axs=plt.subplots(2,2,figsize=(12,8.8))
    fig.suptitle('背景变化与处理方法敏感性',x=.075,ha='left',fontsize=18,y=.99)
    for i,d in enumerate(env):
        axs[0,0].plot(w,bs[i],label=d['tag'],lw=1.5)
    axs[0,0].set(xlim=(400,750),xlabel='波长 / nm',ylabel='背景均值 / DN',title='三次遮挡背景的谱形并不相同')
    axs[0,0].legend()
    x=np.arange(3);width=.23
    for j in [1,2,3]:
        vals=[next(r['背景均值相对后期净信号_pct'] for r in s['env'] if r['环境记录']==d['tag'] and r['波段']==list(BANDS)[j]) for d in env]
        axs[0,1].bar(x+(j-2)*width,vals,width,label=list(BANDS)[j],color=COLORS[j])
    axs[0,1].set(xticks=x,xticklabels=[d['tag'] for d in env],ylabel='背景积分 / 后期净信号 / %',title='蓝波段的背景占比尤其高')
    axs[0,1].legend(fontsize=9)
    for j,ax in [(0,axs[1,0]),(1,axs[1,1])]:
        for key,color,label in [('net_band','#202f46','时变背景（主分析）'),('fixed_band','#cf843e','固定环境1（敏感性）'),('raw_band','#8f99a7','未扣背景（诊断）')]:
            for k,d in enumerate(lamps):
                ax.plot(d['elapsed'],100*(d[key][:,j]/refs[key][j]-1),color=color,lw=.7,alpha=.7,label=label if k==0 else None)
        gaps(ax)
        ax.set(xlabel='从通电起算 / 分钟',ylabel='相对各自后期基准 / %',title=list(BANDS)[j]+'：处理方式会改变漂移估计')
        ax.legend(fontsize=8)
    for ax in axs.flat:grid(ax)
    fig.tight_layout(rect=[0,.025,1,.97],h_pad=2)
    fig.text(.075,.008,'固定背景和未扣背景仅用于敏感性比较；三次遮挡测量不能证明背景在两次测量之间按直线变化。',fontsize=9)
    finish(fig,'02_环境光与敏感性')

    fig,axs=plt.subplots(2,2,figsize=(12,8.8))
    fig.suptitle('光谱变化与异常波动检查',x=.075,ha='left',fontsize=18,y=.99)
    segcolors=['#587db5','#caa153','#5c9c84','#9b6aa4','#243950']
    for d,c in zip(lamps,segcolors):
        axs[0,0].plot(w,d['spectrum_mean'],color=c,label=d['tag'],lw=1.2)
    axs[0,0].set(xlim=(400,750),ylabel='净信号均值 / DN',xlabel='波长 / nm',title='各段平均净光谱')
    axs[0,0].legend(ncol=2,fontsize=8)
    for j in [1,2,3]:
        vals=[next(r['均值相对后期基准偏差_pct'] for r in s['summary'] if r['分段']==d['tag'] and r['波段']==list(BANDS)[j]) for d in lamps]
        axs[0,1].plot([d['elapsed'].mean() for d in lamps],vals,'o',color=COLORS[j],label=list(BANDS)[j])
    axs[0,1].axhline(0,color='#999',lw=.8)
    axs[0,1].set(xlabel='采样段中点 / 开灯分钟',ylabel='分段均值相对后期基准 / %',title='蓝绿红变化不一致，不能只看总量')
    axs[0,1].legend(fontsize=8)
    for j in range(4):
        for k,d in enumerate(lamps):
            axs[1,0].plot(d['elapsed'],d['residual'][:,j],color=COLORS[j],lw=.4,alpha=.65,label=list(BANDS)[j] if k==0 else None)
    axs[1,0].axhline(.5,color='#ac5555',ls='--',lw=1);axs[1,0].axhline(-.5,color='#ac5555',ls='--',lw=1)
    axs[1,0].set(xlabel='从通电起算 / 分钟',ylabel='偏离局部10秒中位数 / %',title='保留所有帧：未检出达到设定阈值的突波')
    for i,d in enumerate(lamps):
        axs[1,1].broken_barh([(d['elapsed'][0],np.ptp(d['elapsed']))],(i-.27,.54),facecolors=segcolors[i])
        axs[1,1].text(d['elapsed'][-1]+.5,i,f"{len(d['t'])} 帧",va='center',fontsize=9)
    axs[1,1].set(yticks=range(5),yticklabels=[d['tag'] for d in lamps],xlabel='从通电起算 / 分钟',
                 xlim=(-1,69),title='亮场记录覆盖：约24.5分钟 / 63.2分钟跨度')
    axs[1,1].invert_yaxis()
    for ax in axs.flat:grid(ax)
    fig.tight_layout(rect=[0,.025,1,.97],h_pad=2)
    fig.text(.075,.008,'突波阈值：任一分波段或主波段超过 max(6×MAD稳健标准差, 0.5%)。未检出突波不等于不存在缓慢漂移。',fontsize=9)
    finish(fig,'03_光谱与波动记录')

    fig,axs=plt.subplots(1,3,figsize=(12,4.4),sharey=True)
    fig.suptitle('环境光短时波动：逐帧保留，不剔除极值',x=.075,ha='left',fontsize=17,y=.99)
    for ax,d in zip(axs,env):
        for j in [0,1]:
            y=d['raw_band'][:,j]
            ax.plot(d['t']-d['t'][0],100*(y-y.mean())/ref[j],'.-',color=COLORS[j],label=list(BANDS)[j],lw=1,ms=3)
        ax.set(title=d['tag'],xlabel='该次背景采集开始后 / 秒');ax.axhline(0,color='#999',lw=.8);grid(ax)
    axs[0].set_ylabel('背景偏离该次均值 / 后期净信号 / %');axs[-1].legend(fontsize=8)
    fig.tight_layout(rect=[0,.04,1,.93])
    fig.text(.075,.015,'纵轴用后期灯光净信号归一化，表示背景波动对净信号误差的潜在量级；不是背景自身的 CV。',fontsize=9)
    finish(fig,'04_环境光逐帧波动')

def write_report(data,lamps,env,w,bt,bs,ref,refs,blocks,s):
    md=[]; page=[]
    def heading(text,level=2):
        md.append('#'*level+' '+text+'\n');page.append(f'<h{level}>{html.escape(text)}</h{level}>')
    def para(text):
        md.append(text+'\n');page.append('<p>'+html.escape(text)+'</p>')
    def table(headers,rows):
        rows=[[str(v) for v in row] for row in rows]
        md.append('| '+' | '.join(headers)+' |\n| '+' | '.join(['---']*len(headers))+' |\n'+'\n'.join('| '+' | '.join(r)+' |' for r in rows)+'\n')
        page.append('<div class="table-wrap"><table><thead><tr>'+''.join('<th>'+html.escape(v)+'</th>' for v in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(v)+'</td>' for v in r)+'</tr>' for r in rows)+'</tbody></table></div>')
    def figure(name,caption):
        md.append(f'![{caption}](figures/{name}.png)\n')
        b64=base64.b64encode((ROOT/'figures'/(name+'.png')).read_bytes()).decode()
        page.append(f'<figure><img src="data:image/png;base64,{b64}" alt="{html.escape(caption)}"><figcaption>{html.escape(caption)}</figcaption></figure>')
    total=sum(len(d['t']) for d in lamps);bgcount=sum(len(d['t']) for d in env)
    end=s['last_lamp_min'];covered=s['observed_lamp_minutes']
    main=[r for r in s['summary'] if r['波段']==list(BANDS)[0]]
    late=main[-3:]
    bgmain=[r for r in s['env'] if r['波段']==list(BANDS)[0]]
    blueex=sum(r['单帧超出正负1pct帧数'] for r in s['exceed'] if r['波段']==list(BANDS)[1])
    heading('灯 1 冷启动、稳定等待与工作时长分析',1)
    para('实验日期：2026-09-20。灯1持续点亮，测量几何与亮度档位固定；OCR 25F02100，积分时间32 ms。5段亮场、3组环境光。')
    heading('结论与可执行范围')
    table(['项目','本次结果','使用边界'],[
      ['预热曲线','早期响应缓慢下降；后期三个短窗的主波段均值相对后期基准为 −0.041%、−0.002%、+0.044%','背景变化较大，下降幅度依赖背景模型，不能全部归因为灯本身热衰减'],
      ['稳定等待时间','蓝绿红三个波段的10秒均值首次观测到同时进入±1%：开灯46.47分钟','25.39～46.47分钟无记录；最短等待时间与连续稳定保持均未完成验证'],
      ['实际排程建议','下一轮可从预热50分钟开始验证','50分钟是对46.47分钟观测结果向上取整的试运行安排，并非已验收参数'],
      ['允许单次工作时长','尚不能给出稳定后的最大连续工作时长','最后亮场到63.16分钟；后期仅3个短窗，16.70分钟跨度不能当作连续通过时长'],
      ['异常记录',f'{total}帧亮场未检出达到稳健阈值的突波；存在早期缓慢漂移及背景波动',f'后期蓝波段有{blueex}帧超出±1%，逐帧时间见附表14']])
    heading('1. 数据与完整时间轴')
    para(f'共有{total}帧亮场和{bgcount}帧背景，288个通道，波长{w[0]:.2f}～{w[-1]:.2f} nm。计时零点为{clock(lamps[0]["t"][0])}。亮场覆盖跨度{end:.2f}分钟，各段实际记录跨度之和{covered:.2f}分钟，覆盖约{covered/end*100:.1f}%。文件名时间戳是导出时间，不能用作实验时间。')
    table(['记录','北京时间','开灯后/min','帧数','记录跨度/s'],[
      [d['tag'],clock(d['t'][0])[11:19]+'–'+clock(d['t'][-1])[11:19],f"{d['elapsed'][0]:.2f}–{d['elapsed'][-1]:.2f}",len(d['t']),f"{np.ptp(d['t']):.2f}"] for d in data])
    para('8个文件的波长网格、积分时间和模式一致，无重复时间戳或缺失值。亮场原始最大值32959 DN。源文件副本及SHA-256见数据包。')
    heading('2. 分析口径')
    para('主指标为420～700 nm的净DN光谱积分，同时报告蓝420～500、绿500～600、红600～700 nm，以及扩展400～700 nm。选择主波段是本次分析口径，不是声称设备在区间外不可用。按实际波长作梯形积分，边界用相邻通道线性插值，单位DN·nm；未做绝对辐射定标或人眼光视效率加权，因此不是瓦特或照度。')
    para('每次环境光使用全部帧平均光谱。主分析在三次背景测量的平均时刻之间逐波长线性插值；首次背景测量前使用环境1，不外推斜率。净信号=亮场DN−估计背景DN。不再另减1000 DN，以免重复扣除偏置。不截断负数，不删除离群帧。')
    para('环境1与环境2相隔约46.57分钟，区间内的背景变化按线性估计。为评估这一假设的影响，另计算固定环境1、最近环境及未扣背景的对照结果。')
    para('后期参考值取第三、四、五段各自净信号均值，再对三段等权平均。该值仅为本次后期实测基准，不是独立标定真值或热平衡极限。相对偏差=100×(净信号/后期基准−1)。每段单独形成不重叠10秒块，至少覆盖8秒且至少10帧才参与稳定判定；各段尾部不足长度的帧仍在原始曲线和分段统计中保留。')
    para('对±1%、±2%、±5%分别寻找“该块及其后所有已观测有效块均在范围内”的首块；再检查其所在连续记录是否还覆盖至少2分钟。2分钟是本次分析选用的最低连续确认长度，不是行业标准。采集空档一律不能算作确认时间。阈值作用于10秒均值；单帧结果另行检查。')
    heading('3. 预热曲线与波段差异')
    figure('01_预热曲线','完整时间轴、早期下降和后期三个采样窗口。阴影区没有亮场数据。')
    table(['分段','开灯后/min','主波段相对后期/%','主波段段内CV/%','段内线性漂移/%每min'],[
      [r['分段'],f"{r['开始开灯分钟']:.2f}–{r['结束开灯分钟']:.2f}",f"{r['均值相对后期基准偏差_pct']:+.3f}",f"{r['单帧CV_pct']:.3f}",f"{r['拟合漂移_pct每min']:+.3f}"] for r in main])
    para('第二段的整体CV包含缓慢下降，不能把它全当成随机噪声。第三至第五段的主波段短时CV约0.094%～0.109%，说明这几个短窗重复性较好；约0.71～0.78分钟的局部斜率也不能线性外推成小时级漂移。')
    table(['波段','冷启动首10帧→第五段末10帧：时变背景/%','同样两端：固定环境1/%'],[
      [list(BANDS)[j],f"{s['net_change_first10_to_last10_pct'][j]:+.2f}",f"{s['fixed_change_first10_to_last10_pct'][j]:+.2f}"] for j in range(5)])
    para('主波段的约−8.39%和蓝波段的约−15.28%均是时变背景假设下的净响应变化。固定环境1时分别为约−3.82%与−2.05%，说明幅度并不稳健。可以确认所测响应随时间改变，但无法仅凭这组记录分离灯光热衰减、环境变化与探头漂移。')
    heading('4. 稳定等待时间')
    table(['指标','容差','首次后续实测块均合格/min','当段剩余连续记录/min','判定'],[
      [r['指标'],'±'+str(r['允许误差_pct'])+'%',f"{r['首次后续实测块均合格分钟']:.2f}",f"{r['所在连续记录剩余分钟']:.2f}",
       '该连续记录满足≥2分钟；后续空档未验证' if r['连续确认至少2分钟'] else '仅有后期短窗支持，连续确认不足'] for r in s['waits']])
    para('只看420～700 nm总量并允许±5%，在当前背景模型下约17.25分钟后进入后期基准范围，并在该段继续观测8.14分钟。该时刻不代表蓝绿红同时稳定。对光谱测量，应优先看三个分波段同时合格的结果。')
    para('对蓝绿红三个分波段，三档容差的首个后续合格观测均为46.47分钟。这主要受25.39～46.47分钟的21.07分钟空档限制，不说明三个物理稳定时间相同，也不证明实际稳定过程单调。50分钟可作为复测的预热安排；±1%正式判定还需更可靠的背景与连续记录。')
    para(f'后期248帧的主波段单帧均在±1%内；蓝波段有{blueex}帧超出±1%，最大绝对偏差约1.44%，但未超出±2%。因此，即便10秒块均值合格，也不能报告“所有单帧蓝光达到±1%”。逐波长SNR筛查中，核心125个通道有{s["evaluable_channels"]}个在三段后期均达到均值/样本标准差≥50；该筛查不是逐波长稳定验收。')
    heading('5. 允许单次工作时长')
    para('稳定后的最大连续工作时长：本次未确定。最后亮场记录结束于开灯63.16分钟；从第三段开始到第五段结束跨越16.70分钟，但三个窗口仅分别记录42.51、46.51和22.16秒，合计111.18秒。不能把这16.70分钟写成连续稳定时长，更不能外推“至少能稳定工作1小时”。灯持续点亮约64分钟是实验条件，不等于全程光学稳定。')
    para('作为单次测量漂移预算的补充，下面只使用第二段连续22.64分钟的记录，以该段开始后前10秒均值为会话基准，计算后续10秒块首次超出该基准的时间。第二段仍处于预热阶段，这些数值不应移用为预热50分钟后的工作时长。')
    work=[r for r in s['work'] if r['会话起点开灯分钟']<3]
    table(['指标','容差','相对会话起点的观测结果','开灯后首次越界/min'],[
      [r['指标'],'±'+str(r['允许误差_pct'])+'%',f"约{r['越界前观测跨度分钟']:.2f}分钟后首个块越界" if r['首次越界块开始分钟'] is not None else f"观察{r['越界前观测跨度分钟']:.2f}分钟未越界",
       f"{r['首次越界块开始分钟']:.2f}" if r['首次越界块开始分钟'] is not None else '未观测到'] for r in work])
    para('上表会话起点为开灯2.75分钟。结果依赖线性背景模型和10秒平均，仅表示这一次连续记录的相对漂移，未计背景系统误差，也不是可保证的时长上限。其他起点5、10、15、20分钟的结果附在CSV中。')
    heading('6. 环境光变化及其影响')
    figure('02_环境光与敏感性','背景谱形、背景占比和两种扣背景方式对漂移曲线的影响。')
    table(['背景','主波段背景占净信号/%','背景单帧标准差占净信号/%','均值标准误占净信号/%'],[
      [r['环境记录'],f"{r['背景均值相对后期净信号_pct']:.2f}",f"{r['背景标准差相对后期净信号_pct']:.2f}",f"{r['背景均值标准误相对后期净信号_pct']:.2f}"] for r in bgmain])
    para('表中背景包含环境光、探头偏置及可能的杂散光，背景占比不是纯环境辐射占比。标准误按标准差/√帧数计算，仅用于独立同分布帧假设下的量级提示；存在时间相关或背景改变时，该值可能低估实际不确定性。它也未包含插值误差、遮挡几何差异和后期参考值的不确定性。')
    para('环境3的主波段背景单帧标准差相当于后期净信号约3.08%，蓝波段约7.29%；其均值标准误量级分别约0.60%和1.43%。因此0.04%级别的后期段均值差不应被解读为灯的真实稳定精度已达到0.04%，蓝波段±1%的严格结论尤其不足。')
    figure('04_环境光逐帧波动','三次背景测量的逐帧变化，环境3的波动明显。')
    table(['扣背景方法','总量±1%首次观测/min','总量±2%首次观测/min','三波段±1%首次观测/min'],[
      [name]+[f"{next(r['首次后续实测块均合格分钟'] for r in s['sensitivity_wait'] if r['背景方法']==name and r['指标']==target and r['允许误差_pct']==th):.2f}" for target,th in [('主波段积分',1),('主波段积分',2),('蓝绿红三个分波段同时',1)]]
      for name in ['时变背景','固定环境1','最近环境','未扣背景']])
    para('“最近环境”会在两次背景测量的中间切换，从而引入人为阶跃；不作为主分析。固定环境与未扣背景会把较大的背景或偏置留在分母，可能使相对变化看起来更小，也不用于替代主分析给出更乐观的等待时间。')
    heading('7. 异常波动记录')
    figure('03_光谱与波动记录','平均光谱、分波段变化、局部残差与采集覆盖。')
    table(['事件','位置/时段','记录与解释'],[
      ['持续下降','冷启动、第二段','主波段早期下降；第二段时变背景下线性拟合变化约−4.34%，不能视为稳定平台'],
      ['短时突波','所有亮场段',f'{total}帧中0帧达到设定稳健阈值；仍保留全部帧参与统计'],
      ['蓝波段±1%单帧越界','第三至第五段',f'共{blueex}帧；属精度越界记录，不据此认定灯具故障'],
      ['背景非恒定','三次环境记录，尤其环境3','影响净信号幅度和严格稳定判定；不能把环境波动全部归因于灯']])
    para('突波筛查：单帧偏离局部10秒中位数超过max(6×1.4826×MAD，0.5%)即标记，各波段独立估计阈值。此项与相对后期基准的±1%单帧精度检查分别计算。')
    heading('8. 下一次验证应补什么')
    para('优先补齐开灯20～55分钟的连续记录，并在50分钟后连续记录不少于拟采用的单次工作时长。若计划每次测量30分钟，就至少覆盖50～80分钟；若需确定上限，应继续记录至出现明确越界，或在结束时只报告已验证下限。至少复测一次完整冷启动，检查等待时间是否可重复。')
    para('背景优先增加测量频次和帧数，以降低插值与均值估计误差。正式验收需明确针对总量、分波段还是逐波长，以及针对单帧还是多帧平均。')
    heading('9. 交付与可复核性')
    para('分析报告.html为离线单文件图文报告，内嵌全部图像。分析报告.md为可编辑文字稿。figures目录包含4张PNG和对应SVG。14份CSV包含文件清单、分段统计、10秒曲线、等待时间、工作窗口、背景统计、异常记录、逐波长与逐帧结果，以及背景敏感性、单帧精度检查和越界时间记录。')
    para('数据来源：'+str(SOURCE)+'。raw目录保留本次8个原始文件副本；文件01给出完整原始文件名和SHA-256。未修改源目录。分析脚本和依赖说明随结果包提供，计算结果均可追溯到逐帧时间戳及源文件。')
    (ROOT/'分析报告.md').write_text('\n'.join(md),encoding='utf-8')
    css='''body{margin:0;background:#f3f5f8;color:#25334a;font-family:"Microsoft YaHei",Arial,sans-serif;font-size:15px;line-height:1.85}main{max-width:1120px;margin:30px auto;padding:38px 48px;background:white;border-top:6px solid #334e76}h1{font-size:29px;line-height:1.5;margin:0 0 20px}h2{font-size:22px;margin:38px 0 12px;border-bottom:1px solid #d8e0e9;padding-bottom:9px}p{margin:12px 0}table{width:100%;border-collapse:collapse;font-size:13px;line-height:1.65}th{background:#334e76;color:white;text-align:left;font-weight:500}td,th{padding:10px 12px;border-bottom:1px solid #dce3eb;vertical-align:top}tr:nth-child(even){background:#f5f7fa}.table-wrap{overflow-x:auto;margin:18px 0}figure{margin:24px 0}img{display:block;width:100%;height:auto}figcaption{font-size:13px;color:#617087;margin-top:9px}a{color:#2d6095}@media(max-width:700px){main{margin:0;padding:22px 16px}h1{font-size:23px}td,th{min-width:100px}}@media print{body{background:white}main{max-width:none;margin:0;padding:0;border:0}h2{break-after:avoid}figure,tr{break-inside:avoid}}'''
    (ROOT/'分析报告.html').write_text('<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>灯1冷启动与稳定性分析</title><style>'+css+'</style></head><body><main>'+''.join(page)+'</main></body></html>',encoding='utf-8')
    (ROOT/'复现说明.txt').write_text('Python 3.12 或更高版本；依赖 numpy、pandas、matplotlib、Pillow。\n运行 analyze.py。需要Windows微软雅黑字体C:/Windows/Fonts/msyh.ttc；其他平台请替换字体路径。\n原始实验目录存在时使用原始目录；不存在时使用随包raw快照。分析始终保留全部帧，不补亮场空档。\n报告中的允许误差为本次分析场景，不是用户指定的验收标准。\n',encoding='utf-8')
    import zipfile
    zip_path=ROOT/'灯1冷启动分析_报告曲线与数据.zip'
    with zipfile.ZipFile(zip_path,'w',zipfile.ZIP_DEFLATED) as z:
        for p in ROOT.iterdir():
            if p.is_file() and p.suffix in ['.csv','.md','.html','.json','.txt','.py']:
                z.write(p,p.name)
        for folder in ['figures','raw']:
            for p in (ROOT/folder).iterdir():
                if p.is_file():z.write(p,str(p.relative_to(ROOT)))
    print('报告与图表完成：',ROOT)
    print('后期蓝波段超过±1%的帧数：',blueex)
    print('结果包字节：',zip_path.stat().st_size)

def validate(result):
    data,lamps,env,w,bt,bs,ref,refs,blocks,s=result
    logs=[]
    assert sum(len(d['t']) for d in lamps)==3389
    assert sum(len(d['t']) for d in env)==74
    logs.append('亮场3389帧、背景74帧与源文件逐项核对一致。')
    for d in data:
        original=d['path'].read_bytes()
        assert hashlib.sha256(original).hexdigest()==hashlib.sha256((ROOT/'raw'/d['path'].name).read_bytes()).hexdigest()
    logs.append('8份源CSV与归档副本SHA-256一致。')
    for d in lamps:
        assert np.allclose(d['net_band'][:,0],d['net_band'][:,1:4].sum(axis=1),rtol=1e-12)
        assert np.allclose(d['raw_band']-d['net_band'],np.column_stack([band_integral(d['background'],w,*b) for b in BANDS.values()]),rtol=1e-12)
    logs.append('所有亮场帧：蓝绿红积分之和等于主波段积分；原始值减背景等于净值。')
    # Independent scalar integration check on the first frame, using manual edge interpolation.
    xx=lamps[0]['x'][0]-bs[0]
    points=[]
    for bound in [420,700]:
        i=int(np.searchsorted(w,bound));f=(bound-w[i-1])/(w[i]-w[i-1])
        points.append((bound,xx[i-1]*(1-f)+xx[i]*f))
    points+= [(float(wl),float(val)) for wl,val in zip(w,xx) if 420<wl<700]
    points.sort()
    manual=sum((b[0]-a[0])*(a[1]+b[1])/2 for a,b in zip(points[:-1],points[1:]))
    assert abs(manual-lamps[0]['net_band'][0,0])<1e-7
    logs.append('首帧净光谱独立标量梯形积分与批量结果一致，绝对误差小于1e-7 DN·nm。')
    assert np.allclose(np.mean([d['net_band'].mean(axis=0) for d in lamps[-3:]],axis=0),ref)
    for r in s['waits']:
        js=[0] if r['指标']=='主波段积分' else [1,2,3]
        selected=[b for b in blocks if b['用于判定'] and b['开始开灯分钟']>=r['首次后续实测块均合格分钟']]
        assert all(abs(b[list(BANDS)[j]+'_偏差_pct'])<=r['允许误差_pct'] for b in selected for j in js)
    logs.append('后期基准等权计算、六项等待阈值的全部后续有效块已核对。')
    lateblue=sum(int((np.abs(100*(d['net_band'][:,1]/ref[1]-1))>1).sum()) for d in lamps[-3:])
    assert lateblue==9
    logs.append('后期蓝波段±1%越界独立复核为9帧；总量后期248帧全部在±1%内。')
    assert all(np.max(np.abs(100*(d['net_band'][:,0]/ref[0]-1)))<=1 for d in lamps[-3:])
    for p in (ROOT/'figures').glob('*.png'):
        from PIL import Image
        with Image.open(p) as im:
            im.verify()
    logs.append('四张PNG均可解码；绘图按分段绘制，不连跨采集空档。')
    (ROOT/'计算核对记录.txt').write_text('\n'.join(logs)+'\n',encoding='utf-8')
    print('计算核对通过：',len(logs),'项')

if __name__=='__main__':
    result=run()
    plot_figures(*result)
    validate(result)
    write_report(*result)
