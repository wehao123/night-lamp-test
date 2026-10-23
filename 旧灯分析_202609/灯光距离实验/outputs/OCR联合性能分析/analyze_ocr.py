"""OCR 积分时间、信噪比及弱光联合分析。

运行: python analyze_ocr.py
依赖: numpy matplotlib。首次运行复制原始 CSV 至本脚本旁的 raw/，此后默认使用快照。
所有数值来自未平滑数据；输出 CSV 为 UTF-8 BOM。输入不被修改。
"""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
import html
import zipfile

LOCAL_PACKAGES = Path(__file__).resolve().parent / 'python_packages'
if LOCAL_PACKAGES.exists():
    sys.path.insert(0, str(LOCAL_PACKAGES))

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE = Path(r'C:\Users\haowei\Desktop\夜间水质资料\夜间水质资料')
FULL_SCALE = 65535  # 工程假设：16-bit DN，须以实际设备确认
LIMIT = FULL_SCALE * .8


def export_csv(path, rows):
    if not rows:
        return
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    text = path.read_text(encoding='utf-8-sig')
    meta = dict(line[2:].split(': ', 1) for line in text.splitlines()
                if line.startswith('# ') and ': ' in line)
    rows = list(csv.reader(line for line in text.splitlines() if not line.startswith('#')))
    headers = rows[0]
    channels = [r for r in rows if r[0].startswith('CH_')]
    t = np.array(next(r[2:] for r in rows if r[0] == 'IntegrationTime_ms'), float)
    modes = set(next(r[2:] for r in rows if r[0] == 'CaptureMode'))
    a = np.array([r[2:] for r in channels], float)
    w = np.array([r[1] for r in channels], float)
    stamps = headers[2:]
    from datetime import datetime
    times = np.array([(datetime.fromisoformat(s) - datetime.fromisoformat(stamps[0])).total_seconds()
                      for s in stamps])
    assert a.shape == (288, len(t)) and np.all(np.isfinite(a)), path
    assert np.all(np.diff(w) > 0) and np.all(np.diff(times) > 0), path
    assert len(set(t)) == 1, f'组内积分时间变化: {path}'
    return dict(path=path, a=a, w=w, t=float(t[0]), modes=modes, times=times,
                stamps=stamps, meta=meta)


def intervals(w, mask):
    ix = np.flatnonzero(mask)
    if len(ix) == 0:
        return '无'
    groups = np.split(ix, np.flatnonzero(np.diff(ix) != 1) + 1)
    return '; '.join(f'{w[g[0]]:.2f}–{w[g[-1]]:.2f}' for g in groups)


def slope_span(a, times):
    x = times-times.mean()
    return (a @ x)/(x @ x)*(times[-1]-times[0])


def save(fig, name, out):
    fig.savefig(out / f'{name}.png', dpi=175, bbox_inches='tight')
    fig.savefig(out / f'{name}.svg', bbox_inches='tight')
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--n-offset', type=float, default=1000,
                        help='N导出码值中仍保留的固定偏置；默认按协议说明1000，若证实导出已去偏置则设0')
    args = parser.parse_args()
    for folder in ('raw/snr', 'raw/linearity', 'figures', 'tables', 'references'):
        (ROOT/folder).mkdir(parents=True, exist_ok=True)
    for src, dest in [('信噪比', 'snr'), ('二代OCR模组线性度', 'linearity')]:
        target = ROOT/'raw'/dest
        if not list(target.glob('*.csv')):
            for p in (args.source/src).glob('*.csv'):
                shutil.copy2(p, target/p.name)
    refpaths = [args.source/'采集软件开发文档/01-接口控制文档ICD.md',
        args.source/'标定上位机V3/标定上位机V3/doc/sensor/OCR协议-上位机专用.md',
        args.source/'标定上位机V3/标定上位机V3/doc/单通道Rrs比对-功能说明书.md']
    for rp in refpaths:
        if rp.exists() and not (ROOT/'references'/rp.name).exists():
            shutil.copy2(rp,ROOT/'references'/rp.name)
    fonts = {f.name for f in font_manager.fontManager.ttflist}
    plt.rcParams['font.sans-serif'] = [f for f in ['Microsoft YaHei', 'SimHei', 'Noto Sans CJK SC', 'DejaVu Sans'] if f in fonts]
    plt.rcParams.update({'axes.unicode_minus': False, 'font.size': 10, 'axes.spines.top': False,
                         'axes.spines.right': False, 'axes.grid': True, 'grid.alpha': .2})
    figdir, tabdir = ROOT/'figures', ROOT/'tables'
    manifest, records = [], {}
    for p in sorted((ROOT/'raw').rglob('*.csv')):
        r = read_csv(p)
        records[p.name] = r
        manifest.append(dict(file=str(p.relative_to(ROOT)), sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                             frames=r['a'].shape[1], channels=len(r['w']), time_ms=r['t'],
                             mode=','.join(sorted(r['modes'])), first_timestamp=r['stamps'][0],
                             last_timestamp=r['stamps'][-1], duration_s=r['times'][-1],
                             min_DN=r['a'].min(), max_DN=r['a'].max(),
                             count_at_or_above_65535=int((r['a'] >= FULL_SCALE).sum())))
    assert len(manifest) == 32, f'预期32个CSV，实得{len(manifest)}'
    export_csv(tabdir/'01_input_manifest.csv', manifest)
    groups = {}
    for p in sorted((ROOT/'raw/snr').glob('*亮值.csv')):
        l = records[p.name]
        d = records[p.name.replace('亮值', '暗值')]
        v, nominal_t = map(int, re.search(r'_(\d+)V-(\d+)MS', p.name).groups())
        assert l['t'] == d['t'] == nominal_t and np.array_equal(l['w'], d['w'])
        assert l['modes'] == {'L'} and d['modes'] == {'D'}
        a, da, w = l['a'], d['a'], l['w']
        dm, ds = da.mean(1), da.std(1, ddof=1)
        net = a-dm[:, None]
        mean, sd = net.mean(1), net.std(1, ddof=1)
        snr = np.divide(mean, sd, out=np.full_like(mean, np.nan), where=sd > 0)
        cv = np.divide(100*sd, np.abs(mean), out=np.full_like(mean, np.nan), where=mean != 0)
        drift = slope_span(net, l['times'])/np.where(mean > 0, mean, np.nan)*100
        block = (net[:, -5:].mean(1)-net[:, :5].mean(1))/np.where(mean > 0, mean, np.nan)*100
        rawmax = a.max(1)
        base = (mean > 0) & (rawmax <= LIMIT) & (np.abs(drift) <= 2)
        core = (w >= 420) & (w <= 700)
        ext = (w > 700) & (w <= 720)
        groups[v, nominal_t] = dict(l=l, d=d, w=w, net=net, mean=mean, sd=sd, ds=ds, dm=dm,
            snr=snr, cv=cv, drift=drift, block=block, rawmax=rawmax, base=base,
            core=core, ext=ext,
            # 独立帧假设下均值差的标准误，仅供诊断，不作为最终置信区间
            sem=np.sqrt(sd**2/a.shape[1]+ds**2/da.shape[1]))
    keys = sorted(groups)
    summary, channelrows, frame_rows = [], [], []
    for key in keys:
        v,t = key
        g = groups[key]; w=g['w']; c=g['core']; e=g['ext']
        ok20=g['base'] & (g['snr'] >= 20); ok50=g['base'] & (g['snr'] >= 50)
        summary.append(dict(voltage_label_V=v, integration_ms=t, light_frames=g['net'].shape[1],
            dark_frames=g['d']['a'].shape[1], duration_s=g['l']['times'][-1],
            net_peak_DN=g['mean'].max(), peak_wavelength_nm=w[g['mean'].argmax()],
            raw_max_DN=g['rawmax'].max(), dark_mean_median_DN=np.median(g['dm']),
            dark_sd_median_DN=np.median(g['ds']), core_SNR_median=np.median(g['snr'][c]),
            core_SNR_min=np.min(g['snr'][c]), core_SNR_ge20_pct=100*np.mean(g['snr'][c]>=20),
            core_SNR_ge50_pct=100*np.mean(g['snr'][c]>=50),
            core_joint20_pct=100*np.mean(ok20[c]), core_joint50_pct=100*np.mean(ok50[c]),
            core_joint20_intervals_nm=intervals(w,ok20 & c), core_joint50_intervals_nm=intervals(w,ok50 & c),
            extension_joint20_pct=100*np.mean(ok20[e]), extension_joint50_pct=100*np.mean(ok50[e]),
            core_abs_drift_p95_pct=np.nanpercentile(np.abs(g['drift'][c]),95),
            core_above80pct_channels=int((g['rawmax'][c]>LIMIT).sum())))
        for j in range(len(w)):
            channelrows.append(dict(voltage_label_V=v,integration_ms=t,channel=j+1,wavelength_nm=w[j],
                mean_net_DN=g['mean'][j], light_temporal_sd_DN=g['sd'][j],dark_mean_DN=g['dm'][j],
                dark_temporal_sd_DN=g['ds'][j], mean_difference_SE_independent_frames=g['sem'][j],
                SNR=g['snr'][j], CV_pct=g['cv'][j], fitted_span_drift_pct=g['drift'][j],
                first_last5_change_pct=g['block'][j], dark_fitted_span_DN=slope_span(g['d']['a'],g['d']['times'])[j],
                raw_max_DN=g['rawmax'][j],joint20_without_linearity=bool(ok20[j]),joint50_without_linearity=bool(ok50[j])))
        series=g['net'][c].sum(0); norm=series/series.mean()
        med=np.median(series); mad=np.median(np.abs(series-med)); flags=np.abs(series-med)>6*1.4826*mad if mad>0 else np.zeros(len(series),bool)
        for i in range(len(series)):
            frame_rows.append(dict(voltage_label_V=v,integration_ms=t,frame=i+1,timestamp=g['l']['stamps'][i],
                elapsed_s=g['l']['times'][i],core_sum_DN_channel=series[i],relative_core_sum=norm[i],
                six_MAD_flag=bool(flags[i]),action='保留原始帧；标记仅供核查'))
    export_csv(tabdir/'02_condition_summary.csv',summary)
    export_csv(tabdir/'03_per_channel_metrics.csv',channelrows)
    export_csv(tabdir/'04_frame_stability.csv',frame_rows)

    # 1: 64ms共同曝光下的强度及谱形
    fig,ax=plt.subplots(1,2,figsize=(13,4.6))
    for v in [60,63,68,72,76]:
        g=groups[v,64]; w=g['w']; s=g['mean']
        ax[0].plot(w,s,label=f'{v}V'); ax[1].plot(w,s/s.max(),label=f'{v}V')
    for a in ax: a.set(xlabel='波长 / nm',xlim=(305,880)); a.legend()
    ax[0].set(ylabel='平均净信号 / DN',title='固定64 ms：五个亮度档的净光谱')
    ax[1].set(ylabel='各自峰值归一化',title='谱形比较：电压不是统一的光谱衰减系数')
    save(fig,'01_64ms_net_spectra',figdir)
    # 2: all SNR
    fig,axes=plt.subplots(2,3,figsize=(15,8),sharex=True,sharey=True)
    for a,v in zip(axes.flat,[60,63,68,72,76]):
        for key in keys:
            if key[0]==v:
                g=groups[key];a.plot(w,g['snr'],label=f'{key[1]} ms')
        a.axhline(20,color='red',ls='--');a.axhline(50,color='green',ls=':')
        a.set(title=f'{v}V亮度档',xlabel='波长 / nm',ylabel='单帧时间SNR',ylim=(0,500));a.legend()
        a.axvspan(420,700,color='grey',alpha=.06)
    axes.flat[-1].axis('off');axes.flat[-1].text(.05,.7,'虚线：SNR=20\n点线：SNR=50\n灰底：420–700 nm\n未平滑、未剔除帧\n包含光源与仪器共同波动',transform=axes.flat[-1].transAxes)
    fig.tight_layout();save(fig,'02_snr_spectra',figdir)
    # 3: heatmap continuous and classification
    fig,ax=plt.subplots(2,1,figsize=(13,8),sharex=True)
    vals=np.array([groups[k]['snr'] for k in keys])
    im=ax[0].imshow(np.clip(vals,0,300),aspect='auto',extent=[0,len(w),len(keys),0],vmin=0,vmax=300)
    fig.colorbar(im,ax=ax[0],label='SNR（色标上限300）')
    codes=[]
    for k in keys:
        g=groups[k];z=np.where(g['snr']>=50,2,np.where(g['snr']>=20,1,0))
        z=np.where(g['base'],z,0);codes.append(z)
    from matplotlib.colors import ListedColormap, BoundaryNorm
    im2=ax[1].imshow(codes,aspect='auto',extent=[0,len(w),len(keys),0],cmap=ListedColormap(['#dddddd','#e4b854','#319575']),vmin=-.5,vmax=2.5)
    cb=fig.colorbar(im2,ax=ax[1],ticks=[0,1,2]);cb.ax.set_yticklabels(['未通过','≥20','≥50'])
    for a in ax:
        a.set_yticks(np.arange(len(keys))+.5,[f'{v}V / {t}ms' for v,t in keys]);a.grid(False)
        ticks=np.array([np.argmin(abs(w-x)) for x in [306,350,420,500,600,700,720,800,878]])
        a.set_xticks(ticks+.5,[f'{w[x]:.0f}' for x in ticks])
    ax[0].set_title('全谱SNR分布（横轴按通道排列，标注实际波长）')
    ax[1].set(title='联合筛选：正响应 + 原始DN≤80%满量程 + 拟合漂移≤2% + SNR；尚未包含线性',xlabel='波长 / nm')
    fig.tight_layout();save(fig,'03_snr_and_validity_map',figdir)
    # 4: dark noise and signal noise
    fig,ax=plt.subplots(1,3,figsize=(16,4.5))
    for k in keys:
        g=groups[k];label=f'{k[0]}V/{k[1]}ms'
        ax[0].plot(w,g['dm'],label=label);ax[1].plot(w,g['ds'],label=label);ax[2].plot(w,g['sd'],alpha=.7,label=label)
    for a in ax:a.set(xlabel='波长 / nm')
    ax[0].set(title='暗场平均值',ylabel='DN');ax[1].set(title='暗场时间标准差',ylabel='DN');ax[2].set(title='亮场时间标准差',ylabel='DN')
    ax[2].legend(fontsize=7,ncol=2);fig.tight_layout();save(fig,'04_dark_and_light_noise',figdir)
    # 5: temporal profiles
    fig,axes=plt.subplots(2,5,figsize=(18,7))
    for a,k in zip(axes.flat,keys):
        g=groups[k];c=g['core'];x=g['l']['times'];y=g['net'][c].sum(0);y=100*(y/y.mean()-1)
        a.plot(x,y,'o-',ms=3);a.plot(x,np.polyval(np.polyfit(x,y,1),x),'--',color='black')
        a.set(title=f'{k[0]}V / {k[1]}ms',xlabel='组内时间 / s',ylabel='核心波段总响应偏离均值 / %')
    fig.tight_layout();save(fig,'05_temporal_stability',figdir)
    # 6-8: paired linearity and SNR improvement
    pair_summary,pair_rows=[],[]
    fig6,axes6=plt.subplots(2,3,figsize=(15,8))
    fig7,axes7=plt.subplots(2,3,figsize=(15,8))
    fig8,axes8=plt.subplots(2,3,figsize=(15,8))
    pair_checks={}
    for idx,v in enumerate([60,63,68,72,76]):
        ts=sorted(t for vv,t in keys if vv==v);lo,hi=groups[v,ts[0]],groups[v,ts[1]]
        ratio=(hi['mean']/ts[1])/(lo['mean']/ts[0]);err=100*(ratio-1)
        eligible=(lo['snr']>=50)&(hi['snr']>=50)&lo['base']&hi['base']
        c=lo['core'];valid=eligible & c; passed=eligible&(abs(err)<=2)
        pair_checks[v]=dict(eligible=eligible,passed=passed,error=err)
        gain=hi['snr']/lo['snr']
        # 传播独立帧均值标准误；存在相关/漂移时不得视为严格置信区间。
        se=abs(ratio)*np.sqrt((lo['sem']/lo['mean'])**2+(hi['sem']/hi['mean'])**2)*100
        pair_summary.append(dict(voltage_label_V=v,short_ms=ts[0],long_ms=ts[1],core_channels=int(c.sum()),
            qualified_core_channels=int(valid.sum()), qualified_core_pct=100*np.mean(eligible[c]),
            median_error_pct=np.median(err[valid]) if valid.any() else np.nan,
            p95_absolute_error_pct=np.percentile(abs(err[valid]),95) if valid.any() else np.nan,
            maximum_absolute_error_pct=max(abs(err[valid])) if valid.any() else np.nan,
            pass_within_qualified_pct=100*np.mean(abs(err[valid])<=2) if valid.any() else np.nan,
            joint_linearity_pass_core_pct=100*np.mean(passed[c]),
            qualified_pass_intervals_nm=intervals(w,passed&c),
            median_SNR_gain_core=np.median(gain[c])))
        for j in range(len(w)):
            pair_rows.append(dict(voltage_label_V=v,short_ms=ts[0],long_ms=ts[1],wavelength_nm=w[j],
                short_net_DN=lo['mean'][j],long_net_DN=hi['mean'][j],
                long_over_short_normalized_ratio=ratio[j],error_pct=err[j],
                ratio_SE_pct_independent_frames=se[j],eligible=bool(eligible[j]),pass_2pct=bool(passed[j]),SNR_gain=gain[j]))
        a=axes6.flat[idx]
        a.plot(w,lo['mean']/ts[0],label=f'{ts[0]}ms');a.plot(w,hi['mean']/ts[1],label=f'{ts[1]}ms',ls='--')
        a.set(title=f'{v}V：净信号/积分时间',xlabel='波长 / nm',ylabel='DN/ms');a.legend()
        a=axes7.flat[idx];a.scatter(hi['mean'],err,s=8,color='#bbbbbb',label='全部通道')
        a.scatter(hi['mean'][eligible],err[eligible],s=10,label='SNR、DN余量及漂移筛选后')
        a.axhline(2,color='red',ls='--');a.axhline(-2,color='red',ls='--');a.axhline(0,color='black',lw=.7)
        a.set(title=f'{v}V：{ts[0]}→{ts[1]}ms',xlabel='长积分时间平均净DN',ylabel='归一化相对偏差 / %',ylim=(-12,12));a.legend(fontsize=7)
        a=axes8.flat[idx];a.plot(w,gain);a.axhline(1,color='black',ls='--');a.set(title=f'{v}V：长/短积分时间SNR',xlabel='波长 / nm',ylabel='SNR提升倍数',ylim=(0,4))
    for f,axes,name in [(fig6,axes6,'06_time_normalized_spectra'),(fig7,axes7,'07_linearity_error_vs_DN'),(fig8,axes8,'08_snr_gain')]:
        axes.flat[-1].axis('off');f.tight_layout();save(f,name,figdir)
    export_csv(tabdir/'05_paired_linearity_summary.csv',pair_summary)
    export_csv(tabdir/'06_paired_linearity_channels.csv',pair_rows)
    # 9: raw full scale headroom
    fig,ax=plt.subplots(figsize=(11,4.6));ax.bar([f'{v}V\n{t}ms' for v,t in keys],[groups[k]['rawmax'].max() for k in keys])
    ax.axhline(LIMIT,color='red',ls='--',label=f'80%满量程={LIMIT:.0f}（16-bit假设）');ax.axhline(FULL_SCALE,color='black',ls=':')
    ax.set(ylabel='全谱全部帧最大原始DN',title='原始码值余量：不能用扣暗后DN判断满量程');ax.legend();save(fig,'09_raw_DN_headroom',figdir)
    # 10: fixed 64 ms weak light panel, measured levels only
    fig,ax=plt.subplots(1,2,figsize=(13,4.8)); voltages=[60,63,68,72,76]
    for target in [420,450,550,650,700,720]:
        j=np.argmin(abs(w-target));ax[0].plot(voltages,[groups[v,64]['snr'][j] for v in voltages],'o-',label=f'{w[j]:.1f}nm')
    for a in ax:a.set(xlabel='调光电压档 / V（非实测亮度）');a.set_xticks(voltages)
    ax[0].set(ylabel='SNR',title='固定64ms：各波长在不同亮度档的表现');ax[0].axhline(20,color='red',ls='--');ax[0].axhline(50,color='green',ls=':');ax[0].legend(fontsize=8,ncol=2)
    for threshold in [20,50]:
        pct=[100*np.mean((groups[v,64]['base']&(groups[v,64]['snr']>=threshold))[groups[v,64]['core']]) for v in voltages]
        ax[1].plot(voltages,pct,'o-',label=f'SNR≥{threshold} + DN余量 + 漂移')
    ax[1].set(ylabel='420–700nm通过通道比例 / %',title='弱光可用覆盖（尚未包含线性）',ylim=(0,105));ax[1].legend(fontsize=8)
    fig.tight_layout();save(fig,'10_weak_light_64ms',figdir)
    # 11: 专项N数据：只做偏置敏感性诊断，不声称已扣暗。
    fig,axes=plt.subplots(2,3,figsize=(15,8));nrows=[];nsummary=[];nprimary=[]
    fig14,axes14=plt.subplots(2,3,figsize=(15,8))
    fig15,axes15=plt.subplots(2,3,figsize=(15,8))
    for i,(end,level) in enumerate([(64,x) for x in [3,4,5]]+[(128,x) for x in [3,4,5]]):
        files=[r for r in records.values() if r['path'].parent.name=='linearity' and re.search(fr'-{level}W-{end}\.csv$',r['path'].name,re.I)]
        assert len(files)==2
        lo,hi=sorted(files,key=lambda r:r['t']);assert lo['modes']==hi['modes']=={'N'}
        sm,hm=lo['a'].mean(1),hi['a'].mean(1);a=axes.flat[i]
        for offset in [0,1000]:
            denom=hm-offset;valid=(sm>offset)&(denom>0)
            er=np.full(len(w),np.nan);er[valid]=100*((denom[valid]/hi['t'])/((sm[valid]-offset)/lo['t'])-1)
            a.scatter(hm[valid],er[valid],s=8,label=f'假设统一减{offset} DN')
            for j in range(len(w)):
                nrows.append(dict(group_max_ms=end,peak_label=f'{level}W',short_file=lo['path'].name,long_file=hi['path'].name,
                    actual_short_ms=lo['t'],actual_long_ms=hi['t'],assumed_offset_DN=offset,wavelength_nm=w[j],
                    short_export_mean_DN=sm[j],long_export_mean_DN=hm[j],normalized_error_pct=er[j],
                    interpretation='偏置敏感性诊断；N模式导出规则未确认，不用于验收'))
        a.set(title=f'{level}万 / {end}ms组；实测{lo["t"]:g}→{hi["t"]:g}ms',xlabel='长积分导出均值DN',ylabel='归一化偏差 / %',ylim=(-15,15))
        a.axhline(2,color='red',ls='--');a.axhline(-2,color='red',ls='--');a.legend(fontsize=7)
        a.text(.02,.03,'纵轴放大至±15%；全部数值见CSV',transform=a.transAxes,fontsize=7)
        sl,sh=sm-args.n_offset,hm-args.n_offset
        snl=sl/lo['a'].std(1,ddof=1);snh=sh/hi['a'].std(1,ddof=1)
        er=100*((sh/hi['t'])/(sl/lo['t'])-1)
        dl=100*slope_span(lo['a'],lo['times'])/sl;dh=100*slope_span(hi['a'],hi['times'])/sh
        eligible=(sl>0)&(sh>0)&(snl>=50)&(snh>=50)&(abs(dl)<=2)&(abs(dh)<=2)
        c=(w>=420)&(w<=700);valid=eligible&c
        nsummary.append(dict(group_max_ms=end,peak_label=f'{level}W',actual_short_ms=lo['t'],actual_long_ms=hi['t'],
            assumed_remaining_offset_DN=args.n_offset,qualified_core_channels=int(valid.sum()),
            median_error_pct=np.median(er[valid]) if valid.any() else np.nan,
            absolute_error_p95_pct=np.percentile(abs(er[valid]),95) if valid.any() else np.nan,
            maximum_absolute_error_pct=max(abs(er[valid])) if valid.any() else np.nan,
            pass_within_qualified_pct=100*np.mean(abs(er[valid])<=2) if valid.any() else np.nan,
            qualified_net_DN_min=sh[valid].min() if valid.any() else np.nan,
            qualified_net_DN_max=sh[valid].max() if valid.any() else np.nan,
            note='条件性结果：假定导出仍含指定偏置。无原始亮暗无法核验ADC余量，不作全范围验收。'))
        for j in range(len(w)):
            nprimary.append(dict(group_max_ms=end,peak_label=f'{level}W',wavelength_nm=w[j],
                short_net_DN=sl[j],long_net_DN=sh[j],short_snr=snl[j],long_snr=snh[j],
                short_fitted_drift_pct=dl[j],long_fitted_drift_pct=dh[j],normalized_error_pct=er[j],
                eligible=bool(eligible[j]),pass2pct=bool(eligible[j] and abs(er[j])<=2),
                assumed_remaining_offset_DN=args.n_offset))
        a=axes14.flat[i];a.scatter(sh,er,s=7,color='#bbbbbb',label='全部通道')
        a.scatter(sh[eligible],er[eligible],s=8,label='SNR≥50且漂移≤2%')
        a.axhline(2,color='red',ls='--');a.axhline(-2,color='red',ls='--');a.axhline(0,color='black',lw=.6)
        a.set(title=f'{level}万/{end}ms组：减{args.n_offset:g}DN',xlabel='长积分时间去偏置DN',ylabel='归一化偏差 / %',ylim=(-8,8));a.legend(fontsize=7)
        a=axes15.flat[i];a.plot(w,sl/lo['t'],label=f'{lo["t"]:g}ms');a.plot(w,sh/hi['t'],'--',label=f'{hi["t"]:g}ms')
        a.set(title=f'{level}万/{end}ms组：减{args.n_offset:g}DN',xlabel='波长 / nm',ylabel='去偏置信号 / 积分时间（DN/ms）');a.legend()
    fig.tight_layout();save(fig,'11_N_mode_offset_sensitivity',figdir);export_csv(tabdir/'07_N_mode_sensitivity.csv',nrows)
    fig14.tight_layout();save(fig14,'14_N_mode_conditional_linearity',figdir)
    fig15.tight_layout();save(fig15,'15_N_mode_time_normalized',figdir)
    export_csv(tabdir/'09_N_mode_conditional_summary.csv',nsummary)
    export_csv(tabdir/'10_N_mode_conditional_channels.csv',nprimary)
    # 12: per wavelength error, no channel selection hidden
    fig,axes=plt.subplots(2,3,figsize=(15,8))
    for a,v in zip(axes.flat,voltages):
        p=pair_checks[v];a.plot(w,p['error'],color='#bbbbbb');a.scatter(w[p['eligible']],p['error'][p['eligible']],s=7)
        a.axhline(2,color='red',ls='--');a.axhline(-2,color='red',ls='--')
        a.set(title=f'{v}V：灰色全部，蓝色可评价通道',xlabel='波长 / nm',ylabel='归一化偏差 / %',ylim=(-12,12))
    axes.flat[-1].axis('off');fig.tight_layout();save(fig,'12_linearity_error_vs_wavelength',figdir)
    # 13: dark frame stability, all channels retained in detailed CSV.
    fig,axes=plt.subplots(2,5,figsize=(18,7))
    for a,k in zip(axes.flat,keys):
        g=groups[k];c=g['core'];x=g['d']['times'];y=g['d']['a'][c].mean(0)
        y=y-y.mean()
        a.plot(x,y,'o-',ms=3);a.plot(x,np.polyval(np.polyfit(x,y,1),x),'--',color='black')
        a.set(title=f'{k[0]}V / {k[1]}ms',xlabel='暗场组内时间 / s',ylabel='核心通道平均暗值偏移 / DN')
    fig.tight_layout();save(fig,'13_dark_temporal_stability',figdir)
    # Combined selection avoids certifying excluded/noisy wavelengths.
    recommendations=[]
    for k in keys:
        v,t=k;g=groups[k];p=pair_checks[v];c=g['core'];e=g['ext']
        for threshold in [20,50]:
            ok=g['base']&(g['snr']>=threshold)&p['passed']
            recommendations.append(dict(voltage_label_V=v,integration_ms=t,SNR_threshold=threshold,
                core_qualified_pct=100*np.mean(ok[c]),extension_qualified_pct=100*np.mean(ok[e]),
                core_intervals_nm=intervals(w,ok&c),extension_intervals_nm=intervals(w,ok&e),
                whole_core_pass=bool(np.all(ok[c])),
                note='包含成对线性筛选；线性评价要求长短两组SNR均≥50。未证明可跨亮度/时间外推。'))
    export_csv(tabdir/'08_joint_working_range.csv',recommendations)
    # Snapshot integrity and independent consistency checks.
    assert np.allclose(groups[60,64]['sd'],groups[60,64]['l']['a'].std(1,ddof=1))
    for g in groups.values():
        positive=g['mean']>0
        assert np.allclose(g['cv'][positive],100/g['snr'][positive])
        assert np.allclose(g['net'].mean(1),g['l']['a'].mean(1)-g['d']['a'].mean(1))
    # Write human-readable results, methods, limits, and exact run instructions.
    lines=['# OCR积分时间响应 信噪比与弱光性能联合分析','',
      '## 分析范围与结论边界','',
      '本次分析32个CSV：10组配对亮暗数据（20个文件）及6对专项线性数据（12个文件）。分析使用同一探头25F02100。原始输入已复制到raw目录并记录SHA-256，脚本默认使用该快照。',
      '调光电压为亮度档标签，不是参考板亮度值，也不假定其与亮度成正比。亮度档之间可能存在谱形变化；不同积分时间仅在同一亮度档内配对。',
      '主评价420–700 nm，700–720 nm单列。所有阈值来自项目方案的建议值，非已冻结验收标准。未测增益变量。',
      '现有数据支持成对积分时间一致性及短时重复性评价，不能给出绝对最低可测亮度、完整积分时间上限、全动态范围线性或硬件噪声归因。','',
      '## 处理与判据','',
      '- 净帧=亮场帧−同条件暗场平均光谱。亮暗不是同步帧，不做逐帧随机配对；暗场为探头遮光还是关灯背景仍需实验记录确认。',
      '- 逐波长均值与样本标准差（ddof=1），SNR=净均值/亮场时间标准差，CV=100×标准差/|净均值|。净信号为正时CV=100/SNR，二者不作为独立证据。',
      '- 不平滑、不插值、不截断负信号、不自动删除异常帧；核心波段总响应以6倍MAD标记疑似异常，保留全部帧计算。',
      '- 暗场均值误差另给出独立帧假设下的均值差标准误。相邻帧可能相关，故不将其包装为严格置信区间；不直接将SNR乘√N。',
      '- 漂移定义为亮场组内时间线性拟合的首尾变化量/净均值，阈值为绝对值≤2%。同时导出首尾5帧均值差；实际只有30或50帧，不等同于方案的100帧测试。',
      '- 工作余量按原始DN最大值≤0.8×65535=52428筛选，16-bit满量程须以设备确认。此为保守工作余量，非物理饱和起点。',
      '- 积分时间偏差δ=100×[(长净均值/长时间)/(短净均值/短时间)−1]；负值表示长曝光归一化响应较低。每档两个点，不报告两点带截距拟合R²。',
      '- 线性可评价通道要求两组SNR均≥50、正响应、DN余量和漂移通过；其上判断|δ|≤2%。未通过可评价条件的通道不直接判成非线性。偏差包含潜在光源变化和暗场失配，不单独证明探头非线性。',
      '- 有效区间按连续实测通道输出，保留中间断点；通道覆盖率不是波长长度加权比例，不用中位数代替逐波长判定。','',
      '## 各条件实测概览','',
      '|调光档|积分时间ms|亮/暗帧数|净峰值DN|原始最大DN|核心SNR中位数|核心SNR最小值|SNR≥20覆盖%|联合≥20覆盖%|',
      '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for s in summary:
        lines.append(f'|{s["voltage_label_V"]}V|{s["integration_ms"]}|{s["light_frames"]}/{s["dark_frames"]}|{s["net_peak_DN"]:.0f}|{s["raw_max_DN"]:.0f}|{s["core_SNR_median"]:.1f}|{s["core_SNR_min"]:.1f}|{s["core_SNR_ge20_pct"]:.1f}|{s["core_joint20_pct"]:.1f}|')
    lines += ['', '联合≥20覆盖同时要求正响应、原始DN余量和漂移，此表未加入线性筛选；最终合并结果见表08。', '',
      '## 成对积分时间结果','',
      '|调光档|时间对ms|可评价核心通道数|偏差中位数%|绝对偏差P95%|绝对偏差最大%|可评价通道内±2%通过率%|核心SNR提升中位数|',
      '|---|---|---:|---:|---:|---:|---:|---:|']
    for s in pair_summary:
        lines.append(f'|{s["voltage_label_V"]}V|{s["short_ms"]}/{s["long_ms"]}|{s["qualified_core_channels"]}/{s["core_channels"]}|{s["median_error_pct"]:.2f}|{s["p95_absolute_error_pct"]:.2f}|{s["maximum_absolute_error_pct"]:.2f}|{s["pass_within_qualified_pct"]:.1f}|{s["median_SNR_gain_core"]:.2f}|')
    lines += ['', '## 工程解释','',
      '1. 五组延长积分时间后的核心波段SNR中位提升倍数见上表。选参必须同时检查强信号余量和弱波段质量，不能单凭峰值或SNR中位数。',
      '2. 76V–64ms全谱最大原始DN为60729，超过暂定80%满量程工作线。未达到65535不能证明不存在提前响应压缩。按逐波长处理可保留其他合格通道，但不推荐整条光谱无条件使用。',
      '3. 最低可用亮度仅能在已测电压档及已测积分时间下描述。没有L(cd/m²)、预期最低工程亮度及更弱档位数据，不能计算绝对Lmin，也不能判断本次最低档已接近探测极限。',
      '4. 不同亮度档的比较包含本次光源光谱分布。图01先检查峰值归一化谱形，不能把不同电压下的DN变化全部归因于探头。',
      '5. 暗场时间标准差与亮场时间标准差分别报告。暗场均值不是噪声幅度，暗均值随时间变化也不能在无温度、偏置记录时直接归因为暗电流。',
      '6. 未证明所有目标波长同时满足指标时，不输出一个无条件的最佳曝光。表08给出逐档合并线性后的连续有效区间；未评价通道不能当作已通过。','',
      '## 专项线性N模式数据','',
      '末尾64/128由采集者确认是组内最大积分时间，3W/4W/5W为目标峰值档。按照实际积分时间配对，64MS-5W-128文件内部所有帧为62ms，故使用128/62倍率并保留命名异常。',
      '用户说明这些数字已做过暗电流处理，但对是否已减1000不确定。已查阅本地软件资料：OCR协议-上位机专用.md将N定义为“采集减去暗值的码值”，L/D为亮/暗值；单通道Rrs比对-功能说明书.md第135–139行说明OCR原始DN通常含1000偏置，比值计算前减去；01-接口控制文档ICD.md第304–310行给出(DN−dn_offset)×K/T，dn_offset典型1000。原文快照保留在references。',
      f'“自动扣暗”与“去除固定偏置”不同。按上述文档，N模式主诊断暂设剩余偏置{args.n_offset:g}DN，计算S=N−偏置；本次CSV是否在导出时已再次去偏置，尚无直接代码/日志佐证，所以这是条件性结果，不能宣称已确证。图11保留减0/减1000两种结果，图14/15和表09/10按所设偏置分析。如果导出已去偏置，以--n-offset 0重算。',
      '亮暗文件CaptureMode分别为L和D，按实测亮值−暗均值处理，不再减1000；若两者带同样偏置，相减时自然抵消。N数据不再减独立暗场，不跨数据集借用暗场。N模式无原始亮场，不能用N码值代替ADC输入判断80%余量。',
      '参考IES的Ratio为短×时间倍率/长，本分析主图用其倒数减1，以便统一“长曝光归一化偏低为负”的符号。未照搬IES的硬件归因、线性区或七阶修正。','',
      '## 专项N模式的条件性结果','',
      '|峰值档/组最大时间|实际时间对ms|可评价核心通道|偏差中位数%|绝对偏差P95%|可评价通道内±2%通过率%|',
      '|---|---|---:|---:|---:|---:|']
    for s in nsummary:
        lines.append(f'|{s["peak_label"]}/{s["group_max_ms"]}ms|{s["actual_short_ms"]:g}/{s["actual_long_ms"]:g}|{s["qualified_core_channels"]}/125|{s["median_error_pct"]:.2f}|{s["absolute_error_p95_pct"]:.2f}|{s["pass_within_qualified_pct"]:.1f}|')
    lines += ['', '以上条件性结果没有ADC余量筛选，不能与亮暗数据主表的通过率直接等同。', '', '## 图表目录','']
    pos=lines.index('## 处理与判据')
    headline=['## 本次主要发现','',
        f'1. 亮暗数据五个亮度档的积分时间加倍后，核心波段逐通道SNR提升倍数中位数为{min(s["median_SNR_gain_core"] for s in pair_summary):.2f}–{max(s["median_SNR_gain_core"] for s in pair_summary):.2f}；这不是所有波长均提升相同倍数。',
        f'2. 亮暗数据经SNR、DN余量和漂移筛选后，各档可评价核心通道为{min(s["qualified_core_channels"] for s in pair_summary)}–{max(s["qualified_core_channels"] for s in pair_summary)}个（核心共125个）。这些通道的成对积分时间偏差均在±2%以内，五档最大绝对偏差为{max(s["maximum_absolute_error_pct"] for s in pair_summary):.2f}%。此结论只适用于已筛选的通道和已测时间对。',
        '3. 按正响应、SNR≥20、逐通道拟合漂移≤2%及原始DN余量筛选，72V–64ms覆盖本次全部420–700nm核心通道；但其弱波段尚未全部满足SNR≥50，且全核心波段线性未被成对高SNR检验覆盖。因此它是现有档位中的优先复核候选，不是已完成全指标验收的最佳工作点。',
        '4. 76V–64ms原始最大值60729DN，超过52428DN工作余量线，导致部分强信号通道被排除。信噪比高不等于线性与动态余量合格。',
        f'5. 专项N数据在“仍含{args.n_offset:g}DN偏置”条件下，两组5万峰值数据的核心可评价通道绝对偏差P95分别为{nsummary[2]["absolute_error_p95_pct"]:.2f}%和{nsummary[5]["absolute_error_p95_pct"]:.2f}%，高信号端存在超出±2%的响应压缩迹象。该判断依赖导出偏置规则，不能直接生成正式非线性校正系数。',
        '6. 全部32个文件未发现达到65535的码值；这只能排除该数值处的硬截顶，不能排除更早的模拟链路/传感器非线性。最低亮度未标定，弱光结论限于本光源谱形和已测档位。','']
    lines[pos:pos]=headline
    for p in sorted(figdir.glob('*.png')):
        lines += [f'### {p.stem}',f'![{p.stem}](figures/{p.name})','']
    lines += ['## 复现与文件说明','',
      '运行 `python analyze_ocr.py`，依赖 `numpy`、`matplotlib`。首次运行从默认源目录复制CSV；已有raw快照时使用快照。若迁移机器，连同raw目录一起复制即可。`--source`可指定首次导入的源目录。`--n-offset 0`表示N数据导出已去固定偏置，默认1000为文档支持但本次导出待核实的条件。',
      '所有计算和绘图代码均在analyze_ocr.py中。图形同时输出PNG和可编辑SVG；tables中保留清单、逐条件、逐通道、逐帧、线性配对和联合工作范围CSV。输出覆盖同名分析结果，但不会修改或覆盖raw输入。',
      '建议补充记录：参考板实测亮度与光源稳定性、暗场操作方式、N模式导出规则、62ms设置说明；针对未通过波段追加亮度/积分时间档和100帧重复采样。',
      '', '参考文档：灯+光谱仪性能实验.docx；杆式夜间水体遥感反射率测量系统-立项报告-0826-v5.docx第5.7.7、5.7.8、5.7.11节；IES非线性分析.pdf（仅方法参考）。']
    (ROOT/'分析报告.md').write_text('\n'.join(lines),encoding='utf-8')
    (ROOT/'requirements.txt').write_text(f'numpy=={np.__version__}\nmatplotlib=={matplotlib.__version__}\n',encoding='utf-8')
    (ROOT/'run_metadata.json').write_text(json.dumps(dict(python=sys.version,numpy=np.__version__,matplotlib=matplotlib.__version__,
        full_scale_assumed=FULL_SCALE,raw_limit=LIMIT,N_remaining_offset_assumed=args.n_offset,core_nm=[420,700],extension_nm=[700,720],
        figure_count=len(list(figdir.glob('*.png'))),inputs=len(manifest),verification='结构、波长匹配、时间、扣暗和CV/SNR恒等式检查通过'),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'summary':summary,'paired':pair_summary,'joint':recommendations},ensure_ascii=False,indent=2))
    print(f'输出目录: {ROOT}')
    # Local HTML reading copy; source and figures stay editable alongside it.
    body=[];in_table=False
    for line in lines:
        if line.startswith('|'):
            if re.match(r'^\|[-:| ]+\|$',line):
                continue
            if not in_table:
                body.append('<table>');in_table=True
            body.append('<tr>'+''.join('<td>'+html.escape(x.strip())+'</td>' for x in line.strip('|').split('|'))+'</tr>')
            continue
        if in_table:
            body.append('</table>');in_table=False
        if line.startswith('!['):
            m=re.match(r'!\[(.*?)\]\((.*?)\)',line)
            body.append(f'<figure><img src="{html.escape(m[2])}" alt="{html.escape(m[1])}"></figure>')
        elif line.startswith('#'):
            level=len(line)-len(line.lstrip('#'));body.append(f'<h{level}>{html.escape(line[level:].strip())}</h{level}>')
        elif line:
            body.append('<p>'+html.escape(line)+'</p>')
    if in_table:body.append('</table>')
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>OCR联合性能分析</title><style>body{font:16px/1.7 "Microsoft YaHei",sans-serif;max-width:1300px;margin:36px auto;padding:0 24px;color:#202830}h1{font-size:28px}h2{margin-top:36px}table{border-collapse:collapse;width:100%;font-size:14px}td{border:1px solid #ddd;padding:7px}tr:first-child{background:#edf2f5;font-weight:bold}img{width:100%;height:auto}figure{margin:20px 0}</style><body>'+''.join(body)+'</body></html>'
    (ROOT/'分析报告.html').write_text(page,encoding='utf-8')
    # Exclude runtime packages, logs and caches from the portable research package.
    with zipfile.ZipFile(ROOT/'OCR联合性能分析_代码与结果.zip','w',zipfile.ZIP_DEFLATED) as z:
        for directory in ['raw','figures','tables','references']:
            for p in sorted((ROOT/directory).rglob('*')):
                if p.is_file():z.write(p,p.relative_to(ROOT))
        for name in ['analyze_ocr.py','verify_analysis.py','requirements.txt','分析报告.md','分析报告.html','run_metadata.json']:
            z.write(ROOT/name,name)


if __name__ == '__main__':
    main()
