"""按用户补充的暂停/重启及约6000DN、排除连续8000DN规则复查。
只读前次导出的全部候选，与原SQLite逐值核验，输出复查版。
7000是用于识别“6000左右”的宽容上界，不是用户确认的硬阈值。
不凑足30帧，不跨高值帧拼接，不修改DN。
"""
from pathlib import Path
import csv,json,sqlite3,statistics,html,zipfile
from datetime import datetime

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'复查版'
DB=Path(r'C:\Users\haowei\Desktop\夜间水质资料\夜间水质资料\标定上位机V3\标定上位机V3\data\2026-09-20.db')

def read(p):
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def write(p,rows):
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def runs(rows,limit):
    result=[];r=[]
    for x in rows:
        if float(x['peak_DN'])<=limit:r.append(x)
        elif r:result.append(r);r=[]
    if r:result.append(r)
    return result

def main():
    OUT.mkdir(exist_ok=True)
    sources=sorted(ROOT.glob('*_逐帧.csv'))
    groups={p.name:read(p) for p in sources}
    allrows={int(r['capture_id']):r for g in groups.values() for r in g}
    selected=[('01_1430_有效环境光32帧',139,170,'时间记录和幅值均吻合'),
      ('02_1532_推荐环境光26帧',7195,7220,'最清楚的连续低值平台，保留全部26帧，不补入高值帧'),
      ('03_1516_后段候选19帧_待核实',5913,5931,'后段稳定在约6000，暂停重启完整批次为36帧；本19帧是幅值筛选子段，操作身份待核实')]
    summaries=[];selected_ids={}
    con=sqlite3.connect(DB.as_uri()+'?mode=ro',uri=True)
    for name,a,b,note in selected:
        g=[allrows[i] for i in range(a,b+1)]
        write(OUT/(name+'_逐帧.csv'),g)
        cal=int(g[0]['calibration_id']);waves=json.loads(con.execute('select wavelengths from calibrations where calibration_id=?',(cal,)).fetchone()[0])
        with (OUT/(name+'_光谱.csv')).open('w',encoding='utf-8-sig',newline='') as f:
            wr=csv.writer(f);wr.writerow(['ItemName','Wavelength_nm']+[r['timestamp_Beijing'] for r in g])
            wr.writerow(['CaptureID','']+[r['capture_id'] for r in g])
            wr.writerow(['IntegrationTime_ms','']+[r['integration_time_ms'] for r in g])
            wr.writerow(['CaptureMode','']+[r['capture_mode'] for r in g])
            for ch in sorted(waves,key=int):wr.writerow(['CH_'+ch,waves[ch]]+[r['CH_'+ch] for r in g])
        summaries.append(dict(name=name,start=g[0]['timestamp_Beijing'],end=g[-1]['timestamp_Beijing'],
           first_id=a,last_id=b,frames=len(g),peak_min=min(float(r['peak_DN']) for r in g),
           peak_median=statistics.median(float(r['peak_DN']) for r in g),peak_max=max(float(r['peak_DN']) for r in g),
           frames_above6000=sum(float(r['peak_DN'])>6000 for r in g),note=note))
        for r in g:
            i=int(r['capture_id']);selected_ids[i]=name
            d=json.loads(con.execute('select d.dn_values from captures c join spectra_dn d using(spectra_dn_id) where c.capture_id=?',(i,)).fetchone()[0])
            assert all(float(r['CH_'+ch])==v for ch,v in d.items())
    write(OUT/'复查筛选汇总.csv',summaries)
    audit=[];sensitivity=[]
    for name,g in groups.items():
        for r in g:
            i=int(r['capture_id']);status=selected_ids.get(i,'未选入；保留原记录供复核')
            audit.append(dict(source_group=name,capture_id=i,timestamp_Beijing=r['timestamp_Beijing'],peak_DN=r['peak_DN'],
                 mean_DN=r['mean_DN'],status=status))
        for threshold in [6000,7000,8000]:
            for run in runs(g,threshold):
                sensitivity.append(dict(group=name,peak_limit=threshold,frames=len(run),first_id=run[0]['capture_id'],
                    last_id=run[-1]['capture_id'],start=run[0]['timestamp_Beijing'],end=run[-1]['timestamp_Beijing']))
    write(OUT/'全部197帧复查标记.csv',audit);write(OUT/'连续段阈值敏感性.csv',sensitivity)
    target=next(g for n,g in groups.items() if '_1532_' in n)
    # Exhaustive contiguous 30-frame windows, not handpicked non-contiguous samples.
    windows=[]
    for i in range(len(target)-29):
        g=target[i:i+30];v=[float(r['peak_DN']) for r in g]
        windows.append(dict(first_id=g[0]['capture_id'],last_id=g[-1]['capture_id'],start=g[0]['timestamp_Beijing'],
          end=g[-1]['timestamp_Beijing'],peak_min=min(v),peak_max=max(v),peak_median=statistics.median(v),
          count_above6000=sum(x>6000 for x in v),count_above7000=sum(x>7000 for x in v),count_ge8000=sum(x>=8000 for x in v)))
    assert min(x['count_ge8000'] for x in windows)>0
    write(OUT/'1532全部连续30帧窗口.csv',windows)
    # Visual shows all84 frames; selected interval is a transparent contiguous subset.
    start=datetime.fromisoformat(target[0]['timestamp_Beijing']);end=datetime.fromisoformat(target[-1]['timestamp_Beijing'])
    def x(r):return 90+(datetime.fromisoformat(r['timestamp_Beijing'])-start).total_seconds()/(end-start).total_seconds()*1100
    def y(v):return 370-float(v)/20000*290
    svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="470"><rect width="1280" height="470" fill="white"/><g font-family="Microsoft YaHei, sans-serif" font-size="14">',
      '<text x="90" y="30" font-size="21">15:32逐帧复查：84帧中推荐保留连续26帧</text>',
      '<text x="90" y="55">绿色：7195–7220；灰色：未选入。所有峰值均为原始导出DN，不扣1000。</text>']
    for val in [0,6000,8000,12000,16000,20000]:
        color='#c83838' if val==8000 else '#ddd'
        svg.append(f'<path d="M90 {y(val)}H1200" stroke="{color}" stroke-dasharray="5 4"/><text x="25" y="{y(val)+4}">{val}</text>')
    pts=' '.join(f'{x(r):.1f},{y(r["peak_DN"]):.1f}' for r in target)
    svg.append(f'<polyline points="{pts}" fill="none" stroke="#aaa"/>')
    for r in target:
        i=int(r['capture_id']);color='#168566' if 7195<=i<=7220 else '#aaa'
        svg.append(f'<circle cx="{x(r):.1f}" cy="{y(r["peak_DN"]):.1f}" r="3.5" fill="{color}"/>')
        if i in [7157,7176,7195,7220,7240]:
            svg.append(f'<text x="{x(r):.1f}" y="402" text-anchor="middle">{r["timestamp_Beijing"][11:23]}</text><text x="{x(r):.1f}" y="425" text-anchor="middle">ID {i}</text>')
    svg.append('<text x="90" y="457">6000是大致水平；若严格逐帧≤6000，最长只有9帧，不能宣称找到了30帧全部≤6000的数据。</text></g></svg>')
    (OUT/'1532逐帧复查.svg').write_text(''.join(svg),encoding='utf-8')
    body=['# 环境光筛选复查版','',
      '本版替代上版的有效环境光判断；上版84帧等完整导出仍保留作为原始候选，不再当成全有效数据。日期2026-09-20，以下均为北京时间。',
      '新依据：连续照明后暂停重启为操作批次线索；有效环境光峰值通常约6000DN，连续8000DN上下不应选入。此处的6000/8000按前次交流的每帧全谱峰值理解，不是全谱均值。',
      '暂停边界只能确定完整批次。15:32的84帧内部没有暂停记录；其中可用子段依靠幅值识别，不能伪称该26帧另有重启边界。','',
      '|组别|开始|结束|帧数|峰值范围DN|','|---|---|---|---:|---|']
    for s in summaries:body.append(f'|{s["name"]}|{s["start"][11:23]}|{s["end"][11:23]}|{s["frames"]}|{s["peak_min"]:.0f}–{s["peak_max"]:.0f}|')
    body+=['','## 重新判定','',
      '1. 14:30的32帧全部低于6000，保留，不随意删成30帧。',
      '2. 14:57的34帧峰值6260–9307，中位7909.5，存在大量8000上下读数，撤回此前将整段认作有效环境光的建议，本版不选入。',
      '3. 15:16完整36帧不能全部认定有效。15:16:48.213–15:16:57.826（5913–5931）连续19帧为5592–6299，单列为后段候选，待操作记录核实；不为凑30帧加入此前7000以上数据。',
      '4. 15:32推荐7195–7220共26帧：15:32:50.806–15:33:05.650，峰值4533–6740。前一帧7194为7513，后一帧7221为9432，均未加入。',
      '5. 对15:32全部55个连续30帧窗口逐一核查，每个窗口都含≥8000帧，故无法找到同时满足连续30帧且没有8000高值的窗口。不能剔除中间高值后拼接成所谓连续30帧。',
      '6. 7000仅是识别约6000平台的分析容差，不是用户指定的新标准。严格≤6000时15:32最长只有9帧（7206–7214），因此推荐26帧有部分略高于6000，范围已明确报告。',
      '7. 14:54的11帧全部高于10000，本版不选为环境光。',
      '', '![1532逐帧复查](1532逐帧复查.svg)','',
      '所有选中帧保持原始DN、时间及ID，与只读SQLite逐通道核对。CSV提供逐帧与转置光谱两种形式。原始候选不删除。代码为recheck_background.py，需与上一级前次导出配套重跑。']
    (OUT/'复查说明.md').write_text('\n'.join(body),encoding='utf-8')
    h=['<meta charset="utf-8"><title>环境光复查</title><body style="font:16px/1.8 Microsoft YaHei;max-width:1250px;margin:30px auto">']
    for line in body:
        h.append('<img src="1532逐帧复查.svg" style="width:100%">' if line.startswith('![') else '<p>'+html.escape(line)+'</p>')
    (OUT/'复查说明.html').write_text(''.join(h)+'</body>',encoding='utf-8')
    (OUT/'核验.json').write_text(json.dumps(dict(selected_frames=77,verified_channels_per_frame=288,
       all30_windows=len(windows),minimum_ge8000_count=min(x['count_ge8000'] for x in windows),
       verification='全部选中DN与数据库逐值一致'),ensure_ascii=False,indent=2),encoding='utf-8')
    con.close()
    with zipfile.ZipFile(OUT/'环境光复查_数据与代码.zip','w',zipfile.ZIP_DEFLATED) as z:
        for p in OUT.iterdir():
            if p.suffix!='.zip' and p.is_file():z.write(p,'复查版/'+p.name)
        z.write(Path(__file__),'recheck_background.py')
        for p in sources:z.write(p,p.name)
    print(json.dumps(summaries,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
