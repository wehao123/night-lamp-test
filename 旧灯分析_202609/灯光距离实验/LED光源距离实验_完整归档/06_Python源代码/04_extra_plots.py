from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "01_原始数据" / "2026-09-11.db"
PROCESSED = ROOT / "03_处理数据"
OUT = ROOT / "04_图表"
OUT.mkdir(exist_ok=True)

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
DATE = "2026-09-11"
PROBE_ID = 2
INTEGRATION_TIME_MS = 0.4

# 带外波段：LED 在此几乎无辐射，可作为环境光探针
OOB_MIN_NM, OOB_MAX_NM = 800.0, 880.0
# LED 主峰波段，用于逐帧时间序列
MAIN_MIN_NM, MAIN_MAX_NM = 560.0, 600.0
# 夜间暗背景水平（DN），作为参考线
DARK_LEVEL = 1000.0
# 光谱图横轴范围：与 400-700 nm 分析波段一致，不再留大片空白
SPEC_X_MIN, SPEC_X_MAX = 410.0, 730.0
SPEC_X_TICKS = [420, 450, 500, 550, 600, 650, 700, 720]

COLORS = ["#2F5597", "#ED7D31", "#70AD47", "#A64D79", "#5B9BD5", "#C00000"]
LABELS = ["1.507 m", "2.032 m", "3.016 m", "3.995 m", "5.013 m"]


def read_csv(name):
    with (PROCESSED / name).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        return header, list(reader)


# ---------------------------------------------------------------------------
# 字体：按平台依次尝试，找不到退回 PIL 默认字体
# ---------------------------------------------------------------------------
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]
FONT_BOLD_CANDIDATES = [
    r"C:\Windows\Fonts\msyhbd.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]


def _first_existing(candidates):
    for path in candidates:
        if Path(path).exists():
            return path
    return None


FONT_PATH = _first_existing(FONT_CANDIDATES)
FONT_BOLD_PATH = _first_existing(FONT_BOLD_CANDIDATES)
if FONT_PATH is None:
    print("警告：未找到中文字体，图中中文可能显示为方块。")


def font(size, bold=False):
    path = FONT_BOLD_PATH if bold and FONT_BOLD_PATH else FONT_PATH
    if path is None:
        return ImageFont.load_default()
    return ImageFont.truetype(path, size)


class Chart:
    def __init__(self, width=1400, height=820, title="", xlabel="", ylabel="", margin=None):
        self.im = Image.new("RGB", (width, height), "white")
        self.d = ImageDraw.Draw(self.im)
        self.w, self.h = width, height
        self.m = margin or (145, 92, 55, 120)
        self.title, self.xlabel, self.ylabel = title, xlabel, ylabel

    def bounds(self):
        l, t, r, b = self.m
        return l, t, self.w - r, self.h - b

    def axes(self, xmin, xmax, ymin, ymax, xticks, yticks, xfmt=str, yfmt=str, title_size=34):
        l, t, r, b = self.bounds()
        self.d.line((l, b, r, b), fill="#333333", width=2)
        self.d.line((l, t, l, b), fill="#333333", width=2)
        f = font(23)
        for y in yticks:
            py = b - (y - ymin) / (ymax - ymin) * (b - t)
            self.d.line((l, py, r, py), fill="#D9D9D9", width=1)
            txt = yfmt(y)
            box = self.d.textbbox((0, 0), txt, font=f)
            self.d.text((l - 14 - (box[2] - box[0]), py - 14), txt, fill="#444444", font=f)
        for x in xticks:
            px = l + (x - xmin) / (xmax - xmin) * (r - l)
            self.d.line((px, b, px, b + 7), fill="#333333", width=2)
            txt = xfmt(x)
            box = self.d.textbbox((0, 0), txt, font=f)
            self.d.text((px - (box[2] - box[0]) / 2, b + 12), txt, fill="#444444", font=f)
        if self.title:
            self.d.text((self.w / 2, 25), self.title, anchor="ma", fill="#222222",
                        font=font(title_size, True))
        if self.xlabel:
            self.d.text((self.w / 2, self.h - 35), self.xlabel, anchor="ms",
                        fill="#333333", font=font(26))
        if self.ylabel:
            yf = font(25)
            box = self.d.textbbox((0, 0), self.ylabel, font=yf)
            label = Image.new("RGBA", (box[2] - box[0] + 14, box[3] - box[1] + 14),
                              (255, 255, 255, 0))
            ImageDraw.Draw(label).text((7, 7), self.ylabel, fill="#333333", font=yf, anchor="la")
            label = label.rotate(90, expand=True)
            self.im.paste(label, (18, int((t + b - label.height) / 2)), label)
        self.scale = (xmin, xmax, ymin, ymax)

    def xy(self, x, y):
        l, t, r, b = self.bounds()
        xmin, xmax, ymin, ymax = self.scale
        return (l + (x - xmin) / (xmax - xmin) * (r - l),
                b - (y - ymin) / (ymax - ymin) * (b - t))

    def line(self, xs, ys, color, width=4, dots=True, dashed=False):
        pts = [self.xy(float(x), float(y)) for x, y in zip(xs, ys)]
        if dashed:
            for a, b in zip(pts[:-1], pts[1:]):
                dx, dy = b[0] - a[0], b[1] - a[1]
                length = max(1, (dx * dx + dy * dy) ** 0.5)
                for s in np.arange(0, length, 18):
                    e = min(s + 10, length)
                    p1 = (a[0] + dx * s / length, a[1] + dy * s / length)
                    p2 = (a[0] + dx * e / length, a[1] + dy * e / length)
                    self.d.line((p1, p2), fill=color, width=width)
        else:
            self.d.line(pts, fill=color, width=width)
        if dots:
            for px, py in pts:
                self.d.ellipse((px - 6, py - 6, px + 6, py + 6), fill=color,
                               outline="white", width=2)

    def scatter(self, xs, ys, color, r=3):
        for x, y in zip(xs, ys):
            px, py = self.xy(float(x), float(y))
            self.d.ellipse((px - r, py - r, px + r, py + r), fill=color)

    def hline(self, y, color="#777777"):
        l, _, r, _ = self.bounds()
        py = self.xy(self.scale[0], y)[1]
        for x in range(int(l), int(r), 24):
            self.d.line((x, py, min(x + 14, r), py), fill=color, width=2)

    def vline(self, x, color="#BBBBBB", width=2):
        _, t, _, b = self.bounds()
        px = self.xy(x, self.scale[2])[0]
        self.d.line((px, t, px, b), fill=color, width=width)

    def vspan(self, x0, x1, color=(255, 205, 205)):
        """在 x 区间填充半透明色块，用于标注问题时段。"""
        l, t, r, b = self.bounds()
        px0 = max(l, self.xy(x0, self.scale[2])[0])
        px1 = min(r, self.xy(x1, self.scale[2])[0])
        if px1 <= px0:
            return
        w_, h_ = int(px1 - px0), int(b - t)
        overlay = Image.new("RGBA", (w_, h_), color + (110,))
        base = self.im.crop((int(px0), int(t), int(px0) + w_, int(t) + h_)).convert("RGBA")
        self.im.paste(Image.alpha_composite(base, overlay).convert("RGB"),
                      (int(px0), int(t)))

    def text_at(self, x, y, txt, size=20, color="#333333", anchor="mm", bold=False):
        px, py = self.xy(x, y)
        self.d.text((px, py), txt, anchor=anchor, fill=color, font=font(size, bold))

    def legend(self, items, x=None, y=None, cols=1, colw=245):
        x = x or self.bounds()[0] + 15
        y = y or self.bounds()[1] + 15
        f = font(21)
        for i, (label, color, dashed) in enumerate(items):
            row, col = divmod(i, cols)
            xx, yy = x + col * colw, y + row * 35
            if dashed:
                for sx in range(int(xx), int(xx + 42), 14):
                    self.d.line((sx, yy + 11, sx + 8, yy + 11), fill=color, width=3)
            else:
                self.d.line((xx, yy + 11, xx + 42, yy + 11), fill=color, width=4)
            self.d.text((xx + 52, yy), label, fill="#333333", font=f)

    def save(self, name):
        self.im.save(OUT / name)


def parse_local_time(text):
    return datetime.fromisoformat(f"{DATE}T{text}").replace(tzinfo=LOCAL_TZ)


def read_database():
    con = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    calibration_id, wavelength_json = con.execute(
        "SELECT calibration_id,wavelengths FROM calibrations "
        "WHERE probe_id=? AND is_active=1", (PROBE_ID,)
    ).fetchone()
    wavelength_map = json.loads(wavelength_json)
    wavelengths = np.array([wavelength_map[str(i)] for i in range(1, 289)], dtype=float)
    rows = con.execute(
        "SELECT c.timestamp,sd.dn_values FROM captures c "
        "JOIN spectra_dn sd ON sd.spectra_dn_id=c.spectra_dn_id "
        "WHERE c.probe_id=? AND sd.calibration_id=? "
        "AND ABS(sd.integration_time_ms-?)<1e-9 ORDER BY c.timestamp",
        (PROBE_ID, calibration_id, INTEGRATION_TIME_MS),
    ).fetchall()
    con.close()
    times = np.array([datetime.fromisoformat(r[0]).astimezone(LOCAL_TZ) for r in rows],
                     dtype=object)
    spectra = np.array([[json.loads(r[1])[str(i)] for i in range(1, 289)] for r in rows],
                       dtype=float)
    return times, spectra, wavelengths


# ===========================================================================
# 图01：中心净响应随距离衰减（五个距离全部参与拟合）
#   拟合指数与 R² 从 CSV 读取，不硬编码
# ===========================================================================
print("绘制图01：距离衰减 ...")
_, dr_rows_all = read_csv("distance_response.csv")
data_rows = [r for r in dr_rows_all if r[0] != "power_exponent"]
exponent_row = next(r for r in dr_rows_all if r[0] == "power_exponent")
power_exponent = float(exponent_row[1])   # 已经是正数（= -slope）
r_squared = float(exponent_row[3])

distance = np.array([float(r[0]) for r in data_rows])
response = np.array([float(r[1]) for r in data_rows])
fit_response = np.array([float(r[3]) for r in data_rows])

relative = response / response[0] * 100
fit_relative = fit_response / response[0] * 100

c = Chart(title="中心净响应随距离衰减", xlabel="距离 (m)", ylabel="相对净响应 (%)")
c.axes(1.4, 5.15, 0, 112, distance, [0, 20, 40, 60, 80, 100],
       lambda x: f"{x:g}", lambda y: f"{int(y)}")
c.line(distance, fit_relative, COLORS[1], dashed=True, dots=False)
c.line(distance, relative, COLORS[0])
for x, y, fitted in zip(distance, relative, fit_relative):
    px, py = c.xy(x, y)
    c.d.text((px, py - 20), f"{y:.1f}%", anchor="ms", font=font(20), fill="#333333")
    c.d.text((px, py + 14), f"({y / fitted * 100 - 100:+.1f}%)", anchor="ms",
             font=font(17), fill="#888888")
c.legend(
    [
        ("实测中心响应", COLORS[0], False),
        # power_exponent 存的是正数，显示时补负号
        (f"幂律拟合 R∝r^-{power_exponent:.2f}   R²={r_squared:.4f}", COLORS[1], True),
    ],
    x=640, y=120, colw=420,
)
c.d.text((c.bounds()[0] + 20, c.bounds()[3] - 32),
         "括号内为相对拟合曲线的偏差；理论平方反比为 r^-2.00",
         fill="#888888", font=font(18))
c.save("01_distance_response.png")

# ===========================================================================
# 图02：横向归一化光斑剖面（配光曲线）
# ===========================================================================
print("绘制图02：横向剖面 ...")
_, lp_rows = read_csv("lateral_profile.csv")
xpos = np.array([-40, -20, 0, 20, 40], float)
profiles = np.array([[float(v) for v in r[1:6]] for r in lp_rows], float) * 100

c = Chart(title="不同距离下的横向归一化光斑（配光剖面）",
          xlabel="横向位置 (cm)", ylabel="相对中心响应 (%)")
c.axes(-42, 42, 0, 108, [-40, -20, 0, 20, 40], [0, 20, 40, 60, 80, 100],
       lambda x: f"{int(x)}", lambda y: f"{int(y)}")
for vals, color in zip(profiles, COLORS):
    c.line(xpos, vals, color)
c.hline(80)
c.legend([(l, co, False) for l, co in zip(LABELS, COLORS)]
         + [("80% 阈值", "#777777", True)], x=175, y=120, cols=2)
c.d.text((c.bounds()[0] + 20, c.bounds()[3] - 32),
         "注：±40 cm 位于光束陡坡，定位误差在此处被显著放大",
         fill="#888888", font=font(18))
c.save("02_lateral_profiles.png")

# ===========================================================================
# 图05（改造）：遮阴段带外信号 —— 环境光探针
#   原版用全部 288 通道求和，混入大量 LED 无辐射波段，对比被稀释。
#   改用 LED 完全不发光的 800-880 nm，直接支撑开测判据。
# ===========================================================================
print("绘制图05：带外环境光水平 ...")
times, spectra, wavelengths = read_database()
oob = (wavelengths >= OOB_MIN_NM) & (wavelengths <= OOB_MAX_NM)
main = (wavelengths >= MAIN_MIN_NM) & (wavelengths <= MAIN_MAX_NM)

_, m_rows = read_csv("measurements.csv")
seg_ids = [int(r[0]) for r in m_rows]
seg_shade = [(r[6], r[7]) for r in m_rows]

oob_mean, oob_std = [], []
for s0, s1 in seg_shade:
    start, end = parse_local_time(s0), parse_local_time(s1)
    chosen = np.array([(t >= start) and (t <= end) for t in times])
    frames = spectra[chosen][:, oob].mean(axis=1)
    oob_mean.append(frames.mean())
    oob_std.append(frames.std(ddof=1) if len(frames) > 1 else 0.0)
oob_mean = np.array(oob_mean)
oob_std = np.array(oob_std)
order = np.array(seg_ids)

c = Chart(width=1650,
          title=f"遮阴段 {int(OOB_MIN_NM)}-{int(OOB_MAX_NM)} nm 带外信号（环境光探针）",
          xlabel="测量顺序 (M01-M31)", ylabel="带外平均 DN")
ymax = (oob_mean + oob_std).max() * 1.15
ymin = min(DARK_LEVEL - 120, (oob_mean - oob_std).min() * 0.95)
c.axes(0.3, 31.7, ymin, ymax, [1, 6, 7, 8, 13, 19, 25, 31],
       np.linspace(ymin, ymax, 6), lambda x: f"{int(x)}", lambda y: f"{int(y)}")
for boundary in [6.5, 7.5, 13.5, 19.5, 25.5]:
    c.vline(boundary)
c.vspan(0.3, 7.5)
for x, m_, s_ in zip(order, oob_mean, oob_std):
    px, _ = c.xy(x, m_)
    _, py_lo = c.xy(x, m_ - s_)
    _, py_hi = c.xy(x, m_ + s_)
    c.d.line((px, py_lo, px, py_hi), fill="#8064A2", width=2)
    c.d.line((px - 5, py_lo, px + 5, py_lo), fill="#8064A2", width=2)
    c.d.line((px - 5, py_hi, px + 5, py_hi), fill="#8064A2", width=2)
c.line(order, oob_mean, "#8064A2", width=3, dots=True)
c.hline(DARK_LEVEL, "#C00000")
c.text_at(4, ymax * 0.96, "暮光时段", size=22, color="#C00000", bold=True)
c.text_at(20, ymax * 0.96, "天黑后（2-5 m 正式数据）", size=22, color="#2F5597", bold=True)
c.d.text((c.bounds()[0] + 20, c.bounds()[3] - 32),
         f"红虚线为夜间暗背景 {int(DARK_LEVEL)} DN；误差棒为帧间标准差。"
         f"开测判据：带外回落至暗背景且波动 <±30 DN",
         fill="#888888", font=font(18))
c.save("05_background_out_of_band.png")

# ===========================================================================
# 图06：光谱形状
#   横轴收窄到 420-700 nm（与分析波段一致），图例下移避开曲线
# ===========================================================================
print("绘制图06：光谱形状 ...")
_, cs_rows = read_csv("center_net_spectra.csv")
wl = np.array([float(r[1]) for r in cs_rows])
valid = np.array([int(r[2]) for r in cs_rows]) == 1
center_specs = np.array([[float(r[col]) for r in cs_rows] for col in range(3, 8)], float)
net_header2, net_rows2 = read_csv("net_spectra.csv")
near_headers = net_header2[3:9]
near_specs = np.array([[float(r[col]) for r in net_rows2] for col in range(3, 9)], float)


def normalized(arr):
    return arr / np.max(arr[:, valid], axis=1)[:, None]


im = Image.new("RGB", (1800, 760), "white")
left = Chart(900, 760, "", "波长 (nm)", "峰值归一化响应", margin=(115, 90, 35, 120))
left.axes(SPEC_X_MIN, SPEC_X_MAX, 0, 1.08, SPEC_X_TICKS, [0, .2, .4, .6, .8, 1.0],
          lambda x: f"{int(x)}", lambda y: f"{y:.1f}")
for vals, color in zip(normalized(center_specs), COLORS):
    left.line(wl[valid], vals[valid], color, width=3, dots=False)
# 左图曲线集中在中部，图例放右上角空白处
left.legend([(l, co, False) for l, co in zip(LABELS, COLORS)], x=600, y=112, cols=1)

right = Chart(900, 760, "", "波长 (nm)", "峰值归一化响应", margin=(115, 90, 35, 120))
right.axes(SPEC_X_MIN, SPEC_X_MAX, -.12, 1.08, SPEC_X_TICKS, [0, .2, .4, .6, .8, 1.0],
           lambda x: f"{int(x)}", lambda y: f"{y:.1f}")
for header, vals, color in zip(near_headers, normalized(near_specs), COLORS):
    is_bad = "右2" in header
    right.line(wl[valid], vals[valid], "#C00000" if is_bad else color,
               width=5 if is_bad else 2, dots=False)
# 右图 400-450 nm 段曲线很低，图例放左上角不会被盖住
right.legend([(h.split("_", 2)[-1], "#C00000" if "右2" in h else co, False)
              for h, co in zip(near_headers, COLORS)], x=145, y=112, cols=1)

im.paste(left.im, (0, 0))
im.paste(right.im, (900, 0))
top = ImageDraw.Draw(im)
top.rectangle((0, 0, 1800, 78), fill="white")
tf = font(34, True)
for cx, title_txt in [(450, "中心净光谱形状（各距离一致）"),
                      (1350, "1.507 m 横向净谱：右2 谱形异常")]:
    box = top.textbbox((0, 0), title_txt, font=tf)
    top.text((cx - (box[2] - box[0]) / 2, 25), title_txt, fill="#222222", font=tf)
im.save(OUT / "06_spectral_shape.png")

# ===========================================================================
# 图07：1.507 m 组逐帧时间序列诊断
#   上：LED 主峰逐帧信号 —— 平台是否稳定、中间2 是否在漂
#   下：带外逐帧信号 —— 环境光污染，右2 时段应明显抬升
# ===========================================================================
print("绘制图07：1.507 m 时间序列诊断 ...")
t_start = parse_local_time("17:48:35")
t_end = parse_local_time("17:54:15")
chosen = np.array([(t >= t_start) and (t <= t_end) for t in times])
seg_times = times[chosen]
elapsed = np.array([(t - t_start).total_seconds() for t in seg_times])
main_sig = spectra[chosen][:, main].mean(axis=1)
oob_sig = spectra[chosen][:, oob].mean(axis=1)

seg_windows = []
for r in m_rows:
    if abs(float(r[1]) - 1.507) > 1e-6:
        continue
    l0 = (parse_local_time(r[4]) - t_start).total_seconds()
    l1 = (parse_local_time(r[5]) - t_start).total_seconds()
    seg_windows.append((r[2], l0, l1))

im = Image.new("RGB", (1700, 1200), "white")

top_c = Chart(1700, 630, "", "",
              f"LED 主峰 {int(MAIN_MIN_NM)}-{int(MAIN_MAX_NM)} nm 逐帧 DN",
              margin=(155, 85, 50, 60))
top_c.axes(0, elapsed.max(), 0, main_sig.max() * 1.15,
           np.arange(0, elapsed.max(), 60),
           np.linspace(0, main_sig.max() * 1.15, 6),
           lambda x: f"{int(x)}", lambda y: f"{y / 1000:.0f}k")
for name, l0, l1 in seg_windows:
    if name == "右2":
        top_c.vspan(l0, l1)
    top_c.text_at((l0 + l1) / 2, main_sig.max() * 1.07, name, size=19,
                  color="#C00000" if name == "右2" else "#555555")
top_c.line(elapsed, main_sig, COLORS[0], width=2, dots=False)
top_c.scatter(elapsed, main_sig, COLORS[0], r=2)

bot_c = Chart(1700, 570, "", "相对 17:48:35 的秒数",
              f"带外 {int(OOB_MIN_NM)}-{int(OOB_MAX_NM)} nm 逐帧 DN",
              margin=(155, 45, 50, 115))
y_lo = min(800, oob_sig.min() * 0.95)
y_hi = oob_sig.max() * 1.1
bot_c.axes(0, elapsed.max(), y_lo, y_hi,
           np.arange(0, elapsed.max(), 60), np.linspace(y_lo, y_hi, 6),
           lambda x: f"{int(x)}", lambda y: f"{int(y)}")
for name, l0, l1 in seg_windows:
    if name == "右2":
        bot_c.vspan(l0, l1)
bot_c.line(elapsed, oob_sig, "#8064A2", width=2, dots=False)
bot_c.scatter(elapsed, oob_sig, "#8064A2", r=2)
bot_c.hline(DARK_LEVEL, "#C00000")

im.paste(top_c.im, (0, 0))
im.paste(bot_c.im, (0, 630))
d7 = ImageDraw.Draw(im)
d7.rectangle((0, 0, 1700, 72), fill="white")
title7 = "1.507 m 组逐帧时间序列诊断（红色区间为右2）"
tf = font(32, True)
box = d7.textbbox((0, 0), title7, font=tf)
d7.text((850 - (box[2] - box[0]) / 2, 20), title7, fill="#222222", font=tf)
d7.text((155, 1168),
        "上图看平台是否稳定；下图带外信号抬升即为环境光污染，天黑后应贴合红色暗背景线",
        fill="#888888", font=font(19))
im.save(OUT / "07_near_distance_diagnosis.png")

print(f"完成：已生成 5 张图表，保存于 {OUT}")
print("  01 距离衰减 / 02 横向剖面 / 05 带外环境光 / 06 光谱形状 / 07 1.507m 诊断")
print(f"  距离衰减指数 = -{power_exponent:.4f}，R² = {r_squared:.4f}（五个距离全部参与拟合）")