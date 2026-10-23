from pathlib import Path
import csv, json, sys, math
from docx import Document
from docx.shared import Cm, Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'outputs' / 'lamp_warmup_20260922' / '环境1完整30帧重算'
OUTDIR = ROOT / 'outputs' / 'lamp_warmup_20260922' / '实验A报告'
OUTDIR.mkdir(exist_ok=True)
FIG = OUTDIR / 'figures'
FIG.mkdir(exist_ok=True)

# The report uses the completed 30-frame environment-1 recomputation.
res = json.loads((DATA/'结果.json').read_text(encoding='utf-8'))
rows = list(csv.DictReader((DATA/'逐帧净积分.csv').open(encoding='utf-8-sig')))
times = [float(r['相对首帧分钟'])*60 for r in rows]
names = ['总量420—700 nm','蓝420—500 nm','绿500—600 nm','红600—700 nm']
cols = ['总量','蓝','绿','红']
vals = [[float(r[c]) for r in rows] for c in cols]

SOURCE_FIG = ROOT / 'outputs' / 'lamp_warmup_20260922' / 'figures'
# These figures are the existing full-sequence plots accompanying the validated analysis.
FIG_MAP = {
    '01_全程响应变化.png': SOURCE_FIG/'01_预热曲线.png',
    '02_滑动稳定性.png': SOURCE_FIG/'03_光谱与波动记录.png',
    '03_环境背景对照.png': SOURCE_FIG/'02_环境光与敏感性.png',
    '04_环境背景逐帧.png': SOURCE_FIG/'04_环境光逐帧波动.png',
}

def shade(cell, fill):
    tcPr=cell._tc.get_or_add_tcPr(); shd=tcPr.find(qn('w:shd'))
    if shd is None: shd=OxmlElement('w:shd'); tcPr.append(shd)
    shd.set(qn('w:fill'),fill)
def margins(cell):
    tcPr=cell._tc.get_or_add_tcPr(); m=tcPr.first_child_found_in('w:tcMar')
    if m is None: m=OxmlElement('w:tcMar'); tcPr.append(m)
    for n in ['top','start','bottom','end']:
        e=m.find(qn('w:'+n))
        if e is None: e=OxmlElement('w:'+n); m.append(e)
        e.set(qn('w:w'),'100'); e.set(qn('w:type'),'dxa')
def repeat_header(row):
    trPr=row._tr.get_or_add_trPr(); e=OxmlElement('w:tblHeader'); e.set(qn('w:val'),'true'); trPr.append(e)
def p(text='', bold=False, indent=True):
    q=doc.add_paragraph(); q.paragraph_format.first_line_indent=Cm(.74) if indent else None
    r=q.add_run(text); r.bold=bold; return q
def eq(text):
    q=doc.add_paragraph(); q.alignment=WD_ALIGN_PARAGRAPH.CENTER; q.paragraph_format.space_before=Pt(3); q.paragraph_format.space_after=Pt(5); r=q.add_run(text); r.font.name='Cambria Math'; r.font.size=Pt(11); return q
def table(headers, data, sizes=None):
    t=doc.add_table(rows=1, cols=len(headers)); t.style='Table Grid'; t.alignment=WD_TABLE_ALIGNMENT.CENTER; t.autofit=False; repeat_header(t.rows[0])
    for j,h in enumerate(headers):
        c=t.rows[0].cells[j]; c.text=str(h); shade(c,'1F4E78'); margins(c); c.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
        for r in c.paragraphs[0].runs: r.font.color.rgb=RGBColor(255,255,255); r.font.bold=True; r.font.size=Pt(8.5); r.font.name='微软雅黑'
        c.paragraphs[0].alignment=WD_ALIGN_PARAGRAPH.CENTER
    for i,row in enumerate(data):
        cs=t.add_row().cells
        for j,v in enumerate(row):
            cs[j].text=str(v); margins(cs[j]); cs[j].vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
            if i%2: shade(cs[j],'EEF4F8')
            for q in cs[j].paragraphs:
                q.paragraph_format.space_after=Pt(0); q.paragraph_format.line_spacing=1.05; q.alignment=WD_ALIGN_PARAGRAPH.CENTER
                for r in q.runs: r.font.name='宋体'; r.font.size=Pt(8.3)
    if sizes:
        for row in t.rows:
            for j,w in enumerate(sizes): row.cells[j].width=Cm(w)
    doc.add_paragraph().paragraph_format.space_after=Pt(1)
    return t
def fig(path, caption, width=15.6):
    q=doc.add_paragraph(); q.alignment=WD_ALIGN_PARAGRAPH.CENTER; q.paragraph_format.keep_with_next=True; q.add_run().add_picture(str(FIG_MAP[path.name]),width=Cm(width))
    q=doc.add_paragraph(); q.alignment=WD_ALIGN_PARAGRAPH.CENTER; q.paragraph_format.space_after=Pt(7); q.add_run(caption).font.size=Pt(9)

doc=Document(); sec=doc.sections[0]; sec.top_margin=Cm(2.25); sec.bottom_margin=Cm(2.1); sec.left_margin=Cm(2.35); sec.right_margin=Cm(2.15)
styles=doc.styles; normal=styles['Normal']; normal.font.name='宋体'; normal._element.rPr.rFonts.set(qn('w:eastAsia'),'宋体'); normal.font.size=Pt(10.5); normal.paragraph_format.line_spacing=1.35; normal.paragraph_format.space_after=Pt(5)
for name,size in [('Title',22),('Heading 1',16),('Heading 2',13),('Heading 3',11.5)]:
    s=styles[name]; s.font.name='黑体'; s._element.rPr.rFonts.set(qn('w:eastAsia'),'黑体'); s.font.size=Pt(size); s.font.color.rgb=RGBColor(0,0,0); s.font.bold=True; s.paragraph_format.keep_with_next=True; s.paragraph_format.space_before=Pt(12 if name!='Title' else 0); s.paragraph_format.space_after=Pt(6)

title=doc.add_paragraph(style='Title'); title.alignment=WD_ALIGN_PARAGRAPH.CENTER; title.add_run('单灯冷启动与输出稳定性实验分析报告')
sub=doc.add_paragraph(); sub.alignment=WD_ALIGN_PARAGRAPH.CENTER; sub.add_run('实验 A').bold=True
table(['项目','内容'],[['实验对象','OCR-25F02100光谱仪与单灯组合'],['采集日期','2026-09-20'],['积分时间','32 ms'],['采集模式','N模式'],['分析数据','6899帧亮场；环境1完整30帧作为固定背景'],['光谱范围','305.883—878.092 nm；积分评价范围420—700 nm']], [4,11.5])
p('本实验评价灯具持续点亮过程中的短时稳定性、长时间响应变化和分波段差异。结果采用环境1完整30帧平均光谱作固定背景，环境2、3作对照。',indent=False)
doc.add_page_break()

doc.add_heading('实验 A  单灯冷启动与输出稳定性',1)
doc.add_heading('A.1 实验目的',2); p('评价持续点亮过程中光谱响应的短时波动、缓慢漂移及不同波段之间的差异，为后续线性度、信噪比和弱光实验提供光源使用依据。')
doc.add_heading('A.2 实验数据与预处理',2); p('实验于2026年9月20日进行。亮场采用32 ms积分时间和N模式，共纳入6899帧，记录范围为14:29:04.359—15:26:29.102，跨度57.41 min。实验期间灯持续点亮，不同记录段之间的空档属于采集安排，不作为灯具重新启动处理。')
table(['项目','处理方式'],[['亮场数据','6899帧，按时间排序'],['环境背景','环境1完整30帧逐波长求平均'],['环境2、3','保留为对照，不参与本版扣背景'],['总量波段','420—700 nm'],['分波段','蓝420—500 nm；绿500—600 nm；红600—700 nm']], [4,11.5])
p('N模式导出值已由设备完成扣暗处理，但亮值和环境值均带有相同的1000 DN偏置。亮场减环境背景时该偏置自动抵消，因此净信号不再额外减1000 DN。')
eq('Sᵢ(λ) = Nᵢ(λ) − (1/30)ΣⱼN环境1,ⱼ(λ)')
p('环境2、3的测量条件与环境1位置基本一致，但可能存在黑板遮挡不完全的影响，因此本版不将三组背景直接插值扣除。三组背景的积分响应另作对照图展示。')
doc.add_heading('A.3 评价方法与判据',2)
doc.add_heading('A.3.1 分波段积分响应',3); p('对扣除环境背景后的净光谱进行梯形积分，波段边界用相邻通道线性插值。积分响应单位为DN·nm，用于表示相对输出，不是经亮度计标定的光度亮度。')
eq('Qᵢ,b = ∫[λb,1,λb,2] Sᵢ(λ)dλ')
doc.add_heading('A.3.2 短时稳定性',3); p('采用5 min滑动窗口，每1 s更新一次。窗口内计算样本标准差、变异系数和线性拟合变化率：')
eq('CV = sQ / |Q̄| × 100%'); eq('r = k / Q̄ × 100% / min')
p('总量稳定性判据为CV≤1.0%且|r|≤0.2%/min，连续满足10 min。窗口内出现超过2 s的记录间隔时，不跨空档拼接。')
doc.add_heading('A.3.3 长时间变化',3); p('20—50 min区间报告已测样本的峰—峰变化；全程报告首10 s与末10 s均值的相对变化。两项指标的统计含义不同，不能互相替代。')
eq('Dpp = (Qmax − Qmin) / Q̄ × 100%'); eq('Dend = (Q末10s / Q首10s − 1) × 100%')
doc.add_heading('A.4 实验结果',2)
doc.add_heading('A.4.1 短时稳定性',3); p('在环境1完整30帧固定背景的处理下，找到连续10 min满足总量稳定双判据的记录。首个合格滑动窗口结束于首帧记录后7.73 min，完成连续10 min确认的时刻为17.73 min。该判定区间内最大滑动CV为0.179%，最大变化率绝对值为0.103%/min。7.73 min是首个可评价合格窗口的结束时刻，不等同于实际通电后的最低预热时间。')
fig(FIG/'01_全程响应变化.png','图A-1  固定环境1完整30帧背景后的全程十秒块相对变化。')
fig(FIG/'02_滑动稳定性.png','图A-2  总积分响应五分钟滑动CV和变化率绝对值。')
doc.add_heading('A.4.2 20—50 min区间变化',3)
table(['波段','CV / %','峰—峰变化 / %','首末变化 / %'],[[names[i],f"{res['cv'][i]:.3f}",f"{res['pp'][i]:.3f}",f"{res['endpoint'][i]:.3f}"] for i in range(4)], [4.7,3.1,3.6,3.6])
p('20—50 min共纳入3534帧。总量峰—峰变化为1.677%，低于2%；绿波段为1.934%，低于2%；蓝、红波段分别为3.195%和2.618%，高于2%。因此总量变化较小不代表所有波段都满足2%稳定性要求。')
doc.add_heading('A.4.3 全程首末变化',3); p('约57 min分析记录中，总积分响应首末下降3.565%；蓝、绿、红波段首末变化分别为−1.760%、−3.543%和−4.176%。数据表明短时波动较小，但较长时间尺度仍存在缓慢下降。')
doc.add_heading('A.4.4 环境背景对照',3); p('环境1完整30帧作为本版固定背景。环境2和环境3仅作对照，其420—700 nm积分响应高于环境1，可能受到遮光不完全影响，不能直接作为时变背景插值使用。')
fig(FIG/'03_环境背景对照.png','图A-3  三组环境背景的420—700 nm积分响应对照。')
fig(FIG/'04_环境背景逐帧.png','图A-4  环境背景逐帧波动，用于检查三组背景的内部一致性。')
doc.add_heading('A.5 使用建议',2); p('后续线性度、信噪比和弱光实验可采用相同光源、参考板和光路条件开展。每次测量前后应记录参考响应，检查本组实验期间是否出现明显变化。')
doc.add_heading('A.6 结论与适用范围',2)
p('（1）在采用环境1完整30帧平均光谱作固定背景的条件下，已测记录中存在连续10 min满足CV≤1.0%且变化率绝对值≤0.2%/min的区间。', bold=True)
p('（2）20—50 min已测总量峰—峰变化为1.677%，绿波段为1.934%，蓝、红波段分别为3.195%和2.618%。总量和绿波段低于2%，蓝、红波段超过2%。')
p('（3）约57 min分析记录中总量首末下降3.565%，说明长时间测量存在缓慢响应变化。')
p('（4）本实验支持后续实验使用该光源组合，但不据此规定固定的最低预热时间。7.73 min和17.73 min是本次记录相对首帧的算法判定时刻，不是实际通电后的物理预热时间。')
doc.add_heading('A.7 数据范围说明',2); p('本报告的定量结果统一采用环境1完整30帧固定背景。环境2、3未删除，作为背景一致性对照保留；由于其背景积分明显偏高，且可能存在遮光不完全，本版不使用三组背景插值结果作为主结论。')

out=ROOT/'OCR-25F02100_室内实验A完整报告.docx'; doc.save(out); print(out)
