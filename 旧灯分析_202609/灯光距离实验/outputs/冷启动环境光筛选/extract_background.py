"""只读提取2026-09-20冷启动实验的环境光候选，保留全部原始DN。
运行：python extract_background.py [--db 数据库路径]
仅依赖Python标准库；不扣暗、不去偏置、不平滑、不删除帧。
"""
from pathlib import Path
import argparse
import csv
import json
import sqlite3
import statistics
from datetime import datetime, timezone, timedelta
import html
import zipfile
import hashlib

ROOT=Path(__file__).resolve().parent
DEFAULT=Path(r'C:\Users\haowei\Desktop\夜间水质资料\夜间水质资料\标定上位机V3\标定上位机V3\data\2026-09-20.db')
TZ=timezone(timedelta(hours=8))

def write_csv(path,rows):
    if not rows:return
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        wr=csv.DictWriter(f,fieldnames=list(rows[0]));wr.writeheader();wr.writerows(rows)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--db',type=Path,default=DEFAULT);args=ap.parse_args()
    ROOT.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(args.db.resolve().as_uri()+'?mode=ro',uri=True)
    con.row_factory=sqlite3.Row
    rows=[]
    for rr in con.execute('''SELECT c.capture_id,c.timestamp,c.capture_batch_id,c.probe_id,
      c.raw_data_id,c.spectra_dn_id,c.spectra_phy_id,d.calibration_id,d.integration_time_ms,
      d.dn_capture_mode,d.dn_values,p.serial_number
      FROM captures c JOIN spectra_dn d USING(spectra_dn_id) JOIN probes p USING(probe_id)
      WHERE c.timestamp >= '2026-09-20T06:28' ORDER BY c.timestamp,c.capture_id'''):
        r=dict(rr);r['dt']=datetime.fromisoformat(r['timestamp']).astimezone(TZ)
        r['values']=json.loads(r['dn_values']);a=list(r['values'].values())
        r['peak']=max(a);r['mean']=statistics.mean(a);rows.append(r)
    # Data-driven low-signal run segmentation, with timestamp gaps as boundaries.
    segments=[];run=[];prev=None
    for r in rows:
        low=r['integration_time_ms']==32 and r['dn_capture_mode']=='N' and r['peak']<20000
        if run and (not low or (r['dt']-prev).total_seconds()>3):segments.append(run);run=[]
        if low:run.append(r)
        prev=r['dt']
    if run:segments.append(run)
    assert [(s[0]['capture_id'],s[-1]['capture_id'],len(s)) for s in segments]==[
        (139,170,32),(3264,3274,11),(3275,3308,34),(5896,5931,36),(7157,7240,84)]
    specs=[('01_环境光候选_1430',139,170,'与14:30:10记录吻合，32帧，保留全段'),
           ('02_环境光候选_1457',3275,3308,'与14:57记录吻合，34帧，保留全段'),
           ('03_环境光候选_1516',5896,5931,'15:16出现独立36帧低信号段，前后均为亮场，疑似额外一次环境光采集'),
           ('04_环境光候选_1532_完整84帧',7157,7240,'完整84帧低信号段，存在中间升高，不任意截成30帧'),
           ('05_附加低信号_1454_11帧',3264,3274,'14:54:55开始的额外11帧，信号高于其他环境光段，可能为操作或遮挡不充分，单列待核实')]
    byid={r['capture_id']:r for r in rows}; summaries=[];selected=set()
    for name,first,last,note in specs:
        group=[byid[i] for i in range(first,last+1)];selected.update(range(first,last+1))
        wavelengths=json.loads(con.execute('SELECT wavelengths FROM calibrations WHERE calibration_id=?',(group[0]['calibration_id'],)).fetchone()[0])
        channel_ids=sorted(group[0]['values'],key=int)
        records=[]
        for r in group:
            rec=dict(capture_id=r['capture_id'],timestamp_UTC=r['timestamp'],timestamp_Beijing=r['dt'].isoformat(timespec='milliseconds'),
                probe_serial=r['serial_number'],calibration_id=r['calibration_id'],integration_time_ms=r['integration_time_ms'],
                capture_mode=r['dn_capture_mode'],capture_batch_id=r['capture_batch_id'],raw_data_id=r['raw_data_id'],
                spectra_dn_id=r['spectra_dn_id'],peak_DN=r['peak'],mean_DN=r['mean'])
            rec.update({f'CH_{i}':r['values'][i] for i in channel_ids});records.append(rec)
        write_csv(ROOT/(name+'_逐帧.csv'),records)
        # Transposed form compatible with prior CSV layout, plus traceability IDs.
        with (ROOT/(name+'_光谱.csv')).open('w',encoding='utf-8-sig',newline='') as f:
            wr=csv.writer(f);wr.writerow(['ItemName','Wavelength_nm']+[r['dt'].isoformat(timespec='milliseconds') for r in group])
            wr.writerow(['CaptureID','']+[r['capture_id'] for r in group])
            wr.writerow(['IntegrationTime_ms','']+[r['integration_time_ms'] for r in group])
            wr.writerow(['CaptureMode','']+[r['dn_capture_mode'] for r in group])
            for i in channel_ids:wr.writerow([f'CH_{i}',wavelengths[i]]+[r['values'][i] for r in group])
        a=group[0];b=group[-1]
        summaries.append(dict(group=name,start_Beijing=a['dt'].isoformat(timespec='milliseconds'),end_Beijing=b['dt'].isoformat(timespec='milliseconds'),
            frame_count=len(group),capture_id_first=first,capture_id_last=last,duration_s=(b['dt']-a['dt']).total_seconds(),
            peak_DN_min=min(r['peak'] for r in group),peak_DN_median=statistics.median(r['peak'] for r in group),
            peak_DN_max=max(r['peak'] for r in group),note=note))
    write_csv(ROOT/'筛选时间段汇总.csv',summaries)
    # Context, including both sides of transitions. No records are silently discarded.
    context=[]
    for r in rows:
        label=next((name for name,lo,hi,_ in specs if lo<=r['capture_id']<=hi),'正常照明或其他记录')
        context.append(dict(capture_id=r['capture_id'],timestamp_UTC=r['timestamp'],timestamp_Beijing=r['dt'].isoformat(timespec='milliseconds'),
            integration_time_ms=r['integration_time_ms'],capture_mode=r['dn_capture_mode'],peak_DN=r['peak'],mean_DN=r['mean'],classification=label))
    write_csv(ROOT/'全程逐帧信号与标记.csv',context)
    # 15:32 only: identify the rise, retain all samples; the 50-frame tail is not a uniquely established 30-frame set.
    parts=[('前段',7157,7182),('中间信号升高段',7183,7190),('后段',7191,7240)]
    write_csv(ROOT/'1532段内部变化.csv',[dict(part=n,capture_id_first=a,capture_id_last=b,frames=b-a+1,
        start_Beijing=byid[a]['dt'].isoformat(timespec='milliseconds'),end_Beijing=byid[b]['dt'].isoformat(timespec='milliseconds'),
        peak_min=min(byid[i]['peak'] for i in range(a,b+1)),peak_max=max(byid[i]['peak'] for i in range(a,b+1))) for n,a,b in parts])
    # Standalone SVG evidence chart, rendered from unaltered peak DN.
    start=datetime(2026,9,20,14,28,tzinfo=TZ);end=datetime(2026,9,20,15,34,tzinfo=TZ)
    def x(dt):return 80+(dt-start).total_seconds()/(end-start).total_seconds()*1120
    def y(v):return 340-v/40000*270
    svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="420" viewBox="0 0 1280 420">',
         '<rect width="1280" height="420" fill="white"/><g font-family="Microsoft YaHei, sans-serif" font-size="13">',
         '<text x="80" y="27" font-size="20">冷启动采集全程与环境光候选段（北京时间；原始导出峰值）</text>']
    for v in [0,10000,20000,30000,40000]:svg += [f'<path d="M80 {y(v)}H1200" stroke="#ddd"/><text x="15" y="{y(v)+5}">{v}</text>']
    for minute in [0,10,20,30,40,50,60,66]:
        dt=start+timedelta(minutes=minute);svg.append(f'<text x="{x(dt)-20}" y="370">{dt:%H:%M}</text>')
    for r in rows:
        color='#d14a34' if r['capture_id'] in selected else '#246da8'
        svg.append(f'<circle cx="{x(r["dt"]):.2f}" cy="{y(r["peak"]):.2f}" r="1.5" fill="{color}"/>')
    for label,a,b in [('14:30 / 32帧',139,170),('14:55 / 11帧',3264,3274),('14:57 / 34帧',3275,3308),('15:16 / 36帧',5896,5931),('15:32 / 84帧',7157,7240)]:
        xx=x(byid[a]['dt']); yy=55 if a!=3264 else 78
        svg.append(f'<text x="{xx}" y="{yy}" text-anchor="middle" fill="#a52c20">{label}</text>')
    svg.append('<text x="80" y="405">红色：低信号候选；蓝色：其他记录。空白处为采集间断，不能按连续测量补齐。</text></g></svg>')
    (ROOT/'筛选总览.svg').write_text(''.join(svg),encoding='utf-8')
    lines=['# 冷启动实验环境光筛选结果','',
        '日期：2026-09-20。数据库时间为UTC，以下均换算为北京时间UTC+8。以只读方式读取原数据库，未修改源数据。',
        '探头：OCR 25F02100。所选5段全部为32ms、CaptureMode=N。N是输出模式，不是环境光状态标志；环境光身份依据用户时间记录、信号突降及独立采集段推断，无法仅靠数据库证明当时是关灯还是遮挡。',
        '筛选依据：14:29后32ms/N数据中，每帧全谱峰值低于20000DN且相邻帧间隔≤3秒形成候选段。正常照明峰值约3.2万DN，四个目标时刻有清晰的低信号段。20000仅用于本次状态分段，不是测量质量阈值。','',
        '|候选段|开始时间|结束时间|帧数|Capture ID|','|---|---|---|---:|---|']
    for s in summaries:lines.append(f'|{s["group"]}|{s["start_Beijing"][11:23]}|{s["end_Beijing"][11:23]}|{s["frame_count"]}|{s["capture_id_first"]}–{s["capture_id_last"]}|')
    lines += ['', '## 重点结论','',
        '- 14:30:10对应完整32帧；14:57对应完整34帧，均已分别导出。',
        '- 15:16:39.458–15:16:57.826有独立36帧低信号采集，之前15:16:15.605、之后15:17:39.831均为约3.17万DN照明状态。形态与另外两段环境光采集一致，建议列为第4次环境光候选，不能忽略。',
        '- 15:32:28.723–15:33:17.367共84帧，末后15:33:17.973恢复到31460DN。没有采集间断可以将84帧可靠拆成某个“30帧”批次，故保留全段。',
        '- 15:32段内部：前26帧（7157–7182），接着8帧升高段（7183–7190，峰值10641–18343DN），后50帧（7191–7240）。升高可能涉及遮挡/操作变化或环境光波动，仅凭光谱不能确定；不自动删掉，也不任意挑选最平稳30帧。',
        '- 另发现14:54:55.426–14:55:00.760的11帧低信号段，峰值10283–14208DN，单列保存供核查，未并入14:57段。',
        '- 因此实际存在4个与所给时间吻合的候选事件，加1个额外短事件，而非可确定的3个30帧批次。',
        '- 所有导出DN逐值保留，不再扣暗或减1000。筛选与偏置问题分开处理。',
        '- 全程还存在采集间断，例如15:26后至15:31之间；后续做冷启动稳定性时应使用真实时间轴，不把缺失记录补成连续采样。','',
        '## 文件说明','',
        '每段提供逐帧CSV（每行一帧，含原始ID、UTC/北京时间及288通道）和光谱CSV（每列一帧，含波长）。全程逐帧信号与标记.csv用于核对边界；1532段内部变化.csv记录内部升高位置。extract_background.py为可复现筛选代码。',
        '![筛选总览](筛选总览.svg)','',f'源数据库：{args.db}']
    (ROOT/'筛选说明.md').write_text('\n'.join(lines),encoding='utf-8')
    body=[]
    for line in lines:
        if line.startswith('!['):body.append('<img src="筛选总览.svg" style="width:100%">')
        else:body.append('<p>'+html.escape(line)+'</p>')
    (ROOT/'筛选说明.html').write_text('<meta charset="utf-8"><title>环境光筛选</title><body style="font:16px/1.7 Microsoft YaHei;max-width:1280px;margin:30px auto">'+''.join(body)+'</body>',encoding='utf-8')
    # Reopen exports and verify every DN against the read-only database values.
    for name,a,b,_ in specs:
        with (ROOT/(name+'_逐帧.csv')).open(encoding='utf-8-sig',newline='') as f:exported=list(csv.DictReader(f))
        assert len(exported)==b-a+1
        for r in exported:
            original=byid[int(r['capture_id'])]
            assert all(float(r[f'CH_{i}'])==v for i,v in original['values'].items())
    (ROOT/'验证结果.json').write_text(json.dumps(dict(source_db=str(args.db),source_sha256=hashlib.sha256(args.db.read_bytes()).hexdigest(),
        selected_frames=len(selected),groups=len(specs),verification='5组197帧的全部288通道与数据库逐值一致',
        source_access='read-only',timezone='UTC+08:00'),ensure_ascii=False,indent=2),encoding='utf-8')
    con.close()
    with zipfile.ZipFile(ROOT/'环境光筛选_数据与代码.zip','w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(ROOT.iterdir()):
            if p.is_file() and p.suffix in ['.csv','.py','.md','.html','.svg','.json']:z.write(p,p.name)
    print(json.dumps(summaries,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
