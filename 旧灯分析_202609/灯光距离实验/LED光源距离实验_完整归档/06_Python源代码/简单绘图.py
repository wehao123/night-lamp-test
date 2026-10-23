"""读取净光谱 CSV，生成实验常用图。

使用方法：
1. 首次使用安装依赖：pip install pandas numpy matplotlib
2. 修改下方“常用设置”。
3. 运行：python 简单绘图.py

输入文件默认使用 net_spectra.csv：每一列是一组测量的扣背景净光谱。
文件名改为 net_mean_spectra.csv，即可用逐帧均值结果作图。
"""

from pathlib import Path
import re

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


# ============================== 常用设置 ==============================
ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "03_处理数据" / "net_spectra.csv"
OUTPUT_DIR = ROOT / "04_图表" / "简单绘图"

WAVELENGTH_MIN = 400.0
WAVELENGTH_MAX = 720.0

# 第一张图显示哪些测量。空列表 [] 表示不限制。
# 建议一次只画一个距离，否则曲线太多。
PLOT_DISTANCES = [1.507]
PLOT_POSITIONS = ["中间1", "右1", "右2", "中间2", "左1", "左2"]

# 正式距离。2.034 m 餐前复测不放入正式距离和横向分布图。
FORMAL_DISTANCES = [1.507, 2.032, 3.016, 3.995, 5.013]

# True：运行后弹出图窗；False：只保存 PNG。
SHOW_PLOTS = True
# ====================================================================


POSITION_TO_CM = {
    "左2": -40,
    "左1": -20,
    "中间1": 0,
    "中间2": 0,
    "中间复测": 0,
    "右1": 20,
    "右2": 40,
}


def set_plot_style() -> None:
    """设置中文字体和图片样式。"""
    plt.rcParams["font.sans-serif"] = [
        "Microsoft YaHei",
        "SimHei",
        "Arial Unicode MS",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.dpi"] = 130
    plt.rcParams["savefig.dpi"] = 300


def read_spectra(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """读取宽表光谱，并把测量列转换成长表信息。"""
    data = pd.read_csv(path, encoding="utf-8-sig")
    required = {"channel", "wavelength_nm"}
    if not required.issubset(data.columns):
        raise ValueError(f"CSV 至少需要这些列：{sorted(required)}")

    pattern = re.compile(r"M(?P<id>\d+)_(?P<distance>\d+(?:\.\d+)?)m_(?P<position>.+)")
    rows = []
    for column in data.columns:
        match = pattern.fullmatch(column)
        if match is None:
            continue
        position = match.group("position")
        rows.append(
            {
                "column": column,
                "id": int(match.group("id")),
                "distance_m": float(match.group("distance")),
                "position": position,
                "lateral_cm": POSITION_TO_CM.get(position, np.nan),
            }
        )

    info = pd.DataFrame(rows).sort_values("id").reset_index(drop=True)
    if info.empty:
        raise ValueError(
            "没有找到测量列。默认列名格式应类似：M01_1.507m_中间1"
        )
    return data, info


def response_table(data: pd.DataFrame, info: pd.DataFrame) -> pd.DataFrame:
    """计算每组测量在有效波段内的积分净响应（各通道 DN 求和）。"""
    band = data["wavelength_nm"].between(WAVELENGTH_MIN, WAVELENGTH_MAX)
    result = info.copy()
    result["response_dn_channel"] = [data.loc[band, c].sum() for c in info["column"]]
    return result


def save_figure(fig: plt.Figure, filename: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / filename, bbox_inches="tight")


def plot_selected_spectra(data: pd.DataFrame, info: pd.DataFrame) -> None:
    """画选定测量的原始净 DN 光谱，不做归一化。"""
    selected = info.copy()
    if PLOT_DISTANCES:
        selected = selected[selected["distance_m"].isin(PLOT_DISTANCES)]
    if PLOT_POSITIONS:
        selected = selected[selected["position"].isin(PLOT_POSITIONS)]

    band = data["wavelength_nm"].between(WAVELENGTH_MIN, WAVELENGTH_MAX)
    wavelength = data.loc[band, "wavelength_nm"]

    fig, ax = plt.subplots(figsize=(10, 6))
    for row in selected.itertuples():
        label = f"{row.distance_m:.3f} m  {row.position}"
        ax.plot(wavelength, data.loc[band, row.column], label=label, linewidth=1.5)
    ax.set(
        title="选定测量的扣背景净光谱",
        xlabel="波长 (nm)",
        ylabel="净信号 (DN)",
    )
    ax.grid(alpha=0.25)
    ax.legend(fontsize=9)
    save_figure(fig, "01_选定测量_净光谱DN.png")


def center_spectra(data: pd.DataFrame, info: pd.DataFrame) -> dict[float, np.ndarray]:
    """同一距离的中间1、中间2先分别取净谱，再求算术平均。"""
    result = {}
    for distance in FORMAL_DISTANCES:
        chosen = info[
            np.isclose(info["distance_m"], distance)
            & info["position"].isin(["中间1", "中间2"])
        ]
        if chosen.empty:
            continue
        result[distance] = data[chosen["column"].tolist()].mean(axis=1).to_numpy()
    return result


def plot_center_spectra(data: pd.DataFrame, centers: dict[float, np.ndarray]) -> None:
    """画各距离中心净光谱：一张保留 DN，一张按各自峰值归一化。"""
    band = data["wavelength_nm"].between(WAVELENGTH_MIN, WAVELENGTH_MAX).to_numpy()
    wavelength = data.loc[band, "wavelength_nm"].to_numpy()

    fig, ax = plt.subplots(figsize=(10, 6))
    for distance, spectrum in centers.items():
        ax.plot(wavelength, spectrum[band], label=f"{distance:.3f} m")
    ax.set(
        title="不同距离的中心净光谱",
        xlabel="波长 (nm)",
        ylabel="净信号 (DN)",
    )
    ax.grid(alpha=0.25)
    ax.legend()
    save_figure(fig, "02_中心净光谱_DN.png")

    fig, ax = plt.subplots(figsize=(10, 6))
    for distance, spectrum in centers.items():
        values = spectrum[band]
        peak = np.max(values)
        normalized = values / peak if peak != 0 else np.full_like(values, np.nan)
        ax.plot(wavelength, normalized, label=f"{distance:.3f} m")
    ax.set(
        title="不同距离的中心净光谱形状",
        xlabel="波长 (nm)",
        ylabel="峰值归一化净信号",
        ylim=(-0.05, 1.05),
    )
    ax.grid(alpha=0.25)
    ax.legend()
    save_figure(fig, "03_中心净光谱_峰值归一化.png")


def plot_distance_response(data: pd.DataFrame, centers: dict[float, np.ndarray]) -> None:
    """中心净光谱在有效波段求和，绘制距离—响应曲线。"""
    band = data["wavelength_nm"].between(WAVELENGTH_MIN, WAVELENGTH_MAX).to_numpy()
    distances = np.array(sorted(centers))
    responses = np.array([centers[d][band].sum() for d in distances])

    fig, ax = plt.subplots(figsize=(8, 5.5))
    ax.plot(distances, responses, "o-", linewidth=1.8)
    ax.set(
        title=f"中心净响应随距离变化（{WAVELENGTH_MIN:.0f}–{WAVELENGTH_MAX:.0f} nm）",
        xlabel="距离 (m)",
        ylabel="中心净响应 (DN·channel)",
        xticks=distances,
    )
    ax.grid(alpha=0.25)
    save_figure(fig, "04_距离响应_DN.png")


def plot_lateral_profiles(result: pd.DataFrame) -> None:
    """各横向位置响应除以该距离中心响应，绘制相对光斑剖面。"""
    fig, ax = plt.subplots(figsize=(9, 6))
    for distance in FORMAL_DISTANCES:
        group = result[np.isclose(result["distance_m"], distance)].copy()
        group = group.dropna(subset=["lateral_cm"])
        if group.empty:
            continue

        # 中心1和中心2横向位置同为 0 cm，在这里取平均。
        profile = group.groupby("lateral_cm", as_index=False)["response_dn_channel"].mean()
        center = profile.loc[profile["lateral_cm"] == 0, "response_dn_channel"]
        if center.empty or center.iloc[0] == 0:
            continue
        profile["relative_percent"] = profile["response_dn_channel"] / center.iloc[0] * 100
        ax.plot(
            profile["lateral_cm"],
            profile["relative_percent"],
            "o-",
            label=f"{distance:.3f} m",
        )

    ax.axhline(80, color="gray", linestyle="--", linewidth=1, label="80% 阈值")
    ax.set(
        title="不同距离的横向归一化光斑",
        xlabel="横向位置 (cm)",
        ylabel="相对中心响应 (%)",
        xticks=[-40, -20, 0, 20, 40],
    )
    ax.grid(alpha=0.25)
    ax.legend()
    save_figure(fig, "05_横向光斑_相对中心.png")


def main() -> None:
    set_plot_style()
    data, info = read_spectra(DATA_FILE)
    result = response_table(data, info)
    centers = center_spectra(data, info)

    plot_selected_spectra(data, info)
    plot_center_spectra(data, centers)
    plot_distance_response(data, centers)
    plot_lateral_profiles(result)

    print(f"输入：{DATA_FILE}")
    print(f"波段：{WAVELENGTH_MIN:.0f}–{WAVELENGTH_MAX:.0f} nm")
    print(f"图片已保存到：{OUTPUT_DIR}")
    if SHOW_PLOTS:
        plt.show()
    else:
        plt.close("all")


if __name__ == "__main__":
    main()
