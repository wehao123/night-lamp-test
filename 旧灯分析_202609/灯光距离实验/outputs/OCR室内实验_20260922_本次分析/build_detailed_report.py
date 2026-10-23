"""Build the detailed report from validated outputs, without changing raw observations."""
from pathlib import Path
import csv, json, html, statistics, math

P = Path(__file__).resolve().parent
S = json.loads((P/'summary.json').read_text(encoding='utf-8'))
def read(name):
    with (P/'tables'/name).open(encoding='utf-8-sig') as f:return list(csv.DictReader(f))
L = read('02_线性度逐通道.csv')
C = sorted(S['conditions'],key=lambda x:(x['voltage_V'],x['integration_ms']))
H=[]; M=[]; toc=[]; section_ids=[]
def title(text):
    H.append('<h1>'+html.escape(text)+'</h1>');M.append('# '+text+'\n')
def section(text,level=2):
    ident='s'+str(len(section_ids)+1)
    section_ids.append(ident)
    if level==2:toc.append((ident,text))
    H.append(f'<h{level} id="{ident}">'+html.escape(text)+f'</h{level}>');M.append('#'*level+' '+text+'\n')
def para(text):H.append('<p>'+html.escape(text)+'</p>');M.append(text+'\n')
def bullets(items):
    H.append('<ul>'+''.join('<li>'+html.escape(x)+'</li>' for x in items)+'</ul>');M.append('\n'.join('- '+x for x in items)+'\n')
def formula(expr,explain=''):
    H.append('<div class="formula">'+html.escape(expr)+'</div>');M.append('```text\n'+expr+'\n```\n')
    if explain:para(explain)
def table(headers,rows):
    rows=[[str(x) for x in r] for r in rows]
    H.append('<div class="table-wrap"><table><thead><tr>'+''.join('<th>'+html.escape(x)+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(x)+'</td>' for x in r)+'</tr>' for r in rows)+'</tbody></table></div>')
    M.append('| '+' | '.join(headers)+' |\n| '+' | '.join(['---']*len(headers))+' |\n'+'\n'.join('| '+' | '.join(r)+' |' for r in rows)+'\n')
def figure(stem,caption):
    H.append(f'<figure><a href="figures/{stem}.png"><img loading="lazy" src="figures/{stem}.png" alt="{html.escape(caption)}"></a><figcaption>{html.escape(caption)}　<a href="figures/{stem}.svg">下载矢量图</a></figcaption></figure>')
    M.append(f'![{caption}](figures/{stem}.png)\n')
def quantile(a,q):
    a=sorted(a); idx=(len(a)-1)*q; lo=int(idx); hi=math.ceil(idx);return a[lo]+(a[hi]-a[lo])*(idx-lo)

title('OCR-25F02100 光谱仪室内实验分析报告')
para('详细版｜2026-09-22｜积分时间相对线性度、信噪比与不同电压下的弱光表现')
para('本报告分析12份线性度CSV及20份亮暗场CSV，覆盖全部288个原生通道，波长范围305.883–878.092 nm。全部原始帧保留，定量结果未使用平滑、滤波或插值。报告适用于本次已测条件的性能分析与参数筛选，不构成完整验收或通用设备规格。')
section('1. 主要结论与如何使用本报告')
bullets([
'线性度：六组呈现相近的码值依赖趋势。中间码值比例关系较好，高码值处长积分实测相对短积分外推偏低，低码值处分散较大。正式主指标为未经锚定归一化的γ＝理论值/实际值。',
'信噪比：短波端普遍弱于中长波段。时间加倍后，各电压档逐通道SNR改善倍数的中位数约1.51–1.55；改善不等于每个通道都按同一倍数增加。',
'弱光：最低已测60 V下，64→128 ms使SNR≥20的通道由235增加至264，仍有24个通道未达到该门槛。',
'高信号：76 V/64 ms虽然全部通道SNR≥20，但589.2–740.2 nm的78个通道超过80%原始量程。高SNR不能替代码值余量检查。',
'在本次短序列筛选下，72 V/64 ms推荐候选连续段为447.2–878.1 nm，60 V/128 ms为474.6–878.1 nm。这些范围尚未通过100帧漂移及最终线性度联合认证。',
'数据边界：信号帧数为30或50；无实测参考板亮度L。不能据此给出绝对最低可测亮度、精确饱和起点或最大允许积分时间。'])
para('阅读顺序：图1看原始非线性比值，图5看逐波长稳定性，图6查条件与波段，图12看综合取舍。图2仅辅助比较曲线形状，不用于报告原始线性误差。')

section('2. 实验数据与预处理')
section('2.1 数据分组、帧数与时间核查',3)
table(['数据类型','实际条件','重复帧数','说明'],[
['线性度','32→64 ms × 3W/4W/5W','3W、4W各30；5W各50','末尾64表示组内最大积分时间'],
['线性度','64→128 ms × 3W/4W','每档30','末尾128表示组内最大积分时间'],
['线性度','62→128 ms × 5W','每档30','短档文件名64MS，内部全部记录为62 ms'],
['信噪比/弱光','60、63 V：64/128 ms；68、72、76 V：32/64 ms','通常亮暗各30；76 V/32 ms亮暗各50','共10个条件，5档电压']])
para('“3W、4W、5W”保留为原始组标签，不推断为实测电功率。不同末尾组、不同组标签不能仅凭相同积分时间拼成固定光强的多点响应曲线。每帧的实际积分时间、时间戳及文件SHA256记录在01表。')
para('一个CSV的每一列时间戳对应一帧，每一行CH对应一个波长通道。288通道不是288次重复；30帧亮值加30帧暗值也不是60帧信号。暗场与亮场非同步采集，不按列序号强行相减。')
section('2.2 N、L、D及1000偏置',3)
table(['标识','含义','本次处理'],[['L','正常接收光时的亮值，含底值','逐帧减去同条件平均暗谱'],['D','遮光采集的暗值','求暗均值、暗标准差及暗漂移'],['N','设备已经扣暗后的码值','扣除已确认的1000偏置，不再减独立暗场']])
formula('线性度：Sᵢ(λ) = Nᵢ(λ) − b，b = 1000 DN\n信噪比/弱光：D̄(λ) = ΣDⱼ(λ)/nD；Sᵢ(λ) = Lᵢ(λ) − D̄(λ)')
para('根据上位机协议及李阳于2026年9月23日10:32–10:34的书面确认，L、D、N三种导出码值均含1000 DN偏置。以未加偏置量记为L₀、D₀，则L=L₀+1000，D=D₀+1000，N=(L₀−D₀)+1000。因此N−1000恢复净光，(L−1000)−(D−1000)=L−D。N=L−D的交流表述指去暗操作，不能将其与三种带偏置导出值之间的等式混用。该确认来自技术人员说明，未直接审计设备固件。')
para('为什么不能漏扣偏置：真实信号10000与20000本来满足倍增关系，若两者各加1000而不处理，则2×11000/21000＝1.04762，产生约4.76%的比值偏差。偏置不是随光信号同比例增长的部分。')
section('2.3 符号和统计口径',3)
table(['符号','含义'],[['λ','实际导出波长；保持原生非等间距网格'],['i、j；nL、nD','亮/净光帧、暗帧编号；对应帧数'],['S̄、sS','净光平均值、帧间样本标准差，单位DN'],['t短、t长','实际积分时间，单位ms'],['τ','组内实际采集经过时间，单位s；区别于积分时间t'],['γ','长积分理论净光/长积分实测净光，无量纲'],['δ','实测相对理论的偏差，分母为理论值'],['DN','数字码值，不是亮度、辐亮度或辐照度']])

section('3. 积分时间相对线性度：原理、公式与结果')
section('3.1 物理思路与适用前提',3)
para('固定光源、光路和采集设置，在同一波长处，理想净光信号应随积分时间成比例增长。类似稳定水流下接水，时间翻倍，水量应翻倍。以短积分为参考，推算长积分应测到的信号，再与实测比较。')
formula('理想响应：S(λ,t) = k(λ)·E(λ)·t\n长积分理论值：S理论,长(λ) = S̄短(λ)·t长/t短\n非线性比值：γ(λ) = S理论,长(λ)/S̄长(λ)')
para('E表示测量期间保持不变的入射光谱量，k是响应系数。本方法不需要知道E的绝对数值，但依赖它在长短积分之间稳定。短积分本身也可能有非线性，所以推算值不是独立的绝对真值。两次采集非同步且无同步亮度记录，整体偏差可能包含光源变化。')
table(['情况','32 ms净光','64 ms理论','64 ms实测','γ','含义'],[['理想比例',10000,20000,20000,'1.00000','符合比例关系'],['长积分偏低',10000,20000,19600,'1.02041','实际比理论低2%'],['长积分偏高',10000,20000,20400,'0.98039','实际比理论高2%']])
para('62→128 ms组使用128/62＝2.064516。若误用2，理论外推值会低3.125%。其余五组使用比例2。')
section('3.2 γ偏差、相对误差和±2%参考带的区别',3)
formula('图中比值偏差：εγ = (γ−1)×100% = (理论−实际)/实际×100%\n实测相对理论偏差：δ = (实际−理论)/理论×100% = (1/γ−1)×100%')
para('两者符号和分母不同，不能混写。下列相对误差统计统一使用δ；保留图1原有γ轴及0.98–1.02绿色参考带。这条带表示|γ−1|≤2%，换成δ约为−1.961%至+2.041%，并不是精确的δ±2%。')
para('±2%是本次描述性参考，不是原PDF规定的线性度验收限。也不是“相对最大拟合残差”：本次没有在每个波长上做多档积分时间直线拟合。每组只有两个时间点，带截距直线可以穿过两点，R²没有实质检验意义。')
linstats=[]
for q in S['linearity']:
    rows=[r for r in L if r['group']==q['group'] and r['both_SNR20']=='True']
    a=[float(r['actual_vs_ideal_percent']) for r in rows]
    linstats.append(dict(group=q['group'],n=len(a),median_delta_percent=statistics.median(a),p95_abs_delta_percent=quantile([abs(x) for x in a],.95),max_abs_delta_percent=max(abs(x) for x in a)))
table(['配对组','SNR均≥20的通道数','δ中位数','|δ|95分位','最大|δ|'],[[x['group'],x['n'],f"{x['median_delta_percent']:.3f}%",f"{x['p95_abs_delta_percent']:.3f}%",f"{x['max_abs_delta_percent']:.3f}%"] for x in linstats])
para('95分位绝对偏差：本组约95%的合格通道绝对偏差不超过该值。它描述通道分布，不是95%置信区间。最大值会受到弱信号通道影响，应结合码值分段看，而不是只给整组一个最大值。统计要求长短积分净光为正、两者SNR均≥20；未满足者仍保留在图和逐通道表里。')
binrows=[]
for low,high in [(0,4000),(4000,8000),(8000,15000),(15000,25000),(25000,35000),(35000,45000),(45000,55000)]:
    rr=[r for r in L if r['both_SNR20']=='True' and low<=float(r['long_net_mean_DN'])<high]
    a=[float(r['actual_vs_ideal_percent']) for r in rr]
    binrows.append(dict(lower_DN=low,upper_DN_exclusive=high,n=len(a),groups=len(set(r['group'] for r in rr)),median_delta_percent=statistics.median(a),p95_abs_delta_percent=quantile([abs(x) for x in a],.95),max_abs_delta_percent=max(abs(x) for x in a)))
section('3.3 不同码值段的结果',3)
table(['长积分净光区间DN','点数/涉及组数','δ中位数','|δ|95分位','最大|δ|'],[[f"[{x['lower_DN']}, {x['upper_DN_exclusive']})",f"{x['n']} / {x['groups']}",f"{x['median_delta_percent']:.3f}%",f"{x['p95_abs_delta_percent']:.3f}%",f"{x['max_abs_delta_percent']:.3f}%"] for x in binrows])
mid=[r for r in L if r['both_SNR20']=='True' and 4000<=float(r['long_net_mean_DN'])<45000]
para(f"4000–45000 DN范围内共有{len(mid)}个合格的‘通道×组’数据点，最大|γ−1|为{max(abs(float(r['ratio_minus_one_percent'])) for r in mid):.3f}%，最大|δ|为{max(abs(float(r['actual_vs_ideal_percent'])) for r in mid):.3f}%。前者对应原报告的约1.71%，后者采用实测相对理论的分母。这些是已测点的统计，不证明区间内每个码值、每个波长及所有条件都经过验证。")
para('低于4000 DN处分散更明显，不能把偏差全部判为器件非线性；噪声、偏置和光源变化也会影响比值。45000 DN以上只有两组5W贡献主要数据，呈γ上扬、δ偏负的趋势，即长积分相对外推值偏低。没有进一步覆盖饱和过程，因此不报告精确饱和起点。')
figure('01_六组线性度原始响应比','图1 正式主图：未经锚定归一化的非线性比值γ（图中记为R），横轴为长积分净光均值。')
para('图1每个点是一个波长在一组配对实验中的结果，颜色代表实验组，不代表波长。γ＝1表示比例一致；右图放大工程相关码值区，左图保留全部通道。高端上翘与响应压缩表现相符，但不能直接作硬件根因结论。')
section('3.4 锚定图与辅助检查的作用',3)
formula('A组 = median{γ：15000≤长积分净光≤25000，且两档SNR≥20}\n锚定归一化比值：γ归一化 = γ/A组')
para('锚定是把每组指定码值区的典型比值对齐到1，方便比较曲线形状。它会移除整体偏差，不用于替代原始线性误差。参考图片标注“锚定区”本身不足以证明其进行了这一除法；本图是额外的辅助分析，不声称精确复现参考图的处理算法。8000 DN竖线仅保留参考图标记，不是已验证的本机阈值。')
figure('02_六组线性度锚定对比','图2 辅助图：各组除以自身锚定中位数后的形状对比，不用于绝对线性判断。')
figure('03_六组光谱实测与理论对比','图3 蓝线为长积分实测，橙虚线为短积分按实际时间比例放大。')
para('图3直接展示偏差出现在哪些波长。两条线重合说明比例接近；5W组强信号波段橙线略高于蓝线，与图1高端γ>1相对应。')
figure('04_波长偏差及偏置敏感性','图4 上图为(γ−1)随波长变化，下图为偏置0与1000假设下γ的差，单位为百分点。')
para('图4下图是处理假设的敏感性，不是仪器实测非线性达到几十个百分点。其作用是说明漏扣偏置对弱信号影响特别大。本次偏置已确认；仍不能仅凭低码值图形拟合通用修正函数。')

section('4. 信噪比：原理、计算和达标判断')
section('4.1 帧间重复性公式',3)
formula('S̄(λ) = ΣSᵢ(λ)/nL\nsS(λ) = sqrt[Σ(Sᵢ(λ)−S̄(λ))²/(nL−1)]\nSNR(λ) = S̄(λ)/sS(λ)\nCV(λ) = sS(λ)/|S̄(λ)|×100%')
para('标准差沿同一波长的重复帧计算，不沿波长方向计算。分母为nL−1，是样本标准差。SNR越高表示相对于平均信号的重复波动越小；它衡量重复性，不证明绝对准确度。信号非正时标为无效，不把负SNR当成可用信号。')
table(['平均净光','帧间标准差','SNR','CV','解释'],[[1000,50,20,'5%','基本重复性门槛'],[1000,20,50,'2%','推荐重复性门槛'],[1000,10,100,'1%','波动更小，但仍需检查系统偏差']])
para('正信号下CV＝100%/SNR，所以SNR≥20与CV≤5%是同一重复性要求的两种表达，不是两份独立证据。减去固定暗均值不改变亮值帧间标准差；主SNR不会再次把暗标准差加到分母，也不会乘√n来报告均值的SNR。')
formula('平均净光的统计标准误：u(S̄) ≈ sqrt(sL²/nL + sD²/nD)')
para('逐通道表额外提供上述标准误，前提是帧间及亮暗批次间独立。它不包含暗场失配、灯漂移、辐射校准误差等系统影响，不是完整测量不确定度。独立噪声假设下多帧平均可减小随机波动，但本次没有据此直接指定平均帧数。')
section('4.2 满量程与漂移判据',3)
formula('16位数字上限：DNFS = 65535\n80%建议上限：0.8×65535 = 52428 DN\n码值筛选：每个通道全部亮值帧的max(Lᵢ−1000) ≤ 52428（等价于max(Lᵢ)≤53428）')
para('80%判据使用去除人工偏置后的全光码值L−1000，不使用导出L，也不使用扣暗净光值L−D。底值同样占据数字量程。所有亮帧均未达到65535，但无数字截顶不等于无软饱和。N模式缺少同步原始亮值，不能只根据N−1000确认ADC余量。')
formula('按组内实际采集时间拟合：Sᵢ(λ) ≈ a(λ)+k(λ)·τᵢ\n拟合漂移：Dfit(λ) = k(λ)·(τ末−τ首)/|S̄(λ)|×100%\n峰峰变化：Dpp(λ) = [max(Sᵢ)−min(Sᵢ)]/|S̄(λ)|×100%')
para('本次工作候选采用|Dfit|≤2%。原方案没有进一步定义漂移算法，因此必须说明采用的是拟合首尾变化；它不等于峰峰变化，后者也包含随机噪声。逐通道表同时保存二者。没有先去趋势再重算SNR，以免人为提高结果。弱信号下随机波动也可能使拟合斜率较大，超限不自动证明灯具持续漂移。')
section('4.3 工作候选与无效波段规则',3)
table(['层级','规则','用途'],[['基本重复性','S̄>0、无数字饱和、SNR≥20且CV≤5%','判断最基本信号质量'],['推荐重复性','S̄>0、无数字饱和、SNR≥50且CV≤2%','较稳定的重复测量'],['工作候选','基本重复性＋原始亮值≤80%量程＋|Dfit|≤2%','本次短序列的参数筛选'],['推荐候选','推荐重复性＋原始亮值≤80%量程＋|Dfit|≤2%','本次短序列中更优的条件']])
para('工作候选尚不包含最终线性度认证和100帧验证。无效规则按逐通道执行：非正响应、数字饱和、码值超限、漂移超限或SNR不足，任一项不满足即不列入对应候选范围。所有不通过通道保留数值和标志，未删除。连续范围按原生相邻通道划分，不跨越中间不通过的通道。')
table(['条件','信号/暗帧','SNR中位数','SNR≥20','SNR≥50','码值超限','漂移超限','工作/推荐候选'],[[x['condition'],f"{x['light_frames']}/{x['dark_frames']}",f"{x['median_SNR']:.1f}",x['basic_SNR20_channels'],x['SNR50_channels'],x['above80pct_channels'],x['fit_drift_over2pct_channels'],f"{x['working_candidate_channels']}/{x['recommended_candidate_channels']}"] for x in C])
para('表中均以288通道为总数。不同问题可发生在同一通道，超限数量不能简单相加。全部正式波段若定义为306–878 nm，没有一个已测条件通过全部工作候选筛选。72 V/64 ms全通道SNR≥20，但16个通道拟合漂移超限；76 V/64 ms另有78个码值超限通道。')
figure('05_各积分时间信噪比','图5 SNR(λ)，按实际积分时间分面，颜色表示电压；红虚线20、灰点线50。纵轴为对数刻度。')
para('图5的短波端低SNR不能用中长波段的高SNR平均掉。锯齿来自逐通道真实统计，未用平滑提高外观或指标。某条曲线高，并不同时证明码值和漂移通过。')
figure('06_全波段工作条件图','图6 每行是一个采集条件，每列位置代表波长，展示工作候选筛选。')
para('图6绿/蓝绿表示通过码值与漂移筛选后不同SNR等级；灰色为SNR不足；黄色为拟合漂移超限；红色为80%量程超限；黑色为非正或数字饱和。多问题通道优先显示非正/饱和、码值、漂移、SNR的第一项，不表示其他问题不存在。')

section('5. 不同电压与积分时间下的弱光响应及可用波段')
section('5.1 弱光性能与最低可测亮度的区别',3)
para('弱光评价关心在较低输入下，哪些波长仍有正响应、足够SNR和可接受重复性。本次以五档电压改变光源，64 ms覆盖全部电压，适合同积分时间比较。电压不是亮度：缺少实测参考板辐亮度及透过率记录，不能把电压比当作辐亮度比，也不能将不同电压视为光谱各处同比例减弱。')
formula('若有实测亮度，目标波段B的操作性定义可写为：\nLmin(B,t) = 最低已验证L，使每个λ∈B均满足\nS̄(λ)>0、无饱和、SNR(λ)≥20、CV(λ)≤5%')
para('Lmin依赖预先规定的输出波段、积分时间、光路及处理方法。不能在每个低亮度档不断裁掉失败通道，再声称达到了同一个全波段Lmin。当前60 V只是最低已测设置，不是已证明的仪器极限。')
figure('07_固定64ms弱光响应与CV','图7 固定64 ms时的净光均值及CV随波长变化，保留全部波段。')
para('电压降低时净光响应下降，短波端CV更容易超限。CV曲线低于5%或2%的含义分别对应SNR≥20或50；它仍需与图6的高码值、漂移筛选配合使用。')
section('5.2 延长积分时间的实测效果',3)
formula('逐波长SNR增益：G(λ) = SNR长(λ)/SNR短(λ)\n单位时间响应比：Q(λ) = [S̄长(λ)/t长]/[S̄短(λ)/t短]')
table(['电压','积分时间变化','G中位数','SNR≥20通道增加','Q中位数'],[[x['voltage_V'],f"{x['short_ms']:g}→{x['long_ms']:g} ms",f"{x['median_SNR_gain']:.3f}",x['basic_added_channels'],f"{x['median_normalized_response_ratio']:.5f}"] for x in S['improvements']])
para('G中位数是逐波长增益的中位数，不等于两个全谱SNR中位数的商。延长积分既增加信号也可能改变噪声、暗电流和非线性影响，所以不强制设定改善一定等于2或√2。相同电压的两次采集非同步，不能完全排除光源变化。')
figure('08_延长积分时间改善','图8 左图为逐波长SNR增益，右图为单位积分时间响应比Q。')
para('G>1表示长积分的重复性指标改善，个别点<1可能来自统计波动或条件变化。Q接近1表示单位时间响应接近；76 V强信号区Q偏低，与响应压缩表现相符，但不能单独完成器件归因。')
section('5.3 推荐候选波段及参数选择',3)
table(['电压/积分时间','最长工作候选连续段','最长推荐候选连续段'],[[x['condition'],x['longest_working_interval'],x['longest_recommended_interval']] for x in C])
para('上表只展示每个条件最长的一段，不代表其余波段全无效。所有连续段，包括零散段，见07表。波段端点取实际通道中心波长，不表示边界已经连续扫描确认。')
bullets(['在60 V弱信号条件下，如时间允许，128 ms相较64 ms能扩展候选波段；此结论仅比较本次已测两档，不表示128 ms是上限。',
'在76 V下，64 ms部分中间波段超过80%原始量程；可优先考虑已测32 ms，并重新检查其短波SNR。不能把长积分高SNR和短积分低码值优势未经验证拼成一个性能结论。',
'若正式输出必须覆盖全部原生波段，当前数据还没有证明存在同时满足所有筛选的设置。若任务允许限定波段，应先确定任务需要的波段，再选择条件。',
'仪器无可调增益，参数表填写“不适用/固定”，不虚构增益档。当前没有证明最佳平均帧数；需同时考虑测量时间和帧间相关性。'])

section('6. 暗场、时间变化与降压谱形检查')
section('6.1 暗场均值和噪声',3)
formula('暗标准差：sD(λ) = sqrt[Σ(Dⱼ(λ)−D̄(λ))²/(nD−1)]')
figure('09_暗场均值与噪声','图9 同条件暗场的底值及帧间标准差。')
para('导出暗值约9000–10000 DN，去除人工偏置后约8000–9000 DN；这些底值并不全部等于暗电流，电路偏置也可能贡献底值。稳定底值可通过匹配暗场扣除；底值随温度、时间或采集设置改变则可能造成失配。这里的暗标准差包含多种噪声与漂移，不能称为纯读出噪声，也不能据此认定暗电流主导。')
section('6.2 整体稳定与局部稳定的区别',3)
formula('逐帧全谱响应积分：Jᵢ = ∫Sᵢ(λ)dλ / t\n图示相对变化：(Jᵢ/J̄−1)×100%')
para('积分按实际非等间距波长用梯形法计算，单位DN·nm/ms，仅是仪器响应的汇总，不是经过辐射定标的光功率。强波段主导全谱积分，因此全谱稳定不保证弱波段稳定。')
figure('10_采集期间漂移','图10 上图为各组全谱响应积分序列，下图为逐波长拟合漂移。')
para(f"十个条件的全谱积分峰峰变化约{min(x['band_integral_peak_to_peak_percent'] for x in C):.3f}%–{max(x['band_integral_peak_to_peak_percent'] for x in C):.3f}%。但部分短波通道拟合相对漂移超过2%。本次采集持续约{min(x['duration_s'] for x in C):.1f}–{max(x['duration_s'] for x in C):.1f}秒，不能替代100帧或更长时段验证，也不能证明不同组之间光源强度不变。")
section('6.3 谱形是否随电压变化',3)
formula('面积归一化谱形：pV(λ) = S̄V(λ)/∫S̄V(λ)dλ\n相对谱形变化：[pV(λ)/p72V(λ)−1]×100%\n光谱角：θ = arccos[(pV·p72V)/(‖pV‖·‖p72V‖)]\nNRMSE = ‖pV−p72V‖/‖p72V‖×100%')
para('面积归一化使用波长加权积分；这里的角度和NRMSE按原生通道向量计算，属于本报告的谱形比较定义。选72 V/64 ms作为参考，是因为其全部通道的原始亮值未超过80%量程；这并不表示该档已被证明完全线性。')
table(['电压（均64 ms）','相对72 V全谱响应','谱形角','NRMSE'],[[x['voltage_V'],f"{x['relative_instrument_response']:.4f}",f"{x['spectral_angle_deg']:.3f}°",f"{x['normalized_shape_NRMSE_percent']:.2f}%"] for x in S['shape']])
figure('11_降电压谱形检查','图11 面积归一化后的实测谱形及相对72 V的变化。')
para('60 V相对72 V的谱形角约6.40°，NRMSE约11.70%，说明实测光谱不是简单的同比例缩小。右图正值只表示该波长在归一化谱中的相对占比增加，不表示降压后其绝对光强反而增加。光源谱形、仪器非线性及其他误差均可能参与，不能将差异唯一归因于灯。')
figure('12_各电压有效通道数','图12 左图只看基本SNR等条件，右图进一步筛选码值余量和拟合漂移。')
para('76 V/64 ms在左图全部通道达标，在右图降至199个工作候选，主要因为78个通道超过80%量程。这说明选择积分时间要同时照顾弱信号与强信号。连接线只引导阅读，未测电压点没有经过验证。')

section('7. 与原实验要求的对应关系')
table(['要求或输出','当前完成程度','报告表述'],[
['逐波长SNR、CV、平均净光、标准差','已计算','适用于30/50帧现有序列'],
['原始DN不超过80%量程','已检查','76 V/64 ms部分通道不满足'],
['100帧信号漂移≤2%','未完成规定帧数','仅报告本次序列拟合漂移'],
['亮度—积分时间—增益表','无亮度L；无可调增益','报告电压—积分时间表，增益不适用'],
['不少于6档且覆盖工程最低亮度以下','仅5档电压；工程目标与L缺失','无法确认覆盖'],
['Lmin','不能确定','最低已测电压档下的弱光表现'],
['推荐积分时间上限','不能确定','比较32/64/128 ms已测档位'],
['推荐平均帧数','尚未专门验证','不把现有帧数写成最优平均帧数'],
['无效波段','已列出条件依赖范围','不将候选范围写成全条件规格'],
['R²、拟合最大残差、饱和起点','当前采集结构不足','不强行给值']])
para('30或50帧可以估计信噪比，结果具有分析价值；不足100帧不是所有计算失效。但统计把握程度及覆盖时间有限，不能把现有结论改写成按原方案完整通过。')
section('8. 改进方向与最小补充验证')
table(['现象','当前证据','下一步行动'],[['弱信号SNR不足','延长积分实测有效','在任务允许的时间内验证更长积分或增加通光量，持续检查强波段余量'],['强信号超出80%量程','76 V/64 ms有78通道超限','优先比较短积分；若要融合长短曝光，应另行验证一致性'],['暗噪声或暗漂移','已获得暗场统计，尚未分离原因','补充温度与多积分时间暗场，区分偏置、暗电流及读出相关影响'],['可能杂散光','当前没有专门对照','需要遮光、光路及背景对照，不能从现有曲线直接归因'],['绝对弱光极限缺失','无实测L与最低档边界','每档记录亮度，增加至少第六档并覆盖工程最低亮度以下'],['正式稳定性验证缺失','信号只有30或50帧','目标设置补采100帧信号并配暗场；保留真实时间戳']])
para('在现有报告基础上，最优先补的是目标设置的100帧和实测亮度记录。若进一步需要可靠非线性校正，应先复核62 ms记录，再在固定稳定光源下增加积分时间档位及独立验证组，不能直接把配对γ拟合成通用补偿多项式。')
section('9. 数据来源、计算表与复现')
bullets(['原始目录：C:/Users/haowei/Desktop/夜间水质资料/夜间水质资料/光谱仪室内实验。',
'实验要求来源：灯+光谱仪性能实验.pdf，第3–5页。相对比值方法及图式参考：IES非线性分析.pdf，第1–2、7–8页，以及用户提供的三张PNG。未移植参考设备硬件归因及阈值作为本机结论。',
'数据定义来源：标定上位机V3/标定上位机V3/doc/sensor/OCR协议-上位机专用.md，第280–284行；K值计算机制说明.md，第40–50行。',
'原始文件指纹、帧数、实际积分时间及时间范围见01表；原始文件未修改。',
'02表中的ratio即γ，ratio_minus_one_percent即εγ，actual_vs_ideal_percent即δ。04表沿用|γ−1|口径；新增11、12表统一使用δ口径，避免混淆。',
'运行analyze_ocr.py重算图和表，再自动调用build_detailed_report.py生成本详细报告。仅修改说明时可单独运行build_detailed_report.py。依赖Python、numpy、matplotlib；--source指定源目录，--offset修改N模式偏置。',
'报告所有定量结果使用原始帧，不平滑、不人为删除异常帧、不插值。图形中的连线是视觉连接，不代表增加新的测量点。'])
for name,rows in [('11_线性度实测相对理论偏差汇总.csv',linstats),('12_码值分段实测相对理论偏差.csv',binrows)]:
    with (P/'tables'/name).open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
H.append('<ul>'+''.join(f'<li><a href="tables/{p.name}">{p.name}</a></li>' for p in sorted((P/'tables').glob('*.csv')))+'</ul>')
M.append('\n'.join(f'- [{p.name}](tables/{p.name})' for p in sorted((P/'tables').glob('*.csv')))+'\n')
style='''body{max-width:1200px;margin:40px auto;padding:0 28px;font:16px/1.85 "Microsoft YaHei",sans-serif;color:#243648;background:#fafbfc}h1{font-size:32px;line-height:1.4}h2{margin-top:46px;border-bottom:2px solid #cddce8;padding-bottom:8px;font-size:24px}h3{font-size:19px;margin-top:28px}p,li{overflow-wrap:anywhere}.formula{white-space:pre-wrap;padding:18px 22px;margin:18px 0;background:#edf3f8;border-left:4px solid #326f9a;font:17px/1.9 "Microsoft YaHei",sans-serif;overflow-wrap:anywhere}.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;background:white;font-size:14px}td,th{padding:10px 12px;border:1px solid #dbe2e8;text-align:left}th{background:#e8f0f6}figure{margin:28px 0}img{max-width:100%;height:auto;background:white}figcaption{font-size:14px;color:#516579}a{color:#236c9c}nav{padding:18px 24px;background:#eef3f6}nav ol{margin:0}.tools{font-size:14px}@media print{body{margin:0;padding:0;background:white;font-size:11pt}nav,.tools{display:none}figure,table,.formula{break-inside:avoid}h2,h3{break-after:avoid}a{color:inherit}}'''
nav='<nav><strong>目录</strong><ol>'+''.join(f'<li><a href="#{i}">{html.escape(t)}</a></li>' for i,t in toc)+'</ol></nav>'
H.insert(3,nav)
(P/'分析报告.html').write_text('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OCR室内实验详细分析报告</title><style>'+style+'</style></head><body><div class="tools"><a href="分析报告.md">文字版</a> · <a href="analyze_ocr.py">分析脚本</a> · <a href="build_detailed_report.py">报告生成脚本</a></div>'+''.join(H)+'</body></html>',encoding='utf-8')
(P/'分析报告.md').write_text('\n'.join(M),encoding='utf-8')
print(json.dumps({'report_sections':len(toc),'figures':12,'tables':len(list((P/'tables').glob('*.csv'))),'markdown_characters':sum(map(len,M)),'mid_max_abs_delta':max(abs(float(r['actual_vs_ideal_percent'])) for r in mid)},ensure_ascii=False))
