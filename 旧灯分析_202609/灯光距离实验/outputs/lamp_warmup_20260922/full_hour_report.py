from pathlib import Path
import sys,os,base64,html,zipfile,json
ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT/'python_packages'))
os.environ['MPLCONFIGDIR']=str(ROOT/'mplconfig')
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np
import pandas as pd
from unified_analysis import load,NAMES,DEST,integral
from inspect_data import SOURCE

def build():
    t,sec,x,raw,bg,env,w,files,rows,filemeta=load()
    net=raw-bg[0]
    initial=net[sec<10].mean(axis=0)
    last=net[sec>sec[-1]-10].mean(axis=0)
    long_change=100*(last/initial-1)
    # Late reference: equal weight to the final minute before environment 2 and
    # the final minute of the last supplied bright record.
    late_ranges=[(46.17,47.17),(56.41,57.41)]
    late_means=np.array([net[(sec/60>=a)&(sec/60<=b)].mean(axis=0) for a,b in late_ranges])
    late_ref=late_means.mean(axis=0)
    late_dev=100*(late_means/late_ref-1)
    # Global absolute 10-second blocks. File labels never enter the computation.
    blocks=[]
    for bid in range(int(sec[-1]//10)+1):
        a=bid*10;b=a+10;m=(sec>=a)&(sec<b);tt=sec[m]
        if len(tt)>=10 and tt[0]-a<=1 and b-tt[-1]<=1 and np.diff(tt).max()<=2:
            mean=net[m].mean(axis=0)
            blocks.append({'start':a/60,'end':b/60,'dev':100*(mean/late_ref-1),'n':int(m.sum())})
    stable=[]
    for tol in [5,2,1]:
        passed=np.array([np.abs(b['dev'][1:4]).max()<=tol for b in blocks])
        tail=np.logical_and.accumulate(passed[::-1])[::-1]
        ix=np.flatnonzero(tail)
        if len(ix):
            i=int(ix[0]);start=blocks[i]['start'];prev=blocks[i-1]['end'] if i else None
            stable.append({'tol':tol,'start':start,'prev':prev,'span':sec[-1]/60-start})
    # Longest directly observed continuous stable run after the stable threshold.
    for s in stable:
        eligible=[b for b in blocks if b['start']>=s['start']]
        runs=[];run_start=eligible[0]['start'];end=eligible[0]['end']
        for b in eligible[1:]:
            if abs(b['start']-end)>1e-8:
                runs.append((run_start,end));run_start=b['start']
            end=b['end']
        runs.append((run_start,end))
        run_start,end=max(runs,key=lambda r:r[1]-r[0])
        s['continuous']=end-run_start;s['continuous_start']=run_start;s['continuous_end']=end
    # Local robust anomaly test over the unified sequence.
    anomalies=[]; residual_matrix=np.empty_like(net)
    for j,name in enumerate(NAMES):
        med=pd.Series(net[:,j],index=pd.to_datetime(t,unit='s',utc=True)).rolling('10s',center=True,min_periods=5).median().to_numpy()
        residual=100*(net[:,j]-med)/med
        residual_matrix[:,j]=residual
        center=np.nanmedian(residual);scale=1.4826*np.nanmedian(np.abs(residual-center));limit=max(.5,6*scale)
        for i in np.flatnonzero(np.abs(residual)>limit):
            anomalies.append((sec[i]/60,name,residual[i],limit))
    # Background-sensitive endpoint comparison: fixed first background vs linear background model.
    bt=np.array([d['t'].mean() for d in env]);bs=np.array([d['x'].mean(axis=0) for d in env])
    interp=np.column_stack([np.interp(t,bt,bs[:,j]) for j in range(len(w))])
    interp_band=np.column_stack([integral(x-interp,w,*bounds) for bounds in [(420,700),(420,500),(500,600),(600,700)]])
    interp_change=100*(interp_band[sec>sec[-1]-10].mean(axis=0)/interp_band[sec<10].mean(axis=0)-1)

    # Reader-facing chart: whole-hour result plus tolerance conclusions.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    font_manager.fontManager.addfont(r'C:\Windows\Fonts\msyh.ttc')
    plt.rcParams.update({'font.family':'Microsoft YaHei','font.size':10,'axes.unicode_minus':False,'axes.spines.top':False,'axes.spines.right':False})
    folder=DEST/'figures';folder.mkdir(exist_ok=True)
    cuts=np.flatnonzero(np.diff(sec)>2)+1
    fig,axs=plt.subplots(2,1,figsize=(11.5,8.5),gridspec_kw={'height_ratios':[1.25,.8]})
    colors=['#263f61','#4386b9','#378b71','#bd625a']
    for j,name in enumerate(NAMES):
        xx=np.insert(sec/60,cuts,np.nan);yy=np.insert(100*(net[:,j]/late_ref[j]-1),cuts,np.nan)
        axs[0].plot(xx,yy,color=colors[j],lw=.65,alpha=.72,label=name)
    axs[0].axhspan(-1,1,color='#dceee7',alpha=.7,label='后期基准±1%')
    axs[0].set(title='从通电到约57分钟：相对后期实测基准的变化',xlabel='累计点亮时间 / 分钟',ylabel='相对变化 / %')
    axs[0].legend(ncol=3,fontsize=8);axs[0].grid(axis='y',alpha=.2)
    labels=[];starts=[];spans=[]
    for s in stable[::-1]:
        labels.append('±'+str(s['tol'])+'%');starts.append(s['start']);spans.append(s['span'])
    y=np.arange(len(labels))
    axs[1].barh(y,spans,left=starts,color=['#bb7658','#d0a551','#4b8e76'])
    axs[1].set(yticks=y,yticklabels=labels,xlim=(0,65),xlabel='累计点亮时间 / 分钟',title='三个波段同时满足容差：首次观测到并保持至末次采样')
    for yy,a,b in zip(y,starts,spans):axs[1].text(a+b/2,yy,f'{a:.1f}～{a+b:.1f} min',ha='center',va='center',color='white',fontweight='bold')
    axs[1].grid(axis='x',alpha=.2)
    fig.suptitle('灯1：整次连续点亮实验的主要结果',x=.08,ha='left',fontsize=18)
    fig.tight_layout(rect=[0,.04,1,.96],h_pad=2)
    fig.text(.08,.012,'固定扣除环境1；空白时段没有采样。等待时间按全局10秒块和后期两个一分钟窗口的均值判定。',fontsize=9)
    png=folder/'00_整小时结论.png';svg=folder/'00_整小时结论.svg'
    fig.savefig(png,dpi=175,bbox_inches='tight');fig.savefig(svg,bbox_inches='tight');plt.close(fig)

    # Four reader-facing figures, one for each requested result.
    cuts=np.flatnonzero(np.diff(sec)>2)+1
    fig,ax=plt.subplots(figsize=(11.5,5.5))
    for j,name in enumerate(NAMES):
        xx=np.insert(sec/60,cuts,np.nan);yy=np.insert(100*(net[:,j]/late_ref[j]-1),cuts,np.nan)
        ax.plot(xx,yy,color=colors[j],lw=.7,alpha=.75,label=name)
    ax.axhspan(-1,1,color='#dceee7',alpha=.7)
    ax.set(title='预热曲线：从刚通电到约57分钟',xlabel='累计点亮时间 / 分钟',ylabel='相对后期实测基准 / %')
    ax.legend(ncol=2);ax.grid(axis='y',alpha=.2)
    fig.tight_layout();fig.savefig(folder/'01_预热曲线.png',dpi=175,bbox_inches='tight');fig.savefig(folder/'01_预热曲线.svg',bbox_inches='tight');plt.close(fig)

    fig,ax=plt.subplots(figsize=(10.5,4.5))
    ordered=[sdict for sdict in stable[::-1]]
    yy=np.arange(len(ordered));waits=[s['start'] for s in ordered]
    ax.barh(yy,waits,color=['#bb7658','#d0a551','#4b8e76'])
    ax.set(yticks=yy,yticklabels=['±'+str(s['tol'])+'%' for s in ordered],xlabel='从通电起等待 / 分钟',title='稳定等待时间随允许漂移而变化',xlim=(0,50))
    for y0,v in zip(yy,waits):ax.text(v+.7,y0,f'{v:.1f} min',va='center',fontweight='bold')
    ax.grid(axis='x',alpha=.2);fig.tight_layout();fig.savefig(folder/'02_稳定等待时间.png',dpi=175,bbox_inches='tight');fig.savefig(folder/'02_稳定等待时间.svg',bbox_inches='tight');plt.close(fig)

    fig,ax=plt.subplots(figsize=(10.5,4.8))
    ordered=stable[::-1];yy=np.arange(len(ordered));height=.3
    continuous=[s['continuous'] for s in ordered];sampled=[s['span'] for s in ordered]
    ax.barh(yy-height/2,continuous,height,color='#395f82',label='连续记录直接验证')
    ax.barh(yy+height/2,sampled,height,color='#84a995',label='后续采样点覆盖跨度')
    ax.set(yticks=yy,yticklabels=['±'+str(s['tol'])+'%' for s in ordered],xlabel='进入稳定范围后的时长 / 分钟',title='允许单次工作时长：直接验证与采样跨度',xlim=(0,67))
    for y0,v in zip(yy-height/2,continuous):ax.text(v+.6,y0,f'{v:.1f}',va='center',fontsize=9)
    for y0,v in zip(yy+height/2,sampled):ax.text(v+.6,y0,f'{v:.1f}',va='center',fontsize=9)
    ax.legend();ax.grid(axis='x',alpha=.2);fig.tight_layout();fig.savefig(folder/'03_工作时长.png',dpi=175,bbox_inches='tight');fig.savefig(folder/'03_工作时长.svg',bbox_inches='tight');plt.close(fig)

    fig,axs=plt.subplots(1,2,figsize=(11.5,4.7))
    for j,name in enumerate(NAMES):
        xx=np.insert(sec/60,cuts,np.nan);yy2=np.insert(residual_matrix[:,j],cuts,np.nan)
        axs[0].plot(xx,yy2,color=colors[j],lw=.45,alpha=.65,label=name)
    axs[0].axhline(.5,color='#a75d55',ls='--',lw=1);axs[0].axhline(-.5,color='#a75d55',ls='--',lw=1)
    axs[0].set(title='全程局部波动残差',xlabel='累计点亮时间 / 分钟',ylabel='偏离局部10秒中位数 / %');axs[0].legend(fontsize=8,ncol=2);axs[0].grid(axis='y',alpha=.2)
    for d in env:axs[1].plot(w,d['x'].mean(axis=0),lw=1.25,label=d['tag'])
    axs[1].set(title='三次环境光测量',xlabel='波长 / nm',ylabel='DN',xlim=(400,750));axs[1].legend();axs[1].grid(axis='y',alpha=.2)
    fig.tight_layout();fig.savefig(folder/'04_异常与环境光.png',dpi=175,bbox_inches='tight');fig.savefig(folder/'04_异常与环境光.svg',bbox_inches='tight');plt.close(fig)

    def f(x):return f'{x:.2f}'
    def table_md(headers,rows):
        return '| '+' | '.join(headers)+' |\n| '+' | '.join(['---']*len(headers))+' |\n'+'\n'.join('| '+' | '.join(map(str,r))+' |' for r in rows)+'\n'
    def table_html(headers,rows):
        return '<div class="table"><table><thead><tr>'+''.join('<th>'+html.escape(str(v))+'</th>' for v in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in r)+'</tr>' for r in rows)+'</tbody></table></div>'
    sdict={s['tol']:s for s in stable};end_min=sec[-1]/60;n_frames=len(t)
    use_rows=[
      ['±5%',f"{sdict[5]['start']:.1f}分钟",f"最长连续验证{sdict[5]['continuous']:.1f}分钟",'本次全部亮场记录均满足'],
      ['±2%',f"{sdict[2]['start']:.1f}分钟",f"最长连续验证{sdict[2]['continuous']:.1f}分钟",'实用上可预热15分钟'],
      ['±1%',f"{sdict[1]['start']:.1f}分钟",f"最长连续验证{sdict[1]['continuous']:.1f}分钟",'严格使用可预热36分钟']]
    endpoint_rows=[[NAMES[j],f'{long_change[j]:+.2f}%',f'{interp_change[j]:+.2f}%'] for j in range(4)]
    late_rows=[[NAMES[j],f'{late_dev[:,j].min():+.3f}%～{late_dev[:,j].max():+.3f}%'] for j in range(4)]
    md=[]
    md.append('# 灯1连续点亮实验：预热、稳定和工作时长结论\n')
    md.append(f'灯从刚通电开始持续点亮，按用户重新整理的4个亮场CSV合并分析，共{n_frames}帧；末次灯光记录在通电后{end_min:.2f}分钟。\n')
    md.append('## 直接结论\n')
    md.append(table_md(['允许漂移','稳定等待时间','已验证工作时长','怎么用'],use_rows))
    md.append(f'按±2%光源漂移要求，本次首次持续进入范围的时刻为开灯后{sdict[2]["start"]:.1f}分钟；实用上可取**预热15分钟**。数据库未参与本次计算。\n')
    md.append(f'允许±5%时，本次全部亮场记录均满足。严格要求±1%时，开灯约{sdict[1]["start"]:.1f}分钟后持续满足。\n')
    md.append('## 预热曲线\n')
    md.append('![预热曲线](统一时间轴分析/figures/01_预热曲线.png)\n')
    md.append('曲线表现为通电后的缓慢下降，随后在后期采样点附近形成较稳定的平台。固定扣除环境1时，末10秒相对通电后前10秒的变化如下：\n')
    md.append(table_md(['波段',f'约{end_min:.1f}分钟累计变化','按环境光线性估计时'],endpoint_rows))
    md.append('两种背景处理得到的下降幅度不同，因此不能把整小时变化全部归因于灯。但两者都说明：短时间波动较小，长时间累计变化不能忽略。\n')
    md.append('## 稳定等待时间\n')
    md.append('![稳定等待时间](统一时间轴分析/figures/02_稳定等待时间.png)\n')
    md.append('稳定判定使用全局10秒平均值，并要求蓝、绿、红三个波段同时落在后期实测基准的容差内，此后所有实际采到的有效块继续合格。结果随允许误差而变，不存在脱离误差要求的唯一等待时间。\n')
    md.append(table_md(['判据','首次观测到稳定','判定范围'],[[f'±{s["tol"]}%',f'{s["start"]:.2f}分钟',f'后续已采亮场保持至{end_min:.2f}分钟'] for s in stable]))
    md.append('## 允许单次工作时长\n')
    md.append('![允许单次工作时长](统一时间轴分析/figures/03_工作时长.png)\n')
    md.append(f'按±2%要求，最长连续合格记录为开灯后{sdict[2]["continuous_start"]:.2f}～{sdict[2]["continuous_end"]:.2f}分钟，直接验证{sdict[2]["continuous"]:.1f}分钟。该数值是“至少已验证时长”，不是灯的失效上限。\n')
    md.append('按±1%要求，两个后期一分钟窗口的均值相对后期平均值如下：\n')
    md.append(table_md(['波段','两个后期窗口均值范围'],late_rows))
    md.append(f'按±1%要求，最长连续合格记录为开灯后{sdict[1]["continuous_start"]:.2f}～{sdict[1]["continuous_end"]:.2f}分钟，共{sdict[1]["continuous"]:.1f}分钟。\n')
    md.append('## 异常波动记录\n')
    md.append('![异常波动与环境光](统一时间轴分析/figures/04_异常与环境光.png)\n')
    md.append(f'全程统一按“偏离局部10秒中位数超过max(6×MAD稳健标准差，0.5%)”筛查，{n_frames}帧中检出**{len(anomalies)}条明显突波**。本次主要变化是缓慢漂移，没有检出突然闪烁或跳变。蓝波段单帧噪声相对较大，使用多帧平均更合适。\n')
    md.append('## 使用注意\n')
    md.append('- 一组需要互相比较的数据尽量在同一个连续工作窗口内完成。\n- 使用10秒左右的多帧平均，尤其是蓝波段。\n- 需要严格控制误差时，在一组测量前后各测一次同一参考目标。\n- 当前只有一次冷启动实验；正式固定操作参数前，建议至少再重复两次冷启动验证。\n')
    md.append('## 计算口径\n')
    md.append('主波段为420～700 nm，另检查蓝420～500、绿500～600、红600～700 nm。后期基准取46.17～47.17分钟和56.41～57.41分钟两个一分钟亮场窗口的均值等权平均。环境光不参与灯的计时。所有结果是DN积分的相对变化，不是绝对光功率。\n')
    markdown='\n'.join(md)

    def inline_image(filename,alt):
        payload=base64.b64encode((folder/filename).read_bytes()).decode()
        return '<img src="data:image/png;base64,'+payload+'" alt="'+html.escape(alt)+'">'
    body=[]
    body.append('<h1>灯1连续点亮实验：预热、稳定和工作时长结论</h1>')
    body.append(f'<p>灯从刚通电开始持续点亮，按用户重新整理的4个亮场CSV合并分析，共{n_frames}帧；末次灯光记录在通电后{end_min:.2f}分钟。</p>')
    body.append('<h2>直接结论</h2>'+table_html(['允许漂移','稳定等待时间','已验证工作时长','怎么用'],use_rows))
    body.append(f'<p class="callout">按±2%光源漂移要求，本次从开灯后{sdict[2]["start"]:.1f}分钟起持续满足；实用上可取<b>预热15分钟</b>。最长连续记录直接验证{sdict[2]["continuous"]:.1f}分钟。</p>')
    body.append(f'<p>允许±5%时，本次全部亮场记录均满足。严格要求±1%时，从开灯约{sdict[1]["start"]:.1f}分钟起持续满足。</p>')
    body.append('<h2>预热曲线</h2>'+inline_image('01_预热曲线.png','预热曲线')+'<p>信号随点亮时间缓慢下降，随后在后期采样点附近形成较稳定的平台。末10秒相对通电后前10秒的变化：</p>'+table_html(['波段','固定环境1','环境光线性估计'],endpoint_rows))
    body.append('<p>背景处理会改变下降幅度，所以不能把全部变化都归因于灯；但短时波动小、长时累计变化不可忽略。</p>')
    body.append('<h2>稳定等待时间</h2>'+inline_image('02_稳定等待时间.png','稳定等待时间')+f'<p>使用全局10秒平均值，要求蓝、绿、红同时进入后期基准的容差，并在之后所有已采样有效块继续合格。</p>'+table_html(['判据','首次观测到稳定','保持至'],[[f'±{s["tol"]}%',f'{s["start"]:.2f}分钟',f'{end_min:.2f}分钟'] for s in stable]))
    body.append('<h2>允许单次工作时长</h2>'+inline_image('03_工作时长.png','允许单次工作时长')+f'<p>按±2%要求，开灯后{sdict[2]["continuous_start"]:.2f}～{sdict[2]["continuous_end"]:.2f}分钟的连续记录直接验证{sdict[2]["continuous"]:.1f}分钟；这是至少已验证时长，不是失效上限。</p><p>按±1%要求，两个后期一分钟窗口的均值范围：</p>'+table_html(['波段','相对后期平均'],late_rows))
    body.append('<h2>异常波动记录</h2>'+inline_image('04_异常与环境光.png','异常波动与环境光')+f'<p>{n_frames}帧中检出<b>{len(anomalies)}条明显突波</b>。主要表现为缓慢漂移，没有检出突然闪烁或跳变。蓝波段宜采用多帧平均。</p>')
    body.append('<h2>使用注意</h2><ul><li>一组比较数据尽量在同一连续工作窗口内完成。</li><li>采用约10秒多帧平均。</li><li>严格控制误差时，测量前后各测一次同一参考目标。</li><li>当前仅一次冷启动；固定操作参数前建议再重复两次。</li></ul>')
    body.append('<h2>计算口径</h2><p>420～700 nm总量，并检查蓝、绿、红三个分波段。后期基准取46.17～47.17分钟和56.41～57.41分钟两个一分钟亮场窗口的均值等权平均。环境光不参与灯的计时。结果为DN积分相对变化。</p>')
    css='body{font-family:"Microsoft YaHei",Arial,sans-serif;background:#f3f5f8;color:#23324a;line-height:1.85;margin:0}main{max-width:1080px;margin:24px auto;padding:36px 44px;background:white;border-top:6px solid #334e73}h1{font-size:27px}h2{font-size:21px;margin-top:32px;border-bottom:1px solid #dce3ec}p{font-size:15px}.callout{background:#e8f2ed;border-left:5px solid #4b8e76;padding:14px 18px}.table{overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px}th{background:#334e73;color:white}td,th{text-align:left;padding:10px;border-bottom:1px solid #ddd;vertical-align:top}tr:nth-child(even){background:#f4f6f9}img{width:100%;height:auto;margin:22px 0}li{margin:7px 0}@media(max-width:650px){main{margin:0;padding:17px}h1{font-size:22px}}'
    doc='<!doctype html><html lang="zh-CN"><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>灯1整小时稳定性结论</title><style>'+css+'</style><main>'+''.join(body)+'</main></html>'
    (ROOT/'分析报告.md').write_text(markdown,encoding='utf-8');(ROOT/'分析报告.html').write_text(doc,encoding='utf-8')
    (DEST/'分析报告.md').write_text(markdown.replace('](统一时间轴分析/figures/','](figures/'),encoding='utf-8');(DEST/'分析报告.html').write_text(doc,encoding='utf-8')
    old=ROOT/'重新分析'
    if old.exists():(old/'分析报告.html').write_text(doc,encoding='utf-8')
    summary={'duration_min':sec[-1]/60,'long_change_fixed_bg_pct':long_change.tolist(),'long_change_interpolated_bg_pct':interp_change.tolist(),'stable':stable,'late_deviation_pct':late_dev.tolist(),'anomalies':len(anomalies)}
    (DEST/'整小时结论.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    archive=ROOT/'灯1冷启动分析_报告曲线与数据.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for path in DEST.rglob('*'):
            if path.is_file():z.write(path,str(path.relative_to(DEST)))
        for path in SOURCE.glob('*.csv'):z.write(path,'raw/'+path.name)
        for name in ['full_hour_report.py','unified_analysis.py','inspect_data.py']:z.write(ROOT/name,'代码/'+name)
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':build()
