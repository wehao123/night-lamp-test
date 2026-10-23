"""根据右2核查总数据.csv生成1.507 m横向净光谱对比图。"""

from pathlib import Path
import re

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
CSV_PATH = ROOT / "右2核查总数据.csv"
OUT_PATH = ROOT / "1.507m横向净光谱对比.png"
FRAME_OUT_PATH = ROOT / "1.507m右2逐帧原始DN.png"

DISTANCE = 1.507
WAVELENGTH_MIN = 400.0
WAVELENGTH_MAX = 720.0

POSITIONS = [
    ("左2", "左2（-40 cm）", "#70AD47", 1.5),
    ("左1", "左1（-20 cm）", "#8064A2", 1.5),
    ("中心", "中心（中间1/中间2平均，0 cm）", "#2F5597", 1.8),
    ("右1", "右1（+20 cm）", "#ED7D31", 1.5),
    ("右2", "右2（+40 cm）", "#C00000", 2.5),
]


def measurement_net(data: pd.DataFrame, position: str, channels: list[str]) -> np.ndarray:
    """逐通道计算LED帧中位数减遮阴帧中位数。"""
    selected = data[
        np.isclose(data["distance_m"], DISTANCE)
        & (data["position"] == position)
    ]
    led = selected[selected["state"] == "LED"][channels].median(axis=0).to_numpy()
    shade = selected[selected["state"] == "shade"][channels].median(axis=0).to_numpy()
    return led - shade


def main() -> None:
    data = pd.read_csv(CSV_PATH, encoding="utf-8-sig")
    channels = [column for column in data.columns if column.startswith("ch")]
    wavelengths = np.array(
        [float(re.search(r"_([0-9.]+)nm$", column).group(1)) for column in channels]
    )
    band = (wavelengths >= WAVELENGTH_MIN) & (wavelengths <= WAVELENGTH_MAX)

    spectra = {
        "左2": measurement_net(data, "左2", channels),
        "左1": measurement_net(data, "左1", channels),
        "右1": measurement_net(data, "右1", channels),
        "右2": measurement_net(data, "右2", channels),
    }
    center1 = measurement_net(data, "中间1", channels)
    center2 = measurement_net(data, "中间2", channels)
    spectra["中心"] = (center1 + center2) / 2

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, ax = plt.subplots(figsize=(11, 6.5))
    for key, label, color, width in POSITIONS:
        ax.plot(
            wavelengths[band], spectra[key][band],
            label=label, color=color, linewidth=width,
        )

    ax.set_title("1.507 m横向位置扣背景净光谱")
    ax.set_xlabel("波长 (nm)")
    ax.set_ylabel("净信号 (DN)")
    ax.set_xlim(WAVELENGTH_MIN, WAVELENGTH_MAX)
    ax.grid(alpha=0.25)
    ax.legend()
    # fig.text(
    #     0.5, 0.015,
    #     "净光谱 = LED时段逐通道中位数 - 遮阴时段逐通道中位数；右2用红色粗线标出",
    #     ha="center", color="#666666",
    # )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(OUT_PATH, dpi=300, bbox_inches="tight")

    # 第二张图：检查右2测量期间是否存在异常帧或明显波动。
    right2 = data[
        np.isclose(data["distance_m"], DISTANCE)
        & (data["position"] == "右2")
    ]
    led_frames = right2[right2["state"] == "LED"][channels].to_numpy()
    shade_frames = right2[right2["state"] == "shade"][channels].to_numpy()
    led_median = np.median(led_frames, axis=0)
    shade_median = np.median(shade_frames, axis=0)

    fig2, ax2 = plt.subplots(figsize=(11, 6.5))
    for index, frame in enumerate(led_frames):
        ax2.plot(
            wavelengths[band], frame[band], color="#BFBFBF", linewidth=0.6,
            alpha=0.65, label="LED各帧" if index == 0 else None,
        )
    for index, frame in enumerate(shade_frames):
        ax2.plot(
            wavelengths[band], frame[band], color="#B4C7E7", linewidth=0.6,
            alpha=0.65, label="遮阴各帧" if index == 0 else None,
        )
    ax2.plot(
        wavelengths[band], led_median[band], color="#C00000",
        linewidth=2.5, label="LED中位数",
    )
    ax2.plot(
        wavelengths[band], shade_median[band], color="#2F5597",
        linewidth=2.5, label="遮阴中位数",
    )
    ax2.set_title("1.507 m右2原始逐帧DN（未扣背景）")
    ax2.set_xlabel("波长 (nm)")
    ax2.set_ylabel("原始DN")
    ax2.set_xlim(WAVELENGTH_MIN, WAVELENGTH_MAX)
    ax2.grid(alpha=0.25)
    ax2.legend()
    fig2.text(
        0.5, 0.015,
        "浅色线为各帧，粗线为各自中位数；本图用于检查帧间波动和异常帧",
        ha="center", color="#666666",
    )
    fig2.tight_layout(rect=(0, 0.04, 1, 1))
    fig2.savefig(FRAME_OUT_PATH, dpi=300, bbox_inches="tight")
    plt.show()


if __name__ == "__main__":
    main()
