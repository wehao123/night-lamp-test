"""从原始SQLite数据库和最终时间戳直接生成全部分析CSV。"""

from __future__ import annotations

import csv
import json
import math
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "01_原始数据" / "2026-09-11.db"
TIMESTAMP_PATH = ROOT / "02_时间戳" / "final_segments.csv"
OUT = ROOT / "03_处理数据"
LOCAL_TZ = ZoneInfo("Asia/Shanghai")
DATE = "2026-09-11"
PROBE_ID = 2
INTEGRATION_TIME_MS = 0.4
BAND_MIN_NM = 400.0
BAND_MAX_NM = 720.0
# ---------------------------------------------------------------------------
# 距离口径定义
#   FORMAL_DISTANCES  : 五个正式测量距离。全部参与距离衰减拟合、横向剖面、
#                       均匀性、对称性等所有统计
#   REFERENCE_DISTANCE: 相对值归一化基准，取最近的 1.507 m，相对值即为
#                       "相对最近距离的百分比"，与图表一致
#   DINNER_DISTANCE   : 餐前对比点（17:57，2.034 m 中间复测）。它与餐后
#                       18:37 的 2.032 m 中间1 构成 40 分钟灯稳定性检验，
#                       是专门设计的对照，不进入任何正式统计
# ---------------------------------------------------------------------------
FORMAL_DISTANCES = [1.507, 2.032, 3.016, 3.995, 5.013]
REFERENCE_DISTANCE = 1.507
DINNER_DISTANCE = 2.034
STABILITY_PAIR_DISTANCE = 2.032   # 与餐前点配对做稳定性比较的餐后距离


def write_csv(path: Path, header: list[str], rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def read_segments() -> list[dict[str, str]]:
    with TIMESTAMP_PATH.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def parse_local_time(text: str) -> datetime:
    return datetime.fromisoformat(f"{DATE}T{text}").replace(tzinfo=LOCAL_TZ)


def read_database():
    con = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    calibration = con.execute(
        "SELECT calibration_id,wavelengths FROM calibrations "
        "WHERE probe_id=? AND is_active=1",
        (PROBE_ID,),
    ).fetchone()
    if calibration is None:
        raise RuntimeError(f"找不到探头{PROBE_ID}的有效波长标定。")
    calibration_id, wavelength_json = calibration
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
    times = np.array(
        [datetime.fromisoformat(row[0]).astimezone(LOCAL_TZ) for row in rows],
        dtype=object,
    )
    spectra = np.array(
        [[json.loads(row[1])[str(i)] for i in range(1, 289)] for row in rows],
        dtype=float,
    )
    return times, spectra, wavelengths


def select_segment(times, spectra, start_text: str, end_text: str):
    start, end = parse_local_time(start_text), parse_local_time(end_text)
    chosen = np.array([(time >= start) and (time <= end) for time in times])
    if not np.any(chosen):
        raise RuntimeError(f"时间段内没有0.4 ms数据：{start_text}–{end_text}")
    frames = spectra[chosen]
    return np.median(frames, axis=0), np.mean(frames, axis=0), frames


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    denominator = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denominator) if denominator else math.nan


def crossing_extent(v20: float, v40: float, threshold: float):
    """线性插值估算相对响应降到 threshold 的横向位置（cm）。

    返回 (位置, 是否超出实测范围)。这是两点线性插值的估计值，
    不是实测宽度，图表与报告中应注明"插值估计"。
    """
    if v20 <= threshold:
        return 20.0 * (1.0 - threshold) / (1.0 - v20), False
    if v40 <= threshold:
        return 20.0 + 20.0 * (v20 - threshold) / (v20 - v40), False
    return 40.0, True


def width_at_threshold(profile: dict[int, float], threshold: float):
    left, left_open = crossing_extent(profile[-20], profile[-40], threshold)
    right, right_open = crossing_extent(profile[20], profile[40], threshold)
    width = left + right
    return width, left_open or right_open


def main() -> None:
    segments = read_segments()
    times, spectra, wavelengths = read_database()
    band = (wavelengths >= BAND_MIN_NM) & (wavelengths <= BAND_MAX_NM)
    if band.sum() != 143:
        raise RuntimeError(
            f"{BAND_MIN_NM:.0f}–{BAND_MAX_NM:.0f} nm应对应143个通道，当前得到{band.sum()}个。"
        )

    records = []
    for segment in segments:
        led_median, led_mean, led_frames = select_segment(
            times, spectra, segment["led_start"], segment["led_end"]
        )
        shade_median, shade_mean, shade_frames = select_segment(
            times, spectra, segment["shade_start"], segment["shade_end"]
        )
        net = led_median - shade_median
        net_mean = led_mean - shade_mean
        response = float(np.sum(net[band]))
        mean_response = float(np.sum(net_mean[band]))

        # 背景噪声：遮阴帧的 MAD 稳健估计
        shade_noise = 1.4826 * np.median(
            np.abs(shade_frames - shade_median), axis=0
        )
        valid_noise = band & (shade_noise > 0)
        snr3_fraction = float(
            np.mean(net[valid_noise] / shade_noise[valid_noise] >= 3)
        )

        # LED 段自身的帧间相对抖动。遮阴噪声只反映背景稳定性，
        # 若 LED 段本身在抖（如 1.507 m 右1 窗口内跨了多个电平），
        # 只看 SNR 会严重高估数据质量。
        led_band_sum = led_frames[:, band].sum(axis=1)
        led_cv = float(
            np.std(led_band_sum, ddof=1) / np.mean(led_band_sum) * 100
        ) if len(led_band_sum) > 1 else 0.0

        peak_channel = np.flatnonzero(band)[np.argmax(net[band])]
        records.append(
            {
                **segment,
                "led_frames": len(led_frames),
                "shade_frames": len(shade_frames),
                "led_median": led_median,
                "led_mean": led_mean,
                "shade_median": shade_median,
                "shade_mean": shade_mean,
                "net": net,
                "net_mean": net_mean,
                "response": response,
                "mean_response": mean_response,
                "mean_minus_median_percent": (
                    (mean_response / response - 1) * 100 if response else math.nan
                ),
                "mean_median_cosine": cosine(net_mean[band], net[band]),
                "mean_median_rmse_dn": float(
                    np.sqrt(np.mean((net_mean[band] - net[band]) ** 2))
                ),
                "mean_median_max_abs_dn": float(
                    np.max(np.abs(net_mean[band] - net[band]))
                ),
                "peak_dn": float(net[peak_channel]),
                "peak_nm": float(wavelengths[peak_channel]),
                "background_all": float(np.sum(shade_median)),
                "snr3_fraction": snr3_fraction,
                "led_cv_percent": led_cv,
                "negative_fraction": float(np.mean(net[band] < 0)),
            }
        )

    def matching(distance, position=None):
        result = [r for r in records if abs(float(r["distance_m"]) - distance) < 1e-6]
        if position is not None:
            result = [r for r in result if r["position"] == position]
        return result

    # 中心响应：中间1 与 中间2 的平均
    center_spectra = {}
    center_responses = {}
    for distance in FORMAL_DISTANCES:
        c1 = matching(distance, "中间1")[0]
        c2 = matching(distance, "中间2")[0]
        center_spectra[distance] = (c1["net"] + c2["net"]) / 2
        center_responses[distance] = (c1["response"] + c2["response"]) / 2

    # 餐前对比点单独取，不并入 FORMAL_DISTANCES 的任何统计
    dinner = matching(DINNER_DISTANCE, "中间复测")[0]
    center_spectra[DINNER_DISTANCE] = dinner["net"]
    center_responses[DINNER_DISTANCE] = dinner["response"]

    # 谱形模板：全部五个距离的中心谱中位数
    normalized_centers = [
        center_spectra[d][band] / np.linalg.norm(center_spectra[d][band])
        for d in FORMAL_DISTANCES
    ]
    template = np.median(np.array(normalized_centers), axis=0)
    for record in records:
        record["cosine_similarity"] = cosine(record["net"][band], template)

    measurement_header = [
        "id", "distance_m", "position", "lateral_cm", "led_start", "led_end",
        "shade_start", "shade_end", "led_frames", "shade_frames",
        "net_response_400_720_dn_channel", "net_peak_dn", "peak_wavelength_nm",
        "shade_sum_all_288_dn_channel", "cosine_similarity_400_720",
        "snr3_fraction_400_720", "led_frame_cv_percent",
        "negative_fraction_400_720",
    ]
    measurement_rows = []
    for r in records:
        measurement_rows.append(
            [
                r["id"], r["distance_m"], r["position"], r["lateral_cm"],
                r["led_start"], r["led_end"], r["shade_start"], r["shade_end"],
                r["led_frames"], r["shade_frames"], r["response"], r["peak_dn"],
                r["peak_nm"], r["background_all"], r["cosine_similarity"],
                r["snr3_fraction"], r["led_cv_percent"], r["negative_fraction"],
            ]
        )
    write_csv(OUT / "measurements.csv", measurement_header, measurement_rows)

    spectrum_header = ["channel", "wavelength_nm", "in_400_720_nm"] + [
        f'M{int(r["id"]):02d}_{r["distance_m"]}m_{r["position"]}' for r in records
    ]
    write_csv(
        OUT / "led_median_spectra.csv",
        spectrum_header,
        [
            [i + 1, wavelength, int(band[i])]
            + [r["led_median"][i] for r in records]
            for i, wavelength in enumerate(wavelengths)
        ],
    )
    write_csv(
        OUT / "shade_median_spectra.csv",
        spectrum_header,
        [
            [i + 1, wavelength, int(band[i])]
            + [r["shade_median"][i] for r in records]
            for i, wavelength in enumerate(wavelengths)
        ],
    )
    write_csv(
        OUT / "net_spectra.csv",
        spectrum_header,
        [
            [i + 1, wavelength, int(band[i])] + [r["net"][i] for r in records]
            for i, wavelength in enumerate(wavelengths)
        ],
    )
    write_csv(
        OUT / "net_mean_spectra.csv",
        spectrum_header,
        [
            [i + 1, wavelength, int(band[i])]
            + [r["net_mean"][i] for r in records]
            for i, wavelength in enumerate(wavelengths)
        ],
    )
    write_csv(
        OUT / "median_mean_comparison.csv",
        [
            "id", "distance_m", "position", "led_frames", "shade_frames",
            "median_net_response_400_720_dn_channel",
            "mean_net_response_400_720_dn_channel",
            "mean_minus_median_percent", "mean_median_cosine_400_720",
            "mean_median_rmse_dn_400_720", "mean_median_max_abs_dn_400_720",
        ],
        [
            [
                r["id"], r["distance_m"], r["position"], r["led_frames"],
                r["shade_frames"], r["response"], r["mean_response"],
                r["mean_minus_median_percent"], r["mean_median_cosine"],
                r["mean_median_rmse_dn"], r["mean_median_max_abs_dn"],
            ]
            for r in records
        ],
    )
    write_csv(
        OUT / "center_net_spectra.csv",
        ["channel", "wavelength_nm", "in_400_720_nm"]
        + [f"{d:.3f}m" for d in FORMAL_DISTANCES],
        [
            [i + 1, wavelength, int(band[i])]
            + [center_spectra[d][i] for d in FORMAL_DISTANCES]
            for i, wavelength in enumerate(wavelengths)
        ],
    )

    # -----------------------------------------------------------------------
    # 距离衰减：五个距离全部参与幂律拟合
    # -----------------------------------------------------------------------
    distance_values = np.array(FORMAL_DISTANCES)
    response_values = np.array([center_responses[d] for d in FORMAL_DISTANCES])
    slope, intercept = np.polyfit(
        np.log(distance_values), np.log(response_values), 1
    )
    fitted = np.exp(intercept) * distance_values**slope
    residual = np.log(response_values) - np.log(fitted)
    r2 = 1 - np.sum(residual**2) / np.sum(
        (np.log(response_values) - np.mean(np.log(response_values))) ** 2
    )
    reference_value = center_responses[REFERENCE_DISTANCE]

    write_csv(
        OUT / "distance_response.csv",
        [
            "distance_m", "center_net_response",
            f"relative_to_{REFERENCE_DISTANCE}m", "fitted_response",
            "deviation_from_fit_percent",
        ],
        [
            [d, value, value / reference_value, fit, (value / fit - 1) * 100]
            for d, value, fit in zip(distance_values, response_values, fitted)
        ]
        + [["power_exponent", -slope, "r_squared", r2, ""]],
    )

    # -----------------------------------------------------------------------
    # 横向剖面与均匀性：全部五个距离
    # -----------------------------------------------------------------------
    position_order = [(-40, "左2"), (-20, "左1"), (0, "中心"), (20, "右1"), (40, "右2")]
    profiles = {}
    profile_rows = []
    for distance in FORMAL_DISTANCES:
        center = center_responses[distance]
        profile = {0: 1.0}
        for x, position in position_order:
            if x:
                profile[x] = matching(distance, position)[0]["response"] / center
        profiles[distance] = profile
        profile_rows.append([distance] + [profile[x] for x, _ in position_order])
    write_csv(
        OUT / "lateral_profile.csv",
        ["distance_m", "left2_-40", "left1_-20", "center_0", "right1_20", "right2_40"],
        profile_rows,
    )

    quality_rows = []
    for distance in FORMAL_DISTANCES:
        p = profiles[distance]
        width80, width80_open = width_at_threshold(p, 0.8)
        width50, width50_open = width_at_threshold(p, 0.5)
        v_left25 = p[-20] + 0.25 * (p[-40] - p[-20])
        v_right25 = p[20] + 0.25 * (p[40] - p[20])
        c1 = matching(distance, "中间1")[0]["response"]
        c2 = matching(distance, "中间2")[0]["response"]
        quality_rows.append(
            [
                distance, min(p[-20], p[20]), min(p[-40], p[40]),
                min(v_left25, v_right25), width80, width80_open,
                width50, width50_open,
                abs(p[-20] - p[20]) / np.mean([p[-20], p[20]]),
                abs(p[-40] - p[40]) / np.mean([p[-40], p[40]]),
                abs(c1 - c2) / np.mean([c1, c2]),
            ]
        )
    write_csv(
        OUT / "uniformity_symmetry_repeatability.csv",
        [
            "distance_m", "min_within_20", "min_at_40", "estimated_min_within_25",
            "width80_cm_interpolated", "width80_extends_beyond_measurement",
            "width50_cm_interpolated_lower_bound",
            "width50_extends_beyond_measurement",
            "asymmetry_20", "asymmetry_40", "center_repeat_difference",
        ],
        quality_rows,
    )

    background_rows = [
        [
            r["id"], r["distance_m"], r["position"], r["shade_start"],
            r["background_all"],
        ]
        for r in records
    ]
    write_csv(
        OUT / "background_by_measurement.csv",
        ["measurement_order", "distance_m", "position", "shade_start", "shade_sum_all_288"],
        background_rows,
    )

    background_summary = []
    for distance in FORMAL_DISTANCES:
        values = np.array([r["background_all"] for r in matching(distance)])
        background_summary.append(
            [
                distance, len(values), np.mean(values), np.min(values),
                np.max(values), np.std(values, ddof=1) / np.mean(values),
            ]
        )
    write_csv(
        OUT / "background_summary.csv",
        ["distance_m", "count", "mean", "minimum", "maximum", "cv"],
        background_summary,
    )

    # -----------------------------------------------------------------------
    # 40 分钟稳定性：餐前 2.034 m vs 餐后 2.032 m
    # 两次距离差 2 mm，按平方反比归算后再比，否则会混入约 0.2% 的距离项
    # -----------------------------------------------------------------------
    after = matching(STABILITY_PAIR_DISTANCE, "中间1")[0]
    dinner_scaled = dinner["response"] * (DINNER_DISTANCE / STABILITY_PAIR_DISTANCE) ** 2
    write_csv(
        OUT / "forty_minute_stability.csv",
        ["metric", f"before_{DINNER_DISTANCE}m",
         f"after_{STABILITY_PAIR_DISTANCE}m", "relative_change"],
        [
            [
                "net_response_400_720_raw", dinner["response"], after["response"],
                after["response"] / dinner["response"] - 1,
            ],
            [
                f"net_response_400_720_scaled_to_{STABILITY_PAIR_DISTANCE}m",
                dinner_scaled, after["response"],
                after["response"] / dinner_scaled - 1,
            ],
            [
                "shade_sum_all_288", dinner["background_all"],
                after["background_all"],
                after["background_all"] / dinner["background_all"] - 1,
            ],
        ],
    )

    deviations = (response_values / fitted - 1) * 100
    print(
        f"完成：31组时间段，{len(times)}帧0.4 ms数据，"
        f"400-720 nm共{band.sum()}个通道。\n"
        f"幂律拟合使用全部 {len(FORMAL_DISTANCES)} 个距离："
        f"衰减指数={-slope:.4f}，R^2={r2:.6f}。\n"
        f"各距离相对拟合偏差："
        + "，".join(f"{d:.3f}m {dev:+.2f}%" for d, dev in zip(distance_values, deviations))
    )


if __name__ == "__main__":
    main()
