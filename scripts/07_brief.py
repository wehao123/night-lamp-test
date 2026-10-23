"""第 7 步：生成给别人看的简报（约 4 页）。数值全部来自 out/results_*.json；完整分析见 05 生成的技术报告。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config as C
from common import OUT, FIG, ROOT
import pandas as pd
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

cj = json.loads((OUT / "results_cold.json").read_text(encoding="utf-8"))
dj = json.loads((OUT / "results_dist.json").read_text(encoding="utf-8"))
sj = json.loads((OUT / "results_snr.json").read_text(encoding="utf-8"))
xj = json.loads((OUT / "results_compare.json").read_text(encoding="utf-8"))
U = pd.DataFrame(dj["U"])
ST = cj["stats"]["前后平均"]
n_pow, _, r2_pow = dj["fits"]["R_sum"]
ratio2 = xj["ratio2"][0]                      # 主分析（旧灯背景 = 环境1）
rmin = min(r["420-700积分比"] for r in xj["ratio2"])
rmax = max(r["420-700积分比"] for r in xj["ratio2"])
OLD_U25 = {1.5: 23.5, 2.0: 43.5, 3.0: 61.8, 4.0: 69.0, 5.0: 77.7}   # 旧报告表 3-4

doc = Document()
sec = doc.sections[0]
sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
sec.left_margin = sec.right_margin = Cm(2.2)
sec.top_margin = sec.bottom_margin = Cm(2.0)
BLUE = RGBColor(0x1F, 0x3A, 0x5F)


def font(style, size, bold=None, east="宋体", color=None):
    style.font.name = "Times New Roman"
    style.element.rPr.rFonts.set(qn("w:eastAsia"), east)
    style.font.size = Pt(size)
    if bold is not None:
        style.font.bold = bold
    if color is not None:
        style.font.color.rgb = color


font(doc.styles["Normal"], 10.5)
doc.styles["Normal"].paragraph_format.space_after = Pt(3)
doc.styles["Normal"].paragraph_format.line_spacing = 1.2
for lvl, size in ((1, 14), (2, 12)):
    s = doc.styles[f"Heading {lvl}"]
    font(s, size, True, "黑体", BLUE)
    s.paragraph_format.space_before = Pt(10)
    s.paragraph_format.space_after = Pt(4)
font(doc.styles["Caption"], 9, True, "黑体", RGBColor(0x33, 0x33, 0x33))


def P(text, bold_prefix=None, size=None):
    p = doc.add_paragraph()
    if bold_prefix:
        p.add_run(bold_prefix).bold = True
    r = p.add_run(text)
    if size:
        r.font.size = Pt(size)
    return p


def B(text, bold_prefix=None):
    p = doc.add_paragraph(style="List Bullet")
    if bold_prefix:
        p.add_run(bold_prefix).bold = True
    p.add_run(text)


def shade(cell, fill):
    sh = OxmlElement("w:shd")
    sh.set(qn("w:val"), "clear")
    sh.set(qn("w:color"), "auto")
    sh.set(qn("w:fill"), fill)
    cell._tc.get_or_add_tcPr().append(sh)


N = {"t": 0, "f": 0}


def TABLE(caption, header, rows, widths=None, good=None, bad=None):
    N["t"] += 1
    c = doc.add_paragraph(f"表{N['t']}  {caption}", style="Caption")
    c.alignment = WD_ALIGN_PARAGRAPH.CENTER
    t = doc.add_table(rows=1 + len(rows), cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for j, h in enumerate(header):
        cell = t.rows[0].cells[j]
        cell.text = ""
        r = cell.paragraphs[0].add_run(h)
        r.bold = True
        r.font.size = Pt(9)
        shade(cell, "DCE6F0")
    for i, row in enumerate(rows):
        for j, v in enumerate(row):
            cell = t.rows[i + 1].cells[j]
            cell.text = ""
            cell.paragraphs[0].add_run(str(v)).font.size = Pt(9)
            if good and good(i, j, v):
                shade(cell, "E2EFDA")
            if bad and bad(i, j, v):
                shade(cell, "FCE4D6")
    if widths:
        for row in t.rows:
            for j, w in enumerate(widths):
                row.cells[j].width = Cm(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def FIGURE(path, caption, width=15.5):
    N["f"] += 1
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run().add_picture(str(path), width=Cm(width))
    c = doc.add_paragraph(f"图{N['f']}  {caption}", style="Caption")
    c.alignment = WD_ALIGN_PARAGRAPH.CENTER


# ---------------- 标题 ----------------
t = doc.add_paragraph()
t.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = t.add_run("新灯（耀乾 FL05 泛光灯）室内测试简报")
r.bold = True
r.font.size = Pt(18)
r.font.color.rgb = BLUE
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.add_run("杆式夜间水体遥感反射率测量系统    测试：2026-10-22 晚，宁波公司室内    操作：郝威").font.size = Pt(9.5)

# ---------------- 结论 ----------------
doc.add_heading("结论", 1)
B(f"50 cm 范围内最低照度在 1.5–5 m 各距离都 ≥ {U['±25估算最低%'].min():.1f}%（要求 80%），80 cm 范围 ≥ {U['±40最低%'].min():.1f}%。"
  "旧灯在同样距离下全部不达标（最好 77.7%）。", "均匀性达标：")
B(f"开灯 20 min 后，水体与参考板间隔 1 min 配对，灯的变化 < 0.1%；20–50 min 波动 {ST['总量420-700']['pp_20_50']:.2f}%（旧灯 1.42%）。", "稳定性达标：")
B(f"中心亮度按 r^−{n_pow:.2f} 衰减（R² = {r2_pow:.4f}），可直接做距离修正。", "距离规律清楚：")
B(f"同为 2 m、灯中心，新灯亮度约为旧灯的 1/{ratio2['420-700积分比']:.0f}，420 nm 只有约 1/{ratio2['420nm']:.0f}。"
  "原因一是泛光把光摊开了，二是灯珠在蓝紫端本身偏弱。", "短板是亮度：")
B("绿、红波段（550、650 nm）在 1.5–5 m 都够；420 nm 和 700–720 nm 是瓶颈。估算安装 2–3 m、长积分时间加多帧平均可能够，但必须实测。",
  "水面能否用，待实测：")
B("样机不拆，新灯临时架在旁边，与样机原装旧灯在同一水面点对比测量，按第 5 节的判据决定是否换灯。", "下一步：")

# ---------------- 测试内容 ----------------
doc.add_heading("1 测试内容", 1)
TABLE("测试条件", ["项目", "内容"], [
    ["灯", "耀乾 FL05 泛光灯，50 W，DC 24 V"],
    ["探头 / 参考板", "IEP_O2N9DA（512 ms 固定积分时间）；25% 参考板，探头与板全程不动"],
    ["冷启动", "开灯后连续测参考板约 90 min"],
    ["距离与光斑", "灯距板 1.5 / 2 / 3 / 4 / 5 m；每个距离测中心及左右各 20、40 cm（共 5 点）"],
    ["亮度", "由各距离中心点数据计算单帧信噪比；与旧灯按辐亮度定标比较"],
], widths=[3.2, 13.3])

# ---------------- 结果 ----------------
doc.add_heading("2 光斑均匀性", 1)
rows = []
for _, r in U.iterrows():
    d = float(r["距离"])
    rows.append([f"{r['实测距离m']:.1f}", f"{r['±20最低%']:.1f}%", f"{r['±40最低%']:.1f}%", f"{r['±25估算最低%']:.1f}%",
                 f"{OLD_U25[d]:.1f}%", "达标" if r["±25估算最低%"] >= 80 else "不达标"])
TABLE("横向最低照度（相对同距离中心）", ["距离 / m", "±20 cm", "±40 cm", "50 cm 范围（新灯）", "50 cm 范围（旧灯）", "新灯判定"], rows,
      widths=[2.2, 2.4, 2.4, 3.3, 3.3, 2.4],
      good=lambda i, j, v: j == 5 and v == "达标", bad=lambda i, j, v: j == 4)
FIGURE(FIG / "dist_lateral.png", "横向光斑剖面：新灯（左）几乎是平的，旧灯（右）中心亮、两侧急降")

doc.add_heading("3 冷启动稳定性", 1)
TABLE("稳定性指标（420–700 nm）", ["指标", "新灯", "旧灯"], [
    ["开灯后前 5 min 变化", f"约 −{abs(cj['supp']['绿500-600']['T0至主序列起点变化%']):.1f}%（绿波段）", "—"],
    ["20–50 min 峰-峰变化", f"{ST['总量420-700']['pp_20_50']:.2f}%", "1.42%"],
    ["1 h 后变暗速率", f"{abs(cj['seg_fits'][3]['总量420-700']):.3f} %/min，接近平台", "0.022 %/min，未进入平台"],
    ["1 min 配对误差", "开灯 20 min 后 < 0.1%", "< 0.1%"],
], widths=[5, 5.8, 5.7])
P("建议开灯后等 20 min 再测，有条件等 1 h。")

doc.add_heading("4 亮度与信噪比", 1)
bt = {r["距离"]: r for r in sj["bands"] if r["噪声"] == "逐通道噪声"}
rows = [[f"{C.DIST_M[d]:.1f}", bt[d]["SNR≥20 最长连续波段nm"].replace("–", " – ")] for d in sorted(bt)]
TABLE("参考板单帧 SNR ≥ 20 的波段（512 ms）", ["距离 / m", "SNR ≥ 20 的连续波段 / nm"], rows, widths=[3, 8])
KEYW = [420, 450, 550, 650, 700]
TABLE("旧灯 ÷ 新灯 参考板辐亮度（2 m，灯中心）", [f"{w} nm" for w in KEYW] + ["420–700 nm"],
      [[f"{ratio2[f'{w}nm']:.1f} 倍" for w in KEYW] + [f"{ratio2['420-700积分比']:.1f} 倍"]], widths=[2.6] * 6)
P(f"两盏灯用不同探头测量，各自按同一台标准灯（Lamp2501）的定标换算成辐亮度后比较，误差约 ±20%（420–700 nm 比值范围 {rmin:.1f}–{rmax:.1f} 倍）。"
  f"新灯 420 nm 相对 450 nm 只有旧灯的约 1/3，属于灯珠本身的光谱特性。", size=9.5)
md = {(r["Rrs"], r["平均帧数"]): r for r in sj["maxd"]}
rows = []
for rrs in C.RRS_CASES:
    rows.append([f"{rrs}", md[(rrs, 1)]["420nm"], md[(rrs, 10)]["420nm"], md[(rrs, 1)]["700nm"], md[(rrs, 10)]["700nm"]])
TABLE("新灯在水面上满足 SNR ≥ 20 的最大安装距离（估算）", ["水体 Rrs / sr⁻¹", "420 nm 单帧", "420 nm 10 帧平均", "700 nm 单帧", "700 nm 10 帧平均"], rows,
      widths=[3.2, 3.2, 3.4, 3.2, 3.4])
P("估算条件：积分时间最长 8192 ms；假设水体反射率各波长相同、噪声不随积分时间增大。实际水体蓝端反射率通常更低，结果仅供参考，以实测为准。", size=9.5)

doc.add_heading("5 下一步：水面对比测试", 1)
P("样机不拆。原装旧灯照常使用，新灯用支架临时架在旁边、单独供电，对准同一水面点。用样机自己的探头分别测两盏灯，同时测一次参考板在样机位置和水面测点位置的照度差。")
TABLE("决策判据", ["实测结果", "结论"], [
    ["旧灯：参考板两个位置照度接近且稳定，水面 420–700 nm SNR ≥ 20", "样机暂不改动"],
    ["旧灯：参考板两个位置照度差别大或不稳定", "必须换灯（光斑问题，与亮度无关）"],
    ["新灯：在样机安装距离下水面 420 nm SNR ≥ 20", "换新灯"],
    ["新灯：420 nm 不够，440 nm 以上够", "换新灯并加一盏，或分析波段从约 440 nm 起"],
], widths=[10, 6.5])

doc.add_paragraph()
P("完整数据与方法见《新灯FL05室内实验报告_20261022_v2.docx》。", size=9.5)

out = ROOT / "新灯FL05测试简报_20261022.docx"
doc.save(out)
print("saved", out)
