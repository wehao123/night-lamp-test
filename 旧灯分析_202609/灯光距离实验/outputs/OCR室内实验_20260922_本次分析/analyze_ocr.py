"""OCR indoor experiments. Run with Python + numpy + matplotlib; source files read only."""
from pathlib import Path
import argparse, csv, re, json, hashlib, sys, os, html
from datetime import datetime

HERE = Path(__file__).resolve().parent
DEPS = HERE.parents[1] / 'tmp' / 'ocr_analysis_deps'
if DEPS.exists():
    sys.path.insert(0, str(DEPS))
os.environ.setdefault('MPLCONFIGDIR', str(HERE / '_mplconfig'))
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.font_manager import fontManager

parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, default=Path(r'C:\Users\haowei\Desktop\夜间水质资料\夜间水质资料\光谱仪室内实验'))
parser.add_argument('--offset', type=float, default=1000)
args = parser.parse_args()
ROOT, OFFSET = args.source, args.offset
FIG = HERE / 'figures'; TAB = HERE / 'tables'
FIG.mkdir(exist_ok=True); TAB.mkdir(exist_ok=True)
fontManager.addfont(r'C:\Windows\Fonts\msyh.ttc')
plt.rcParams.update({'font.family':'Microsoft YaHei','axes.unicode_minus':False,'font.size':10,
                     'axes.spines.top':False,'axes.spines.right':False,'axes.titlepad':10,
                     'savefig.dpi':220,'svg.fonttype':'path'})
COL = ['#2678B2','#E49D28','#299878','#C65B79','#7965B2','#38A6BA']

def export(name, rows):
    rows = list(rows)
    with (TAB/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

def load(p):
    rows=list(csv.reader(x for x in p.read_text(encoding='utf-8-sig').splitlines() if x and not x.startswith('#')))
    meta={r[0]:r[2:] for r in rows[1:] if not r[0].startswith('CH_')}
    channels=[r for r in rows[1:] if r[0].startswith('CH_')]
    a=np.array([r[2:] for r in channels],float); wave=np.array([r[1] for r in channels],float)
    ts=[datetime.fromisoformat(x) for x in rows[0][2:]]
    sec=np.array([(x-ts[0]).total_seconds() for x in ts])
    times=np.array(meta['IntegrationTime_ms'],float); modes=set(meta['CaptureMode'])
    assert a.shape==(288,len(ts)) and np.isfinite(a).all() and np.all(np.diff(wave)>0)
    assert len(set(times))==1 and len(modes)==1 and np.all(np.diff(sec)>0)
    return dict(p=p,a=a,w=wave,t=times[0],mode=next(iter(modes)),sec=sec,n=a.shape[1],ts=ts)

def drift(a, sec):
    x=sec-sec.mean(); slope=a@x/(x@x)
    return slope, slope*(sec[-1]-sec[0])

def intervals(mask,w):
    ids=np.where(mask)[0]
    if not len(ids): return []
    return [(float(w[x[0]]),float(w[x[-1]]),len(x)) for x in np.split(ids,np.where(np.diff(ids)>1)[0]+1)]

def longest(mask,w):
    groups=intervals(mask,w)
    if not groups:return '无'
    a,b,n=max(groups,key=lambda x:x[2]); return f'{a:.1f}–{b:.1f} nm（{n}通道）'

plots=[]
def save(fig,name,caption):
    fig.savefig(FIG/(name+'.png'),bbox_inches='tight',facecolor='white')
    fig.savefig(FIG/(name+'.svg'),bbox_inches='tight',facecolor='white')
    plt.close(fig); plots.append((name,caption))

files={p.name:load(p) for p in sorted(ROOT.rglob('*.csv'))}
wave=next(iter(files.values()))['w']
assert all(np.array_equal(f['w'],wave) for f in files.values())
manifest=[]
for f in files.values():
    named_t=float(re.search(r'(\d+)MS',f['p'].name,re.I)[1])
    manifest.append(dict(file=str(f['p']),sha256=hashlib.sha256(f['p'].read_bytes()).hexdigest(),
       mode=f['mode'],channels=288,frames=f['n'],filename_ms=named_t,actual_ms=f['t'],
       time_mismatch=named_t!=f['t'],start_UTC=f['ts'][0].isoformat(),end_UTC=f['ts'][-1].isoformat(),
       duration_s=f['sec'][-1],raw_min=f['a'].min(),raw_max=f['a'].max(),nonfinite=0))
export('01_文件核查.csv',manifest)

# Linearity pairs: group suffix is maximum integration time, not repeat count.
lin=[]; lr=[]; ls=[]; bins=[]
for suffix in (64,128):
    for power in (3,4,5):
        pair=[f for f in files.values() if f['p'].parent.name=='二代OCR模组线性度' and re.search(fr'-{power}W-{suffix}\.csv$',f['p'].name,re.I)]
        assert len(pair)==2
        s,l=sorted(pair,key=lambda f:f['t']); assert s['mode']==l['mode']=='N'
        a=s['a']-OFFSET; b=l['a']-OFFSET
        sm=a.mean(1); lm=b.mean(1); factor=l['t']/s['t']; ideal=sm*factor
        valid=(sm>0)&(lm>0)
        ratio=np.divide(ideal,lm,out=np.full(288,np.nan),where=valid)
        se=ratio*np.sqrt((a.std(1,ddof=1)/np.sqrt(s['n'])/sm)**2+(b.std(1,ddof=1)/np.sqrt(l['n'])/lm)**2)
        snrs=sm/a.std(1,ddof=1); snrl=lm/b.std(1,ddof=1)
        quality=valid&(snrs>=20)&(snrl>=20)
        anchor=quality&(lm>=15000)&(lm<=25000)
        k=float(np.median(ratio[anchor])) if anchor.any() else np.nan
        norm=ratio/k
        raw_ratio=factor*s['a'].mean(1)/l['a'].mean(1)
        label=f"{s['t']:g}→{l['t']:g} ms · {power}W"
        sd=drift(a,s['sec'])[1]/sm*100; ld=drift(b,l['sec'])[1]/lm*100
        d=dict(s=s,l=l,sm=sm,lm=lm,ideal=ideal,ratio=ratio,norm=norm,raw_ratio=raw_ratio,
               label=label,quality=quality,k=k,power=power,suffix=suffix,sd=sd,ld=ld)
        lin.append(d)
        for i in range(288):
            lr.append(dict(group=label,channel=i+1,wavelength_nm=wave[i],short_ms=s['t'],long_ms=l['t'],
                short_net_mean_DN=sm[i],long_net_mean_DN=lm[i],ideal_long_DN=ideal[i],ratio=ratio[i],
                ratio_minus_one_percent=(ratio[i]-1)*100,actual_vs_ideal_percent=(1/ratio[i]-1)*100,
                ratio_SE_independent_frames_assumed=se[i],short_SNR=snrs[i],long_SNR=snrl[i],
                both_SNR20=bool(quality[i]),short_fit_drift_percent=sd[i],long_fit_drift_percent=ld[i],
                anchor_median=k,anchor_normalized_ratio=norm[i],ratio_offset0=raw_ratio[i]))
        ls.append(dict(group=label,short_frames=s['n'],long_frames=l['n'],factor=factor,
             net_peak_DN=lm.max(),qualified_channels=int(quality.sum()),
             median_ratio=float(np.median(ratio[quality])),p95_absolute_deviation_percent=float(np.percentile(abs(ratio[quality]-1)*100,95)),
             within_1pct_count=int((quality&(abs(ratio-1)<=.01)).sum()),within_2pct_count=int((quality&(abs(ratio-1)<=.02)).sum()),
             anchor_channels=int(anchor.sum()),anchor_median=k,
             median_short_abs_fit_drift_percent=float(np.median(abs(sd[quality]))),median_long_abs_fit_drift_percent=float(np.median(abs(ld[quality])))))
        for low,high in zip([0,4000,8000,15000,25000,35000,45000],[4000,8000,15000,25000,35000,45000,55000]):
            m=quality&(lm>=low)&(lm<high)
            bins.append(dict(group=label,lower_DN=low,upper_DN_exclusive=high,n=int(m.sum()),
                    median_ratio=float(np.median(ratio[m])) if m.any() else '',
                    p95_abs_deviation_percent=float(np.percentile(abs(ratio[m]-1)*100,95)) if m.any() else '',
                    within_2pct_fraction=float(np.mean(abs(ratio[m]-1)<=.02)) if m.any() else ''))
export('02_线性度逐通道.csv',lr); export('03_线性度汇总.csv',ls); export('04_线性度码值分段.csv',bins)

fig,axs=plt.subplots(1,2,figsize=(15,6),layout='constrained')
for j,d in enumerate(lin):
    for ax in axs: ax.scatter(d['lm'],d['ratio'],s=13,color=COL[j],marker=['o','s','^','D','+','x'][j],alpha=.7,label=d['label'])
for ax in axs:
    ax.axhline(1,color='#333333',ls='--',lw=1.2); ax.axhspan(.98,1.02,color='#D6E8DB',alpha=.4)
    ax.set(xlabel='长积分净光均值 / DN',ylabel='响应比 R = 时间比 × 短积分 / 长积分'); ax.grid(alpha=.2)
axs[0].set_title('全部288通道 · 未作锚定归一化'); axs[0].legend(fontsize=8)
axs[1].set(xlim=(4000,53000),ylim=(.94,1.10),title='工程区间放大 · 绿色为±2%参考带')
fig.suptitle('OCR-25F02100 积分时间相对线性度（六组对比）',fontsize=16)
save(fig,'01_六组线性度原始响应比','按N−1000及实际积分时间计算。放大图范围外的点保留在左图和CSV中。±2%仅为本次描述性参考，不是原方案验收要求。')

fig,ax=plt.subplots(figsize=(12,6),layout='constrained')
for j,d in enumerate(lin):ax.scatter(d['lm'],d['norm'],s=13,c=COL[j],alpha=.7,label=f"{d['label']}；锚定中位数={d['k']:.4f}")
ax.axvspan(15000,25000,color='gray',alpha=.1); ax.axvline(8000,color='gray',ls=':'); ax.axhline(1,color='#333',ls='--')
ax.set(xlabel='长积分净光均值 / DN',ylabel='R / 锚定区R中位数',title='参考图风格：六组锚定归一化对比（形状比较）',ylim=(.85,1.25)); ax.legend(fontsize=8); ax.grid(alpha=.2)
save(fig,'02_六组线性度锚定对比','锚定区15000–25000 DN内、长短积分SNR均≥20的通道计算R中位数。8000 DN仅为参考图标线；归一化会移除组间整体偏移，不用于判断绝对线性误差。')

fig,axs=plt.subplots(2,3,figsize=(15,8),layout='constrained')
for ax,d in zip(axs.flat,lin):
    ax.plot(wave,d['lm'],label='长积分实测',color=COL[0]); ax.plot(wave,d['ideal'],ls='--',label='短积分按时间比例放大',color=COL[1])
    ax.set(title=d['label'],xlabel='波长 / nm',ylabel='净光均值 / DN');ax.grid(alpha=.2);ax.legend(fontsize=8)
save(fig,'03_六组光谱实测与理论对比','每条曲线为本条件全部帧的均值，未进行平滑；两次采集非同步，组间灯漂移可能影响响应比。')

fig,axs=plt.subplots(2,1,figsize=(13,8),layout='constrained')
for j,d in enumerate(lin):
    axs[0].plot(wave,(d['ratio']-1)*100,color=COL[j],label=d['label'],lw=1)
    axs[1].plot(d['lm'],(d['raw_ratio']-d['ratio'])*100,'.',color=COL[j],ms=3)
axs[0].axhspan(-2,2,color='green',alpha=.07);axs[0].axhline(0,c='gray',ls='--');axs[0].legend(ncol=3,fontsize=8)
axs[0].set(xlabel='波长 / nm',ylabel='(R−1) / %',title='全部波段的相对线性偏差')
axs[1].set(xlabel='按1000偏置计算的长积分净光 / DN',ylabel='R(偏置0)−R(偏置1000) / 百分点',title='偏置敏感性：不扣1000与扣1000的差别（假设比较）')
for ax in axs:ax.grid(alpha=.2)
save(fig,'04_波长偏差及偏置敏感性','偏置0仅作敏感性对照，不代表另一种同等有效的数据定义。1000偏置经李阳于2026-09-23确认；偏置0仅用于展示遗漏偏置的影响。')

# Repeatability and low-light analysis.
conds=[]; detail=[]; sums=[]; ranges=[]; temporal=[]
for p in sorted((ROOT/'信噪比').glob('*亮值.csv')):
    l=files[p.name]; d=files[p.name.replace('亮值','暗值')]
    assert l['mode']=='L' and d['mode']=='D' and l['t']==d['t']
    v=int(re.search(r'_(\d+)V',p.name)[1]); a=l['a']; dark=d['a']; dm=dark.mean(1); net=a-dm[:,None]
    mean=net.mean(1); sd=net.std(1,ddof=1); ds=dark.std(1,ddof=1)
    snr=mean/sd; cv=sd/abs(mean)*100
    slope,change=drift(net,l['sec']); change_pct=change/abs(mean)*100
    dark_slope,dark_change=drift(dark,d['sec'])
    p2p=np.ptp(net,axis=1)/abs(mean)*100
    # L and D exports both carry +1000 DN (Li Yang, 2026-09-23).
    # Their offsets cancel in L-D; ADC headroom must use L-1000.
    maxraw=(a-1000).max(1); saturated=((a-1000)>=65535).any(1); headroom=maxraw<=.8*65535
    positive=mean>0; basic=positive&(~saturated)&(snr>=20)&(cv<=5)
    rec=positive&(~saturated)&(snr>=50)&(cv<=2)
    # Working candidates: PDF C headroom criterion + explicitly chosen fit-drift definition.
    stable=abs(change_pct)<=2; work=basic&headroom&stable; recommended=rec&headroom&stable
    state=np.where(~positive|saturated,0,np.where(~headroom,1,np.where(~stable,2,np.where(snr<20,3,np.where(snr<50,4,5)))))
    label=f'{v} V / {l["t"]:g} ms'
    integ=np.trapezoid(net,wave,axis=0)/l['t']; rel=(integ/integ.mean()-1)*100
    c=dict(l=l,d=d,v=v,t=l['t'],label=label,mean=mean,sd=sd,dm=dm,ds=ds,snr=snr,cv=cv,
           drift=change_pct,headroom=headroom,basic=basic,work=work,recommended=recommended,state=state,relative=rel)
    conds.append(c)
    for i in range(288):
        detail.append(dict(voltage_V=v,integration_ms=l['t'],channel=i+1,wavelength_nm=wave[i],light_frames=l['n'],dark_frames=d['n'],
          light_mean_DN=a[i].mean(),dark_mean_DN=dm[i],net_mean_DN=mean[i],net_SD_DN=sd[i],dark_SD_DN=ds[i],SNR=snr[i],CV_percent=cv[i],
          net_mean_SE_independent_frames_assumed=float(np.sqrt(sd[i]**2/l['n']+ds[i]**2/d['n'])),
          fit_drift_percent=change_pct[i],peak_to_peak_percent=p2p[i],dark_slope_DN_per_s=dark_slope[i],dark_fit_change_DN=dark_change[i],
          exported_L_max_DN=a[i].max(),light_mean_offset_removed_DN=a[i].mean()-1000,dark_mean_offset_removed_DN=dm[i]-1000,
          raw_max_DN=maxraw[i],saturated=bool(saturated[i]),raw_within_80pct=bool(headroom[i]),
          basic_SNR20=bool(basic[i]),SNR50=bool(rec[i]),working_candidate=bool(work[i]),recommended_candidate=bool(recommended[i])))
    sums.append(dict(condition=label,voltage_V=v,integration_ms=l['t'],light_frames=l['n'],dark_frames=d['n'],duration_s=l['sec'][-1],
        peak_net_DN=mean.max(),median_SNR=float(np.median(snr)),min_SNR=snr.min(),basic_SNR20_channels=int(basic.sum()),SNR50_channels=int(rec.sum()),
        above80pct_channels=int((~headroom).sum()),saturated_channels=int(saturated.sum()),fit_drift_over2pct_channels=int((~stable).sum()),
        working_candidate_channels=int(work.sum()),recommended_candidate_channels=int(recommended.sum()),
        longest_working_interval=longest(work,wave),longest_recommended_interval=longest(recommended,wave),
        spectrum_integral_DN_nm_per_ms=float(integ.mean()),band_integral_fit_drift_percent=float(drift(rel[None,:],l['sec'])[1][0]),
        band_integral_peak_to_peak_percent=float(np.ptp(rel))))
    for kind,mask in [('SNR20_basic',basic),('SNR50_basic',rec),('working_candidate',work),('recommended_candidate',recommended)]:
        for aa,bb,n in intervals(mask,wave): ranges.append(dict(condition=label,criterion=kind,start_nm=aa,end_nm=bb,channels=n))
    for i in range(l['n']):temporal.append(dict(condition=label,timestamp_UTC=l['ts'][i].isoformat(),elapsed_s=l['sec'][i],
                spectral_integral_DN_nm_per_ms=integ[i],relative_to_series_mean_percent=rel[i]))
conds.sort(key=lambda c:(c['v'],c['t']))
export('05_信噪比弱光逐通道.csv',detail);export('06_条件汇总.csv',sums);export('07_连续有效波段.csv',ranges);export('08_逐帧全谱积分序列.csv',temporal)

fig,axs=plt.subplots(1,3,figsize=(16,5),layout='constrained')
for ax,t in zip(axs,[32,64,128]):
    for c in conds:
        if c['t']==t:ax.plot(wave,c['snr'],lw=1,label=f"{c['v']} V",color=COL[[60,63,68,72,76].index(c['v'])])
    ax.axhline(20,c='#C34C4C',ls='--',label='基本门槛20');ax.axhline(50,c='#444',ls=':',label='推荐门槛50')
    ax.set(xlabel='波长 / nm',ylabel='SNR（均值 / 帧间标准差）',title=f'{t} ms',yscale='log',ylim=(5,600));ax.grid(alpha=.2);ax.legend(fontsize=8)
save(fig,'05_各积分时间信噪比','所有帧逐波长统计，未平滑。每组30帧，76 V/32 ms为50帧。扣平均暗谱不改变亮值帧间标准差；暗均值估计不确定度另列于CSV。')

fig,ax=plt.subplots(figsize=(14,6),layout='constrained')
edges=np.r_[wave[0]-(wave[1]-wave[0])/2,(wave[1:]+wave[:-1])/2,wave[-1]+(wave[-1]-wave[-2])/2]
cmap=ListedColormap(['#292D36','#C35B52','#DCAC56','#E2E5E8','#76B5C5','#318060'])
im=ax.pcolormesh(edges,np.arange(11),np.array([c['state'] for c in conds]),cmap=cmap,norm=BoundaryNorm(np.arange(-.5,6.5),6),shading='flat')
ax.set(yticks=np.arange(10)+.5,yticklabels=[c['label'] for c in conds],xlabel='波长 / nm',title='逐通道工作条件筛选（全部波段；不含线性度最终认证）');ax.invert_yaxis()
cb=fig.colorbar(im,ax=ax,ticks=np.arange(6),pad=.02)
cb.ax.set_yticklabels(['非正/数字饱和','原始亮值>80%量程','拟合漂移>2%','SNR<20','20≤SNR<50','SNR≥50'])
save(fig,'06_全波段工作条件图','分类优先级依图例自上而下；码值采用每通道所有帧最大原始亮值。漂移为时间线性拟合首尾变化/净光均值。该图不等同于完成线性度验证。')

fig,axs=plt.subplots(1,2,figsize=(14,5),layout='constrained')
for c in conds:
    if c['t']==64:
        color=COL[[60,63,68,72,76].index(c['v'])]
        axs[0].plot(wave,c['mean'],label=f"{c['v']} V",color=color)
        axs[1].plot(wave,c['cv'],label=f"{c['v']} V",color=color,lw=1)
axs[0].set(xlabel='波长 / nm',ylabel='净光均值 / DN',title='固定64 ms：降电压后的净光响应')
axs[1].set(xlabel='波长 / nm',ylabel='CV / %',title='固定64 ms：逐波长重复性',yscale='log')
axs[1].axhline(5,c='#C34C4C',ls='--');axs[1].axhline(2,c='#444',ls=':')
for ax in axs:ax.legend();ax.grid(alpha=.2)
save(fig,'07_固定64ms弱光响应与CV','电压是光源控制条件，不是亮度。CV与SNR在正响应下互为倒数；CV=5%与SNR=20是同一重复性门槛。')

fig,axs=plt.subplots(1,2,figsize=(14,5),layout='constrained')
improvements=[]
for j,v in enumerate([60,63,68,72,76]):
    short,long=sorted([c for c in conds if c['v']==v],key=lambda c:c['t'])
    gain=long['snr']/short['snr']; response=(long['mean']/long['t'])/(short['mean']/short['t'])
    axs[0].plot(wave,gain,c=COL[j],label=f"{v} V：{short['t']:g}→{long['t']:g} ms",lw=1)
    axs[1].plot(wave,response,c=COL[j],lw=1)
    improvements.append(dict(voltage_V=v,short_ms=short['t'],long_ms=long['t'],median_SNR_gain=float(np.median(gain)),
         basic_added_channels=int(long['basic'].sum()-short['basic'].sum()),median_normalized_response_ratio=float(np.median(response))))
axs[0].axhline(1,c='gray',ls='--');axs[0].legend(fontsize=8);axs[0].set(xlabel='波长 / nm',ylabel='SNR长 / SNR短',title='延长积分时间带来的实测SNR变化')
axs[1].axhline(1,c='gray',ls='--');axs[1].set(xlabel='波长 / nm',ylabel='(净光长/t长) / (净光短/t短)',title='单位积分时间响应比（含光源及暗场变化）')
for ax in axs:ax.grid(alpha=.2)
save(fig,'08_延长积分时间改善','同电压的两组采集非同步。SNR改善受光源波动、噪声和非线性共同影响，不强制拟合平方根时间规律。')
export('09_延长积分时间改善.csv',improvements)

fig,axs=plt.subplots(1,2,figsize=(14,5),layout='constrained')
for c in conds:
    axs[0].plot(wave,c['dm']-1000,label=c['label'],lw=1)
    axs[1].plot(wave,c['ds'],lw=1,label=c['label'])
axs[0].set(xlabel='波长 / nm',ylabel='平均暗值（D−1000）/ DN',title='匹配暗场的平均底值（已去偏置）');axs[0].legend(fontsize=7,ncol=2)
axs[1].set(xlabel='波长 / nm',ylabel='暗值帧间标准差 / DN',title='匹配暗场噪声（不等同于纯读出噪声）')
for ax in axs:ax.grid(alpha=.2)
save(fig,'09_暗场均值与噪声','暗场标准差同时包含读出噪声、暗电流波动和可能的漂移，现有实验无法将其分离。暗值测量时间不与亮值帧一一对应。')

fig,axs=plt.subplots(2,1,figsize=(13,8),layout='constrained')
for c in conds:
    axs[0].plot(c['l']['sec'],c['relative'],label=c['label'],lw=1)
    axs[1].plot(wave,c['drift'],lw=.9)
axs[0].set(xlabel='本组采集起点后的时间 / s',ylabel='全谱积分相对均值变化 / %',title='各组采集期间全谱信号变化');axs[0].legend(ncol=5,fontsize=8)
axs[1].set(xlabel='波长 / nm',ylabel='拟合首尾变化 / %',title='逐波长拟合漂移（不去趋势后重算SNR）');axs[1].axhspan(-2,2,color='green',alpha=.08)
for ax in axs:ax.grid(alpha=.2)
save(fig,'10_采集期间漂移','全谱积分使用真实非等间距波长做梯形积分。漂移判断使用未去趋势序列；该短时间采集不能替代方案中的100帧稳定性检验。')

fig,axs=plt.subplots(1,2,figsize=(14,5),layout='constrained')
ref=next(c for c in conds if c['v']==72 and c['t']==64)
ref_shape=ref['mean']/np.trapezoid(ref['mean'],wave)
shape=[]
for j,c in enumerate([x for x in conds if x['t']==64]):
    y=c['mean']/np.trapezoid(c['mean'],wave)
    axs[0].plot(wave,y,c=COL[j],label=f"{c['v']} V")
    axs[1].plot(wave,(y/ref_shape-1)*100,c=COL[j],lw=1)
    angle=np.degrees(np.arccos(np.clip(np.dot(y,ref_shape)/np.linalg.norm(y)/np.linalg.norm(ref_shape),-1,1)))
    shape.append(dict(voltage_V=c['v'],integration_ms=64,reference_V=72,
        relative_instrument_response=float(np.trapezoid(c['mean'],wave)/np.trapezoid(ref['mean'],wave)),spectral_angle_deg=float(angle),
        normalized_shape_NRMSE_percent=float(np.linalg.norm(y-ref_shape)/np.linalg.norm(ref_shape)*100)))
axs[0].set(xlabel='波长 / nm',ylabel='面积归一化响应 / (1/nm)',title='固定64 ms：测得谱形随电压的变化');axs[0].legend()
axs[1].set(xlabel='波长 / nm',ylabel='相对72 V归一化谱形变化 / %',title='以72 V为参考（全部通道原始亮值≤80%量程）');axs[1].axhline(0,c='gray',ls='--')
for ax in axs:ax.grid(alpha=.2)
save(fig,'11_降电压谱形检查','仅描述仪器测得的响应谱形，采用72 V/64 ms为参考。76 V/64 ms高码值可能引入非线性，未辐射定标，故不能将差异全部归因于灯的真实谱形变化，也不能把相对响应当作亮度比。')
export('10_固定64ms相对谱形.csv',shape)

fig,axs=plt.subplots(1,2,figsize=(14,5),layout='constrained')
for t,marker,color in [(32,'s',COL[0]),(64,'o',COL[2]),(128,'^',COL[3])]:
    cc=[c for c in conds if c['t']==t]
    axs[0].plot([c['v'] for c in cc],[c['basic'].sum() for c in cc],marker=marker,c=color,label=f'{t} ms')
    axs[1].plot([c['v'] for c in cc],[c['work'].sum() for c in cc],marker=marker,c=color,label=f'{t} ms')
for ax in axs:
    ax.axhline(288,c='gray',ls=':');ax.set(xlabel='光源设置电压 / V',ylabel='达标通道数 / 288',xticks=[60,63,68,72,76],ylim=(170,298));ax.grid(alpha=.2);ax.legend()
axs[0].set_title('基本SNR门槛：正响应、无数字饱和、SNR≥20')
axs[1].set_title('再筛选80%量程与拟合漂移≤2%的工作候选')
save(fig,'12_各电压有效通道数','只连接实际测量档位，不表示中间电压经过验证。76 V/64 ms的候选通道减少主要来自高码值余量限制。工作候选尚未经过最终线性度认证。')

# Self-contained HTML report with linked full-resolution local artifacts; Markdown companion.
def table(headers,rows):
    return '<table><thead><tr>'+''.join('<th>'+html.escape(str(x))+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(x))+'</td>' for x in r)+'</tr>' for r in rows)+'</tbody></table>'

mid=[r for r in lr if r['both_SNR20'] and 4000<=r['long_net_mean_DN']<45000]
key_results=[
f"六组已测数据中，长短积分SNR均≥20且长积分净光在4000–45000 DN的{len(mid)}个通道-组数据点，|R−1|最大为{max(abs(r['ratio_minus_one_percent']) for r in mid):.2f}%，均落在±2%参考带内。这是已测点的结果，不是全区间校准认证。",
'在45000 DN以上的已测高码值段，两组5W的R中位数约1.0193和1.0200，即长积分实测较短积分外推低约1.9%和2.0%；低于4000 DN的离散更大。',
'同电压下积分时间加倍，各组逐通道SNR增益中位数为1.51–1.55倍。60 V从64增至128 ms，SNR≥20通道由235增至264。',
'76 V/64 ms全288通道满足SNR≥20，但589.2–740.2 nm的78通道超过80%原始量程；当前条件宜优先比较32 ms的结果。',
'72 V/64 ms有272个工作候选通道，其中最长连续段409.0–878.1 nm；推荐候选最长连续段447.2–878.1 nm。60 V/128 ms推荐候选连续段为474.6–878.1 nm。候选尚不等于完成线性度认证。',
f"固定64 ms，60 V相对72 V的面积归一化谱形角约{shape[0]['spectral_angle_deg']:.2f}°、NRMSE约{shape[0]['normalized_shape_NRMSE_percent']:.1f}%。测得谱形随电压变化，不能把降压视为所有波长同比例衰减；未将变化唯一归因于灯。",
'全部十个条件均无65535数字截顶，但没有一个条件使全部288通道同时通过本次工作候选筛选。不能给出全波段统一通过结论。']
lines=['# OCR-25F02100 室内实验分析\n',
'分析日期：2026-09-22。完整波段305.883–878.092 nm，288通道。原始32个CSV全部保留，未剔除任何帧、未平滑、未插值。\n',
'## 主要发现\n'+''.join('- '+x+'\n' for x in key_results),
'## 数据定义与结论边界\n',
f'- 线性度：12个N模式文件，净光=N−{OFFSET:g}。N已扣暗，不能再减独立暗场。L、D、N均含1000偏置，依据李阳于2026-09-23的确认。\n',
'- 信噪比/弱光：20个L/D文件，组成10个条件。净光帧=L帧−同条件暗均值，不再减1000。每个条件均核对积分时间与波长。\n',
'- 线性度32/64 ms、5W配对各50帧，其余各30帧；信噪比76 V/32 ms亮暗各50帧，其余各30帧。没有100帧条件。\n',
'- 文件64MS-5W-128内部全部为62 ms：本分析用128/62=2.064516，而非2。另一个末尾64的5W组实际为32/64 ms。\n',
'- “3W/4W/5W”仅保留原始组名，未将其解释为实测瓦数。末尾64/128表示该组最大积分时间。\n',
'- 全部波段均报告，不预先裁掉低响应两端。各图可用范围取决于具体条件，不能由峰值或全谱平均SNR替代逐波长判定。\n',
'- 电压是控制档位，未发现各档对应的亮度实测表。只报告相对弱光表现，不给出cd/m²等绝对最低可测亮度。最低60 V仍不是已证明的检测极限。\n',
'- 本次只有五档电压、每档两个积分时间，与实验方案至少六档弱光、每档三个积分时间（SNR实验）和100帧要求不完全一致。\n',
'## 线性度\n',
'R=(t长/t短)×均值短/均值长。R>1表示长积分实测低于短积分外推，但短积分也可能非线性，故R是相对响应比而非绝对校正函数。实际相对理论误差=(1/R−1)×100%。\n',
'以长短积分SNR均≥20、两者净光均值为正的通道汇总。±1%、±2%为描述性参考带，并非原PDF指定验收限。各组只有两个时间点，不能冒充六档积分时间拟合或据此给出可信的R²。不同波长不作为独立重复实验。\n',
'锚定版按15000–25000 DN合格通道R中位数归一化，仅比较曲线形状；其整体偏移已被人为消除。原始比值版才保留组间整体误差。8000 DN是参考图标线，不是本机已确定的噪声界限。\n']
for x in ls: lines.append(f"- {x['group']}：合格{x['qualified_channels']}通道，R中位数{x['median_ratio']:.5f}，|R−1|的95分位{x['p95_absolute_deviation_percent']:.2f}%，锚定中位数{x['anchor_median']:.5f}。\n")
lines += ['\n组内漂移已在逐通道表中保留。长短积分并非同步采集，缺少同步亮度监测，不能将全部偏差唯一归因于探测器。未拟合或应用七阶校正多项式，也不作硬件根因结论。\n',
'## 信噪比与弱光\n',
'SNR=净光均值/亮值帧间样本标准差（ddof=1），CV=标准差/|净光均值|×100%。减固定暗均值不改变帧间标准差。该SNR是当前灯与仪器组合的重复性，不是均值的SNR，不乘√帧数。暗噪声另行报告，不重复加到主SNR分母。\n',
'逐通道表另列净光均值标准误sqrt(sL²/nL+sD²/nD)，线性度另列比值传播标准误；均假设帧独立，不包含系统漂移或暗场失配，因此不作为完整测量不确定度。\n',
'基本通道：正响应、未数字饱和、SNR≥20且CV≤5%；推荐重复性：SNR≥50且CV≤2%。正信号下SNR与CV门槛等价。\n',
'工作候选通道进一步要求：每帧去偏置亮值L−1000≤65535×80%=52428 DN，且线性拟合首尾变化/净光均值的绝对值≤2%。原方案未详细定义漂移，本次明确采用上述拟合定义，并同时提供峰峰变化；两者不混用。N数据无法还原同步原始亮值，不能单凭净光值认证其ADC余量。\n',
'工作候选仍未包含最终线性度认证，不能直接叫作已验证的可靠工作区。采集无数字饱和也不代表没有软饱和。\n']
for x in sums:lines.append(f"- {x['condition']}：SNR≥20共{x['basic_SNR20_channels']}/288，工作候选{x['working_candidate_channels']}/288，推荐候选{x['recommended_candidate_channels']}/288；最长工作候选连续段{x['longest_working_interval']}。\n")
lines+=['\n## 积分时间选择及现阶段结论\n']
for x in improvements:lines.append(f"- {x['voltage_V']} V，{x['short_ms']:g}→{x['long_ms']:g} ms：逐通道SNR增益中位数{x['median_SNR_gain']:.2f}倍，SNR≥20通道增加{x['basic_added_channels']}个。\n")
lines+=['- 在最低已测60 V档，128 ms较64 ms增加SNR达标通道，可用于评估弱波段改善，但仍不能覆盖全部波段的最低门槛。\n',
'- 76 V/64 ms需特别关注高码值通道：SNR很高并不抵消原始亮值超出80%量程的风险。优先比较32 ms结果，具体可用段见条件表。\n',
'- 所有条件均未使全部288通道同时通过本次工作候选筛选时，应报告条件依赖的分段范围，而不是给出单一全波段通过结论。\n',
'- 码值分段结果见04表：其覆盖有限、波长及组间分布不均，本次不强行给出跨条件通用的线性工作码值区。\n',
'- 若需确定绝对弱光极限，应补充实测亮度、最低工程亮度以下档位及更多衰减档；若需正式校正，应确认62 ms异常和同步光源稳定性，并增加同条件积分时间档位。\n',
'## 来源与可复现性\n',
f'- 原始数据目录：{ROOT}\n',
'- 判据来源：灯+光谱仪性能实验.pdf，第3–5页。比值方法与图式参考：IES非线性分析.pdf，第1–2、7–8页及三张参考PNG。参考硬件归因和阈值未移植为本机结论。\n',
'- N/L/D定义：标定上位机V3/doc/sensor/OCR协议-上位机专用.md，第280–284行；偏置：K值计算机制说明.md，第40–50行。\n',
'- 01表记录每个源文件SHA256、帧数、时间、实际积分时间；02–10表提供处理结果。布尔值为逐通道质量标记，未通过的通道仍保留原数值。\n',
'- 重现：使用Python、numpy和matplotlib运行同目录analyze_ocr.py；可用--source指定源目录、--offset改变N模式偏置作敏感性分析。重运行会覆盖本输出目录的计算结果，不改源文件。\n']
(HERE/'分析报告.md').write_text(''.join(lines),encoding='utf-8')
body='<h1>OCR-25F02100 室内实验分析</h1><p class="intro">线性度 · 信噪比 · 弱光性能<br>全部288通道 / 305.88–878.09 nm / 2026-09-22</p>'
body+='<p><a href="分析报告.md">完整方法与结论（Markdown）</a>　<a href="analyze_ocr.py">可复现脚本</a></p>'
body+='<h2>主要发现</h2><ul>'+''.join('<li>'+html.escape(x)+'</li>' for x in key_results)+'</ul>'
body+='<h2>数据与方法</h2><p>N模式按文档默认偏置减1000；L/D模式用亮帧减同条件暗均值。使用全部原始帧，未平滑。62→128 ms组使用真实积分时间比。L、D、N的1000偏置已由李阳于2026-09-23确认。</p>'
body+='<p>“工作候选”满足SNR、正响应、数字饱和、原始亮值80%量程和拟合漂移筛选；尚不等同于完成线性度认证。无实测亮度，不能给出绝对最低可测亮度。</p>'
body+='<h2>线性度汇总（未锚定）</h2>'+table(['组别','合格通道','R中位数','|R−1| 95分位','锚定中位数'],[[x['group'],x['qualified_channels'],f"{x['median_ratio']:.5f}",f"{x['p95_absolute_deviation_percent']:.2f}%",f"{x['anchor_median']:.5f}"] for x in ls])
body+='<h2>信噪比与工作候选范围</h2>'+table(['条件','帧数','SNR≥20','工作候选','推荐候选','最长工作候选连续段'],[[x['condition'],x['light_frames'],x['basic_SNR20_channels'],x['working_candidate_channels'],x['recommended_candidate_channels'],x['longest_working_interval']] for x in sums])
for name,caption in plots: body+=f'<section><h2>{name.replace("_"," ")}</h2><img src="figures/{name}.png"><p>{html.escape(caption)}</p><a href="figures/{name}.svg">矢量SVG</a></section>'
body+='<h2>完整计算表</h2><ul>'+''.join(f'<li><a href="tables/{p.name}">{p.name}</a></li>' for p in sorted(TAB.glob('*.csv')))+'</ul>'
body+='<h2>解释与限制</h2>'+''.join('<p>'+html.escape(x.strip())+'</p>' for x in lines if not x.startswith('#'))
(HERE/'分析报告.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>OCR室内实验分析</title><style>body{max-width:1250px;margin:40px auto;padding:0 28px;font:16px/1.75 "Microsoft YaHei",sans-serif;color:#203040;background:#fafbfc}h1{font-size:32px}h2{margin-top:32px;font-size:22px}.intro{color:#567}table{border-collapse:collapse;width:100%;background:white;font-size:14px}td,th{padding:10px;border-bottom:1px solid #ddd;text-align:left}th{background:#eaf0f5}img{width:100%;background:white}section{margin-top:32px;border-top:1px solid #ddd}a{color:#246c9b}p{overflow-wrap:anywhere}</style>'+body+'</html>',encoding='utf-8')

summary={'files':len(files),'channels':len(wave),'linearity':ls,'conditions':sums,'improvements':improvements,'shape':shape,'plots':len(plots)}
(HERE/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
# Independent spot checks against direct formulas; guards against accidental frame/wavelength-axis mistakes.
for c in conds:
    for i in [0,100,287]:
        aa=c['l']['a'][i]; dd=c['d']['a'][i]
        manual_sd=(sum((float(x)-float(aa.mean()))**2 for x in aa)/(len(aa)-1))**.5
        assert np.isclose(c['snr'][i],(sum(aa)/len(aa)-sum(dd)/len(dd))/manual_sd)
        assert np.isclose(c['cv'][i]*abs(c['snr'][i]),100)
assert len(lin)==6 and len(conds)==10 and len(detail)==2880 and len(lr)==1728
assert sum(x['time_mismatch'] for x in manifest)==1
assert not any(c['l']['a'].max()>=65535 for c in conds)
print(json.dumps(summary,ensure_ascii=False,indent=2))
import subprocess
subprocess.run([sys.executable, '-X', 'utf8', str(HERE/'build_detailed_report.py')], check=True)
