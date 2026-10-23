"""只读筛选测灯连续段及启动附近数据，标准库实现，可直接 python analyze_lamp.py。"""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import sqlite3,csv,json,statistics as st,math,html,zipfile
ROOT=Path(__file__).resolve().parent
DB=Path(r'C:\Users\haowei\Desktop\夜间水质资料\夜间水质资料\标定上位机V3\标定上位机V3\data\2026-09-20.db')
TZ=timezone(timedelta(hours=8))
EXCLUDED_IDS=set(range(171,222))

def write(name,rows):
    with (ROOT/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def stats(g):
    x=[(r['dt']-g[0]['dt']).total_seconds() for r in g];y=[r['core'] for r in g]
    mean=st.mean(y);xm=st.mean(x);den=sum((a-xm)**2 for a in x)
    slope=sum((a-xm)*(b-mean) for a,b in zip(x,y))/den if den else 0
    residual=[b-(mean+slope*(a-xm)) for a,b in zip(x,y)]
    return dict(n=len(g),start=g[0]['dt'].isoformat(timespec='milliseconds'),end=g[-1]['dt'].isoformat(timespec='milliseconds'),
        first_id=g[0]['id'],last_id=g[-1]['id'],duration_s=x[-1],core_mean=mean,
        core_CV_pct=100*st.stdev(y)/mean if len(y)>1 else None,
        fitted_change_pct=100*slope*x[-1]/mean if len(y)>1 else None,
        detrended_CV_pct=100*st.stdev(residual)/mean if len(y)>1 else None,
        peak_median=st.median(r['peak'] for r in g))

def export(name,g,corekeys):
    rows=[]
    for r in g:
        a=dict(capture_id=r['id'],timestamp_UTC=r['utc'],timestamp_Beijing=r['dt'].isoformat(timespec='milliseconds'),
            integration_time_ms=r['t'],mode=r['mode'],peak_DN=r['peak'],core_sum_DN_channel=r['core'],
            capture_batch_id=r['batch'],calibration_id=r['cal'])
        a.update({'CH_'+k:v for k,v in sorted(r['a'].items(),key=lambda kv:int(kv[0]))});rows.append(a)
    write(name,rows)

def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(DB.as_uri()+'?mode=ro',uri=True)
    w=json.loads(con.execute('select wavelengths from calibrations where calibration_id=2').fetchone()[0])
    corekeys=[k for k,v in w.items() if 420<=v<=700]
    rows=[]
    for i,ts,t,mode,a,batch,cal in con.execute('''select c.capture_id,c.timestamp,d.integration_time_ms,d.dn_capture_mode,d.dn_values,c.capture_batch_id,d.calibration_id
        from captures c join spectra_dn d using(spectra_dn_id) where c.timestamp>='2026-09-20T06:28' order by c.timestamp'''):
        a=json.loads(a);rows.append(dict(id=i,utc=ts,dt=datetime.fromisoformat(ts).astimezone(TZ),t=t,mode=mode,a=a,
          batch=batch,cal=cal,peak=max(a.values()),core=sum(a[k] for k in corekeys)))
    groups=[];g=[];previous=None
    for r in rows:
        ok=r['t']==32 and r['mode']=='N' and r['peak']>25000 and r['id'] not in EXCLUDED_IDS
        if g and (not ok or (r['dt']-previous).total_seconds()>3):groups.append(g);g=[]
        if ok:g.append(r)
        previous=r['dt']
    if g:groups.append(g)
    expected=[(36,138),(222,3263),(3309,5895),(5932,7107),(7108,7156),(7241,7241)]
    assert [(g[0]['id'],g[-1]['id']) for g in groups]==expected
    # Remove only this script's old generated segment exports, avoiding stale 51-frame or renumbered files.
    for old in ROOT.glob('[0-9][0-9]_测灯段_*.csv'):
        assert old.resolve().parent==ROOT.resolve()
        old.unlink()
    write('排除记录清单.csv',[dict(capture_id=r['id'],timestamp_Beijing=r['dt'].isoformat(timespec='milliseconds'),
        reason='用户确认：暂停切换自动积分前的51帧手动积分数据；不参与测灯统计和绘图') for r in rows if r['id'] in EXCLUDED_IDS])
    summaries=[]
    for n,g in enumerate(groups,1):
        export(f'{n:02d}_测灯段_{g[0]["dt"]:%H%M%S}_{len(g)}帧.csv',g,corekeys)
        s=stats(g);s['segment']=n;s['note']='单帧恢复照明记录，不计算稳定性' if len(g)==1 else ('切换自动积分后的测灯段，保存的实际积分时间仍为32ms' if n==2 else '亮态连续采集段；重启采集不等于重启光源')
        summaries.append(s)
    lamp=[r for g in groups for r in g]
    export('全部测灯帧.csv',lamp,corekeys)
    startup=[r for r in rows if r['id']<=170]
    export('启动附近原始记录_含512ms与首次背景.csv',startup,corekeys)
    write('测灯时间段与稳定性.csv',summaries)
    minutes={}
    for r in lamp:minutes.setdefault(r['dt'].strftime('%H:%M'),[]).append(r)
    bins=[]
    for minute,g in minutes.items():
        s=stats(g);s['minute']=minute;s['partial_minute']=len(g)<80;bins.append(s)
    write('测灯逐分钟统计.csv',bins)
    # robust equal-duration windows, latest substantial segment excludes the isolated final frame.
    initial=[r for r in groups[0] if (r['dt']-groups[0][0]['dt']).total_seconds()<=30]
    final=groups[-2] # only22.6s present; clearly report actual duration rather than claim30s
    base=st.mean(r['core'] for r in initial);last=st.mean(r['core'] for r in final)
    diff=100*(last/base-1)
    offset=1000*len(corekeys);adjusted=100*((last-offset)/(base-offset)-1)
    peakdiff=100*(st.mean(r['peak'] for r in final)/st.mean(r['peak'] for r in initial)-1)
    initial5=[r for r in lamp if (r['dt']-lamp[0]['dt']).total_seconds()<300]
    late5=[r for r in lamp if datetime(2026,9,20,15,21,tzinfo=TZ)<=r['dt']<datetime(2026,9,20,15,26,tzinfo=TZ)]
    details=dict(total_lamp_frames=len(lamp),excluded_capture_ids=[171,221],excluded_frame_count=51,raw_core_change_pct=diff,offset1000_sensitivity_change_pct=adjusted,
        mean_peak_change_pct=peakdiff,first_window=stats(initial),last_window=stats(final),first5_observed=stats(initial5),late5_observed=stats(late5),
        core_channel_count=len(corekeys),note='全程主指标为原始导出N码值的420–700nm通道和，未扣同期环境光；反映测量链响应，不直接等同灯的净输出。')
    (ROOT/'比较指标.json').write_text(json.dumps(details,ensure_ascii=False,indent=2),encoding='utf-8')
    # fixed baseline strongest channel, preserve spectral drift visibility independently of peak shifts
    channelmean={k:st.mean(r['a'][k] for r in initial) for k in corekeys}
    strongest=max(channelmean,key=channelmean.get)
    write('代表波长与分波段检查.csv',[dict(channel=k,wavelength_nm=w[k],initial_mean=st.mean(r['a'][k] for r in initial),
        final_mean=st.mean(r['a'][k] for r in final),change_pct=100*(st.mean(r['a'][k] for r in final)/st.mean(r['a'][k] for r in initial)-1)) for k in corekeys])
    # SVG scatter avoids drawing lines across interruptions; panels use actual elapsed clock time.
    t0=lamp[0]['dt'];lasttime=rows[-1]['dt'];width=1100
    def chart(name,subset,span,low,high,title):
        def x(r):return 90+(r['dt']-t0).total_seconds()/span*width
        def y(val):return 360-(val-low)/(high-low)*270
        svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="450"><rect width="1280" height="450" fill="white"/><g font-family="Microsoft YaHei, sans-serif" font-size="14">',f'<text x="90" y="30" font-size="20">{title}</text>',
             '<text x="90" y="57">420–700nm导出码值通道和，相对第一段前30秒均值；不连接停采空档，不扣环境光</text>']
        for f in [0,.25,.5,.75,1]:
            val=low+(high-low)*f;svg.append(f'<path d="M90 {y(val)}H1200" stroke="#ddd"/><text x="20" y="{y(val)+4}">{val:.1f}%</text>')
        for r in subset:
            value=100*(r['core']/base-1)
            if low<=value<=high:svg.append(f'<circle cx="{x(r):.2f}" cy="{y(value):.2f}" r="1.8" fill="#296c9d" opacity=".65"/>')
        for frac in [0,.2,.4,.6,.8,1]:
            dt=t0+timedelta(seconds=span*frac);svg.append(f'<text x="{90+frac*width}" y="395" text-anchor="middle">{dt:%H:%M:%S}</text>')
        svg.append('<text x="90" y="432">横轴北京时间；时间零点为第一帧32ms亮态记录14:29:03.975，不是已确认开灯时刻。</text></g></svg>')
        (ROOT/name).write_text(''.join(svg),encoding='utf-8')
    vals=[100*(r['core']/base-1) for r in lamp]
    chart('测灯全程趋势.svg',lamp,(lasttime-t0).total_seconds(),min(vals)-.2,max(vals)+.2,'测灯全程：短时波动与慢漂移')
    vals5=[100*(r['core']/base-1) for r in initial5]
    chart('启动附近前5分钟.svg',initial5,300,min(vals5)-.1,max(vals5)+.1,'启动附近前5分钟：只比较32ms亮态记录')
    lines=['# 冷启动测灯时间段筛选与稳定性检查','',
       '2026-09-20北京时间。只读原数据库，探头OCR 25F02100。根据32ms、N模式、每帧峰值>25000DN识别亮态，间隔>3秒或中间状态改变则切段。阈值只用于这批数据分段；不能从重新开始采集推断灯重新通电。',
       '本版按用户确认，排除14:31:17.372–14:31:44.230的51帧（ID171–221）：这是暂停切换自动积分前的手动积分数据。排除范围仅此51帧，14:29的103帧启动记录继续保留。全部统计、图表和数据包已重算；原数据库未修改。','',
       '|段|开始|结束|帧数|原始核心响应CV%|段内拟合变化%|','|---|---|---|---:|---:|---:|']
    for n,s in enumerate(summaries,1):
        cv='不计算' if s['core_CV_pct'] is None else f'{s["core_CV_pct"]:.3f}'
        change='不计算' if s['fitted_change_pct'] is None else f'{s["fitted_change_pct"]:.3f}'
        lines.append(f'|{n}|{s["start"][11:23]}|{s["end"][11:23]}|{s["n"]}|{cv}|{change}|')
    lines+=['','## 是否稳定','',
       f'共筛出{len(lamp)}帧。最早32ms亮态从14:29:03.975开始，测量末端仍有15:33:17.973单帧。第一段前30秒与15:31:51.495–15:32:14.079的49帧相比，原始核心波段总响应变化{diff:.3f}%，每帧峰值的均值变化{peakdiff:.3f}%。',
       f'前5分钟已采到的亮态数据：CV={details["first5_observed"]["core_CV_pct"]:.3f}%；15:21–15:26亮态数据CV={details["late5_observed"]["core_CV_pct"]:.3f}%。CV基于各窗口实际存在的帧，未填补中断；全段CV包含慢漂移，不能等同纯随机噪声。',
       '可区分短时稳定和长期恒定：逐帧波动较小，并不意味着一小时完全不变；存在缓慢下降。表中段内拟合变化以该段均值归一，首尾比较以首段前30秒均值归一，二者口径不同。',
       f'此处未扣随时间变化的环境光，因此下降只能称为测量链响应漂移，不能全部归因为灯热衰减。若假设N模式仍带1000DN偏置，统一去偏置后的首尾变化为{adjusted:.3f}%，仅作偏置敏感性对照，不改变导出数据。','',
       '## 冷启动附近重点','',
       '14:28:41.874–14:28:52.420有11帧512ms数据，随后14:29:03.975起改为32ms。前一段不能与后面的原始DN直接拼接来判断预热，可能涉及环境或采集设置变化。已单独保留启动附近全部原始记录。',
       '14:29:03.975–14:29:47.429是首个103帧32ms亮态段，按用户要求保留；之后暂停并采集14:30低信号。原14:31:17.372起的51帧已排除，后续纳入的测灯记录从14:31:49.224开始。数据库没有明确电源通电事件，不能给出从通电起算的严格预热时间。',
       '用户确认14:31:44.230到14:31:49.224约5秒空档是暂停采集，将手动积分改为自动积分。此处不是环境光采集，也不代表重新开灯。自动积分是控制方式，后续保存的实际积分时间仍为32ms；CaptureMode=N不表示手动或自动积分。',
       '15:26:29.544到15:31:51.495存在约5分22秒空档，不能据此声称连续无中断测量一小时。最后15:33:17.973只有一帧恢复照明，单独保留，不据此计算稳定性。','',
       '![全程](测灯全程趋势.svg)','![前5分钟](启动附近前5分钟.svg)','',
       '## 文件与验证','',
       '全部测灯帧.csv及6个分段CSV包含原始ID、UTC与北京时间、积分时间、模式和288通道。排除记录清单.csv仅列出已排除ID和原因。逐分钟表用于复核短时变化；代表波长表可区分谱形变化。所有保留数据逐值核对原库，无扣暗、去偏置、平滑或缺失填补。分析代码为analyze_lamp.py，仅需Python标准库。']
    (ROOT/'测灯筛选说明.md').write_text('\n'.join(lines),encoding='utf-8')
    parts=['<meta charset="utf-8"><title>测灯筛选与启动检查</title><body style="max-width:1280px;margin:30px auto;font:16px/1.8 Microsoft YaHei">']
    for l in lines:
        if l.startswith('!['):parts.append('<img style="width:100%" src="'+l.split('](')[1][:-1]+'">')
        else:parts.append('<p>'+html.escape(l)+'</p>')
    (ROOT/'测灯筛选说明.html').write_text(''.join(parts)+'</body>',encoding='utf-8')
    exported=list(csv.DictReader((ROOT/'全部测灯帧.csv').open(encoding='utf-8-sig')))
    assert len(exported)==len(lamp)==6958
    assert not EXCLUDED_IDS.intersection(int(r['capture_id']) for r in exported)
    assert len(list(ROOT.glob('[0-9][0-9]_测灯段_*.csv')))==6
    for r,s in zip(lamp,exported):
        assert int(s['capture_id'])==r['id'] and all(float(s['CH_'+k])==v for k,v in r['a'].items())
    con.close()
    (ROOT/'核验.json').write_text(json.dumps(dict(frames=6958,excluded_frames=51,excluded_id_range=[171,221],channels=288,mode='read-only',verification='导出逐值一致，排除ID无残留，分段文件6个'),ensure_ascii=False),encoding='utf-8')
    with zipfile.ZipFile(ROOT/'测灯筛选_数据图表与代码.zip','w',zipfile.ZIP_DEFLATED) as z:
        for p in ROOT.iterdir():
            if p.is_file() and p.suffix!='.zip':z.write(p,p.name)
    print(json.dumps(dict(segments=summaries,metrics=details),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
