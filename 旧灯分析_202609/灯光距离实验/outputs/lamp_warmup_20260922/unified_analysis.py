"""One lamp, one clock. File identity is provenance only."""
from pathlib import Path
import sys,os,json,html,base64,zipfile,hashlib
ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT/'python_packages'))
os.environ['MPLCONFIGDIR']=str(ROOT/'mplconfig')
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np
import pandas as pd
from datetime import datetime
from inspect_data import read_data,TZ

DEST=ROOT/'统一时间轴分析'
DEST.mkdir(exist_ok=True)
NAMES=['总量420–700','蓝420–500','绿500–600','红600–700']
BOUNDS=[(420,700),(420,500),(500,600),(600,700)]
COLORS=['#253f61','#4386b9','#378b71','#bd625a']

def integral(x,w,lo,hi):
    inside=(w>lo)&(w<hi)
    def edge(v):
        j=np.searchsorted(w,v)
        return x[...,j-1]+(x[...,j]-x[...,j-1])*(v-w[j-1])/(w[j]-w[j-1])
    values=np.concatenate([edge(lo)[...,None],x[...,inside],edge(hi)[...,None]],axis=-1)
    return np.trapezoid(values,np.r_[lo,w[inside],hi],axis=-1)

def clock(t):return datetime.fromtimestamp(float(t),TZ).isoformat(timespec='milliseconds')
def outcsv(name,rows):pd.DataFrame(rows).to_csv(DEST/name,index=False,encoding='utf-8-sig',float_format='%.8f')

def load():
    # Use exactly the timestamp-named CSV files supplied by the user.
    data=read_data();sources=[d for d in data if '环境' not in d['tag']];env=[d for d in data if '环境' in d['tag']]
    w=sources[0]['w'];filemeta=[]
    for d in data:
        assert np.array_equal(d['w'],w) and np.isfinite(d['x']).all()
        assert np.all(d['integration']==32) and set(d['modes'])=={'N'}
        filemeta.append({'来源文件':d['path'].name,'类型':'背景' if '环境' in d['tag'] else '灯光',
            '帧数':len(d['t']),'首个时间':clock(d['t'][0]),'末个时间':clock(d['t'][-1]),
            'SHA256':hashlib.sha256(d['path'].read_bytes()).hexdigest()})
    t=np.concatenate([d['t'] for d in sources]);x=np.concatenate([d['x'] for d in sources])
    files=np.concatenate([np.repeat(d['path'].name,len(d['t'])) for d in sources])
    rows=np.concatenate([np.arange(1,len(d['t'])+1) for d in sources])
    order=np.argsort(t);t,x,files,rows=t[order],x[order],files[order],rows[order]
    assert len(t)==6899 and np.all(np.diff(t)>0)
    for d in env: assert np.array_equal(d['w'],w)
    seconds=t-t[0]
    raw=np.column_stack([integral(x,w,*b) for b in BOUNDS])
    background=np.array([[integral(d['x'],w,*b).mean() for b in BOUNDS] for d in env])
    return t,seconds,x,raw,background,env,w,files,rows,filemeta

def evaluate(seconds,raw,background):
    """No file labels, per-file offsets or per-file baselines enter this function."""
    # Absolute grid anchored once to lamp power-on: [0,10),[10,20),... seconds.
    bins={};binrows=[]
    for bid in range(int(seconds[-1]//10)+1):
        a=bid*10;b=a+10;m=(seconds>=a)&(seconds<b);tt=seconds[m]
        valid=(len(tt)>=10 and tt[0]-a<=1 and b-tt[-1]<=1 and np.diff(tt).max()<=2) if len(tt)>1 else False
        if valid:
            bins[bid]={'start':a,'end':b,'raw':raw[m].mean(axis=0),'indices':np.flatnonzero(m)}
        binrows.append({'全局十秒块编号':bid,'开始开灯分钟':a/60,'结束开灯分钟':b/60,'帧数':int(m.sum()),'采样覆盖合格':bool(valid),
            **{NAMES[j]+'_原始均值':raw[m,j].mean() if m.any() else None for j in range(4)}})
    windows=[]
    for bid,entry in bins.items():
        for h in [.5,1,3,5,10]:
            ids=list(range(bid,bid+round(h*6)))
            if not all(k in bins for k in ids):continue
            means=np.array([bins[k]['raw'] for k in ids]);base=means[0]
            indices=np.concatenate([bins[k]['indices'] for k in ids])
            assert np.diff(seconds[indices]).max()<=2
            den=base[None,:]-background
            assert den.min()>0
            deviation=100*(means[:,None,:]-base[None,None,:])/den[None,:,:]
            point=100*(raw[indices,None,:]-base[None,None,:])/den[None,:,:]
            for label,js in [('总量',[0]),('蓝绿红同时',[1,2,3])]:
                windows.append({'窗口起点_开灯分钟':entry['start']/60,'窗口终点_开灯分钟':(entry['start']+h*60)/60,
                    '窗口时长分钟':h,'指标':label,'帧数':len(indices),'实际首帧分钟':seconds[indices[0]]/60,'实际末帧分钟':seconds[indices[-1]]/60,
                    '10秒均值最大偏移_环境1_pct':float(np.abs(deviation[:,0,js]).max()),
                    '10秒均值最大偏移_三背景最坏_pct':float(np.abs(deviation[:,:,js]).max()),
                    '单帧最大偏移_三背景最坏_pct':float(np.abs(point[:,:,js]).max()),
                    **{NAMES[j]+'_10秒均值最大偏移_三背景最坏_pct':float(np.abs(deviation[:,:,j]).max()) for j in range(4)}})
    # Fixed absolute start times selected independently of filenames and pass/fail outcomes.
    selected=[r for r in windows if r['窗口起点_开灯分钟'] in [0,3,5,10,15,20] and (r['窗口时长分钟'] in [1,3,5,10] or r['窗口起点_开灯分钟']==0)]
    sessions=[]
    for minute in [0,3,5,10,15,20]:
        bid=minute*6
        if bid not in bins:continue
        ids=[];k=bid
        while k in bins:ids.append(k);k+=1
        means=np.array([bins[k]['raw'] for k in ids]);base=means[0]
        deviation=100*(means[:,None,:]-base[None,None,:])/(base[None,None,:]-background[None,:,:])
        for label,js in [('总量',[0]),('蓝绿红同时',[1,2,3])]:
            worst=np.abs(deviation[:,:,js]).max(axis=(1,2))
            for tolerance in [1,2,5]:
                bad=np.flatnonzero(worst>tolerance);stop=int(bad[0]) if len(bad) else len(ids)
                assert stop>0
                end=bins[ids[stop-1]]['end']/60
                sessions.append({'起点_开灯分钟':minute,'指标':label,'容差_pct':tolerance,
                    '已覆盖合格时间_分钟':end-minute,'首个越界块起点_开灯分钟':bins[ids[stop]]['start']/60 if stop<len(ids) else None,
                    '结论':'随后观测到越界块' if stop<len(ids) else '未到已测上限，仅报告覆盖时长'})
    return bins,binrows,windows,selected,sessions

def analyze():
    t,seconds,x,raw,bg,env,w,files,rows,filemeta=load()
    bins,binrows,windows,selected,sessions=evaluate(seconds,raw,bg)
    global_reference=raw[seconds<10].mean(axis=0)-bg[0]
    net=raw-bg[0]
    assert np.allclose(net[:,0],net[:,1:].sum(axis=1),rtol=1e-12)
    frames=[{'全局帧序号':i+1,'开灯分钟':seconds[i]/60,'北京时间':clock(t[i]),'来源文件':files[i],'文件内帧序号':rows[i],
        **{NAMES[j]+'_固定环境1净积分':net[i,j] for j in range(4)},
        **{NAMES[j]+'_相对通电后前10秒均值变化_pct':100*(net[i,j]/global_reference[j]-1) for j in range(4)}} for i in range(len(t))]
    # Local residual uses actual timestamps, with one scale for the entire run per band.
    anomalies=[];residual=np.empty_like(net);noise=[]
    for j,name in enumerate(NAMES):
        med=pd.Series(net[:,j],index=pd.to_datetime(t,unit='s',utc=True)).rolling('10s',center=True,min_periods=5).median().to_numpy()
        residual[:,j]=100*(net[:,j]-med)/med
        center=np.nanmedian(residual[:,j]);scale=1.4826*np.nanmedian(np.abs(residual[:,j]-center));limit=max(.5,6*scale)
        noise.append({'波段':name,'局部残差稳健标准差_pct':scale,'全程统一突波阈值_pct':limit})
        for i in np.flatnonzero(np.abs(residual[:,j])>limit):
            anomalies.append({'北京时间':clock(t[i]),'开灯分钟':seconds[i]/60,'全局帧序号':int(i+1),'波段':name,
                '局部残差_pct':residual[i,j],'阈值_pct':limit,'来源文件':files[i],'文件内帧序号':int(rows[i])})
    # Time-based local slopes, not file-based fits.
    slopes=[]
    for minute in range(int(seconds[-1]//60)+1):
        m=(seconds>=minute*60)&(seconds<(minute+1)*60);tt=seconds[m]
        if len(tt)<30 or np.ptp(tt)<30 or np.diff(tt).max()>2:continue
        for j,name in enumerate(NAMES):
            yy=net[m,j]
            slopes.append({'绝对时间窗口起点_分钟':minute,'实际样本跨度秒':np.ptp(tt),'波段':name,
                '净积分均值':yy.mean(),'线性变化率_pct每分钟':np.polyfit(tt-tt[0],yy,1)[0]*60/yy.mean()*100})
    background=[]
    for i,d in enumerate(env):
        for j,b in enumerate(BOUNDS):
            yy=integral(d['x'],w,*b)
            background.append({'环境记录':d['tag'],'波段':NAMES[j],'开灯分钟':(d['t'].mean()-t[0])/60,
                '背景积分均值':yy.mean(),'背景标准差':yy.std(ddof=1)})
    outcsv('01_统一时间序列.csv',frames);outcsv('02_全局十秒块.csv',binrows)
    outcsv('03_全部时间窗口.csv',windows);outcsv('04_固定时刻测量结果.csv',selected)
    outcsv('05_单次工作时间.csv',sessions);outcsv('06_局部变化率.csv',slopes)
    outcsv('07_异常波动记录.csv',anomalies or [{'结果':'未检出超过设定阈值的突波'}]);outcsv('08_异常判据.csv',noise)
    outcsv('09_环境光统计.csv',background);outcsv('10_数据来源.csv',filemeta)
    # A source re-partition cannot change results: evaluator accepts only time and intensity.
    altered=np.concatenate(np.array_split(np.arange(len(t)),11))
    check=evaluate(seconds[altered],raw[altered],bg)
    assert check[2]==windows and check[4]==sessions
    # Independently check 3 and 10 minute starts, for 5 and 10 minute windows.
    for start,h in [(3,5),(3,10),(10,5),(10,10)]:
        reference=raw[(seconds>=start*60)&(seconds<start*60+10)].mean(axis=0)
        worst=0
        for jj in [1,2,3]:
            for background_row in bg:
                for k in range(h*6):
                    a=start*60+k*10;m=(seconds>=a)&(seconds<a+10)
                    mean=raw[m,jj].mean()
                    worst=max(worst,abs(100*(mean-reference[jj])/(reference[jj]-background_row[jj])))
        expected=next(r for r in windows if r['窗口起点_开灯分钟']==start and r['窗口时长分钟']==h and r['指标']=='蓝绿红同时')
        assert abs(worst-expected['10秒均值最大偏移_三背景最坏_pct'])<1e-9
    (DEST/'计算核对.txt').write_text('从用户按时间戳命名的4个亮场CSV读取6899帧并按时间排序，时间戳唯一。\n主波段积分等于蓝绿红之和。\n分析函数只接收时间、信号和背景，不接收文件标签。\n重新拆成11份再合并，全部窗口与工作时长结果完全一致。\n3分钟和10分钟起点的5分钟、10分钟窗口，独立逐波段逐背景计算一致。\n',encoding='utf-8')
    print('统一分析完成：',len(t),'帧；',len(windows),'个指标窗口；',len(anomalies),'条突波标记')
    return t,seconds,raw,net,bg,env,w,global_reference,bins,windows,selected,sessions,residual,noise,anomalies,slopes

def plots(result):
    t,sec,raw,net,bg,env,w,reference,bins,windows,selected,sessions,residual,noise,anomalies,slopes=result
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    font_manager.fontManager.addfont(r'C:\Windows\Fonts\msyh.ttc')
    plt.rcParams.update({'font.family':'Microsoft YaHei','font.size':10,'axes.unicode_minus':False,'axes.spines.top':False,'axes.spines.right':False})
    folder=DEST/'figures';folder.mkdir(exist_ok=True)
    cut=np.flatnonzero(np.diff(sec)>2)+1
    def broken_y(y):
        return np.insert(sec/60,cut,np.nan),np.insert(y,cut,np.nan)
    def save(fig,name):
        fig.savefig(folder/(name+'.png'),dpi=170,bbox_inches='tight');fig.savefig(folder/(name+'.svg'),bbox_inches='tight');plt.close(fig)
    fig,axs=plt.subplots(3,1,figsize=(11.5,10.4),gridspec_kw={'height_ratios':[1.15,1,.8]})
    for j,name in enumerate(NAMES):
        xx,yy=broken_y(100*(net[:,j]/reference[j]-1))
        axs[0].plot(xx,yy,lw=.6,alpha=.7,color=COLORS[j],label=name)
        axs[1].plot(xx,yy,lw=.6,alpha=.7,color=COLORS[j])
    axs[0].set(title='一条时间轴、同一个参考值：从刚通电到最后记录',ylabel='相对通电后前10秒均值 / %',xlabel='累计点亮时间 / 分钟')
    axs[0].legend(ncol=2,fontsize=9)
    axs[1].set(title='前25分钟放大：不按文件重新归零',xlim=(-.1,25.5),ylabel='相对通电后前10秒均值 / %',xlabel='累计点亮时间 / 分钟')
    for j,name in enumerate(NAMES):
        rr=[r for r in slopes if r['波段']==name]
        axs[2].plot([r['绝对时间窗口起点_分钟']+.5 for r in rr],[r['线性变化率_pct每分钟'] for r in rr],'.',color=COLORS[j],ms=5,label=name)
    axs[2].axhline(0,color='#aaa',lw=.7);axs[2].set(title='按绝对分钟窗口计算局部变化率',ylabel='变化率 / %每分钟',xlabel='累计点亮时间 / 分钟')
    for ax in axs:ax.grid(axis='y',alpha=.2)
    fig.suptitle('灯1：一次连续点亮实验的完整曲线',x=.08,ha='left',fontsize=18)
    fig.tight_layout(rect=[0,.03,1,.96],h_pad=1.8)
    fig.text(.08,.008,'曲线固定扣除环境1；文件边界不参与分析。空白处没有采样，曲线不补点连接。跨时刻变化仍可能含环境光影响。',fontsize=9)
    save(fig,'01_统一时间轴曲线')
    fig,axs=plt.subplots(2,2,figsize=(11.5,8.2),sharex=True,sharey=True)
    for ax,h in zip(axs.flat,[1,3,5,10]):
        for name,color in [('总量',COLORS[0]),('蓝绿红同时','#b16c42')]:
            rr=[r for r in windows if r['指标']==name and r['窗口时长分钟']==h]
            ax.plot([r['窗口起点_开灯分钟'] for r in rr],[r['10秒均值最大偏移_三背景最坏_pct'] for r in rr],color=color,label=name,lw=1.2)
        ax.axhline(1,color='#929eaf',ls='--',lw=1);ax.grid(axis='y',alpha=.2)
        ax.set(title=f'从所选时刻起连续测{h}分钟',xlabel='测量起点：累计点亮分钟',ylabel='窗口内10秒均值最大偏移 / %')
    axs[0,0].legend(fontsize=9)
    fig.suptitle('测量窗口由时钟选取，与文件边界无关',x=.08,ha='left',fontsize=17)
    fig.tight_layout(rect=[0,.04,1,.96],h_pad=1.6)
    fig.text(.08,.008,'每10秒扫描一个起点；以窗口前10秒均值为测量参考。三组背景分别固定扣除，取最大偏移；虚线为±1%限值。',fontsize=9)
    save(fig,'02_绝对时间窗口')
    fig,axs=plt.subplots(1,2,figsize=(11.5,4.6))
    for j in range(4):
        xx,yy=broken_y(residual[:,j]);axs[0].plot(xx,yy,color=COLORS[j],alpha=.6,lw=.45,label=NAMES[j])
    axs[0].set(title='全程局部残差',xlabel='累计点亮时间 / 分钟',ylabel='偏离局部10秒中位数 / %');axs[0].legend(fontsize=8,ncol=2)
    for i,d in enumerate(env):axs[1].plot(w,d['x'].mean(axis=0),lw=1.2,label=d['tag'])
    axs[1].set(title='三组环境光均值',xlabel='波长 / nm',ylabel='DN',xlim=(400,750));axs[1].legend()
    for ax in axs:ax.grid(axis='y',alpha=.2)
    fig.tight_layout();save(fig,'03_波动与背景')

def report(result):
    t,sec,raw,net,bg,env,w,reference,bins,windows,selected,sessions,residual,noise,anomalies,slopes=result
    md=[];page=[]
    def h(text,level=2):md.append('#'*level+' '+text+'\n');page.append(f'<h{level}>{html.escape(text)}</h{level}>')
    def p(text):md.append(text+'\n');page.append('<p>'+html.escape(text)+'</p>')
    def table(head,rows):
        rows=[[str(v) for v in row] for row in rows]
        md.append('| '+' | '.join(head)+' |\n| '+' | '.join(['---']*len(head))+' |\n'+'\n'.join('| '+' | '.join(row)+' |' for row in rows)+'\n')
        page.append('<div class="table"><table><thead><tr>'+''.join('<th>'+html.escape(v)+'</th>' for v in head)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(v)+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table></div>')
    def pic(name):
        md.append('!['+name+'](figures/'+name+'.png)\n')
        b64=base64.b64encode((DEST/'figures'/(name+'.png')).read_bytes()).decode()
        page.append('<img src="data:image/png;base64,'+b64+'" alt="'+name+'">')
    def get(start,duration,label='蓝绿红同时'):
        return next((r for r in selected if r['窗口起点_开灯分钟']==start and r['窗口时长分钟']==duration and r['指标']==label),None)
    h('灯1连续点亮实验：统一时间轴分析',1)
    p('2026-09-20；OCR 25F02100；32 ms积分时间。全部3389帧灯光记录合并为一条按首次通电计时的序列，三组环境光独立作为背景。')
    h('结论')
    p('光源测量信号随累计点亮时间缓慢下降，同时叠加较小的短时波动。本次最短预热时间尚未确定；不能从文件起点或后期采样时刻直接推导。可明确的是：在指定累计点亮时刻开始，某个长度的测量窗口能否满足所选漂移要求。')
    rows=[]
    for start,horizon in [(3,1),(3,3),(3,5),(3,10),(10,10)]:
        r=get(start,horizon)
        rows.append([f'{start}～{start+horizon}',horizon,f"{r['10秒均值最大偏移_三背景最坏_pct']:.3f}",
            '通过' if r['10秒均值最大偏移_三背景最坏_pct']<=1 else '未通过'])
    table(['累计点亮时间范围/min','连续测量时长/min','三波段10秒均值最大偏移/%','±1%判定'],rows)
    p('表中3分钟、10分钟是按统一时钟选定的检验起点，不是最短预热时间，也不是重新开灯。判据为相对各测量窗口前10秒均值的变化，不能等同于单帧或逐波长的±1%精度。')
    h('1. 完整预热变化曲线')
    pic('01_统一时间轴曲线')
    p('整条曲线只设一个通电零点和一个展示参考：通电后前10秒平均值。没有按文件重新归零，也没有把后期均值当作必须达到的热平衡值。各文件名仅保留在来源字段中。局部变化率按统一时钟的一分钟区间计算。')
    initial=net[sec<10].mean(axis=0);last=net[sec>sec[-1]-10].mean(axis=0)
    table(['波段','最后10秒相对通电后前10秒变化/%'],[[NAMES[j],f'{100*(last[j]/initial[j]-1):+.2f}'] for j in range(4)])
    p('上表固定扣除环境1，反映本次测得响应的跨时刻变化；背景也可能变化，因此这些百分比不能全部解释成灯本身的热衰减。完整曲线和局部测量稳定性分别评价。')
    h('2. 按实际时间检查测量窗口')
    pic('02_绝对时间窗口')
    table(['检验起点：累计点亮/min','连续1min最大偏移/%','连续3min/%','连续5min/%','连续10min/%'],[
        [start]+[f"{get(start,horizon)['10秒均值最大偏移_三背景最坏_pct']:.3f}" if get(start,horizon) else '无完整采样覆盖' for horizon in [1,3,5,10]] for start in [3,5,10,15,20]])
    p('窗口从首次通电起每10秒选取一次，不读取文件边界。仅使用采样覆盖完整的窗口；缺少采样的区间不填充。每个10秒块至少10帧、两端采样各在1秒以内且内部最大帧间隔不超过2秒。这是本次覆盖检查规则，不是灯的工作状态判据。')
    h('3. 单次工作时长')
    rows=[]
    for start in [3,5,10,15,20]:
        for tol in [1,2]:
            r=next(v for v in sessions if v['起点_开灯分钟']==start and v['指标']=='蓝绿红同时' and v['容差_pct']==tol)
            rows.append([start,'±'+str(tol)+'%',f"{r['已覆盖合格时间_分钟']:.2f}",r['结论']])
    table(['测量起点：累计点亮/min','三波段10秒均值容差','已覆盖合格时长/min','结果'],rows)
    p('计时从所选测量起点开始，以当时前10秒均值为参考，直到首次越界或有效数据结束。各行可观测的剩余时间不同，“后来测得的合格时长较短”不意味着灯退化。未观测到越界时，不能推断最大允许工作时长。')
    h('4. 异常波动')
    pic('03_波动与背景')
    p(f'合并后的3389帧记录采用全程统一的分波段稳健阈值，检出{len(anomalies)}条突波记录。阈值为max(6×1.4826×MAD，0.5%)，其中MAD针对相对局部10秒中位数的残差计算。缓慢漂移和单帧超出精度要求分别保留，未检出突波不等于所有单帧都满足±1%。')
    table(['累计点亮范围/min','三波段10秒均值最大偏移/%','三波段单帧最大偏移/%'],[
        [f'{start}～{start+horizon}',f"{get(start,horizon)['10秒均值最大偏移_三背景最坏_pct']:.3f}",f"{get(start,horizon)['单帧最大偏移_三背景最坏_pct']:.3f}"] for start,horizon in [(3,5),(3,10),(10,10)]])
    h('5. 环境光与计算口径')
    p('不对环境光作时间插值。每个测量窗口分别固定扣除环境1、环境2、环境3，再取相对偏移最大的结果，避免人为引入背景斜率。三次背景只用于固定背景敏感性检查，不能排除真实环境变化，也不是背景误差的置信区间。')
    p('总量范围420～700 nm，分为蓝420～500、绿500～600、红600～700 nm，按实际波长梯形积分。指标是DN积分的相对变化，不是绝对光功率。整条曲线的参考始终为通电后前10秒；计算一次测量期间的漂移时，参考设在所选时间窗口的开始，与文件名称无关。')
    p('本次仅有一次冷启动。结论可用于描述已观测的工作窗口，尚不能确定可重复的最短预热时间或灯具最大连续工作时长。')
    h('数据与验证')
    p('10份CSV包含统一逐帧序列、全局时间块、全部测量窗口、固定时刻比较、工作时长、变化率、异常及来源哈希。将同一时间序列重新拆成11份再合并，计算结果完全一致；3分钟和10分钟起点的代表窗口已独立复核。报告以本版为准。')
    css='body{font-family:"Microsoft YaHei",Arial,sans-serif;background:#f3f5f8;color:#23324a;line-height:1.85;margin:0}main{max-width:1100px;margin:24px auto;background:white;padding:34px 40px;border-top:5px solid #334e73}h1{font-size:27px}h2{font-size:21px;margin-top:30px;border-bottom:1px solid #dce3ec}p{font-size:15px}.table{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:10px;text-align:left;border-bottom:1px solid #ddd}th{background:#334e73;color:white}tr:nth-child(even){background:#f4f6f9}img{width:100%;height:auto;margin:18px 0}@media(max-width:650px){main{margin:0;padding:16px}h1{font-size:22px}}'
    doc='<!doctype html><html lang="zh-CN"><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>灯1统一时间轴分析</title><style>'+css+'</style><main>'+''.join(page)+'</main></html>'
    (DEST/'分析报告.html').write_text(doc,encoding='utf-8');(DEST/'分析报告.md').write_text('\n'.join(md),encoding='utf-8')
    (ROOT/'分析报告.html').write_text(doc,encoding='utf-8');(ROOT/'分析报告.md').write_text('\n'.join(md).replace('](figures/','](统一时间轴分析/figures/'),encoding='utf-8')
    # Existing report entry points now lead to the corrected report too.
    old=ROOT/'重新分析'
    if old.exists():
        (old/'分析报告.html').write_text(doc,encoding='utf-8')
        (old/'分析报告.md').write_text('本目录旧结果已被统一时间轴分析替代。请查看 ../统一时间轴分析/分析报告.md。\n',encoding='utf-8')
    archive=ROOT/'灯1冷启动分析_报告曲线与数据.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for f in DEST.rglob('*'):
            if f.is_file():z.write(f,str(f.relative_to(DEST)))
        for f in (ROOT/'raw').glob('*.csv'):z.write(f,'raw/'+f.name)
        for name in ['unified_analysis.py','inspect_data.py']:z.write(ROOT/name,'代码/'+name)
        z.writestr('复现说明.txt','Python依赖numpy、pandas、matplotlib、Pillow。运行代码/unified_analysis.py，输出位于代码/统一时间轴分析。Windows微软雅黑字体。原始目录不可用时读取随包raw文件。')
    print('统一时间轴报告、曲线、数据包已更新。')

if __name__=='__main__':
    result=analyze()
    plots(result)
    report(result)
