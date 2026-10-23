"""公共函数：读存档 CSV、插值去定位笔、偏置、波段积分、读操作记录。"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "out"
FIG = OUT / "fig"
OUT.mkdir(exist_ok=True)
FIG.mkdir(exist_ok=True)

BJ = pd.Timedelta(hours=8)

# 定位笔谱线插值区间、判定用的峰区与对照区（nm）
LASER_BAND = (655.0, 672.0)
LASER_PEAK = (660.0, 670.0)
LASER_REF = (675.0, 690.0)
BIAS_BAND = (850.0, 940.0)

BANDS = {  # 冷启动波段（梯形积分，DN·nm）
    "总量420-700": (420, 700),
    "蓝420-500": (420, 500),
    "绿500-600": (500, 600),
    "红600-700": (600, 700),
    "红边700-720": (700, 720),
}


def load_dn(path=DATA / "IEP-IEP_O2N9DA-2-DN_full_20261022.csv"):
    """返回 (t_utc: DatetimeIndex, it_ms, mode, wl[256], dn[帧, 256])。首次读取后缓存为 npz。"""
    cache = OUT / f"_cache_{Path(path).stem}.npz"
    if cache.exists() and cache.stat().st_mtime > Path(path).stat().st_mtime:
        z = np.load(cache, allow_pickle=False)
        return pd.to_datetime(z["t"].astype(str), utc=True), z["it"], z["mode"], z["wl"], z["dn"]
    df = pd.read_csv(path, comment="#", encoding="utf-8-sig", low_memory=False)
    cols = df.columns[2:]
    t = pd.to_datetime(cols, utc=True)
    it = df.iloc[0, 2:].astype(float).values
    mode = df.iloc[1, 2:].values.astype(str)
    wl = df.iloc[2:, 1].astype(float).values
    dn = df.iloc[2:, 2:].astype(float).values.T
    np.savez(cache, t=np.array(cols, dtype=str), it=it, mode=mode, wl=wl, dn=dn)
    return t, it, mode, wl, dn


def bj(t):
    """UTC Timestamp/Index → 北京时间字符串"""
    return (t + BJ).strftime("%H:%M:%S.%f")[:-3] if isinstance(t, pd.Timestamp) else (t + BJ)


def laser_interp(wl, spec, band=LASER_BAND):
    """band（默认 655–672 nm）内用两侧最近通道线性插值替换；spec 为 1D 或 2D（帧 × 通道）。"""
    spec = np.array(spec, dtype=float, copy=True)
    inside = (wl >= band[0]) & (wl <= band[1])
    lo = np.where(wl < band[0])[0][-1]
    hi = np.where(wl > band[1])[0][0]
    w = (wl[inside] - wl[lo]) / (wl[hi] - wl[lo])
    if spec.ndim == 1:
        spec[inside] = spec[lo] + w * (spec[hi] - spec[lo])
    else:
        spec[:, inside] = spec[:, [lo]] + w[None, :] * (spec[:, [hi]] - spec[:, [lo]])
    return spec


def laser_metric(wl, dn):
    """定位笔指标：max(DN 660–670) − mean(DN 675–690)，逐帧。"""
    pk = (wl >= LASER_PEAK[0]) & (wl <= LASER_PEAK[1])
    rf = (wl >= LASER_REF[0]) & (wl <= LASER_REF[1])
    return dn[:, pk].max(axis=1) - dn[:, rf].mean(axis=1)


def pen_metric(wl, dn):
    """定位笔判定指标（本分析采用）：660–670 nm 相对平滑基线的最大超出量。
    基线 = 640–647 nm 均值与 680–690 nm 均值之间的直线。灯亮笔关约 −300，笔开 1000–50000。"""
    a = (wl >= 640) & (wl <= 647)
    c = (wl >= 680) & (wl <= 690)
    p = (wl >= LASER_PEAK[0]) & (wl <= LASER_PEAK[1])
    xa, xc = wl[a].mean(), wl[c].mean()
    ya, yc = dn[:, a].mean(axis=1), dn[:, c].mean(axis=1)
    base = ya[:, None] + (wl[p][None, :] - xa) / (xc - xa) * (yc - ya)[:, None]
    return (dn[:, p] - base).max(axis=1)


def runs(mask):
    """布尔序列 → [(起始下标, 结束下标含)]"""
    m = np.concatenate([[False], np.asarray(mask, bool), [False]])
    d = np.diff(m.astype(int))
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0] - 1))


def pad(mask, n):
    """把 True 区段前后各扩 n 帧"""
    out = np.asarray(mask, bool).copy()
    for a, b in runs(mask):
        out[max(0, a - n):b + n + 1] = True
    return out


def setup_plot():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.dpi"] = 110
    return plt


def bias(wl, dn):
    m = (wl >= BIAS_BAND[0]) & (wl <= BIAS_BAND[1])
    return dn[:, m].mean(axis=1)


def band_integral(wl, spec, lo, hi):
    """梯形积分（DN·nm）。端点用线性插值补齐，使积分区间严格为 [lo, hi]。"""
    spec = np.atleast_2d(spec)
    grid = np.concatenate([[lo], wl[(wl > lo) & (wl < hi)], [hi]])
    vals = np.vstack([np.interp(grid, wl, s) for s in spec])
    return np.trapezoid(vals, grid, axis=1)


def channel_sum(wl, spec, lo=400, hi=720):
    m = (wl >= lo) & (wl <= hi)
    return np.atleast_2d(spec)[:, m].sum(axis=1)


def read_records():
    """读两份操作记录。距离光斑记录文件后半部分是备注表，分开读。"""
    cold = pd.read_csv(ROOT / "raw" / "冷启动记录_2026-10-22.csv", encoding="utf-8-sig")
    cold["utc"] = pd.to_datetime(cold["UTC"], utc=True)
    text = (ROOT / "raw" / "距离光斑记录_2026-10-22.csv").read_text(encoding="utf-8-sig")
    import re
    from io import StringIO
    parts = [p for p in re.split(r"\r?\n\s*\r?\n", text) if p.strip()]
    seg = pd.read_csv(StringIO(parts[0]))
    notes = pd.read_csv(StringIO(parts[1])) if len(parts) > 1 else pd.DataFrame()
    seg["t0"] = pd.to_datetime(seg["开始UTC"], utc=True)
    seg["t1"] = pd.to_datetime(seg["结束UTC"], utc=True)
    return cold, seg, notes
