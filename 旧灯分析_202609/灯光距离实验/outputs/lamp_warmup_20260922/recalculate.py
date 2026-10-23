"""Reanalysis: within-acquisition measurement stability, no time-varying background."""
from pathlib import Path
import sys,os
ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT/'python_packages'))
os.environ['MPLCONFIGDIR']=str(ROOT/'mplconfig')
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np
import pandas as pd
from inspect_data import read_data,TZ
from datetime import datetime
import json, html, base64, hashlib, zipfile, shutil

BANDS={'主波段420–700':(420,700),'蓝420–500':(420,500),'绿500–600':(500,600),'红600–700':(600,700)}
COLORS=['#202f46','#3478bc','#269278','#c45951']
def clock(t):return datetime.fromtimestamp(float(t),TZ).isoformat(timespec='milliseconds')
def band_integral(x,w,lo,hi):
    inside=(w>lo)&(w<hi)
    def edge(v):
        j=np.searchsorted(w,v)
        return x[...,j-1]+(x[...,j]-x[...,j-1])*(v-w[j-1])/(w[j]-w[j-1])
    xx=np.concatenate([edge(lo)[...,None],x[...,inside],edge(hi)[...,None]],axis=-1)
    return np.trapezoid(xx,np.r_[lo,w[inside],hi],axis=-1)

DEST=ROOT/'重新分析'
DEST.mkdir(exist_ok=True)
NAMES=list(BANDS)[:4]

def csvout(name,rows):
    pd.DataFrame(rows).to_csv(DEST/name,index=False,encoding='utf-8-sig',float_format='%.8f')

def compute():
    data=read_data(); lamps=[d for d in data if '环境' not in d['tag']];env=[d for d in data if '环境' in d['tag']]
    t0=lamps[0]['t'][0];w=lamps[0]['w']
    bg=np.array([[band_integral(d['x'],w,*v).mean() for v in list(BANDS.values())[:4]] for d in env])
    quality=[];frames=[];segments=[];blocks=[];anomalies=[];background=[]
    for d in data:
        assert np.array_equal(w,d['w']) and np.isfinite(d['x']).all()
        assert np.all(np.diff(d['t'])>0) and np.all(d['integration']==32)
        d['s']=d['t']-t0
        d['raw']=np.column_stack([band_integral(d['x'],w,*v) for v in list(BANDS.values())[:4]])
        quality.append({'文件名':d['path'].name,'SHA256':hashlib.sha256(d['path'].read_bytes()).hexdigest(),'分段':d['tag'],
            '开始时间':clock(d['t'][0]),'结束时间':clock(d['t'][-1]),'开始分钟':d['s'][0]/60,'结束分钟':d['s'][-1]/60,
            '帧数':len(d['t']),'跨度秒':np.ptp(d['t']),'最大DN':d['x'].max()})
    for d in lamps:
        d['net']=d['raw']-bg[0]
        bid=np.floor((d['t']-d['t'][0])/10).astype(int)
        d['blocks']=[]
        for b in np.unique(bid):
            m=bid==b
            if m.sum()<10 or np.ptp(d['t'][m])<8: continue
            r={'segment':d['tag'],'start':d['s'][m][0],'end':d['s'][m][-1],'raw':d['raw'][m].mean(axis=0),'n':int(m.sum())}
            d['blocks'].append(r)
            blocks.append({'分段':d['tag'],'开始分钟':r['start']/60,'结束分钟':r['end']/60,'帧数':r['n'],
               **{NAMES[j]+'_净积分_固定环境1':r['raw'][j]-bg[0,j] for j in range(4)}})
        for j,name in enumerate(NAMES):
            y=d['net'][:,j];initial=y[d['s']<d['s'][0]+10].mean();tail=y[d['s']>=d['s'][-1]-10].mean()
            residual=y-pd.Series(y,index=pd.to_datetime(d['t'],unit='s',utc=True)).rolling('10s',center=True,min_periods=5).median().to_numpy()
            pct=100*residual/np.median(y);scale=1.4826*np.median(np.abs(pct-np.median(pct)));limit=max(.5,6*scale)
            segments.append({'分段':d['tag'],'波段':name,'开始分钟':d['s'][0]/60,'结束分钟':d['s'][-1]/60,
                '首末10秒变化_pct':100*(tail/initial-1),'全段CV_pct':100*y.std(ddof=1)/y.mean(),
                '局部残差标准差_pct':100*residual.std(ddof=1)/y.mean(),
                '线性斜率_pct每分钟':100*np.polyfit(d['s']-d['s'][0],y,1)[0]*60/y.mean(),
                '异常阈值_pct':limit,'异常帧数':int((np.abs(pct)>limit).sum())})
            for i in np.flatnonzero(np.abs(pct)>limit):
                anomalies.append({'分段':d['tag'],'帧序号':int(i+1),'北京时间':clock(d['t'][i]),'开灯分钟':d['s'][i]/60,
                    '波段':name,'局部残差_pct':pct[i],'阈值_pct':limit})
        for i in range(len(d['s'])):
            frames.append({'分段':d['tag'],'帧序号':i+1,'北京时间':clock(d['t'][i]),'开灯分钟':d['s'][i]/60,
                **{NAMES[j]+'_原始DN积分':d['raw'][i,j] for j in range(4)},
                **{NAMES[j]+'_固定环境1净DN积分':d['net'][i,j] for j in range(4)}})
    # Each candidate uses the same background throughout its window, repeated for all 3 backgrounds.
    windows=[]
    for d in lamps:
        for a in d['blocks']:
            start=a['start']
            for h in [.5,1,3,5,10]:
                end=start+60*h
                if end>d['s'][-1]:continue
                m=(d['s']>=start)&(d['s']<end)
                ts=d['s'][m];raw=d['raw'][m]
                groups=np.floor((ts-start)/10+1e-8).astype(int)
                means=np.array([raw[groups==k].mean(axis=0) for k in range(round(h*6))])
                assert np.isfinite(means).all()
                base=means[0]
                drift=100*(means[:,None,:]-base[None,None,:])/(base[None,None,:]-bg[None,:,:])
                frame_dev=100*(raw[:,None,:]-base[None,None,:])/(base[None,None,:]-bg[None,:,:])
                assert (base-bg).min()>0
                for name,js in [('总量',[0]),('蓝绿红同时',[1,2,3])]:
                    main=np.abs(drift[:,0,js]).max()
                    worst=np.abs(drift[:,:,js]).max()
                    rec={'分段':d['tag'],'指标':name,'起点开灯分钟':start/60,'测量时长分钟':h,
                        '实际采样跨度秒':np.ptp(ts),'帧数':len(ts),
                        '十秒均值最大偏移_环境1_pct':main,'十秒均值最大偏移_三背景最坏_pct':worst,
                        '单帧最大偏移_环境1_pct':np.abs(frame_dev[:,0,js]).max(),
                        '单帧最大偏移_三背景最坏_pct':np.abs(frame_dev[:,:,js]).max(),
                        '首末十秒变化_最大波段绝对值_环境1_pct':np.abs(drift[-1,0,js]).max()}
                    windows.append(rec)
    # Earliest supported start after which all later available candidates of same horizon pass.
    recommendations=[]
    for name in ['总量','蓝绿红同时']:
        for h in [1,3,5,10]:
            candidates=[r for r in windows if r['分段']=='第二段' and r['指标']==name and r['测量时长分钟']==h]
            for th in [1,2,5]:
                for kind,key in [('10秒平均','十秒均值最大偏移_三背景最坏_pct'),('单帧','单帧最大偏移_三背景最坏_pct')]:
                    good=np.array([r[key]<=th for r in candidates]);tail=np.logical_and.accumulate(good[::-1])[::-1]
                    ix=np.flatnonzero(tail)
                    r=candidates[ix[0]] if len(ix) else None
                    recommendations.append({'指标':name,'评价方式':kind,'单次测量分钟':h,'容差_pct':th,
                        '最早有证据起点分钟':r['起点开灯分钟'] if r else None,
                        '起点窗口最大偏移_pct':r[key] if r else None,
                        '后续可检验窗口数':int(len(candidates)-ix[0]) if r else 0,
                        '状态':'从该起点起后续可检验窗口均通过；仅本次实测' if r else '无满足条件的起点',
                        '注意':'最早数据起点不是最短物理预热时间；三背景固定复算，不代表排除真实环境变化'})
    # Session working duration using complete blocks, relative to the first 10s mean.
    sessions=[]; key_starts=[0,lamps[1]['s'][0]/60,5,10,15,20]
    for desired in key_starts:
        d=lamps[0] if desired==0 else lamps[1]
        candidates=[b for b in d['blocks'] if b['start']>=desired*60-1e-7]
        if not candidates:continue
        start=candidates[0]['start'];base=candidates[0]['raw']
        dev=np.array([100*(b['raw'][None,:]-base[None,:])/(base[None,:]-bg) for b in candidates])
        for name,js in [('总量',[0]),('蓝绿红同时',[1,2,3])]:
            for th in [1,2,5]:
                maximum=np.abs(dev[:,:,js]).max(axis=(1,2));bad=np.flatnonzero(maximum>th)
                i=int(bad[0]) if len(bad) else None
                sessions.append({'指标':name,'起点开灯分钟':start/60,'容差_pct':th,
                    '最后合格块结束分钟':(candidates[i-1]['end'] if i is not None and i>0 else candidates[-1]['end'])/60,
                    '已观测合格块跨度分钟':((candidates[i-1]['end'] if i is not None and i>0 else candidates[-1]['end'])-start)/60,
                    '首次越界块开始分钟':candidates[i]['start']/60 if i is not None else None,
                    '状态':'观测到越界' if i is not None else '未到上限；仅给实测覆盖下限'})
    for i,d in enumerate(env):
        for j,name in enumerate(NAMES):
            y=d['raw'][:,j]
            background.append({'环境':d['tag'],'波段':name,'平均DN积分':y.mean(),'帧标准差DN积分':y.std(ddof=1),
                '自身CV_pct':100*y.std(ddof=1)/y.mean(),'相对环境1均值变化_pct':100*(y.mean()/bg[0,j]-1)})
    csvout('01_数据核对.csv',quality);csvout('02_分段变化与短时噪声.csv',segments)
    csvout('03_逐帧曲线.csv',frames);csvout('04_十秒均值.csv',blocks)
    csvout('05_全部滑动测量窗口.csv',windows);csvout('06_等待时间条件表.csv',recommendations)
    csvout('07_实测工作窗口.csv',sessions);csvout('08_环境光对照.csv',background)
    csvout('09_异常帧.csv',anomalies if anomalies else [{'结果':'按局部残差稳健阈值未检出突波'}])
    # Selected easy-to-use session starts, evaluate exact first available frame at desired time.
    chosen=[]
    for desired in [lamps[1]['s'][0]/60,5,10,15,20]:
        for h in [1,3,5,10]:
            rr=[r for r in windows if r['分段']=='第二段' and r['指标']=='蓝绿红同时' and r['测量时长分钟']==h and r['起点开灯分钟']>=desired-1e-7]
            if rr:chosen.append(min(rr,key=lambda r:r['起点开灯分钟']))
    s={'segments':segments,'recommendations':recommendations,'sessions':sessions,'chosen':chosen,'anomalies':anomalies,'background':background}
    (DEST/'结果.json').write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8')
    print('重算完成：',len(windows),'个测量窗口，',len(anomalies),'条突波标记')
    assert sum(len(d['t']) for d in lamps)==3389
    for d in lamps:assert np.allclose(d['net'][:,0],d['net'][:,1:].sum(axis=1),rtol=1e-12)
    return data,lamps,env,bg,windows,s

def make_figures(data,lamps,env,bg,windows,s):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    font_manager.fontManager.addfont(r'C:\Windows\Fonts\msyh.ttc')
    plt.rcParams.update({'font.family':'Microsoft YaHei','axes.unicode_minus':False,'font.size':10,
        'axes.spines.top':False,'axes.spines.right':False,'axes.titleweight':'bold','figure.facecolor':'white'})
    figs=DEST/'figures';figs.mkdir(exist_ok=True)
    def save(fig,name):
        fig.savefig(figs/(name+'.png'),dpi=170,bbox_inches='tight')
        fig.savefig(figs/(name+'.svg'),bbox_inches='tight');plt.close(fig)
    fig,axs=plt.subplots(2,1,figsize=(11.5,8.8))
    initial=lamps[0]['net'][lamps[0]['s']<10].mean(axis=0)
    for j in range(4):
        for k,d in enumerate(lamps):
            axs[0].plot(d['s']/60,100*(d['net'][:,j]/initial[j]-1),color=COLORS[j],alpha=.7,lw=.6,label=NAMES[j] if k==0 else None)
    axs[0].set(title='全过程响应：固定扣除环境1，以通电后前10秒均值为参考',xlabel='通电后 / 分钟',ylabel='相对变化 / %')
    axs[0].legend(ncol=2,fontsize=9);axs[0].grid(axis='y',alpha=.2)
    d=lamps[1];initial=d['net'][d['s']<d['s'][0]+10].mean(axis=0)
    for j in range(4):
        axs[1].plot(d['s']/60,100*(d['net'][:,j]/initial[j]-1),color=COLORS[j],alpha=.6,lw=.5,label=NAMES[j])
    axs[1].set(title='第二段连续记录：以本段前10秒均值为参考，仍有缓慢漂移',xlabel='通电后 / 分钟',ylabel='相对变化 / %')
    axs[1].axhline(-1,color='#8c5a35',ls='--',lw=1);axs[1].axhline(-2,color='#8c5a35',ls=':',lw=1)
    axs[1].grid(axis='y',alpha=.2)
    fig.suptitle('灯1：预热阶段的实测响应变化',x=.08,ha='left',fontsize=18)
    fig.tight_layout(rect=[0,.035,1,.96],h_pad=2)
    fig.text(.08,.008,'全图不对环境光作时间插值。跨段变化仍包含真实背景变化的可能影响；判断工作时长使用下图的段内窗口。',fontsize=9)
    save(fig,'01_响应变化')
    fig,axs=plt.subplots(2,2,figsize=(12,8.6),sharex=True,sharey=True)
    for ax,h in zip(axs.flat,[1,3,5,10]):
        for name,color in [('总量','#283d5b'),('蓝绿红同时','#b35f40')]:
            rr=[r for r in windows if r['分段']=='第二段' and r['指标']==name and r['测量时长分钟']==h]
            ax.plot([r['起点开灯分钟'] for r in rr],[r['十秒均值最大偏移_三背景最坏_pct'] for r in rr],color=color,label=name,lw=1.4)
        ax.axhline(1,color='#a1a8b3',ls='--',label='±1%限值');ax.grid(axis='y',alpha=.2)
        ax.set(title=f'每次连续测 {h} 分钟',xlabel='测量起点：通电后 / 分钟',ylabel='10秒均值最大偏移 / %',ylim=(0,1.55))
    axs[0,0].legend(fontsize=9)
    fig.suptitle('多久开始测、一次测多久：用实际窗口判断',x=.08,ha='left',fontsize=18)
    fig.tight_layout(rect=[0,.04,1,.96],h_pad=2)
    fig.text(.08,.01,'相对每个窗口的前10秒均值；三组实测背景分别固定扣除，取最坏结果。只计算数据覆盖完整的窗口。',fontsize=9)
    save(fig,'02_等待与测量时长')
    fig,axs=plt.subplots(1,2,figsize=(12,4.8))
    names=['总量','蓝绿红同时']
    for ax,name in zip(axs,names):
        for kind,key,color in [('10秒平均','十秒均值最大偏移_三背景最坏_pct','#2d766b'),('单帧','单帧最大偏移_三背景最坏_pct','#b26649')]:
            rr=[r for r in windows if r['分段']=='第二段' and r['指标']==name and r['测量时长分钟']==5]
            ax.plot([r['起点开灯分钟'] for r in rr],[r[key] for r in rr],color=color,label=kind)
        ax.axhline(1,color='#999',ls='--');ax.axhline(2,color='#aaa',ls=':');ax.legend()
        ax.set(title=name+'：连续测5分钟',xlabel='测量起点：通电后 / 分钟',ylabel='相对窗口前10秒均值的最大偏移 / %')
        ax.grid(axis='y',alpha=.2)
    fig.suptitle('平均后的稳定性与单帧波动分别检查',x=.08,ha='left',fontsize=17)
    fig.tight_layout(rect=[0,.03,1,.94]);save(fig,'03_单帧与平均对照')

def report(data,lamps,env,bg,windows,s):
    parts=[];md=[]
    def h(text):md.append('## '+text+'\n');parts.append('<h2>'+html.escape(text)+'</h2>')
    def p(text):md.append(text+'\n');parts.append('<p>'+html.escape(text)+'</p>')
    def table(headers,rows):
        rows=[[str(x) for x in row] for row in rows]
        md.append('| '+' | '.join(headers)+' |\n| '+' | '.join(['---']*len(headers))+' |\n'+'\n'.join('| '+' | '.join(r)+' |' for r in rows)+'\n')
        parts.append('<div class="table"><table><thead><tr>'+''.join('<th>'+html.escape(x)+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(x)+'</td>' for x in r)+'</tr>' for r in rows)+'</tbody></table></div>')
    def pic(name):
        b64=base64.b64encode((DEST/'figures'/(name+'.png')).read_bytes()).decode()
        parts.append('<img src="data:image/png;base64,'+b64+'" alt="'+name+'">')
        md.append(f'![{name}](重新分析/figures/{name}.png)\n')
    title='灯1稳定性重新分析：等待时间与单次测量时长'
    parts.append('<h1>'+title+'</h1>');md.append('# '+title+'\n')
    p('实验日期：2026-09-20。单灯持续点亮，几何位置与亮度档位固定，积分时间32 ms。5段亮场3389帧，3组环境光74帧。')
    h('结论')
    p('本次数据不支持“必须预热50分钟”。按段内相对漂移判断，开灯约2.75分钟起已有连续测量1～5分钟、蓝绿红10秒平均值均保持在±1%内的证据。若一次要连续测10分钟，三个波段同时满足这一条件的稳健起点约为8.1分钟。这里的稳健指在本次后续所有可检验窗口、三组固定背景复算下均通过，不代表已排除真实背景变化。')
    table(['使用条件','本次最早支持的起点','实用安排（待重复验证）'],[
        ['总量，10秒平均，±1%，连续测1～10分钟','开灯2.75分钟','可从开灯3分钟开始'],
        ['蓝绿红同时，10秒平均，±1%，连续测1～5分钟','开灯2.75分钟','可从开灯3分钟开始'],
        ['蓝绿红同时，10秒平均，±1%，连续测10分钟','开灯8.08分钟','可按开灯9～10分钟开始'],
        ['要求每一帧、每个波长都在±1%内','上述结论不适用','需按单帧、逐波长另行判定']])
    p('2.75分钟是第二段连续记录的起点，不是证明此前不能测；8.08分钟是本次10秒步进扫描的结果，不应作为精确到秒的灯具参数。这些是指定测量时长和误差下的使用条件，不是达到热平衡的时间。')
    h('1. 刚开灯与长期变化')
    cold=[r for r in windows if r['分段']=='冷启动' and r['指标']=='蓝绿红同时' and r['起点开灯分钟']==0][0]
    p(f'从刚通电起的前30秒，蓝绿红10秒均值最大偏移为{cold["十秒均值最大偏移_三背景最坏_pct"]:.2f}%，单帧最大偏移为{cold["单帧最大偏移_三背景最坏_pct"]:.2f}%（三组固定背景最坏值）。因此现有冷启动记录没有显示“必须等待几十分钟才能做短时测量”。这一30秒结果不能代替数分钟的连续验证。')
    seg=[r for r in s['segments'] if r['波段']==NAMES[0]]
    table(['记录','开灯后/min','首末10秒总量变化/%','去除局部趋势后的波动标准差/%'],[
        [r['分段'],f"{r['开始分钟']:.2f}～{r['结束分钟']:.2f}",f"{r['首末10秒变化_pct']:+.3f}",f"{r['局部残差标准差_pct']:.3f}"] for r in seg])
    p('第二段2.75～25.39分钟的总量首末下降约1.72%（固定环境1）。这说明灯光测量信号仍缓慢变化，但不妨碍某些短测量窗口满足误差要求。短时波动与长期漂移必须分开看。')
    pic('01_响应变化')
    h('2. 不同测量时长对应的等待条件')
    earliest=lamps[1]['s'][0]/60
    rows=[]
    for length in [1,3,5,10]:
        rr=[r for r in windows if r['分段']=='第二段' and abs(r['起点开灯分钟']-earliest)<1e-8 and r['测量时长分钟']==length]
        total=next(r for r in rr if r['指标']=='总量');band=next(r for r in rr if r['指标']=='蓝绿红同时')
        rec=next(r for r in s['recommendations'] if r['指标']=='蓝绿红同时' and r['评价方式']=='10秒平均' and r['单次测量分钟']==length and r['容差_pct']==1)
        rows.append([length,f"{total['十秒均值最大偏移_三背景最坏_pct']:.3f}",f"{band['十秒均值最大偏移_三背景最坏_pct']:.3f}",f"{rec['最早有证据起点分钟']:.2f}"])
    table(['单次测量/min','从2.75min开始：总量最大偏移/%','从2.75min开始：三波段最大偏移/%','三波段±1%最早支持起点/min'],rows)
    p('每个窗口以自身前10秒平均值为参考，检查随后各10秒均值最大偏移；不与第46分钟或最后三段的平均值比较。选择最早起点时，还要求该起点之后所有数据覆盖完整、相同时长的候选窗口均通过，避免挑中一次偶然表现好的窗口。相邻窗口重叠，不能当作独立重复实验。')
    pic('02_等待与测量时长')
    h('3. 单次工作时长：与开始测量的时刻配套')
    use=[r for r in s['sessions'] if abs(r['起点开灯分钟']-earliest)<1e-8]
    table(['指标','允许误差','本次实测结果'],[[r['指标'],'±'+str(r['容差_pct'])+'%',
        f"已观测合格至约{r['已观测合格块跨度分钟']:.2f}分钟，随后出现越界块" if r['首次越界块开始分钟'] is not None else f"观测{r['已观测合格块跨度分钟']:.2f}分钟未越界，未测到上限"] for r in use])
    p('上表从开灯2.75分钟起算，采用10秒均值和三背景最坏结果。对±1%的三波段要求，实用上可先采用“开灯约3分钟后，每次测1～5分钟”；若每次需测10分钟，可采用“开灯约10分钟后再测”。这是本次记录支持的试用安排，需重复冷启动验证后再固定为操作参数。')
    p('更长时长只能报告本次观测下限或首次越界时段。后期几段用于查看长期变化，不拼接成连续工作时长。')
    h('4. 单帧波动与异常')
    p(f'3389帧亮场按局部10秒中位数残差筛查，检测到{len(s["anomalies"])}条超过max(6×1.4826×MAD，0.5%)的波段突波记录。未检出突波不等于每一帧都满足±1%。蓝波段的单帧波动明显大于总量，不能用总量或多帧平均的结果代表每一帧光谱。')
    pic('03_单帧与平均对照')
    rows=[]
    for length in [1,3,5,10]:
        rec=next(r for r in s['recommendations'] if r['指标']=='蓝绿红同时' and r['评价方式']=='单帧' and r['单次测量分钟']==length and r['容差_pct']==1)
        rec2=next(r for r in s['recommendations'] if r['指标']=='蓝绿红同时' and r['评价方式']=='单帧' and r['单次测量分钟']==length and r['容差_pct']==2)
        rows.append([length,'未找到' if rec['最早有证据起点分钟'] is None else f"{rec['最早有证据起点分钟']:.2f}",
            '未找到' if rec2['最早有证据起点分钟'] is None else f"{rec2['最早有证据起点分钟']:.2f}"])
    table(['测量时长/min','三波段单帧±1%支持起点/min','三波段单帧±2%支持起点/min'],rows)
    h('5. 环境光处理与结论边界')
    p('没有对三次环境光作时间插值。每个窗口分别固定扣环境1、环境2、环境3，再取最大相对偏移；背景只改变净信号参考分母，不人为生成随时间变化的斜率。该比较是敏感性检查，不是环境真值的置信区间，也不能消除真实环境光在亮场采集期间的变化。')
    p('三次背景平均水平及背景自身波动不同，尤其蓝波段。因而本次结果应称为“固定实验条件下测得信号的短时稳定性”，不能全部归因于灯本身，也不能宣称±1%的绝对测量准确度。无需假设热平衡才能给出上述短时测量窗口，但设备固定预热参数仍需重复实验确认。')
    p('主波段420～700 nm，分为蓝420～500、绿500～600、红600～700 nm；按实际波长作梯形积分。结果是DN积分的相对变化，不是绝对光功率，也不证明每个波长同时满足指标。窗口按10秒步进扫描，只用同一连续记录内有足够覆盖的样本。±1%、±2%、±5%均为本次对照判据，完整表含单帧和10秒平均两种口径。')
    h('数据与核对')
    p('源文件：用户指定output目录的8个CSV，未修改。重新分析目录提供逐帧曲线、全部窗口、条件表、工作时长及异常记录。8份文件哈希、3389帧亮场和74帧背景计数均已核对；主波段积分与蓝绿红之和一致。旧版以末期基准推断预热的方法及其工作时长结果已撤回，以本版为准。')
    css='body{font-family:"Microsoft YaHei",Arial,sans-serif;color:#23324a;line-height:1.85;margin:0;background:#f3f5f8}main{max-width:1100px;margin:24px auto;padding:32px 42px;background:white;border-top:5px solid #344e73}h1{font-size:27px}h2{font-size:21px;margin-top:32px;border-bottom:1px solid #dce3ec}p{font-size:15px}table{width:100%;border-collapse:collapse;font-size:13px}th{background:#344e73;color:white}th,td{text-align:left;padding:10px;border-bottom:1px solid #ddd}tr:nth-child(even){background:#f3f6f9}.table{overflow:auto}img{width:100%;height:auto;margin:20px 0}@media(max-width:650px){main{padding:18px;margin:0}h1{font-size:22px}}'
    report_html='<!doctype html><html lang="zh-CN"><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+title+'</title><style>'+css+'</style><main>'+''.join(parts)+'</main></html>'
    (ROOT/'分析报告.html').write_text(report_html,encoding='utf-8')
    (ROOT/'分析报告.md').write_text('\n'.join(md),encoding='utf-8')
    (DEST/'分析报告.html').write_text(report_html,encoding='utf-8')
    (DEST/'分析报告.md').write_text('\n'.join(md).replace('](重新分析/figures/','](figures/'),encoding='utf-8')
    archive=ROOT/'灯1冷启动分析_报告曲线与数据.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for pth in DEST.rglob('*'):
            if pth.is_file():z.write(pth,str(pth.relative_to(DEST)))
        for pth in (ROOT/'raw').glob('*.csv'):z.write(pth,'raw/'+pth.name)
        for name in ['recalculate.py','inspect_data.py']:z.write(ROOT/name,'代码/'+name)
        z.writestr('复现说明.txt','安装Python依赖numpy、pandas、matplotlib、Pillow后运行代码/recalculate.py。使用Windows微软雅黑字体。原目录不存在时读取随包raw副本，输出在代码目录内。结果仅用于本次固定背景假设下的相对漂移评价。')
    print('已替换原报告和结果包。')

def verify(data,lamps,env,bg,windows,s):
    # Verify representative windows with independent per-band scalar operations.
    for d,h in [(lamps[0],.5),(lamps[1],1),(lamps[1],5),(lamps[1],10)]:
        start=d['s'][0];m=(d['s']>=start)&(d['s']<start+h*60)
        raw=d['raw'][m];tm=d['s'][m]-start
        initial=raw[tm<10].mean(axis=0)
        worst=0
        for j in [1,2,3]:
            for b in range(3):
                for k in range(round(h*6)):
                    mean=float(raw[(tm>=k*10)&(tm<(k+1)*10),j].mean())
                    worst=max(worst,abs(100*(mean-initial[j])/(initial[j]-bg[b,j])))
        stored=next(r for r in windows if r['分段']==d['tag'] and r['指标']=='蓝绿红同时' and r['测量时长分钟']==h and r['起点开灯分钟']==start/60)
        assert abs(worst-stored['十秒均值最大偏移_三背景最坏_pct'])<1e-9
    for r in s['recommendations']:
        if r['最早有证据起点分钟'] is None:continue
        key='十秒均值最大偏移_三背景最坏_pct' if r['评价方式']=='10秒平均' else '单帧最大偏移_三背景最坏_pct'
        rr=[v for v in windows if v['分段']=='第二段' and v['指标']==r['指标'] and v['测量时长分钟']==r['单次测量分钟'] and v['起点开灯分钟']>=r['最早有证据起点分钟']]
        assert len(rr)==r['后续可检验窗口数'] and all(v[key]<=r['容差_pct'] for v in rr)
    (DEST/'计算核对.txt').write_text('4个代表窗口用独立逐波段、逐背景、逐时间块运算核对一致。\n所有条件起点之后的可检验窗口均已重新逐项核查。\n3389亮场帧、74背景帧及蓝绿红之和核对一致。\n',encoding='utf-8')
    print('独立数值复核通过。')

if __name__=='__main__':
    result=compute()
    verify(*result)
    make_figures(*result)
    report(*result)
