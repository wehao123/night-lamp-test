"""导出 1.507 m 右2异常核查材料包。"""

from __future__ import annotations

import csv
import json
import math
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "01_原始数据" / "2026-09-11.db"
SEGMENT_PATH = ROOT / "02_时间戳" / "final_segments.csv"
OUT = ROOT / "07_右2异常核查材料包"

DATE = "2026-09-11"
LOCAL_TZ = ZoneInfo("Asia/Shanghai")
PROBE_ID = 2
INTEGRATION_TIME_MS = 0.4
BAND_MIN, BAND_MAX = 400.0, 720.0
MAIN_MIN, MAIN_MAX = 560.0, 600.0
OOB_MIN, OOB_MAX = 800.0, 880.0

FONT_PATHS = [
    Path(r"C:\Windows\Fonts\msyh.ttc"),
    Path(r"C:\Windows\Fonts\simhei.ttf"),
]
COLORS = ["#2F5597", "#ED7D31", "#C00000", "#70AD47", "#8064A2"]


def font(size: int, bold: bool = False):
    candidates = [Path(r"C:\Windows\Fonts\msyhbd.ttc")] if bold else []
    candidates += FONT_PATHS
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def write_csv(path: Path, header, rows) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def read_segments():
    with SEGMENT_PATH.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def parse_time(text: str):
    return datetime.fromisoformat(f"{DATE}T{text}").replace(tzinfo=LOCAL_TZ)


def read_db():
    con = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    calibration_id, wavelength_json = con.execute(
        "SELECT calibration_id,wavelengths FROM calibrations "
        "WHERE probe_id=? AND is_active=1",
        (PROBE_ID,),
    ).fetchone()
    wavelength_map = json.loads(wavelength_json)
    wavelengths = np.array([wavelength_map[str(i)] for i in range(1, 289)], float)
    rows = con.execute(
        "SELECT c.timestamp,sd.dn_values FROM captures c "
        "JOIN spectra_dn sd ON sd.spectra_dn_id=c.spectra_dn_id "
        "WHERE c.probe_id=? AND sd.calibration_id=? "
        "AND ABS(sd.integration_time_ms-?)<1e-9 ORDER BY c.timestamp",
        (PROBE_ID, calibration_id, INTEGRATION_TIME_MS),
    ).fetchall()
    con.close()
    times = np.array(
        [datetime.fromisoformat(r[0]).astimezone(LOCAL_TZ) for r in rows], dtype=object
    )
    spectra = np.array(
        [[json.loads(r[1])[str(i)] for i in range(1, 289)] for r in rows], float
    )
    return times, spectra, wavelengths


def select_frames(times, spectra, start_text, end_text):
    start, end = parse_time(start_text), parse_time(end_text)
    chosen = np.array([(start <= t <= end) for t in times])
    return times[chosen], spectra[chosen]


def cosine(a, b):
    den = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / den) if den else math.nan


class Chart:
    def __init__(self, title, xlabel, ylabel, width=1600, height=920,
                 margin=(150, 95, 55, 120)):
        self.im = Image.new("RGB", (width, height), "white")
        self.d = ImageDraw.Draw(self.im)
        self.width, self.height = width, height
        self.margin = margin
        self.title, self.xlabel, self.ylabel = title, xlabel, ylabel

    def bounds(self):
        left, top, right, bottom = self.margin
        return left, top, self.width - right, self.height - bottom

    def axes(self, xmin, xmax, ymin, ymax, xticks, yticks, xfmt, yfmt):
        self.scale = xmin, xmax, ymin, ymax
        left, top, right, bottom = self.bounds()
        self.d.line((left, bottom, right, bottom), fill="#333333", width=2)
        self.d.line((left, top, left, bottom), fill="#333333", width=2)
        tick_font = font(22)
        for y in yticks:
            py = self.xy(xmin, y)[1]
            self.d.line((left, py, right, py), fill="#E0E0E0", width=1)
            text = yfmt(y)
            box = self.d.textbbox((0, 0), text, font=tick_font)
            self.d.text((left - 12 - (box[2] - box[0]), py - 13), text,
                        fill="#444444", font=tick_font)
        for x in xticks:
            px = self.xy(x, ymin)[0]
            self.d.line((px, bottom, px, bottom + 7), fill="#333333", width=2)
            text = xfmt(x)
            box = self.d.textbbox((0, 0), text, font=tick_font)
            self.d.text((px - (box[2] - box[0]) / 2, bottom + 12), text,
                        fill="#444444", font=tick_font)
        self.d.text((self.width / 2, 25), self.title, anchor="ma",
                    fill="#222222", font=font(32, True))
        self.d.text((self.width / 2, self.height - 30), self.xlabel, anchor="ms",
                    fill="#333333", font=font(25))
        ylabel_font = font(24)
        box = self.d.textbbox((0, 0), self.ylabel, font=ylabel_font)
        label = Image.new(
            "RGBA", (box[2] - box[0] + 16, box[3] - box[1] + 16),
            (255, 255, 255, 0),
        )
        ImageDraw.Draw(label).text(
            (8, 8), self.ylabel, fill="#333333", font=ylabel_font, anchor="la"
        )
        label = label.rotate(90, expand=True)
        self.im.paste(label, (14, int((top + bottom - label.height) / 2)), label)

    def xy(self, x, y):
        left, top, right, bottom = self.bounds()
        xmin, xmax, ymin, ymax = self.scale
        px = left + (x - xmin) / (xmax - xmin) * (right - left)
        py = bottom - (y - ymin) / (ymax - ymin) * (bottom - top)
        return px, py

    def line(self, xs, ys, color, width=4):
        points = [self.xy(float(x), float(y)) for x, y in zip(xs, ys)]
        if len(points) >= 2:
            self.d.line(points, fill=color, width=width)

    def span(self, x0, x1, color):
        left, top, right, bottom = self.bounds()
        px0 = max(left, self.xy(x0, self.scale[2])[0])
        px1 = min(right, self.xy(x1, self.scale[2])[0])
        if px1 > px0:
            self.d.rectangle((px0, top, px1, bottom), fill=color)

    def legend(self, items, x=1040, y=115):
        self.d.rectangle(
            (x - 18, y - 12, min(self.width - 25, x + 485), y + len(items) * 36 + 8),
            fill="white", outline="#DDDDDD", width=1,
        )
        for i, (label, color) in enumerate(items):
            yy = y + i * 36
            self.d.line((x, yy + 12, x + 45, yy + 12), fill=color, width=5)
            self.d.text((x + 55, yy), label, fill="#333333", font=font(21))

    def save(self, name):
        self.im.save(OUT / name)


def chart_range(values, padding=0.08):
    lo, hi = float(np.nanmin(values)), float(np.nanmax(values))
    span = hi - lo if hi > lo else max(abs(hi), 1.0)
    return lo - span * padding, hi + span * padding


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    segments = read_segments()
    times, spectra, wavelengths = read_db()
    band = (wavelengths >= BAND_MIN) & (wavelengths <= BAND_MAX)
    main_band = (wavelengths >= MAIN_MIN) & (wavelengths <= MAIN_MAX)
    oob_band = (wavelengths >= OOB_MIN) & (wavelengths <= OOB_MAX)

    records = []
    for s in segments:
        led_times, led_frames = select_frames(
            times, spectra, s["led_start"], s["led_end"]
        )
        shade_times, shade_frames = select_frames(
            times, spectra, s["shade_start"], s["shade_end"]
        )
        led_median = np.median(led_frames, axis=0)
        shade_median = np.median(shade_frames, axis=0)
        net = led_median - shade_median
        led_band_sum = led_frames[:, band].sum(axis=1)
        noise = 1.4826 * np.median(np.abs(shade_frames - shade_median), axis=0)
        valid_noise = band & (noise > 0)
        peak_i = np.flatnonzero(band)[np.argmax(net[band])]
        records.append(
            {
                **s,
                "led_times": led_times,
                "led_frames_data": led_frames,
                "shade_times": shade_times,
                "shade_frames_data": shade_frames,
                "led_median": led_median,
                "shade_median": shade_median,
                "net": net,
                "response": float(net[band].sum()),
                "peak_dn": float(net[peak_i]),
                "peak_nm": float(wavelengths[peak_i]),
                "led_cv": float(np.std(led_band_sum, ddof=1) / np.mean(led_band_sum) * 100),
                "negative_fraction": float(np.mean(net[band] < 0)),
                "snr3_fraction": float(np.mean(net[valid_noise] / noise[valid_noise] >= 3)),
                "shade_oob_mean": float(shade_frames[:, oob_band].mean()),
            }
        )

    def find(distance, position):
        return next(
            r for r in records
            if abs(float(r["distance_m"]) - distance) < 1e-6
            and r["position"] == position
        )

    near = [find(1.507, p) for p in ["中间1", "右1", "右2", "中间2", "左1", "左2"]]
    far_right2 = find(2.032, "右2")
    compare = near + [far_right2]

    # 精简版总表：一行是一帧，列名同时带通道号和标定波长。
    # 包含1.507 m六个位置以及2.032 m右2，可从这一张表重新计算全部核查图。
    frame_header = [
        "measurement_id", "distance_m", "position", "lateral_cm", "state",
        "frame_index", "timestamp", "integration_time_ms",
    ] + [
        f"ch{i + 1:03d}_{wavelengths[i]:.3f}nm" for i in range(len(wavelengths))
    ]
    frame_rows = []
    for r in compare:
        for state, frame_times, frames in [
            ("LED", r["led_times"], r["led_frames_data"]),
            ("shade", r["shade_times"], r["shade_frames_data"]),
        ]:
            for frame_index, (timestamp, frame) in enumerate(
                zip(frame_times, frames), start=1
            ):
                frame_rows.append(
                    [
                        r["id"], r["distance_m"], r["position"], r["lateral_cm"],
                        state, frame_index, timestamp.isoformat(), INTEGRATION_TIME_MS,
                    ]
                    + frame.tolist()
                )
    write_csv(OUT / "06_右2核查总数据.csv", frame_header, frame_rows)

    centers = {}
    for distance in [1.507, 2.032]:
        c1, c2 = find(distance, "中间1"), find(distance, "中间2")
        centers[distance] = {
            "net": (c1["net"] + c2["net"]) / 2,
            "response": (c1["response"] + c2["response"]) / 2,
        }

    summary_rows = []
    for r in compare:
        distance = float(r["distance_m"])
        center = centers[distance]
        summary_rows.append(
            [
                r["id"], distance, r["position"], r["lateral_cm"],
                r["led_start"], r["led_end"], r["shade_start"], r["shade_end"],
                len(r["led_frames_data"]), len(r["shade_frames_data"]),
                r["response"], r["response"] / center["response"] * 100,
                r["peak_dn"], r["peak_nm"], r["led_cv"],
                cosine(r["net"][band], center["net"][band]),
                r["snr3_fraction"] * 100, r["negative_fraction"] * 100,
                r["shade_oob_mean"],
            ]
        )
    write_csv(
        OUT / "01_测量摘要.csv",
        [
            "id", "distance_m", "position", "lateral_cm", "led_start", "led_end",
            "shade_start", "shade_end", "led_frames", "shade_frames",
            "net_response_400_720_dn_channel", "relative_to_center_percent",
            "net_peak_dn", "peak_wavelength_nm", "led_frame_cv_percent",
            "cosine_to_same_distance_center", "snr3_channels_percent",
            "negative_channels_percent", "shade_800_880_mean_dn",
        ],
        summary_rows,
    )

    r2 = find(1.507, "右2")
    cnear = centers[1.507]["net"]
    write_csv(
        OUT / "02_代表光谱.csv",
        [
            "channel", "wavelength_nm", "in_400_720_nm",
            "right2_led_median_dn", "right2_shade_median_dn", "right2_net_dn",
            "center_average_net_dn", "right1_net_dn", "left2_net_dn",
            "2.032m_right2_net_dn",
        ],
        [
            [
                i + 1, wavelengths[i], int(band[i]), r2["led_median"][i],
                r2["shade_median"][i], r2["net"][i], cnear[i],
                find(1.507, "右1")["net"][i], find(1.507, "左2")["net"][i],
                far_right2["net"][i],
            ]
            for i in range(len(wavelengths))
        ],
    )

    def export_frames(path, frame_times, frames):
        write_csv(
            path,
            ["timestamp", "channel", "wavelength_nm", "dn"],
            [
                [t.isoformat(), channel + 1, wavelengths[channel], frame[channel]]
                for t, frame in zip(frame_times, frames)
                for channel in range(len(wavelengths))
            ],
        )

    export_frames(
        OUT / "03_右2_LED逐帧光谱.csv", r2["led_times"], r2["led_frames_data"]
    )
    export_frames(
        OUT / "04_右2_遮阴逐帧光谱.csv", r2["shade_times"], r2["shade_frames_data"]
    )

    window_start, window_end = parse_time("17:48:35"), parse_time("17:54:15")
    chosen = np.array([(window_start <= t <= window_end) for t in times])
    t_win, s_win = times[chosen], spectra[chosen]

    def segment_label(t):
        for r in near:
            if parse_time(r["led_start"]) <= t <= parse_time(r["led_end"]):
                return r["position"], "LED"
            if parse_time(r["shade_start"]) <= t <= parse_time(r["shade_end"]):
                return r["position"], "shade"
        return "", "transition"

    timeline_rows = []
    for t, frame in zip(t_win, s_win):
        position, state = segment_label(t)
        timeline_rows.append(
            [
                t.isoformat(), (t - window_start).total_seconds(), position, state,
                frame[band].sum(), frame[main_band].mean(), frame[oob_band].mean(),
            ]
        )
    write_csv(
        OUT / "05_1.507m逐帧时间序列.csv",
        [
            "timestamp", "elapsed_seconds", "position", "state",
            "sum_400_720_dn_channel", "mean_560_600_dn", "mean_800_880_dn",
        ],
        timeline_rows,
    )

    # 图1：绝对净光谱
    xs = wavelengths[band]
    plot_specs = [
        ("1.507 m 中心平均", cnear, COLORS[0]),
        ("1.507 m 右1", find(1.507, "右1")["net"], COLORS[1]),
        ("1.507 m 右2", r2["net"], COLORS[2]),
        ("1.507 m 左2", find(1.507, "左2")["net"], COLORS[3]),
        ("2.032 m 右2", far_right2["net"], COLORS[4]),
    ]

    # 发给同事的极简图：只比较1.507 m同组五个横向位置。
    # 中心使用中间1和中间2净光谱的平均，图例明确写出横向坐标。
    simple_specs = [
        ("左2（-40 cm）", find(1.507, "左2")["net"], "#70AD47"),
        ("左1（-20 cm）", find(1.507, "左1")["net"], "#8064A2"),
        ("中心（中间1/中间2平均，0 cm）", cnear, "#2F5597"),
        ("右1（+20 cm）", find(1.507, "右1")["net"], "#ED7D31"),
        ("右2（+40 cm）", r2["net"], "#C00000"),
    ]
    simple_y = np.concatenate([values[band] for _, values, _ in simple_specs])
    sy0, sy1 = chart_range(simple_y)
    chart = Chart("1.507 m横向位置扣背景净光谱", "波长 (nm)", "净信号 (DN)")
    chart.axes(
        400, 720, sy0, sy1, [400, 450, 500, 550, 600, 650, 700, 720],
        np.linspace(sy0, sy1, 6), lambda x: f"{int(x)}", lambda y: f"{y / 1000:.0f}k",
    )
    for label, values, color in simple_specs:
        chart.line(xs, values[band], color, 5 if "右2" in label else 3)
    chart.legend([(label, color) for label, _, color in simple_specs], x=980, y=112)
    chart.d.text(
        (chart.width / 2, chart.height - 76),
        "净光谱 = LED时段逐通道中位数 − 遮阴时段逐通道中位数；右2用红色粗线标出",
        anchor="mm", fill="#777777", font=font(18),
    )
    chart.save("图00_1.507m横向净光谱对比.png")

    all_y = np.concatenate([s[1][band] for s in plot_specs])
    ymin, ymax = chart_range(all_y)
    chart = Chart("扣背景后绝对净光谱（未归一化）", "波长 (nm)", "净信号 (DN)")
    chart.axes(400, 720, ymin, ymax, [400, 450, 500, 550, 600, 650, 700, 720],
               np.linspace(ymin, ymax, 6), lambda x: f"{int(x)}",
               lambda y: f"{y / 1000:.0f}k")
    for _, values, color in plot_specs:
        chart.line(xs, values[band], color, 5 if color == COLORS[2] else 3)
    chart.legend([(label, color) for label, _, color in plot_specs], x=1050, y=120)
    chart.d.text(
        (chart.width / 2, chart.height - 76),
        "净光谱 = LED时段逐通道中位数 − 遮阴时段逐通道中位数",
        anchor="mm", fill="#777777", font=font(18),
    )
    chart.save("图01_绝对净光谱对比.png")

    # 图2：峰值归一化谱形
    normalized_specs = [values[band] / np.max(values[band]) for _, values, _ in plot_specs]
    normalized_min = min(float(np.min(values)) for values in normalized_specs)
    plot_ymin = min(-0.08, normalized_min - 0.04)
    chart = Chart(
        "峰值归一化谱形（低SNR质量诊断）",
        "波长 (nm)", "各曲线按自身峰值归一化",
    )
    chart.axes(400, 720, plot_ymin, 1.08,
               [400, 450, 500, 550, 600, 650, 700, 720],
               np.linspace(plot_ymin, 1.0, 6), lambda x: f"{int(x)}",
               lambda y: f"{y:.1f}")
    for normalized, (_, _, color) in zip(normalized_specs, plot_specs):
        chart.line(xs, normalized, color, 5 if color == COLORS[2] else 3)
    chart.legend([(label, color) for label, _, color in plot_specs], x=1050, y=120)
    chart.d.text(
        (chart.width / 2, chart.height - 76),
        "1.507 m右2仅为中心约8%，归一化会放大噪声；本图不代表LED真实谱形发生改变",
        anchor="mm", fill="#A00000", font=font(18, True),
    )
    chart.save("图02_峰值归一化谱形.png")

    # 图3：全组逐帧时间序列（上下两幅）
    elapsed = np.array([(t - window_start).total_seconds() for t in t_win])
    main_values = s_win[:, main_band].mean(axis=1)
    oob_values = s_win[:, oob_band].mean(axis=1)
    im = Image.new("RGB", (1600, 1200), "white")
    top = Chart("", "", "560–600 nm平均DN", 1600, 620, (150, 90, 55, 65))
    y0, y1 = chart_range(main_values)
    top.axes(0, elapsed.max(), y0, y1, np.arange(0, 341, 60), np.linspace(y0, y1, 6),
             lambda x: f"{int(x)}", lambda y: f"{y / 1000:.0f}k")
    top.line(elapsed, main_values, COLORS[0], 2)
    bottom = Chart("", "相对17:48:35的秒数", "800–880 nm平均DN",
                   1600, 580, (150, 35, 55, 105))
    z0, z1 = chart_range(oob_values)
    bottom.axes(0, elapsed.max(), z0, z1, np.arange(0, 341, 60), np.linspace(z0, z1, 6),
                lambda x: f"{int(x)}", lambda y: f"{int(y)}")
    bottom.line(elapsed, oob_values, COLORS[4], 2)
    for r in near:
        if r["position"] == "右2":
            a = (parse_time(r["led_start"]) - window_start).total_seconds()
            b = (parse_time(r["shade_end"]) - window_start).total_seconds()
            for panel in [top, bottom]:
                px0 = panel.xy(a, panel.scale[2])[0]
                px1 = panel.xy(b, panel.scale[2])[0]
                l, t, rr, bb = panel.bounds()
                overlay = Image.new("RGBA", panel.im.size, (255, 255, 255, 0))
                od = ImageDraw.Draw(overlay)
                od.rectangle((px0, t, px1, bb), fill=(255, 205, 205, 90))
                panel.im = Image.alpha_composite(panel.im.convert("RGBA"), overlay).convert("RGB")
                panel.d = ImageDraw.Draw(panel.im)
    im.paste(top.im, (0, 0))
    im.paste(bottom.im, (0, 620))
    draw = ImageDraw.Draw(im)
    draw.rectangle((0, 0, 1600, 60), fill="white")
    draw.text((800, 20), "1.507 m全组逐帧时间序列（红区为右2完整操作时段）",
              anchor="ma", fill="#222222", font=font(31, True))
    im.save(OUT / "图03_1.507m逐帧时间序列.png")

    # 图4：右2 LED和遮阴的所有逐帧光谱
    values_all = np.concatenate(
        [r2["led_frames_data"][:, band].ravel(), r2["shade_frames_data"][:, band].ravel()]
    )
    y0, y1 = chart_range(values_all)
    chart = Chart("1.507 m右2原始逐帧DN（未扣背景）", "波长 (nm)", "原始DN")
    chart.axes(400, 720, y0, y1, [400, 450, 500, 550, 600, 650, 700, 720],
               np.linspace(y0, y1, 6), lambda x: f"{int(x)}",
               lambda y: f"{y / 1000:.0f}k")
    for frame in r2["led_frames_data"]:
        chart.line(xs, frame[band], "#C8C8C8", 1)
    for frame in r2["shade_frames_data"]:
        chart.line(xs, frame[band], "#B4C7E7", 1)
    chart.line(xs, r2["led_median"][band], COLORS[2], 5)
    chart.line(xs, r2["shade_median"][band], COLORS[0], 5)
    chart.legend(
        [("LED各帧", "#C8C8C8"), ("遮阴各帧", "#B4C7E7"),
         ("LED中位数", COLORS[2]), ("遮阴中位数", COLORS[0])],
        x=1080, y=120,
    )
    chart.d.text(
        (chart.width / 2, chart.height - 76),
        "灰/浅蓝线为各帧，红/深蓝线为各自中位数；本图用于检查帧间波动",
        anchor="mm", fill="#777777", font=font(18),
    )
    chart.save("图04_右2逐帧光谱.png")

    rel = r2["response"] / centers[1.507]["response"] * 100
    cos = cosine(r2["net"][band], centers[1.507]["net"][band])
    far_rel = far_right2["response"] / centers[2.032]["response"] * 100
    far_cos = cosine(far_right2["net"][band], centers[2.032]["net"][band])
    note = f"""# 1.507 m右2异常核查材料

## 测量信息

- 距离：1.507 m
- 位置：右2（中心右侧40 cm）
- LED时段：{r2['led_start']}–{r2['led_end']}
- 遮阴时段：{r2['shade_start']}–{r2['shade_end']}
- 探头：{PROBE_ID}
- 积分时间：{INTEGRATION_TIME_MS} ms
- 分析波段：{BAND_MIN:.0f}–{BAND_MAX:.0f} nm
- 净光谱定义：LED段逐通道中位数 − 遮阴段逐通道中位数

## 当前数据表现

- 右2净响应：{r2['response']:.0f} DN·channel
- 相对同距离中心平均：{rel:.1f}%
- LED段帧间CV：{r2['led_cv']:.1f}%
- 与同距离中心谱形余弦相似度：{cos:.4f}
- SNR≥3的有效波段通道比例：{r2['snr3_fraction'] * 100:.1f}%
- 400–720 nm负值通道比例：{r2['negative_fraction'] * 100:.1f}%

作为对照，2.032 m右2相对同距离中心也只有{far_rel:.1f}%，但它与中心谱形的余弦相似度为{far_cos:.4f}，LED段帧间CV为{far_right2['led_cv']:.1f}%。这说明右2位于光斑边缘、绝对信号很弱可能是正常空间分布；1.507 m右2真正异常的是在弱信号之外还出现了谱形失真和更大的帧间波动。

仅凭汇总值不能唯一判断失真原因，需要结合逐帧变化和现场操作确认。

## 请协助确认

1. 右2测量时，灯、参考板或光谱仪是否发生移动或重新定位？
2. 光谱仪视场是否完全落在参考板及灯斑范围内？
3. 现场是否有人经过、遮挡或形成反射？
4. 遮阴板是否完全覆盖光谱仪视场对应的参考板区域？
5. 右2测量期间是否调整过积分时间、增益或其他仪器设置？
6. 原始视频中17:50:44–17:51:09是否能看到操作变化？

## 文件说明

- `01_测量摘要.csv`：1.507 m六个位置及2.032 m右2的质量指标。
- `02_代表光谱.csv`：右2的LED、遮阴和净谱，以及相邻位置对照。
- `03_右2_LED逐帧光谱.csv`：右2 LED时段原始逐帧、逐通道DN。
- `04_右2_遮阴逐帧光谱.csv`：右2遮阴时段原始逐帧、逐通道DN。
- `05_1.507m逐帧时间序列.csv`：1.507 m整组测量的逐帧波段统计。
- `图01`：判断右2是单纯变暗还是存在波段差异。
- `图02`：去掉强度差后比较谱形。
- `图03`：检查右2附近是否存在时间突变和带外环境变化。
- `图04`：检查右2异常来自全部帧还是少数离群帧。
"""
    (OUT / "00_发给同事的说明.md").write_text(note, encoding="utf-8")
    simple_note = f"""# 1.507 m右2异常核查

数据文件只有一个：`右2核查总数据.csv`。

- 每行是一帧原始测量。
- `state`区分正常LED照明和遮阴背景。
- `position`区分中间、左1、左2、右1和右2。
- 后面的288列是光谱通道，列名中同时写有通道号和标定波长。
- 包含1.507 m六个位置和2.032 m右2对照。
- 积分时间为{INTEGRATION_TIME_MS} ms。

1.507 m右2净响应约为同距离中心的{rel:.1f}%，谱形余弦相似度为{cos:.4f}，LED段帧间CV为{r2['led_cv']:.1f}%。2.032 m右2同样只有中心的{far_rel:.1f}%，但谱形相似度为{far_cos:.4f}，说明右2信号弱可能来自光斑边缘；需要进一步确认1.507 m右2为何还出现谱形失真和较大波动。

请协助确认17:50:44–17:51:09期间是否发生灯具、参考板、光谱仪移动，人员遮挡或反射，遮阴板覆盖不完整，或者仪器设置变化。
"""
    (OUT / "00_精简版说明.md").write_text(simple_note, encoding="utf-8")
    minimal_note = """# 发给同事

图中比较的是1.507 m下五个横向位置扣背景后的净光谱。中心为中间1和中间2的平均；左1、右1对应±20 cm，左2、右2对应±40 cm。右2为红色粗线。

想请你帮忙看一下：右2明显弱于左2，而且扣背景后的曲线波动更大。当时右2测量期间是否发生过位置偏差、遮挡、人员走动、反射或遮阴板覆盖不完整？

CSV中每行是一帧原始数据，`state`区分LED和遮阴，后面288列为各光谱通道DN。
"""
    (OUT / "00_极简说明.md").write_text(minimal_note, encoding="utf-8")
    print(f"材料包已生成：{OUT}")
    print(f"右2相对中心={rel:.1f}%，CV={r2['led_cv']:.1f}%，谱形余弦={cos:.4f}")


if __name__ == "__main__":
    main()
