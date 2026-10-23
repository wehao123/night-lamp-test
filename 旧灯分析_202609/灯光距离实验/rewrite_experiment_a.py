from pathlib import Path
from docx import Document
from docx.shared import Cm, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


ROOT = Path(r"C:\Users\haowei\Documents\ChatGPT\灯光距离实验")
SOURCE = ROOT / "OCR-25F02100_室内实验B_C_D完整报告.docx"
OUTPUT = ROOT / "OCR-25F02100_室内实验A_B_C_D完整报告.docx"
FIG = ROOT / "outputs" / "lamp_warmup_20260922" / "统一时间轴分析" / "figures"


def shade(cell, fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    node = tc_pr.find(qn("w:shd"))
    if node is None:
        node = OxmlElement("w:shd")
        tc_pr.append(node)
    node.set(qn("w:fill"), fill)


def cell_margins(cell, value=90):
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for side in ("top", "start", "bottom", "end"):
        node = tc_mar.find(qn(f"w:{side}"))
        if node is None:
            node = OxmlElement(f"w:{side}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def repeat_header(row):
    tr_pr = row._tr.get_or_add_trPr()
    node = OxmlElement("w:tblHeader")
    node.set(qn("w:val"), "true")
    tr_pr.append(node)


doc = Document(SOURCE)
before_count = len(doc.element.body)


def p(text, bold_lead=None):
    para = doc.add_paragraph()
    para.paragraph_format.first_line_indent = Cm(0.74)
    if bold_lead and text.startswith(bold_lead):
        para.add_run(bold_lead).bold = True
        para.add_run(text[len(bold_lead):])
    else:
        para.add_run(text)
    return para


def bullet(text):
    para = doc.add_paragraph(style="List Bullet")
    para.paragraph_format.left_indent = Cm(0.75)
    para.add_run(text)


def numbered(text):
    para = doc.add_paragraph(style="List Number")
    para.paragraph_format.left_indent = Cm(0.75)
    para.add_run(text)


def equation(text):
    para = doc.add_paragraph()
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    para.paragraph_format.keep_together = True
    run = para.add_run(text)
    run.font.name = "Cambria Math"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Cambria Math")
    run.font.size = Pt(11)


def table(headers, rows, widths=None, font_size=8.5):
    tbl = doc.add_table(rows=1, cols=len(headers))
    tbl.style = "Table Grid"
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False
    repeat_header(tbl.rows[0])
    for j, value in enumerate(headers):
        cell = tbl.rows[0].cells[j]
        cell.text = str(value)
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        shade(cell, "1F4E78")
        cell_margins(cell)
        for run in cell.paragraphs[0].runs:
            run.font.color.rgb = RGBColor(255, 255, 255)
            run.font.bold = True
            run.font.size = Pt(font_size)
            run.font.name = "微软雅黑"
            run._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
    for i, values in enumerate(rows):
        cells = tbl.add_row().cells
        for j, value in enumerate(values):
            cells[j].text = str(value)
            cells[j].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            cells[j].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER if j > 0 else WD_ALIGN_PARAGRAPH.LEFT
            cells[j].paragraphs[0].paragraph_format.space_after = Pt(0)
            if i % 2:
                shade(cells[j], "EEF4F8")
            cell_margins(cells[j])
            for run in cells[j].paragraphs[0].runs:
                run.font.size = Pt(font_size)
                run.font.name = "宋体"
                run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    if widths:
        for row in tbl.rows:
            for j, width in enumerate(widths):
                row.cells[j].width = Cm(width)
    doc.add_paragraph().paragraph_format.space_after = Pt(1)


def figure(filename, caption, width=16.0):
    para = doc.add_paragraph()
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    para.paragraph_format.keep_with_next = True
    para.add_run().add_picture(str(FIG / filename), width=Cm(width))
    cap = doc.add_paragraph(style="Caption")
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap.add_run(caption)


# ---------------------------------------------------------------- 实验 A
doc.add_heading("实验 A  灯光冷启动稳定性", level=1)

doc.add_heading("A.1 实验目的", level=2)
p("评价灯具从冷态通电后光谱响应随时间的变化，确定不同允许漂移条件下的稳定等待时间，分析单次连续测量期间的响应漂移和短时异常波动，并为室外实验提供预热时间、连续工作时长和参考检查方法。")
p("本实验评价的是灯具、光路、环境背景与光谱仪共同构成的测量系统。结果以DN光谱积分的相对变化表示，未进行绝对辐射定标，不能直接换算为光功率或辐亮度。")

doc.add_heading("A.2 实验数据与预处理", level=2)
p("实验于2026年9月20日进行。光谱仪积分时间为32 ms，采集模式为N，覆盖288个原生通道。分析使用3389帧灯光数据和74帧环境背景数据，以首次开灯帧的时间戳作为通电计时零点。灯光末次记录位于通电后63.16分钟。")
table(["记录", "累计点亮时间 / min", "帧数", "实际记录跨度", "用途"], [
    ["灯光采样窗口1（刚通电）", "0.00–0.71", "101", "42.68 s", "记录刚通电后的初始响应"],
    ["灯光采样窗口2", "2.75–25.39", "3040", "22.64 min", "主要连续预热记录"],
    ["灯光采样窗口3", "46.47–47.17", "100", "42.51 s", "后期参考窗口1"],
    ["灯光采样窗口4", "56.64–57.41", "100", "46.51 s", "后期参考窗口2"],
    ["灯光采样窗口5", "62.79–63.16", "48", "22.16 s", "后期参考窗口3"],
    ["环境背景采样窗口", "约1.25、47.82、63.90", "30、18、26", "共39.39 s", "背景扣除与敏感性分析"],
], widths=[2.8, 3.5, 1.7, 3.0, 4.5], font_size=8.2)
p("灯具从首次通电到实验结束始终保持点亮，没有在各文件或各采样窗口之间关闭、重新启动。表中的窗口划分只表示光谱仪在不同时间段采集了灯光数据，其间穿插环境背景采集或存在未记录灯光光谱的时段。全部灯光数据按时间戳合并为一条连续的累计点亮时间轴，背景采集期间预热计时仍继续。")
p("文件名仅用于追溯数据来源，不作为重新计时、重新归一化或重新定义冷启动的依据。没有灯光光谱记录的时段保留为空档，不进行插值补帧；这些空档不代表灯被关闭，但由于缺少灯光观测，不能计入光学稳定性的连续验证时长。")
p("N模式已经由设备完成暗值处理。灯光记录与环境背景记录具有相同的固定偏置，二者相减时偏置自动抵消，因此净信号不再额外减去1000 DN。全部原始帧均保留，未进行平滑或人为删除异常帧。")

doc.add_heading("A.3 评价方法", level=2)
doc.add_heading("A.3.1 波段积分与背景处理", level=3)
p("以420–700 nm为主波段，同时分别检查蓝光420–500 nm、绿光500–600 nm和红光600–700 nm。对实际波长网格采用梯形积分，波段边界由相邻通道线性插值得到。")
equation("B(t; λ₁,λ₂) = ∫[N灯(λ,t) − N背景(λ)] dλ")
p("其中，B为波段净DN积分，单位为DN·nm。当前操作结论采用固定扣除第一次环境背景的结果，以避免对背景时间变化作未经验证的精确假设；同时使用三次环境背景的线性估计结果进行敏感性对照。两种处理得到的长期变化幅度不同，因此本章将“测量系统响应变化”与“灯具自身热衰减”区分表述。")

doc.add_heading("A.3.2 后期参考值与相对偏差", level=3)
p("后期参考值取通电约46.5、56.6和62.8分钟附近三次灯光记录的分段均值，并对三段等权平均：")
equation("Bref = (B̄窗口3 + B̄窗口4 + B̄窗口5) / 3")
equation("Δ(t) = [B(t)/Bref − 1] × 100%")
p("该参考值仅表示本次实验后期的实测水平，不是独立标定真值，也不证明灯具已经达到严格热平衡。")

doc.add_heading("A.3.3 稳定等待时间", level=3)
p("将各波段数据按实际时间划分为约10秒的平均块。对给定允许漂移±ε，稳定等待时间定义为：蓝、绿、红三个分波段的10秒均值首次同时进入后期参考值的±ε范围，并且此后所有实际采集到的有效块继续满足该范围时，对应的累计点亮时间。")
p("分别检查±1%、±2%和±5%三档允许漂移。稳定等待时间依赖所选容差、背景处理方法和采样覆盖范围，不存在脱离这些条件的唯一数值。")

doc.add_heading("A.3.4 连续工作时长", level=3)
p("连续工作时长只使用时间上连续的灯光光谱记录进行验证，不跨越环境背景采集或未记录灯光数据的空档。灯在这些空档期间仍持续点亮，但没有对应的灯光观测，无法确认期间是否始终满足漂移要求。进入规定漂移范围后，从首次合格时刻到连续灯光记录结束之间的实测时长记为直接验证时长；后续离散采样点之间的时间仅记为采样覆盖跨度，不能等同于连续验证。")

doc.add_heading("A.3.5 异常波动筛查", level=3)
p("对每帧计算其相对局部10秒中位数的残差。任一主波段或分波段的残差超过下列稳健阈值时，标记为疑似短时突波：")
equation("T = max[6 × 1.4826 × MAD，0.5%]")
p("其中，MAD为绝对中位差。该筛查用于发现突然闪烁或跳变，不用于替代长期漂移评价；未检出突波也不表示每一帧均满足±1%的测量精度。")

doc.add_heading("A.4 实验结果", level=2)
doc.add_heading("A.4.1 冷启动响应变化", level=3)
p("从刚通电到约63分钟，测得响应整体呈缓慢下降趋势，后期三个短时采样窗口接近同一水平。固定扣除第一次环境背景时，末10秒相对通电后前10秒的变化如下。")
table(["波段", "固定环境1时累计变化", "按环境光线性估计时"], [
    ["总量420–700 nm", "−3.76%", "−8.33%"],
    ["蓝420–500 nm", "−2.03%", "−15.27%"],
    ["绿500–600 nm", "−3.68%", "−8.70%"],
    ["红600–700 nm", "−4.46%", "−5.44%"],
], widths=[5.0, 5.1, 5.4], font_size=9.0)
p("两种背景处理均显示长期累计变化不可忽略，但下降幅度存在明显差异，特别是蓝波段。因此，可以确认本次测量系统的光谱响应随时间发生变化，不能将全部变化直接归因于灯具热衰减。")
figure("01_预热曲线.png", "图A-1  从刚通电到约63分钟的预热曲线。灯具全程持续点亮；图中空白区表示没有灯光光谱记录，不表示灯具关闭。")

doc.add_heading("A.4.2 稳定等待时间", level=3)
table(["允许漂移", "首次观测到稳定", "后续判定范围", "操作含义"], [
    ["±5%", "0.0 min", "至末次灯光记录63.16 min", "本次固定背景口径下全程处于范围内"],
    ["±2%", "14.8 min", "至末次灯光记录63.16 min", "建议实际操作预热15 min"],
    ["±1%", "最迟46.5 min已满足", "后续采样跨度16.7 min", "25.4–46.5 min无数据，无法确定精确进入时刻"],
], widths=[2.4, 3.2, 4.6, 5.3], font_size=8.2)
p("若按±2%的系统响应漂移要求使用，本次数据支持将预热时间设为15分钟。该数值以固定环境1背景处理和蓝、绿、红三个分波段同时满足为依据，是本次实验条件下的实用参数。不同背景处理方法会改变等待时间，因此不能把15分钟解释为灯具本体在所有环境中的固定热稳定时间。")
p("±1%条件下，只能确认通电46.5分钟时已经进入范围。由于25.4–46.5分钟之间存在21.1分钟采集空档，实际进入±1%范围的时刻可能更早，但本次数据无法确定。")
figure("02_稳定等待时间.png", "图A-2  稳定等待时间随允许漂移范围的变化。数值基于蓝、绿、红分波段的10秒均值联合判定。")

doc.add_heading("A.4.3 允许单次工作时长", level=3)
p("按±2%要求，从约14.6分钟开始到25.4分钟的连续记录保持在规定范围内，原始时间跨度约10.8分钟；考虑10秒分块边界后，直接验证时长约10.5分钟。因此，当前建议将单次连续测量先按10分钟安排。")
p("通电46.5、56.6和62.8分钟附近的后续采样仍满足±2%，表明灯持续点亮到约63分钟时，已采样时刻仍处于合格范围。但中间存在环境背景采集或未记录灯光光谱的空档，不能把约48分钟的采样跨度写成连续验证时长，也不能据此认定整个一小时内每一时刻的光学响应都已得到验证。")
table(["允许漂移", "连续记录直接验证", "后续采样覆盖", "本次建议"], [
    ["±5%", "从开灯起已直接覆盖约0.7 min；第二段连续记录也满足", "采样点覆盖至63.2 min", "本次范围内可用，但仍应关注长期累计变化"],
    ["±2%", "进入范围后约10.5 min", "后续采样仍合格至63.2 min", "单次连续工作先按10 min"],
    ["±1%", "后期单段最长仅约0.7 min", "后续采样跨度16.7 min", "连续工作时长尚未确定"],
], widths=[2.3, 4.5, 4.4, 4.3], font_size=8.0)
figure("03_工作时长.png", "图A-3  各允许漂移条件下的连续记录直接验证时长与后续采样覆盖跨度。")

doc.add_heading("A.4.4 后期重复性与异常波动", level=3)
p("在通电46.5–63.2分钟的三个后期采样窗口中，各波段分段均值相对后期参考值的范围如下。")
table(["波段", "三个后期窗口均值范围"], [
    ["总量420–700 nm", "−0.183%～+0.188%"],
    ["蓝420–500 nm", "−0.226%～+0.217%"],
    ["绿500–600 nm", "−0.159%～+0.191%"],
    ["红600–700 nm", "−0.215%～+0.173%"],
], widths=[6.0, 9.5], font_size=9.0)
p("上述结果说明后期各采样窗口的段均值接近，但不代表每一帧均达到同样精度。后期248帧的主波段均处于±1%内；蓝波段共有9帧超过±1%，最大绝对偏差约1.44%，但均未超过±2%。因此，严格控制蓝波段时宜使用约10秒的多帧平均。")
p("全程3389帧在稳健突波判据下未检出明显突波。主要变化表现为缓慢漂移，没有发现达到设定阈值的突然闪烁或跳变。")
figure("04_异常与环境光.png", "图A-4  全程局部波动残差及三次环境背景光谱。背景记录随时间变化，说明严格稳定性判断需同时考虑背景不确定性。")

doc.add_heading("A.4.5 环境背景的影响", level=3)
p("三次背景记录的主波段均值分别约占后期净信号的24.43%、30.02%和29.39%。环境3的主波段背景单帧标准差约占后期净信号3.08%，蓝波段约占7.29%。背景记录包含环境光、探头输出基线及可能的杂散光，其变化会直接影响净信号和稳定等待时间的估计。")
table(["背景记录", "主波段背景占后期净信号", "主波段背景标准差占比", "蓝波段背景标准差占比"], [
    ["环境1", "24.43%", "1.06%", "5.11%"],
    ["环境2", "30.02%", "1.04%", "2.17%"],
    ["环境3", "29.39%", "3.08%", "7.29%"],
], widths=[3.1, 4.6, 4.1, 3.7], font_size=8.4)
p("因此，后期段均值之间约0.04%量级的差异不能直接解释为灯具真实稳定精度已经达到0.04%。本实验更适合支持±2%级别的操作建议；若需进行±1%正式验收，应增加背景测量频次、连续采样覆盖和重复冷启动试验。")

doc.add_heading("A.5 操作建议", level=2)
numbered("按±2%系统响应漂移要求，室外实验前建议预热15分钟；每组需要相互比较的数据，单次连续测量先控制在10分钟以内。")
numbered("优先采用约10秒的多帧平均，特别是蓝波段。若测量时间超过10分钟，应在测量前后重复测量同一参考目标，以检查期间漂移。")
numbered("灯具在本实验中始终保持点亮。正式测量时，一组需要相互比较的数据仍应尽量在同一个连续灯光采样窗口内完成；环境背景采集或未记录灯光数据的时段可以继续计入点亮时间，但不能计入连续稳定性验证时长。")
numbered("正式固定操作参数前，建议至少再完成两次独立冷启动试验，检查15分钟预热建议的重复性，并在预热后连续记录不少于计划采用的实际工作时长。")

doc.add_heading("A.6 结论与适用范围", level=2)
numbered("本次灯光记录覆盖通电后0–63.16分钟，共3389帧。测得响应随时间缓慢下降，后期采样窗口接近稳定平台；未检出达到稳健阈值的突然闪烁或跳变。")
numbered("在固定扣除第一次环境背景、蓝绿红三个分波段联合判定的口径下，±2%条件对应的稳定等待时间约为14.8分钟。因此，现阶段可采用“预热15分钟”的实际操作参数。")
numbered("进入±2%范围后，连续灯光记录直接支持约10.5分钟的测量时长，故单次连续工作建议先按10分钟执行。灯具在后续空档期间一直保持点亮，且后续采样合格至约63分钟；但空档内没有灯光光谱记录，不能计为连续验证。")
numbered("±1%条件下，本次只能确认通电46.5分钟时已经满足，无法确定精确稳定时刻和最大连续工作时长。蓝波段部分单帧仍超过±1%，宜采用多帧平均。")
numbered("长期变化幅度和等待时间受背景处理方法影响，当前结果属于灯具、环境、光路和仪器共同系统的室内评价。若用于正式验收，需增加背景测量、补齐中期连续记录并重复冷启动实验。")

doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

# 把实验 A 移到实验 B 之前
body = doc.element.body
new_elements = list(body)[before_count:]
target = None
for para in doc.paragraphs:
    if para.text.strip().startswith("实验 B"):
        target = para._p
        break
if target is None:
    raise RuntimeError("未找到实验 B 标题")
for element in new_elements:
    target.addprevious(element)

# 更新封面说明
for para in doc.paragraphs:
    if "实验 B 积分时间线性度" in para.text and "实验 D 弱光性能" in para.text:
        para.text = "实验 A 灯光冷启动稳定性  实验 B 积分时间线性度  实验 C 信噪比  实验 D 弱光性能"
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for run in para.runs:
            run.font.name = "黑体"
            run._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")
            run.font.size = Pt(12)
    if para.text.startswith("本报告汇总积分时间相对线性度"):
        para.text = "本报告汇总灯光冷启动稳定性、积分时间相对线性度、信噪比和弱光性能四项室内实验结果。全部定量结果均由原始重复帧计算，未进行平滑、滤波或插值。"

doc.core_properties.subject = "实验 A 灯光冷启动稳定性 实验 B 积分时间线性度 实验 C 信噪比 实验 D 弱光性能"
doc.save(OUTPUT)
print(OUTPUT)
