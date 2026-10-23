"""第 6 步：新旧灯参考板辐亮度对比（两个探头都用 Lamp2501 标准灯定标）。

旧灯：2026-09-20 冷启动数据（OCR 25F02100，32 ms，N 模式），末段 48.6–57.4 min 亮场 − 环境1 遮挡。
      旧灯距离实验（2026-09-11）实际用的是 OCR 25F01830，没有 Lamp2501 定标，不能用。
新灯：2026-10-22 距离实验 2.033 m 中心（69、73），净光谱 = 亮场中位 − 遮挡中位（与 03 相同）。
换算：L = (DN − 1000) × k / 积分时间(ms)，k 取自定标文件（与采集软件 night_water_acq/calibration.py 相同；
      新探头已用数据库 PHY 逐通道验证一致）。
旧灯冷启动时灯与参考板的距离未记录，结果按假设距离给出：新灯按实测幂律 r^−n 换算到该距离。
"""
import json
import runpy
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config as C
from common import *

plt = setup_plot()
LOG = []


def log(*a):
    s = " ".join(str(v) for v in a)
    print(s)
    LOG.append(s)


RAW_OLD = ROOT / "raw_old"
CAL_OLD = RAW_OLD / "OCR-25F02100_Radiance_Cal_by_Lamp2501.json"
CAL_NEW = ROOT / "raw" / "IEP-IEP_O2N9DA_Cal_by_Lamp2501.json"   # 采集软件 cal/iep 下同名文件的副本
OLD_T0 = pd.Timestamp("2026-09-20 14:29:04.359")          # 旧报告时间零点（北京时间）
OLD_ENV = {"环境1": ("14:30:10", "14:30:28"), "环境2": ("14:54:55", "14:57:23"), "环境3": ("15:16:39", "15:16:58")}
OLD_BRIGHT_MIN = (48.60, 57.41)                           # 旧报告"末段"
ASSUMED_D = [1.5, 2.0, 2.5, 3.0]
OLD_D = 2.0                                               # 操作人确认：旧灯冷启动时灯离参考板约 2 m，对着板子中心


def load_cal(path, n):
    cal = json.loads(Path(path).read_text(encoding="utf-8"))
    rc = cal["radiometric_calibration"]
    k = np.full(n, np.nan)
    for pt in rc["calibration_points"]:
        vals = [v for v in pt["sensitivity"] if v is not None]
        if vals:
            k[pt["pixel_index"] - 1] = vals[0]       # 各积分时间档位的 k 相同（已核对）
    lo, hi = cal["absolute_radiometric_calibration"]["valid_wavelength_range_nm"]
    return k, (lo, hi), rc["dn_offset"]


# ---------------- 旧灯 ----------------
con = sqlite3.connect(f"file:{(RAW_OLD / '2026-09-20_readonly_copy.db').as_posix()}?mode=ro", uri=True)
sn = dict(con.execute("select probe_id, serial_number from probes").fetchall())
pid = [k for k, v in sn.items() if v == "25F02100"][0]
wl_old = np.array(list(json.loads(con.execute(
    "select wavelengths from calibrations where probe_id=?", (pid,)).fetchone()[0]).values()))
r = pd.read_sql("select c.timestamp, d.integration_time_ms it, d.dn_values v from captures c "
                "join spectra_dn d on d.spectra_dn_id=c.spectra_dn_id where c.probe_id=? order by c.timestamp", con, params=(pid,))
dn_old = np.vstack([np.array(list(json.loads(v).values()), float) for v in r.v])
bj_old = (pd.to_datetime(r.timestamp, utc=True) + BJ).dt.tz_localize(None)
tau_old = (bj_old - OLD_T0).dt.total_seconds().values / 60
it_old = r.it.values
k_old, valid_old, off_old = load_cal(CAL_OLD, len(wl_old))
poly = json.loads(CAL_OLD.read_text(encoding="utf-8"))["wavelength_calibration"]["coefficients"]
p = np.arange(1, len(wl_old) + 1)
wl_poly = sum(poly[f"L{i}"] * p ** i for i in range(6))
log(f"旧探头 25F02100：数据库波长与 Lamp2501 定标多项式最大差 {np.abs(wl_poly - wl_old).max():.2e} nm；定标有效范围 {valid_old} nm")

old_laser = laser_interp(wl_old, dn_old, (655.0, 670.0))       # 旧报告插值区间
tot_old = band_integral(wl_old, old_laser - 1000, 420, 700)
mb = (it_old == 32) & (tau_old >= OLD_BRIGHT_MIN[0]) & (tau_old <= OLD_BRIGHT_MIN[1]) & (tot_old > 0.5 * np.median(tot_old[it_old == 32]))
env = {}
for name, (a, b) in OLD_ENV.items():
    m = (it_old == 32) & (bj_old >= pd.Timestamp(f"2026-09-20 {a}")) & (bj_old <= pd.Timestamp(f"2026-09-20 {b}")) & (tot_old < 0.5 * np.median(tot_old[it_old == 32]))
    env[name] = old_laser[m].mean(0)
    log(f"旧灯 {name}: {m.sum()} 帧，占末段亮场 {band_integral(wl_old, env[name] - 1000, 420, 700)[0] / tot_old[mb].mean() * 100:.1f}%")
log(f"旧灯末段亮场 {mb.sum()} 帧（τ {tau_old[mb].min():.2f}–{tau_old[mb].max():.2f} min），最大 DN {dn_old[mb].max():.0f}")
bright_old = old_laser[mb].mean(0)
L_old = {name: (bright_old - e) * k_old / 32.0 for name, e in env.items()}
L_old["只扣偏置"] = (bright_old - off_old) * k_old / 32.0
L_old["环境2、3平均"] = (bright_old - (env["环境2"] + env["环境3"]) / 2) * k_old / 32.0

# ---------------- 新灯 ----------------
D = runpy.run_path(str(Path(__file__).parent / "03_distance.py"), run_name="cmp_import")
wl_new = D["wl"]
k_new, valid_new, off_new = load_cal(CAL_NEW, len(wl_new))
n_pow = D["fits"]["R_sum"][0]
NET = D["NET"]
S2 = (NET[(2.0, "中心1")] + NET[(2.0, "中心2")]) / 2
L_new2 = S2 * k_new / 512.0
r2 = C.DIST_M[2.0]
# 新灯 1.5 m 中心作交叉检查（按幂律换算到 2.033 m 应与 2 m 实测一致）
L_new15 = (NET[(1.5, "中心1")] + NET[(1.5, "中心2")]) / 2 * k_new / 512.0 * (r2 / C.DIST_M[1.5]) ** (-n_pow)

# ---------------- 对比（统一插值到 5 nm 网格） ----------------
grid = np.arange(405, 721, 5.0)
lo = max(valid_old[0], valid_new[0], 400)
hi = min(valid_old[1], valid_new[1], 720)
grid = grid[(grid >= lo) & (grid <= hi)]


def on_grid(wl, L):
    ok = ~np.isnan(L)
    return np.interp(grid, wl[ok], L[ok])


Lo = {k: on_grid(wl_old, v) for k, v in L_old.items()}
Ln = on_grid(wl_new, L_new2)
Ln15 = on_grid(wl_new, L_new15)
log(f"新灯 1.5 m 中心按 r^−{n_pow:.3f} 换算到 2.033 m 后与 2.033 m 实测之比（420–700 nm 中位）："
    f"{np.median(Ln15[(grid >= 420) & (grid <= 700)] / Ln[(grid >= 420) & (grid <= 700)]):.3f}")

KEY = [420, 450, 500, 550, 600, 650, 700, 720]
rows = []
for d in ASSUMED_D:
    Ln_d = Ln * (d / r2) ** (-n_pow)
    row = {"假设旧灯距离m": d}
    for w in KEY:
        i = np.argmin(np.abs(grid - w))
        row[f"{w}nm"] = Lo["环境1"][i] / Ln_d[i]
    band = (grid >= 420) & (grid <= 700)
    row["420-700积分比"] = np.trapezoid(Lo["环境1"][band], grid[band]) / np.trapezoid(Ln_d[band], grid[band])
    rows.append(row)
ratio = pd.DataFrame(rows)
ratio.to_csv(OUT / "compare_old_over_new.csv", index=False, encoding="utf-8-sig")
log("\n旧灯 / 新灯 参考板辐亮度比（灯中心，旧灯背景=环境1）：\n" + ratio.round(3).to_string(index=False))

bg_sens = {}
band = (grid >= 420) & (grid <= 700)
for k, v in Lo.items():
    bg_sens[k] = np.trapezoid(v[band], grid[band]) / np.trapezoid(Lo["环境1"][band], grid[band])
log("旧灯辐亮度对背景选择的敏感性（420–700 积分，相对环境1）：" + json.dumps({k: round(v, 3) for k, v in bg_sens.items()}, ensure_ascii=False))

# 按确认的 2 m：各背景处理下的比值
Ln_old_d = Ln * (OLD_D / r2) ** (-n_pow)
r2rows = []
for k, v in Lo.items():
    row = {"旧灯背景": k}
    for w in KEY:
        i = np.argmin(np.abs(grid - w))
        row[f"{w}nm"] = v[i] / Ln_old_d[i]
    row["420-700积分比"] = np.trapezoid(v[band], grid[band]) / np.trapezoid(Ln_old_d[band], grid[band])
    r2rows.append(row)
ratio2 = pd.DataFrame(r2rows)
ratio2.to_csv(OUT / "compare_2m_by_background.csv", index=False, encoding="utf-8-sig")
log(f"\n旧灯冷启动距离 {OLD_D} m：旧灯/新灯 中心辐亮度比（不同旧灯背景）：\n" + ratio2.round(3).to_string(index=False))

# 同一盏旧灯、同约 2 m、对板中心：距离实验（25F01830，0.4 ms，旧报告表 3-2 中心净响应）与冷启动（25F02100，32 ms）每 ms 读数之比
OLD_R_2M_25F01830 = 1179421.0      # DN·channel，400–720 nm（143 通道），0.4 ms
mo = (wl_old >= 400) & (wl_old <= 720)
cs_per_ms = (bright_old - env["环境1"])[mo].sum() / 32.0
probe_ratio = (OLD_R_2M_25F01830 / 0.4) / cs_per_ms
log(f"\n旧灯约 2 m 中心每 ms 净通道和：距离实验（25F01830）{OLD_R_2M_25F01830 / 0.4:,.0f}；冷启动（25F02100）{cs_per_ms:,.0f}；"
    f"比值 {probe_ratio:.0f} 倍")

# 辐亮度绝对值（mW/(m² nm sr)）
absrows = []
for w in KEY:
    i = np.argmin(np.abs(grid - w))
    absrows.append({"波长nm": w, "旧灯（约 2 m）": Lo["环境1"][i], "新灯 2.033 m": Ln[i], "新灯 1.5 m": Ln[i] * (C.DIST_M[1.5] / r2) ** (-n_pow)})
absdf = pd.DataFrame(absrows)
absdf.to_csv(OUT / "compare_radiance_abs.csv", index=False, encoding="utf-8-sig")
log("\n参考板辐亮度 / mW/(m² nm sr)：\n" + absdf.round(4).to_string(index=False))

# 谱形（各自 450 nm 归一化）
shape_o = Lo["环境1"] / Lo["环境1"][np.argmin(np.abs(grid - 450))]
shape_n = Ln / Ln[np.argmin(np.abs(grid - 450))]
log("\n谱形（相对 450 nm）：" + "  ".join(f"{w}: 旧 {shape_o[np.argmin(np.abs(grid - w))]:.3f} / 新 {shape_n[np.argmin(np.abs(grid - w))]:.3f}" for w in KEY))

for k, v in Lo.items():
    sh = v / v[np.argmin(np.abs(grid - 450))]
    log(f"旧灯谱形（背景={k}）：" + "  ".join(f"{w}:{sh[np.argmin(np.abs(grid - w))]:.3f}" for w in KEY))

# 距离等效：旧灯 = 新灯时对应的距离
d_eq = r2 * (np.trapezoid(Lo["环境1"][band], grid[band]) / np.trapezoid(Ln[band], grid[band])) ** (-1 / n_pow)
log(f"\n若两灯在中心亮度相同，旧灯冷启动距离应为 {d_eq:.2f} m（按新灯 n={n_pow:.3f} 换算）")

fig, ax = plt.subplots(1, 2, figsize=(11, 4.3))
ax[0].plot(grid, Lo["环境1"], color="#2a6fdb", label="旧灯（冷启动末段，约 2 m）")
for d, ls in zip(ASSUMED_D, ["-", "--", "-.", ":"]):
    ax[0].plot(grid, Ln * (d / r2) ** (-n_pow), color="#d9452b", ls=ls, lw=1, label=f"新灯换算到 {d} m")
ax[0].set_xlabel("波长 / nm")
ax[0].set_ylabel("参考板辐亮度 / mW/(m² nm sr)")
ax[0].legend(fontsize=8)
ax[0].grid(alpha=0.3)
ax[0].set_title("灯中心处 25% 参考板辐亮度", fontsize=10)
ax[1].plot(grid, shape_o, color="#2a6fdb", label="旧灯")
ax[1].plot(grid, shape_n, color="#d9452b", label="新灯")
ax[1].set_xlabel("波长 / nm")
ax[1].set_ylabel("相对 450 nm")
ax[1].legend(fontsize=8)
ax[1].grid(alpha=0.3)
ax[1].set_title("谱形比较", fontsize=10)
fig.tight_layout()
fig.savefig(FIG / "compare_old_new_radiance.png")

res = {"ratio": ratio.to_dict("records"), "bg_sens": bg_sens, "abs": absdf.to_dict("records"), "d_eq": float(d_eq),
       "n_pow": float(n_pow), "shape": {str(w): [float(shape_o[np.argmin(np.abs(grid - w))]), float(shape_n[np.argmin(np.abs(grid - w))])] for w in KEY},
       "cross15": float(np.median(Ln15[band] / Ln[band])), "ratio2": ratio2.to_dict("records"), "old_d": OLD_D, "probe_ratio": float(probe_ratio), "old_bright_n": int(mb.sum())}
(OUT / "results_compare.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
(OUT / "compare_log.txt").write_text("\n".join(LOG), encoding="utf-8")
