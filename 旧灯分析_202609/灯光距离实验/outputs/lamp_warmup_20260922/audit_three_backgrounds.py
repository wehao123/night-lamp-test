from pathlib import Path
import csv, json, datetime as dt, html
import numpy as np

ROOT=Path(__file__).resolve().parent
SRC=Path(r'C:\Users\haowei\Desktop\夜间水质资料\夜间水质资料\标定上位机V3\标定上位机V3\output')
OUT=ROOT/'三组背景重算'
OUT.mkdir(exist_ok=True)
names=['总量','蓝','绿','红']; bounds=[(420,700),(420,500),(500,600),(600,700)]
files=[]
for p in sorted(SRC.glob('*.csv')):
    rows=list(csv.reader(l for l in p.read_text(encoding='utf-8-sig').splitlines() if l and not l.startswith('#')))
    times=np.array([dt.datetime.fromisoformat(v.replace('Z','+00:00')).timestamp() for v in rows[0][2:]])
    assert all(float(v)==32 for v in rows[1][2:]) and all(v=='N' for v in rows[2][2:])
    wave=np.array([float(r[1]) for r in rows[3:]])
    x=np.array([list(map(float,r[2:])) for r in rows[3:]]).T
    files.append(dict(name=p.name,t=times,x=x,w=wave))
w=files[0]['w']
assert all(np.array_equal(f['w'],w) for f in files)
def integ(x):
    vals=[]
    for lo,hi in bounds:
        grid=np.r_[lo,w[(w>lo)&(w<hi)],hi]
        vals.append(np.array([np.trapezoid(np.interp(grid,w,row),grid) for row in np.atleast_2d(x)]))
    return np.array(vals).T
env=sorted([f for f in files if '环境' in f['name']],key=lambda f:f['t'][0])
bright=[f for f in files if '环境' not in f['name']]
t=np.concatenate([f['t'] for f in bright]);x=np.concatenate([f['x'] for f in bright]);ix=np.argsort(t);t=t[ix];x=x[ix]
sec=t-t[0]; assert len(t)==6899 and np.all(np.diff(t)>0)
raw=integ(x)
selected=[slice(2,17),slice(None),slice(None)]
bg=np.array([integ(f['x'][s]).mean(axis=0) for f,s in zip(env,selected)])
bt=np.array([f['t'][s].mean() for f,s in zip(env,selected)])
bgall=np.array([integ(f['x']).mean(axis=0) for f in env])
def varying(b):return np.column_stack([np.interp(t,bt,b[:,j]) for j in range(4)])
nets={'固定环境1选15帧':raw-bg[0],'三背景时间插值':raw-varying(bg),'三背景全帧敏感性':raw-np.column_stack([np.interp(t,[f['t'].mean() for f in env],bgall[:,j]) for j in range(4)])}
nets['固定环境1完整30帧']=raw-bgall[0]
results={}
for method,y in nets.items():
    mask=(sec>=1200)&(sec<=3000);z=y[mask]
    rolling=[]
    for end in range(300,int(sec[-1])+1):
        i,j=np.searchsorted(sec,[end-300,end],side='left'); j=np.searchsorted(sec,end,side='right')
        tt=sec[i:j]; yy=y[i:j,0]
        if len(tt)<10 or tt[0]-(end-300)>1 or end-tt[-1]>1 or np.any(np.diff(tt)>2):continue
        cv=yy.std(ddof=1)/yy.mean()*100
        rate=np.dot(tt-tt.mean(),yy-yy.mean())/np.sum((tt-tt.mean())**2)/yy.mean()*6000
        rolling.append((end,cv,abs(rate)))
    run=[];first=None
    for v in rolling:
        if v[1]>1 or v[2]>.2:run=[];continue
        if run and v[0]-run[-1][0]!=1:run=[]
        run.append(v)
        if run[-1][0]-run[0][0]>=600:
            first=dict(start_min=run[0][0]/60,confirmed_min=run[-1][0]/60,max_cv=max(q[1] for q in run),max_rate=max(q[2] for q in run));break
    results[method]=dict(pp=(np.ptp(z,axis=0)/z.mean(axis=0)*100).tolist(),cv=(z.std(axis=0,ddof=1)/z.mean(axis=0)*100).tolist(),endpoint=((y[sec>sec[-1]-10].mean(axis=0)/y[sec<10].mean(axis=0)-1)*100).tolist(),stable=first,positive=bool((y>0).all()))
checks=[]
for k,f in enumerate(env):
    q=integ(f['x']);peaks=f['x'].max(axis=1)
    checks.append(dict(group=k+1,frames=len(peaks),selected=len(f['t'][selected[k]]),peak_min=float(peaks.min()),peak_max=float(peaks.max()),cv_raw=(q.std(axis=0,ddof=1)/q.mean(axis=0)*100).tolist(),net_background_integrals=(bg[k]-1000*np.array([280,80,100,100])).tolist()))
# Independently subtract interpolated spectra before wavelength integration.
bs=np.array([f['x'][s].mean(axis=0) for f,s in zip(env,selected)])
for i in [0,100,3000,6000,len(t)-1]:
    spec=np.array([np.interp(t[i],bt,bs[:,j]) for j in range(len(w))])
    assert np.allclose(integ(x[i]-spec)[0],nets['三背景时间插值'][i],rtol=1e-12,atol=1e-7)
for y in nets.values():assert np.allclose(y[:,0],y[:,1:].sum(axis=1),atol=1e-7)
assert abs(results['固定环境1选15帧']['pp'][0]-1.665305707)<1e-8
with (OUT/'背景逐帧核查.csv').open('w',encoding='utf-8-sig',newline='') as out:
    writer=csv.writer(out);writer.writerow(['组','帧','时间','用于主对比','峰值DN',*names])
    for k,f in enumerate(env):
        q=integ(f['x'])
        for i in range(len(q)):writer.writerow([k+1,i+1,dt.datetime.fromtimestamp(f['t'][i]).isoformat(),k!=0 or 2<=i<17,f['x'][i].max(),*q[i]])
with (OUT/'逐帧处理结果.csv').open('w',encoding='utf-8-sig',newline='') as out:
    writer=csv.writer(out);writer.writerow(['秒',*[m+'_'+n for m in nets for n in names]])
    for i in range(len(t)):writer.writerow([sec[i],*[float(v) for y in nets.values() for v in y[i]]])
svg=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1100 740"><rect width="1100" height="740" fill="white"/><g font-family="Microsoft YaHei" font-size="14">']
for j in range(4):
    curves=[]
    for method in list(nets)[:2]:
        y=nets[method];ref=y[sec<10,j].mean();xx=[];yy=[]
        for b in range(int(sec[-1]//10)+1):
            mask=(sec>=b*10)&(sec<(b+1)*10)
            xx.append((b+.5)/6);yy.append((y[mask,j].mean()/ref-1)*100 if mask.sum()>=10 else np.nan)
        curves.append((method,xx,yy))
    ox=70+(j%2)*550;oy=45+(j//2)*370
    low=min(v for _,_,yy in curves for v in yy if np.isfinite(v))-.5;high=.5
    Y=lambda v:oy+260-(v-low)/(high-low)*240
    svg.append(f'<text x="{ox}" y="{oy-15}">{names[j]}：相对首10秒变化 / %</text>')
    for v in np.linspace(low,high,5):svg.append(f'<path d="M{ox} {Y(v)}h450" stroke="#ddd"/><text x="{ox-50}" y="{Y(v)}">{v:.1f}</text>')
    for v in range(0,61,10):svg.append(f'<text x="{ox+v*7.5}" y="{oy+282}">{v}</text>')
    for k,(method,xx,yy) in enumerate(curves):
        d=[];gap=True;color=['#287dc1','#c74b49'][k]
        for a,b in zip(xx,yy):
            if not np.isfinite(b):gap=True;continue
            d.append(f'{"M" if gap else "L"}{ox+a*7.5:.2f} {Y(b):.2f}');gap=False
        svg.append(f'<path d="{" ".join(d)}" stroke="{color}" fill="none" stroke-width="1.5"/><text x="{ox+k*225}" y="{oy+330}" fill="{color}">{method}</text>')
    svg.append(f'<text x="{ox+100}" y="{oy+307}">相对首帧时间 / min</text>')
svg.append('</g></svg>');(OUT/'背景处理对比.svg').write_text(''.join(svg),encoding='utf-8')
report={'background_checks':checks,'background_relative_change_pct':((bg/bg[0]-1)*100).tolist(),'results':results}
(OUT/'结果.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
text='# 实验A：三组环境背景重算\n\n沿用相同6899帧亮场记录，仅改变背景处理，避免将数据范围变化混入方法比较。环境1采用已选第3～17帧；环境2、3分别采用现有文件全部18、26帧。三组均为N模式，亮场减背景时1000 DN偏置抵消，不再额外扣除。\n\n时间插值：以各组所选帧平均时刻及平均光谱为节点，节点间线性插值；早于首节点采用环境1，不向外延伸斜率。环境3虽晚于最后亮场记录，仍参与环境2至3之间的背景估计。\n\n'
text+='|方法|总量峰峰变化%（20–50 min）|蓝%|绿%|红%|总量首末变化%|\n|---|---:|---:|---:|---:|---:|\n'
for m,r in results.items():text+='|'+m+'|'+'|'.join(f'{v:.3f}' for v in [*r['pp'],r['endpoint'][0]])+'|\n'
text+='\n主对比保留环境2、3全部已导出帧，未仅凭幅值高低删帧。逐帧核查另表保留。两种背景方法都需要假设：固定法假设背景不随时间改变，插值法假设三组背景可比且变化近似线性。插值结果作为背景敏感性对比，不单凭插值结果判定真实灯具漂移。\n\n![背景处理对比](背景处理对比.svg)\n'
text+='\n## 重算结论\n\n三组背景处理对结论有显著影响。固定环境1时，总量20～50分钟峰—峰变化为1.665%；三组背景按时间插值后为5.317%，首末下降由3.542%变为8.943%。环境1改用全部30帧后，插值结果仍为4.914%，因此差异不只由环境1选帧造成。\n\n采用环境1所选15帧及环境2、3插值时，未找到连续10分钟满足双判据的记录；环境1改用30帧时，在13.90～23.90分钟找到连续合格判定。稳定时间对背景处理与选帧敏感，不能确定统一的最低预热时间。\n\n环境2、3整段总积分的帧间CV分别为3.458%、10.470%（含偏置导出响应），不是两组均值之间的变化率。环境3尤其缺乏稳定背景平台的证据；本次不以幅值为由继续删帧，也不将插值法自动认作真实背景。\n\n最终结论：当前数据可见响应缓慢下降，但“总量漂移小于2%、已经稳定达标”不能作为不依赖背景处理方式的最终结论。三组背景重算已完成，后续应使用与亮场同位置、同视场条件下的交替背景或同步参考监测确定真实变化。\n'
(OUT/'复核报告.md').write_text(text,encoding='utf-8')
table='<table><tr><th>处理方法</th><th>总量</th><th>蓝</th><th>绿</th><th>红</th><th>总量首末变化</th></tr>'
for m,r in results.items():table+='<tr><td>'+html.escape(m)+'</td>'+''.join(f'<td>{v:.3f}%</td>' for v in [*r['pp'],r['endpoint'][0]])+'</tr>'
table+='</table>'
doc='<html lang="zh-CN"><meta charset="utf-8"><title>三组背景重算</title><style>body{max-width:1050px;margin:35px auto;font:16px/1.8 Microsoft YaHei;color:#243448}table{border-collapse:collapse;width:100%}td,th{border:1px solid #bbb;padding:8px}svg{width:100%}pre{white-space:pre-wrap;font:inherit}</style><h1>实验A：三组环境背景重算</h1><p>表中总量、蓝、绿、红为20～50分钟已测数据的峰—峰变化。全部方法使用相同6899帧亮场。</p>'+table+''.join(svg)+'<pre>'+html.escape(text.replace('![背景处理对比](背景处理对比.svg)',''))+'</pre></html>'
(OUT/'复核报告.html').write_text(doc,encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))

# Current user-selected method: complete environment 1, fixed throughout.
dest=ROOT/'环境1完整30帧重算';dest.mkdir(exist_ok=True)
method='固定环境1完整30帧';r=results[method];y=nets[method];stable=r['stable']
direct=integ(x[[0,100,3000,-1]]-env[0]['x'].mean(axis=0))
assert np.allclose(direct,y[[0,100,3000,-1]],rtol=1e-12,atol=1e-7)
with (dest/'逐帧净积分.csv').open('w',encoding='utf-8-sig',newline='') as f:
    writer=csv.writer(f);writer.writerow(['相对首帧分钟',*names]);writer.writerows([[sec[i]/60,*y[i]] for i in range(len(y))])
with (dest/'固定背景光谱.csv').open('w',encoding='utf-8-sig',newline='') as f:
    writer=csv.writer(f);writer.writerow(['波长nm','环境1全部30帧平均导出N']);writer.writerows(zip(w,env[0]['x'].mean(axis=0)))
(dest/'结果.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
rows='\n'.join('|'+names[j]+'|'+ '|'.join(f'{v:.3f}' for v in [r['cv'][j],r['pp'][j],r['endpoint'][j]])+'|' for j in range(4))
summary=(f"找到连续10分钟满足总量稳定双判据的记录；首次合格窗口结束于首帧后{stable['start_min']:.2f}分钟，确认时刻为{stable['confirmed_min']:.2f}分钟。该连续判定区间最大滑动CV为{stable['max_cv']:.3f}%，最大变化率绝对值为{stable['max_rate']:.3f}%/min。" if stable else '未找到连续10分钟满足总量稳定双判据的记录。')
md=f'''# 实验 A　单灯冷启动与输出稳定性

## A.1 实验目的
评价持续点亮过程中总积分响应和分波段响应的短时稳定性及长时间变化，为后续光谱实验提供依据。

## A.2 实验数据与预处理
采用2026年9月20日OCR-25F02100、32 ms、N模式的6899帧亮场记录，时间为14:29:04.359—15:26:29.102，跨度57.41分钟。灯持续点亮，以首帧记录作为时间零点。

环境1完整30帧逐波长求平均，作为全程固定背景，不再选取其中15帧。环境2、3保留作对照，不参与本版扣背景。N模式已扣暗，亮场与背景相减时相同1000 DN偏置抵消，净信号不再额外减1000。

净信号：Sᵢ(λ)=Nᵢ(λ)−平均环境1(λ)。

## A.3 评价方法与判据
对净光谱采用梯形积分，波段边界线性插值，得到总量420—700 nm、蓝420—500 nm、绿500—600 nm、红600—700 nm响应，单位DN·nm。

5分钟滑动窗口每秒更新，以样本标准差计算CV=标准差/均值×100%；归一化变化率为窗口内响应对时间的线性拟合斜率/均值×100%，单位%/min。总量CV≤1%且变化率绝对值≤0.2%/min，连续满足10分钟。窗口内缺测超过2秒不跨段拼接，边缘覆盖容差为1秒。

20—50分钟已测样本峰—峰变化=(最大值−最小值)/均值×100%；首末变化=(末10秒均值/首10秒均值−1)×100%。后者覆盖本版57.41分钟记录。两项指标不混用。

## A.4 实验结果
### A.4.1 短时稳定性
{summary}

### A.4.2 区间变化及首末变化
|波段|20—50分钟CV/%|20—50分钟峰—峰变化/%|57分钟首末变化/%|
|---|---:|---:|---:|
{rows}

20—50分钟共3534帧。表中区间统计使用原始逐帧净积分，不使用绘图平滑值。

## A.5 结论与适用范围
（1）按环境1完整30帧固定扣背景，已测总量存在连续10分钟满足短时稳定双判据的记录。

（2）20—50分钟已测总量峰—峰变化为{r['pp'][0]:.3f}%；蓝、绿、红分别为{r['pp'][1]:.3f}%、{r['pp'][2]:.3f}%、{r['pp'][3]:.3f}%。总量和绿波段低于2%，蓝、红波段高于2%。

（3）约57分钟记录中总量首末下降{abs(r['endpoint'][0]):.3f}%，存在缓慢下降。

（4）结果采用全程固定背景口径。最低实际预热时间未确定，7.73分钟是首个可评价合格窗口的结束时刻，不是必须等待的预热时间。
'''
(dest/'分析报告.md').write_text(md,encoding='utf-8')
body=[]
for line in md.splitlines():
    if line.startswith('### '):body.append('<h3>'+html.escape(line[4:])+'</h3>')
    elif line.startswith('## '):body.append('<h2>'+html.escape(line[3:])+'</h2>')
    elif line.startswith('# '):body.append('<h1>'+html.escape(line[2:])+'</h1>')
    elif line.startswith('|波段'):
        body.append('<table><tr><th>波段</th><th>20—50分钟CV/%</th><th>20—50分钟峰—峰变化/%</th><th>57分钟首末变化/%</th></tr>')
        for j in range(4):body.append('<tr><td>'+names[j]+'</td>'+''.join(f'<td>{v:.3f}</td>' for v in [r['cv'][j],r['pp'][j],r['endpoint'][j]])+'</tr>')
        body.append('</table>')
    elif line and not line.startswith('|'):body.append('<p>'+html.escape(line)+'</p>')
page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>实验A—环境1完整30帧固定背景</title><style>body{max-width:1050px;margin:35px auto;font:16px/1.8 Microsoft YaHei;color:#243448}table{border-collapse:collapse;width:100%}td,th{border:1px solid #bbb;padding:8px}</style>'+''.join(body)+'</html>'
(dest/'分析报告.html').write_text(page,encoding='utf-8')
print('CURRENT_30_FRAME_RESULT',json.dumps(r,ensure_ascii=False))
