"""第 4 步：信号水平与信噪比；外推到水面（估算）。

需要先运行 03_distance.py（读取其选帧规则：本脚本重新按同一规则选帧）。
输出： out/snr_*.csv、out/results_snr.json、out/fig/snr_*.png
"""
import json
import runpy
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


# 复用 03 的选帧结果（SEL、occl_for、NET 等），不重复实现
D = runpy.run_path(str(Path(__file__).parent / "03_distance.py"), run_name="snr_import")
SEL, occl_for, DNm, wl, t, it = D["SEL"], D["occl_for"], D["DN"]["main"], D["wl"], D["t"], D["it"]
dn_raw = D["dn"]
m_an = (wl >= 420) & (wl <= 720)


def nearest(w):
    return int(np.argmin(np.abs(wl - w)))


def snr_point(bi, oi):
    f = SEL[bi]
    sig = DNm[f].mean(0) - np.median(DNm[SEL[oi]], axis=0)
    noise = dn_raw[f].std(0, ddof=1)          # 噪声用未插值的原始帧（插值区间内为插值后的值，不代表噪声）
    noise_i = DNm[f].std(0, ddof=1)
    return sig, noise, len(f)


def longest_run(mask):
    rr = runs(mask)
    if not rr:
        return None
    a, b = max(rr, key=lambda x: x[1] - x[0])
    return a, b


def smooth_noise(noise, half=3):
    out = np.empty_like(noise)
    for i in range(len(noise)):
        out[i] = np.median(noise[max(0, i - half):i + half + 1])
    return out


rows, curves = [], {}
band_rows = []
for d in sorted(C.PAIRS):
    pts = C.PAIRS[d]
    per = {}
    for pos in ("中心1", "中心2"):
        bi = pts[pos][0]
        oi = occl_for[bi]
        sig, noise, n = snr_point(bi, oi)
        snr = sig / noise
        snr_s = sig / smooth_noise(noise)
        per[pos] = (sig, noise, snr, snr_s, n)
        row = {"距离": d, "实测距离m": C.DIST_M[d], "位置": pos, "亮场段": bi, "遮挡段": oi, "帧数": n}
        for w in C.SNR_WL:
            k = nearest(w)
            row[f"{w}nm 净信号DN"] = sig[k]
            row[f"{w}nm SNR"] = snr[k]
        rows.append(row)
    snr_min = np.minimum(per["中心1"][2], per["中心2"][2])
    snr_min_s = np.minimum(per["中心1"][3], per["中心2"][3])
    curves[d] = (per, snr_min)
    for lab, s_ in (("逐通道噪声", snr_min), ("平滑噪声(±3通道中位)", snr_min_s)):
        r = {"距离": d, "噪声": lab}
        for thr in (C.SNR_WORK, C.SNR_REC):
            good = m_an & (s_ >= thr)
            lr = longest_run(good)
            fails = wl[m_an & (s_ < thr)]
            r[f"SNR≥{int(thr)} 通道数/总数"] = f"{int(good.sum())}/{int(m_an.sum())}"
            r[f"SNR≥{int(thr)} 最长连续波段nm"] = f"{wl[lr[0]]:.1f}–{wl[lr[1]]:.1f}" if lr else "无"
            r[f"SNR<{int(thr)} 的通道nm"] = ", ".join(f"{v:.1f}" for v in fails) if len(fails) <= 12 else \
                f"{len(fails)} 个：{fails[0]:.1f}…{fails[-1]:.1f}"
        band_rows.append(r)
snr_tab = pd.DataFrame(rows)
band_tab = pd.DataFrame(band_rows)
snr_tab.to_csv(OUT / "snr_points.csv", index=False, encoding="utf-8-sig")
band_tab.to_csv(OUT / "snr_bands.csv", index=False, encoding="utf-8-sig")
pd.set_option("display.width", 250)
log("各距离中心点单帧 SNR（参考板，512 ms）：\n" + snr_tab.round(1).to_string(index=False))
log("\n420–720 nm 满足判据的通道（取中心1、中心2 中较低的 SNR）：\n" + band_tab.to_string(index=False))

# 1.5 m 与交接说明初步结果核对
log("\n1.5 m 中心核对（交接说明 6.2 节为 1.5 m 中心单帧结果）：")
for pos in ("中心1", "中心2"):
    sig, noise, snr, _, n = curves[1.5][0][pos]
    log(f"  {pos}: " + "  ".join(f"{w}:{sig[nearest(w)]:.0f}/{snr[nearest(w)]:.0f}" for w in C.SNR_WL))

# 干净参照：冷启动中定位笔关闭的连续 30 帧（灯约 2 m，距离未精确记录）
xb = (t + BJ).tz_localize(None)
ref = np.where((it == 512) & (xb >= pd.Timestamp(f"{C.DATE} 22:00:00")) & (xb <= pd.Timestamp(f"{C.DATE} 22:00:40")))[0][:30]
pre = (xb >= pd.Timestamp(f"{C.DATE} {C.PRE_BG[0]}")) & (xb <= pd.Timestamp(f"{C.DATE} {C.PRE_BG[1]}")) & (it == 512)
post = (xb >= pd.Timestamp(f"{C.DATE} {C.POST_BG[0]}")) & (xb <= pd.Timestamp(f"{C.DATE} {C.POST_BG[1]}")) & (it == 512)
bg = (DNm[pre].mean(0) + DNm[post].mean(0)) / 2
tt = np.arange(len(ref))
A = np.vstack([tt, np.ones_like(tt)]).T
resid = dn_raw[ref] - A @ np.linalg.lstsq(A, dn_raw[ref], rcond=None)[0]
noise_ref = resid.std(0, ddof=2)
sig_ref = DNm[ref].mean(0) - bg
snr_ref = sig_ref / noise_ref
dark_noise = dn_raw[post].std(0, ddof=1)
log(f"\n冷启动干净参照（22:00:00 起 {len(ref)} 帧，定位笔关，灯约 2 m）：" +
    "  ".join(f"{w}:{sig_ref[nearest(w)]:.0f}/{snr_ref[nearest(w)]:.0f}" for w in C.SNR_WL))
log("噪声水平（DN，420–720 nm 中位）：亮场 1.5 m 中心1 %.1f；冷启动参照 %.1f；关灯背景（记录81）%.1f" % (
    np.median(curves[1.5][0]["中心1"][1][m_an]), np.median(noise_ref[m_an]), np.median(dark_noise[m_an])))

# ---------------- 外推到水面 ----------------
n_pow = D["fits"]["R_sum"][0]
r15 = C.DIST_M[1.5]
S15 = (curves[1.5][0]["中心1"][0] + curves[1.5][0]["中心2"][0]) / 2
# 噪声：10 个中心点亮场帧噪声的逐通道中位，再做 ±3 通道平滑
noise_all = np.median(np.vstack([curves[d][0][p][1] for d in curves for p in ("中心1", "中心2")]), axis=0)
sigma = smooth_noise(noise_all)
LIN_MAX = 45000.0      # 旧探头线性上限（新探头未验证）
OFFSET = 1000.0
ext_rows = []
for r_inst in C.INSTALL_DIST:
    for rrs in C.RRS_CASES:
        f = np.pi * rrs / C.PANEL_REFL
        Sw512 = S15 * (r_inst / r15) ** (-n_pow) * f
        t_sat = 512 * (LIN_MAX - OFFSET) / Sw512[m_an].max()
        t_use = min(C.INT_MAX_MS, t_sat)
        for N in C.N_AVG:
            row = {"安装距离m": r_inst, "Rrs": rrs, "Lw/L板": f, "积分时间ms": t_use,
                   "受限于": "8192 ms 上限" if t_use == C.INT_MAX_MS else "45000 DN 线性上限", "平均帧数": N}
            for w in C.EXTRAP_WL:
                k = nearest(w)
                row[f"{w}nm SNR"] = Sw512[k] * (t_use / 512) / sigma[k] * np.sqrt(N)
            row["512ms单帧 550nm SNR"] = Sw512[nearest(550)] / sigma[nearest(550)]
            ext_rows.append(row)
ext = pd.DataFrame(ext_rows)
ext.to_csv(OUT / "snr_water_extrapolation.csv", index=False, encoding="utf-8-sig")
log(f"\n水面外推（幂律 n={n_pow:.3f}，以 1.5 m 中心净光谱为基准；Rrs 光谱平坦假设）：\n" + ext.round(1).to_string(index=False))

# 满足 SNR≥20 的最大安装距离（距离网格 1.5–10 m，>5 m 为外推）
rg = np.round(np.arange(1.5, 10.0001, 0.01), 2)
maxd_rows = []
for rrs in C.RRS_CASES:
    f = np.pi * rrs / C.PANEL_REFL
    for N in C.N_AVG:
        row = {"Rrs": rrs, "平均帧数": N}
        for w in C.EXTRAP_WL:
            k = nearest(w)
            ok_r = []
            for r_inst in rg:
                Sw = S15 * (r_inst / r15) ** (-n_pow) * f
                t_use = min(C.INT_MAX_MS, 512 * (LIN_MAX - OFFSET) / Sw[m_an].max())
                ok_r.append(Sw[k] * (t_use / 512) / sigma[k] * np.sqrt(N) >= C.SNR_WORK)
            ok_r = np.array(ok_r)
            if not ok_r[0]:
                row[f"{w}nm"] = "< 1.5 m"
            elif ok_r.all():
                row[f"{w}nm"] = "> 10 m"
            else:
                rmax = rg[np.where(~ok_r)[0][0] - 1]
                row[f"{w}nm"] = f"{rmax:.1f} m" + ("（外推）" if rmax > 5.05 else "")
        maxd_rows.append(row)
maxd = pd.DataFrame(maxd_rows)
maxd.to_csv(OUT / "snr_max_distance.csv", index=False, encoding="utf-8-sig")
log("\n满足 SNR≥20 的最大安装距离（估算）：\n" + maxd.to_string(index=False))

# ---------------- 图 ----------------
cmap = plt.get_cmap("viridis")
fig, ax = plt.subplots(figsize=(10, 4.6))
for j, d in enumerate(sorted(curves)):
    ax.semilogy(wl[m_an], np.clip(curves[d][1][m_an], 0.5, None), color=cmap(j / 4.5), lw=1, label=f"{C.DIST_M[d]:.3f} m")
ax.semilogy(wl[m_an], np.clip(snr_ref[m_an], 0.5, None), color="0.5", lw=1, ls="--", label="冷启动参照（约 2 m，笔关）")
ax.axhline(C.SNR_WORK, color="r", ls="--", lw=0.8)
ax.axhline(C.SNR_REC, color="orange", ls="--", lw=0.8)
ax.axvspan(*C.LASER_INTERP_MAIN, color="0.9", lw=0)
ax.set_xlabel("波长 / nm")
ax.set_ylabel("单帧 SNR")
ax.set_title("各距离中心点单帧 SNR（参考板，512 ms；取中心1/中心2 较低者；灰带为定位笔插值区）", fontsize=10)
ax.legend(fontsize=8, ncol=3)
ax.grid(alpha=0.3, which="both")
fig.tight_layout()
fig.savefig(FIG / "snr_curves.png")

fig, ax = plt.subplots(figsize=(10, 4.2))
for j, rrs in enumerate(C.RRS_CASES):
    f = np.pi * rrs / C.PANEL_REFL
    for N, ls in ((1, "-"), (10, ":")):
        yy = []
        for r_inst in rg:
            Sw = S15 * (r_inst / r15) ** (-n_pow) * f
            t_use = min(C.INT_MAX_MS, 512 * (LIN_MAX - OFFSET) / Sw[m_an].max())
            yy.append(Sw[nearest(420)] * (t_use / 512) / sigma[nearest(420)] * np.sqrt(N))
        ax.semilogy(rg, yy, ls=ls, color=["#2a6fdb", "#2e9e4f", "#d9452b"][j], label=f"Rrs={rrs}，N={N}")
ax.axhline(20, color="r", ls="--", lw=0.8)
ax.axvline(5.032, color="0.5", ls=":", lw=0.8)
ax.text(5.1, ax.get_ylim()[0] * 1.5, "实测范围外 →", fontsize=8, color="0.4")
ax.set_xlabel("安装距离 / m")
ax.set_ylabel("420 nm 估计 SNR")
ax.set_title("420 nm 水面信号 SNR 外推（估算，偏乐观；积分时间取 min(8192 ms, 45000 DN 上限)）", fontsize=10)
ax.legend(fontsize=8, ncol=3)
ax.grid(alpha=0.3, which="both")
fig.tight_layout()
fig.savefig(FIG / "snr_water_420.png")

res = {"points": snr_tab.to_dict("records"), "bands": band_tab.to_dict("records"),
       "ref": {str(w): [float(sig_ref[nearest(w)]), float(snr_ref[nearest(w)])] for w in C.SNR_WL},
       "noise_med": {"bright15": float(np.median(curves[1.5][0]["中心1"][1][m_an])), "ref": float(np.median(noise_ref[m_an])),
                     "dark": float(np.median(dark_noise[m_an]))},
       "ext": ext.to_dict("records"), "maxd": maxd.to_dict("records"), "n_pow": float(n_pow),
       "wl_used": {str(w): float(wl[nearest(w)]) for w in sorted(set(C.SNR_WL + C.EXTRAP_WL))}}
(OUT / "results_snr.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
(OUT / "snr_log.txt").write_text("\n".join(LOG), encoding="utf-8")
