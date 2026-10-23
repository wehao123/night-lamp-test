"""第 2 步：冷启动漂移分析（方法与旧报告第 2 章一致，差异见 config.py 注释）。

输出： out/cold_*.csv、out/results_cold.json、out/fig/cold_*.png
"""
import json
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


def T(s):
    return pd.Timestamp(f"{C.DATE} {s}")


t, it, mode, wl, dn = load_dn()
xb = (t + BJ).tz_localize(None)          # 北京时间
ok = (it == C.INTEGRATION_MS) & (mode == C.MODE)
t0 = T(C.T0)
tau = (xb - t0).total_seconds().values / 60.0   # min
pm = pen_metric(wl, dn)
dn_i = laser_interp(wl, dn, C.LASER_INTERP_MAIN)


def frames_in(a, b):
    return np.where(ok & (xb >= T(a)) & (xb <= T(b)))[0]


# ---------------- 背景 ----------------
i_pre, i_post = frames_in(*C.PRE_BG), frames_in(*C.POST_BG)
i_post2 = np.where((xb >= T(C.POST_BG2[0])) & (xb <= T(C.POST_BG2[1])))[0]
log(f"灯前背景 {C.PRE_BG}: {len(i_pre)} 帧；定位笔指标中位 {np.median(pm[i_pre]):.0f}")
log(f"灯后背景（记录81）{C.POST_BG}: {len(i_post)} 帧；定位笔指标中位 {np.median(pm[i_post]):.0f}")
log(f"灯后背景（记录82）{C.POST_BG2}: 共 {len(i_post2)} 帧，积分时间 {sorted(set(it[i_post2]))} ms，"
    f"模式 {sorted(set(mode[i_post2]))} → 无 512 ms 帧，不可用")
bg_pre, bg_post = dn_i[i_pre].mean(0), dn_i[i_post].mean(0)
BGS = {"灯前背景": bg_pre, "灯后背景": bg_post, "前后平均": (bg_pre + bg_post) / 2}
MAIN_BG = "前后平均"


def bands_of(S):
    return pd.DataFrame({k: band_integral(wl, S, *v) for k, v in BANDS.items()})


# 背景差异
bgdiff = {}
for k, (lo, hi) in BANDS.items():
    a = band_integral(wl, bg_pre[None, :], lo, hi)[0]
    b = band_integral(wl, bg_post[None, :], lo, hi)[0]
    bgdiff[k] = (a, b)

# ---------------- 帧分类 ----------------
win = ok & (tau >= 0) & (xb <= T("22:30:00"))
tot_all = band_integral(wl, dn_i - BGS[MAIN_BG], 420, 700)
level = np.median(tot_all[win & (tau > 1) & (tau < 80)])
abn = win & (np.abs(tot_all / level - 1) > 1 - C.OCCL_RATIO)     # 遮挡/灯未亮/扰动
pen = win & (pm > C.PEN_THRESHOLD)

# 灯被挪动的时刻：T+80 遮挡结束后，首个相对遮挡前 1 min 亮场偏离 >1% 且之后持续偏离的帧。
# 用蓝波段判断（此时定位笔开着且在衰减，会影响总量和红波段，对蓝波段影响 <0.1%）
blue_all = band_integral(wl, dn_i - dn_i[ok & (xb >= T(C.PRE_BG[0])) & (xb <= T(C.PRE_BG[1]))].mean(0), 420, 500)
occl80_end = max(b for a, b in runs(abn) if xb[a] < T("22:21:30"))
ref = np.where(win & ~abn & (xb >= T("22:19:20")) & (xb < T("22:20:20")))[0]
ref_level = np.median(blue_all[ref])
after = np.arange(occl80_end + 1, occl80_end + 400)
dev = np.abs(blue_all[after] / ref_level - 1) > 0.01
k_move = next(i for i in range(len(after) - 5) if dev[i:i + 5].all())
i_move = after[k_move]
log(f"T+80 遮挡结束最后一帧 {bj(t[occl80_end])}；其后亮场与遮挡前相比偏离 >1% 并持续：首帧 {bj(t[i_move])}"
    f"（τ={tau[i_move]:.2f} min）→ 灯开始挪动，冷启动数据到此为止")
cold = win & (np.arange(len(t)) < i_move)

# 开灯时刻（数据）
first_lit = np.where(cold & (tot_all > 0.9 * level))[0][0]
partial = np.where(cold & (tot_all > 0.05 * level))[0][0]
log(f"数据中首帧有灯光 {bj(t[partial])}（{tot_all[partial] / level * 100:.0f}% 亮度，积分中途开灯），"
    f"首个满亮度帧 {bj(t[first_lit])}；记录 T0={C.T0}，相差约 {(t[partial] - (t0 - BJ).tz_localize('UTC')).total_seconds():.1f} s")

excl_runs = []
for a, b in runs(abn & cold):
    excl_runs.append(("遮挡/异常（数据判定）", a, b))
for a, b in runs(pen & cold):
    excl_runs.append(("定位笔开", a, b))
excl = pad(abn & cold, C.OCCL_PAD_FRAMES) | pad(pen & cold, C.PEN_PAD_FRAMES)
for a, b, why in C.EXTRA_EXCLUDE:
    m = (xb >= T(a)) & (xb <= T(b))
    excl |= m
    excl_runs.append((why, np.where(m)[0][0], np.where(m)[0][-1]))
# 灯未亮帧
excl |= cold & (np.arange(len(t)) < first_lit)
if C.INTERFERENCE_EXCLUDE:
    for name, a, b in C.INTERFERENCE:
        excl |= (xb >= T(a)) & (xb <= T(b))
valid = cold & ~excl

# 剔除时段表（合并 pad 后的区间）
rows = []
for a, b in runs(cold & excl):
    why = sorted({w for w, ra, rb in excl_runs if not (rb < a or ra > b)}) or ["开灯前/过渡帧"]
    rows.append({"开始(北京)": bj(t[a]), "结束(北京)": bj(t[b]), "τ开始/min": round(tau[a], 2),
                 "τ结束/min": round(tau[b], 2), "帧数": b - a + 1, "原因": "；".join(why),
                 "定位笔指标中位": int(np.median(pm[a:b + 1]))})
excl_tab = pd.DataFrame(rows)
excl_tab.to_csv(OUT / "cold_exclusions.csv", index=False, encoding="utf-8-sig")
log("\n剔除时段（含前后各 3 帧过渡帧）：\n" + excl_tab.to_string(index=False))

# 记录中的遮挡 vs 数据判定
log("\n记录的遮挡时段 vs 数据台阶：")
for name, a, b in C.COLD_OCCLUSIONS:
    r = [(ra, rb) for ra, rb in runs(abn & cold) if xb[rb] >= T(a) - pd.Timedelta(seconds=15) and xb[ra] <= T(b) + pd.Timedelta(seconds=15)]
    s = "；".join(f"{bj(t[ra])}–{bj(t[rb])}（{rb - ra + 1} 帧，占亮场 {np.median(tot_all[ra:rb + 1]) / level * 100:.1f}%，定位笔指标 {np.median(pm[ra:rb + 1]):.0f}）" for ra, rb in r)
    log(f"  {name}: 记录 {a}–{b} → 数据 {s}")

# 定位笔状态（数据为准）
log("\n定位笔状态（数据判定，亮场帧）：")
pen_tab = []
for a, b in runs(pen & cold & ~abn):
    pen_tab.append({"开始(北京)": bj(t[a]), "结束(北京)": bj(t[b]), "帧数": b - a + 1,
                    "指标中位": int(np.median(pm[a:b + 1])), "指标最大": int(pm[a:b + 1].max())})
pen_tab = pd.DataFrame(pen_tab)
log(pen_tab.to_string(index=False))
pen_tab.to_csv(OUT / "cold_pen_state.csv", index=False, encoding="utf-8-sig")
log(f"笔关亮场帧的指标：中位 {np.median(pm[valid]):.0f}，范围 {pm[valid].min():.0f}–{pm[valid].max():.0f}")

# 定位笔开关前后各波段的跳变（说明为什么要剔除）
jump_rows = []
near_occl = pad(abn, 12)          # 离遮挡 12 帧以内的帧可能有遮光板半遮，不用于估计跳变
for a, b in runs(pen & cold & ~abn):
    for edge, i in (("关→开", a), ("开→关", b + 1)):
        pre_i = [j for j in range(i - 10, i - 1) if cold[j] and not near_occl[j]]
        post_i = [j for j in range(i + 2, i + 11) if j < len(t) and cold[j] and not near_occl[j]]
        if len(pre_i) < 5 or len(post_i) < 5:
            continue
        on_i, off_i = (post_i, pre_i) if edge == "关→开" else (pre_i, post_i)
        Bm = bands_of(dn_i[on_i + off_i] - BGS[MAIN_BG])
        Bw = bands_of(laser_interp(wl, dn[on_i + off_i], C.LASER_INTERP_WIDE) - laser_interp(wl, BGS[MAIN_BG], C.LASER_INTERP_WIDE))
        n = len(on_i)
        row = {"时刻": bj(t[i]), "方向": edge, "笔开时指标": int(pm[on_i].mean())}
        for k in BANDS:
            row[k + "(655-672插值)%"] = round((Bm[k][:n].mean() / Bm[k][n:].mean() - 1) * 100, 3)
            row[k + "(645-680插值)%"] = round((Bw[k][:n].mean() / Bw[k][n:].mean() - 1) * 100, 3)
        jump_rows.append(row)
jump_tab = pd.DataFrame(jump_rows)
jump_tab.to_csv(OUT / "cold_pen_jumps.csv", index=False, encoding="utf-8-sig")
log("\n定位笔开/关引起的波段跳变（笔开相对笔关，%）：\n" + jump_tab.to_string(index=False))

# ---------------- 波段时间序列（各背景） ----------------
S_by_bg = {k: bands_of(dn_i[valid] - v) for k, v in BGS.items()}
S_by_bg["只扣偏置"] = bands_of(dn_i[valid] - bias(wl, dn[valid])[:, None])
tv = tau[valid]
xv = xb[valid]


def segments(tm):
    gaps = np.where(np.diff(tm) * 60 > C.GAP_MAX_S)[0]
    edges = np.concatenate([[0], gaps + 1, [len(tm)]])
    return [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]


SEGS = segments(tv)
log(f"\n主序列有效帧 {valid.sum()}，τ {tv[0]:.2f}–{tv[-1]:.2f} min（{bj(t[valid][0])}–{bj(t[valid][-1])}），"
    f"{len(SEGS)} 个连续段：" + "；".join(f"{tv[a]:.2f}–{tv[b - 1]:.2f}" for a, b in SEGS))


def blocks(tm, q, t_from, t_to):
    """10 s 块均值（每块 ≥5 帧），块从 t_from 起对齐"""
    edges = np.arange(t_from, t_to + 1e-9, C.BLOCK_S / 60)
    out = []
    for a, b in zip(edges[:-1], edges[1:]):
        m = (tm >= a) & (tm < b)
        if m.sum() >= C.BLOCK_MIN_FRAMES:
            out.append(((a + b) / 2, q[m].mean()))
    return np.array(out)


def sliding(tm, q):
    res = []
    W = C.SLIDE_WIN_MIN
    tol = C.GAP_MAX_S / 60
    for a, b in SEGS:
        ts, qs = tm[a:b], q[a:b]
        if ts[-1] - ts[0] < W:
            continue
        for s in np.arange(ts[0], ts[-1] - W + 1e-9, C.SLIDE_STEP_S / 60):
            m = (ts >= s) & (ts < s + W)
            tt, qq = ts[m], qs[m]
            if tt[0] - s > tol or (s + W) - tt[-1] > tol:
                continue
            mu = qq.mean()
            k = np.polyfit(tt, qq, 1)[0]
            res.append((s, s + W, qq.std(ddof=1) / mu * 100, k / mu * 100, len(qq)))
    return pd.DataFrame(res, columns=["start", "end", "CV", "r", "n"])


def stats_for(df):
    """一种背景下各波段的指标"""
    out = {}
    first = tv <= tv[0] + 10 / 60
    last = tv >= tv[-1] - 10 / 60
    m2050 = (tv >= 20) & (tv <= 50)
    for k in BANDS:
        q = df[k].values
        blk = blocks(tv[m2050], q[m2050], 20, 50)
        out[k] = {
            "CV_20_50": q[m2050].std(ddof=1) / q[m2050].mean() * 100,
            "pp_20_50": (blk[:, 1].max() - blk[:, 1].min()) / q[m2050].mean() * 100,
            "first_last": (q[last].mean() / q[first].mean() - 1) * 100,
            "n_20_50": int(m2050.sum()), "nblk_20_50": len(blk),
        }
    return out


STATS = {bgname: stats_for(df) for bgname, df in S_by_bg.items()}
main = S_by_bg[MAIN_BG]

# 滑动窗口（总量）
sw = sliding(tv, main["总量420-700"].values)
sw["pass"] = (sw.CV <= C.CV_MAX) & (sw.r.abs() <= C.R_MAX)
sw.to_csv(OUT / "cold_sliding_total.csv", index=False, encoding="utf-8-sig")
log(f"\n滑动窗口（总量）: {len(sw)} 个可评价窗口，满足判据 {sw['pass'].sum()} 个；最大 CV {sw.CV.max():.3f}%，"
    f"最大 |r| {sw.r.abs().max():.3f} %/min（出现在窗口起点 τ={sw.start[sw.r.abs().idxmax()]:.2f} min）")
sw_band = {}
for k in BANDS:
    s2 = sliding(tv, main[k].values)
    sw_band[k] = {"n": len(s2), "maxCV": s2.CV.max(), "maxR": s2.r.abs().max(),
                  "npass": int(((s2.CV <= C.CV_MAX) & (s2.r.abs() <= C.R_MAX)).sum())}


def find_tstable(sw):
    """首个窗口起点 s0：起点在 [s0, s0+10 min] 内的所有可评价窗口均满足判据，且这些窗口跨度 ≥ 10 min。"""
    st = sw.start.values
    ps = sw["pass"].values
    for i in range(len(st)):
        if not ps[i]:
            continue
        m = (st >= st[i]) & (st <= st[i] + C.STABLE_HOLD_MIN)
        if st[m].max() - st[i] < C.STABLE_HOLD_MIN - 1 / 60:
            continue
        if ps[m].all():
            return st[i], sw.end.values[i]
    return None, None


ts0, te0 = find_tstable(sw)
first_eval = sw.start.min()
log(f"Tstable（窗口起点计）= τ {ts0:.2f} min；首个可评价窗口起点 τ {first_eval:.2f} min"
    + ("（首个可评价窗口即满足 → Tstable 不晚于此时刻，此前因定位笔/遮挡无可评价数据）" if abs(ts0 - first_eval) < 1e-6 else ""))
# 不满足判据的窗口
bad = sw[~sw["pass"]]
if len(bad):
    log(f"不满足判据的窗口：起点 τ {bad.start.min():.2f}–{bad.start.max():.2f} min，共 {len(bad)} 个；"
        f"其中 CV 超限 {int((bad.CV > C.CV_MAX).sum())}、|r| 超限 {int((bad.r.abs() > C.R_MAX).sum())}")

# 分段线性拟合
seg_rows = []
for a, b in C.SEG_FITS:
    m = (tv >= a) & (tv < b)
    if m.sum() < 20:
        continue
    row = {"区间/min": f"{a}–{b}", "实际覆盖/min": f"{tv[m].min():.2f}–{tv[m].max():.2f}", "帧数": int(m.sum())}
    for k in BANDS:
        q = main[k].values[m]
        row[k] = np.polyfit(tv[m], q, 1)[0] / q.mean() * 100
    seg_rows.append(row)
seg_tab = pd.DataFrame(seg_rows)
seg_tab.to_csv(OUT / "cold_segment_fits.csv", index=False, encoding="utf-8-sig")
log("\n分段线性拟合下降速率（%/min）：\n" + seg_tab.round(4).to_string(index=False))

# 配对误差：10 s 块均值相隔 60 s 的相对变化
blk_tot = blocks(tv, main["总量420-700"].values, tv[0], tv[-1])
pair = []
for tc, q in blk_tot:
    j = np.argmin(np.abs(blk_tot[:, 0] - (tc + 1)))
    if abs(blk_tot[j, 0] - (tc + 1)) < 1 / 60:
        pair.append((tc, abs(blk_tot[j, 1] / q - 1) * 100))
pair = np.array(pair)
pair_rows = []
for a, b in [(0, 20), (20, 50), (50, 90), (0, 90)]:
    m = (pair[:, 0] >= a) & (pair[:, 0] < b)
    if m.sum():
        pair_rows.append({"区间/min": f"{a}–{b}", "配对数": int(m.sum()), "中位%": np.median(pair[m, 1]),
                          "95%分位%": np.percentile(pair[m, 1], 95), "最大%": pair[m, 1].max()})
pair_tab = pd.DataFrame(pair_rows)
log("\n1 min 配对误差（10 s 块均值相隔 60 s 的相对变化绝对值）：\n" + pair_tab.round(4).to_string(index=False))

# 干扰时段检查
intf_rows = []
for name, a, b in C.INTERFERENCE:
    ta, tb = (T(a) - t0).total_seconds() / 60, (T(b) - t0).total_seconds() / 60
    for k in BANDS:
        q = main[k].values
        around = (tv >= ta - 10) & (tv <= tb + 10)
        inside = (tv >= ta) & (tv <= tb)
        fitm = around & ~inside
        p = np.polyfit(tv[fitm], q[fitm], 2)
        res = (q / np.polyval(p, tv) - 1) * 100
        bi = blocks(tv[inside], res[inside], ta, tb)
        bo = blocks(tv[fitm], res[fitm], ta - 10, tb + 10)
        intf_rows.append({"时段": f"{name} {a[:8]}–{b[:8]}", "波段": k, "段内帧数": int(inside.sum()),
                          "段内残差均值%": res[inside].mean(), "段内10s块残差最大绝对%": np.abs(bi[:, 1]).max() if len(bi) else np.nan,
                          "段外10s块残差标准差%": bo[:, 1].std(ddof=1)})
intf_tab = pd.DataFrame(intf_rows)
sd = intf_tab["段外10s块残差标准差%"]
intf_tab["判定"] = np.select(
    [(intf_tab["段内残差均值%"].abs() > 3 * sd) & (intf_tab["段内残差均值%"].abs() > 0.05),
     intf_tab["段内10s块残差最大绝对%"] > 4 * sd],
    ["整体偏移", "有短时尖峰"], "无可见影响")
intf_tab.to_csv(OUT / "cold_interference.csv", index=False, encoding="utf-8-sig")
log("\n干扰时段检查（相对 ±10 min 二次拟合的残差）：\n" + intf_tab.round(4).to_string(index=False))

# 剔除干扰时段后的敏感性
m_int = np.zeros(len(tv), bool)
for name, a, b in C.INTERFERENCE:
    m_int |= (xv >= T(a)) & (xv <= T(b))
q = main["总量420-700"].values
m2050 = (tv >= 20) & (tv <= 50)
intf_effect = {
    "含干扰时段_首末%": STATS[MAIN_BG]["总量420-700"]["first_last"],
    "含干扰时段_CV20_50": STATS[MAIN_BG]["总量420-700"]["CV_20_50"],
    "剔除干扰时段_CV20_50": q[m2050 & ~m_int].std(ddof=1) / q[m2050 & ~m_int].mean() * 100,
    "剔除干扰时段_帧数": int((~m_int).sum()),
}
log("干扰时段剔除前后：" + json.dumps({k: round(v, 4) for k, v in intf_effect.items()}, ensure_ascii=False))

# ---------------- 补充：含定位笔帧的蓝、绿波段（覆盖 T+0–5 min） ----------------
supp = cold & ~pad(abn & cold, C.OCCL_PAD_FRAMES) & (np.arange(len(t)) >= first_lit)
for a, b, why in C.EXTRA_EXCLUDE:
    supp &= ~((xb >= T(a)) & (xb <= T(b)))
Ssupp = bands_of(dn_i[supp] - BGS[MAIN_BG])
ts_ = tau[supp]
supp_res = {}
end_ref_s = ts_ >= tv[-1] - C.END_REF_MIN
for k in ["蓝420-500", "绿500-600"]:
    qq = Ssupp[k].values
    f10 = ts_ <= ts_[0] + 10 / 60
    at5 = (ts_ >= tv[0]) & (ts_ <= tv[0] + 10 / 60)
    m05 = ts_ < 5
    supp_res[k] = {
        "首10s_τ": float(ts_[0]),
        "T0至主序列起点变化%": (qq[at5].mean() / qq[f10].mean() - 1) * 100,
        "T0至主序列末变化%": (qq[ts_ >= tv[-1] - 10 / 60].mean() / qq[f10].mean() - 1) * 100,
        "0-5min斜率%/min": np.polyfit(ts_[m05], qq[m05], 1)[0] / qq[m05].mean() * 100,
    }
log("\n补充（含定位笔帧，蓝/绿波段受定位笔影响 ≤0.13%）：" + json.dumps(supp_res, ensure_ascii=False, default=float))

# 补充序列上的滑动窗口（蓝、绿），用来估计 T+5 min 之前何时满足判据（判据原本针对总量，此处仅作参考）
_SEGS_main = SEGS
SEGS = segments(ts_)
supp_sw = {}
for k in ["蓝420-500", "绿500-600"]:
    s2 = sliding(ts_, Ssupp[k].values)
    s2["pass"] = (s2.CV <= C.CV_MAX) & (s2.r.abs() <= C.R_MAX)
    fail = s2[~s2["pass"]]
    early = s2[s2.start < tv[0]]
    supp_sw[k] = {"首个窗口起点": float(s2.start.min()), "窗口数": int(len(s2)),
                  "最后一个不满足窗口起点": float(fail.start.max()) if len(fail) else None,
                  "不满足窗口数": int(len(fail)),
                  "τ<5.2起点窗口最大|r|": float(early.r.abs().max()) if len(early) else None,
                  "τ<5.2起点窗口最大CV": float(early.CV.max()) if len(early) else None,
                  "Tstable": find_tstable(s2)[0]}
    s2.to_csv(OUT / f"cold_sliding_supp_{k[:1]}.csv", index=False, encoding="utf-8-sig")
SEGS = _SEGS_main
log("补充序列连续段：" + "；".join(f"{ts_[a]:.2f}–{ts_[b - 1]:.2f}" for a, b in segments(ts_)))
log("补充序列滑动窗口：" + json.dumps(supp_sw, ensure_ascii=False, default=float))

# ---------------- 开灯前那次短暂点亮（1024 ms） ----------------
fl = np.where((it == 1024) & (xb >= T("20:41:00")) & (xb <= T("20:42:30")))[0]
fl_tot = band_integral(wl, dn_i[fl] - bias(wl, dn[fl])[:, None], 420, 700)
lit = fl[fl_tot > 0.9 * fl_tot.max()]          # 只用满亮度帧（首帧为积分中途开灯的半亮帧）
lt = band_integral(wl, dn_i[lit] - bias(wl, dn[lit])[:, None], 420, 700)
dl = (xb[lit] - xb[lit[0]]).total_seconds().values
flash = {"首帧有灯光(北京)": bj(t[lit[0]]), "最后一帧有灯光(北京)": bj(t[lit[-1]]), "帧数": int(len(lit)),
         "持续_s_至少": float(dl[-1]), "首10s到末10s变化%": float((lt[dl >= dl[-1] - 10].mean() / lt[dl <= 10].mean() - 1) * 100),
         "之后采集中断至": "20:46:25.950", "峰值DN": int(dn[lit][:, (wl > 400) & (wl < 720)].max()),
         "与T0间隔_min_至少": float((t0 - xb[lit[-1]]).total_seconds() / 60)}
log("\n开灯前短暂点亮：" + json.dumps(flash, ensure_ascii=False))

# ---------------- 汇总表 ----------------
summary = []
for k in BANDS:
    s = STATS[MAIN_BG][k]
    summary.append({"波段": k, "20-50min CV%": s["CV_20_50"], "20-50min 峰-峰(10s块)%": s["pp_20_50"],
                    "全程首末%": s["first_last"], "滑动窗最大CV%": sw_band[k]["maxCV"],
                    "滑动窗最大|r|%/min": sw_band[k]["maxR"]})
summary = pd.DataFrame(summary)
summary.to_csv(OUT / "cold_summary.csv", index=False, encoding="utf-8-sig")
log("\n主分析（背景=灯前灯后平均）：\n" + summary.round(4).to_string(index=False))

sens = []
for bgname in ["只扣偏置", "灯前背景", "灯后背景", "前后平均"]:
    s = STATS[bgname]
    sens.append({"背景": bgname, **{f"{k[:2]}首末%": s[k]["first_last"] for k in BANDS},
                 "总量峰-峰%": s["总量420-700"]["pp_20_50"], "蓝峰-峰%": s["蓝420-500"]["pp_20_50"]})
sens = pd.DataFrame(sens)
sens.to_csv(OUT / "cold_bg_sensitivity.csv", index=False, encoding="utf-8-sig")
log("\n背景敏感性：\n" + sens.round(3).to_string(index=False))
bgd = pd.DataFrame([{"波段": k, "灯前": a, "灯后": b, "灯后-灯前": b - a,
                     "差占亮场%": (b - a) / main[k].mean() * 100, "灯前占亮场%": a / main[k].mean() * 100}
                    for k, (a, b) in bgdiff.items()])
log("\n背景积分（DN·nm，含偏置已在相减中处理前的原始插值谱 → 此处为含偏置积分，仅比较差值）：\n" + bgd.round(3).to_string(index=False))

# 每帧结果存档
fr = pd.DataFrame({"北京时间": [bj(v) for v in t[cold]], "tau_min": tau[cold], "有效": valid[cold],
                   "遮挡或异常": abn[cold], "定位笔开": pen[cold], "定位笔指标": pm[cold]})
allS = bands_of(dn_i[cold] - BGS[MAIN_BG])
fr = pd.concat([fr, allS], axis=1)
fr.to_csv(OUT / "cold_frames.csv", index=False, encoding="utf-8-sig")

# ---------------- 图 ----------------
end_ref = tv >= tv[-1] - C.END_REF_MIN
colors = {"总量420-700": "#333333", "蓝420-500": "#2a6fdb", "绿500-600": "#2e9e4f", "红600-700": "#d9452b", "红边700-720": "#8e3fbf"}
fig, axs = plt.subplots(2, 1, figsize=(10, 7.2), sharex=True, gridspec_kw={"height_ratios": [2.2, 1]})
ax = axs[0]
for k in [b for b in BANDS if b != "红边700-720"]:
    q = main[k].values
    ref_m = q[end_ref].mean()
    for a, b in SEGS:
        blk = blocks(tv[a:b], q[a:b], tv[a], tv[b - 1])
        ax.plot(blk[:, 0], (blk[:, 1] / ref_m - 1) * 100, color=colors[k], lw=1.3, label=k if a == 0 else None)
for k in ["蓝420-500", "绿500-600"]:
    q = Ssupp[k].values
    ref_m = q[end_ref_s].mean()
    m = ts_ < tv[0]
    blk = blocks(ts_[m], q[m], ts_[0], tv[0])
    ax.plot(blk[:, 0], (blk[:, 1] / ref_m - 1) * 100, color=colors[k], lw=1, ls=":")
k = "红边700-720"
q = main[k].values
ref_m = q[end_ref].mean()
for a, b in SEGS:
    blk = blocks(tv[a:b], q[a:b], tv[a], tv[b - 1])
    axs[1].plot(blk[:, 0], (blk[:, 1] / ref_m - 1) * 100, color=colors[k], lw=0.6, alpha=0.5, label="10 s 块" if a == 0 else None)
    edges = np.arange(tv[a], tv[b - 1] + 1e-9, 1.0)
    bm = [((e0 + e1) / 2, q[a:b][(tv[a:b] >= e0) & (tv[a:b] < e1)].mean()) for e0, e1 in zip(edges[:-1], edges[1:])
          if ((tv[a:b] >= e0) & (tv[a:b] < e1)).sum() >= 20]
    if bm:
        bm = np.array(bm)
        axs[1].plot(bm[:, 0], (bm[:, 1] / ref_m - 1) * 100, color=colors[k], lw=1.6, label="1 min 块" if a == 0 else None)
for a_ in axs:
    for _, r in excl_tab.iterrows():
        a_.axvspan(r["τ开始/min"], r["τ结束/min"], color="0.85", lw=0)
    for name, a, b in C.INTERFERENCE:
        a_.axvspan((T(a) - t0).total_seconds() / 60, (T(b) - t0).total_seconds() / 60, color="#f2c94c", alpha=0.25, lw=0)
    a_.axhline(0, color="0.5", lw=0.6)
    a_.grid(alpha=0.3)
axs[1].set_xlabel("开灯后时间 τ / min")
ax.set_ylabel("相对末段均值的变化 / %")
axs[1].set_ylabel("红边 700–720 nm / %")
axs[1].legend(fontsize=8, loc="upper right")
ax.set_title(f"各波段 10 s 块均值相对末段（τ {tv[-1] - C.END_REF_MIN:.1f}–{tv[-1]:.1f} min）均值的变化\n灰=剔除时段（定位笔开/遮挡），黄=记录的干扰时段；点线=含定位笔帧的蓝、绿波段（补充）", fontsize=10)
ax.legend(fontsize=8, ncol=4, loc="upper right")
fig.tight_layout()
fig.savefig(FIG / "cold_bands_relative.png")

fig, ax = plt.subplots(2, 1, figsize=(10, 5.5), sharex=True)
ax[0].plot(sw.start + C.SLIDE_WIN_MIN / 2, sw.CV, ".", ms=1.5, color="#333")
ax[0].axhline(C.CV_MAX, color="r", lw=0.8, ls="--")
ax[0].set_ylabel("滑动 CV / %")
ax[0].set_ylim(0, max(1.1, sw.CV.max() * 1.1))
ax[1].plot(sw.start + C.SLIDE_WIN_MIN / 2, sw.r.abs(), ".", ms=1.5, color="#333")
ax[1].axhline(C.R_MAX, color="r", lw=0.8, ls="--")
ax[1].set_ylabel("|r| / (%/min)")
ax[1].set_xlabel("窗口中心 τ / min")
for a_ in ax:
    a_.grid(alpha=0.3)
    for _, r in excl_tab.iterrows():
        a_.axvspan(r["τ开始/min"], r["τ结束/min"], color="0.85", lw=0)
ax[0].set_title("总量（420–700 nm）5 min 滑动窗口 CV 与变化率绝对值（虚线为判据）", fontsize=10)
fig.tight_layout()
fig.savefig(FIG / "cold_sliding_total.png")

fig, ax = plt.subplots(1, 2, figsize=(11, 4.2))
for j, k in enumerate(["总量420-700", "蓝420-500"]):
    for bgname, ls in [("只扣偏置", ":"), ("灯前背景", "--"), ("灯后背景", "-."), ("前后平均", "-")]:
        q = S_by_bg[bgname][k].values
        ref_m = q[end_ref].mean()
        for a, b in SEGS:
            blk = blocks(tv[a:b], q[a:b], tv[a], tv[b - 1])
            ax[j].plot(blk[:, 0], (blk[:, 1] / ref_m - 1) * 100, ls=ls, lw=1, label=bgname if a == 0 else None)
    ax[j].set_title(k)
    ax[j].set_xlabel("τ / min")
    ax[j].grid(alpha=0.3)
ax[0].set_ylabel("相对末段均值 / %")
ax[0].legend(fontsize=8)
fig.suptitle("背景处理方式敏感性（10 s 块均值）", fontsize=10)
fig.tight_layout()
fig.savefig(FIG / "cold_bg_sensitivity.png")

fig, ax = plt.subplots(2, 1, figsize=(11, 5.5), sharex=True)
c = cold & (np.arange(len(t)) >= first_lit)
ax[0].plot(tau[c & ~valid], tot_all[c & ~valid] / level * 100, ".", ms=1.5, color="#d9452b", label="剔除")
ax[0].plot(tau[valid], tot_all[valid] / level * 100, ".", ms=1.5, color="#333", label="有效")
ax[0].set_ylim(95, 110)
ax[0].set_ylabel("总量 / 全程中位 %")
ax[0].legend(fontsize=8, markerscale=5)
ax[1].semilogy(tau[c], np.clip(pm[c], 1, None), ".", ms=1.5, color="#8e3fbf")
ax[1].axhline(C.PEN_THRESHOLD, color="r", ls="--", lw=0.8)
ax[1].set_ylabel("定位笔指标 / DN")
ax[1].set_xlabel("τ / min")
for name, a, b in C.INTERFERENCE:
    for a_ in ax:
        a_.axvspan((T(a) - t0).total_seconds() / 60, (T(b) - t0).total_seconds() / 60, color="#f2c94c", alpha=0.3)
ax[0].set_title("冷启动数据质量：总量逐帧（红=剔除）与定位笔指标；黄=记录的干扰时段", fontsize=10)
for a_ in ax:
    a_.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(FIG / "cold_qa_timeline.png")

res = {
    "T0": C.T0, "data_first_light": bj(t[partial]), "data_full_light": bj(t[first_lit]),
    "lamp_move_frame": bj(t[i_move]), "lamp_move_tau": float(tau[i_move]),
    "n_valid": int(valid.sum()), "tau_first": float(tv[0]), "tau_last": float(tv[-1]),
    "time_first": bj(t[valid][0]), "time_last": bj(t[valid][-1]),
    "segments": [(float(tv[a]), float(tv[b - 1])) for a, b in SEGS],
    "n_pre_bg": int(len(i_pre)), "n_post_bg": int(len(i_post)),
    "sliding": {"n": int(len(sw)), "npass": int(sw["pass"].sum()), "maxCV": float(sw.CV.max()),
                "maxR": float(sw.r.abs().max()), "maxR_at": float(sw.start[sw.r.abs().idxmax()]),
                "Tstable": float(ts0), "first_eval": float(first_eval),
                "bad_range": [float(bad.start.min()), float(bad.start.max())] if len(bad) else None,
                "n_bad": int(len(bad))},
    "sliding_bands": {k: {kk: float(vv) for kk, vv in v.items()} for k, v in sw_band.items()},
    "stats": STATS, "seg_fits": seg_tab.to_dict("records"), "pair": pair_tab.to_dict("records"),
    "interference": intf_tab.to_dict("records"), "intf_effect": intf_effect,
    "supp": supp_res, "supp_sliding": supp_sw, "flash": flash, "bgdiff": bgd.to_dict("records"),
    "pen_jumps": jump_tab.to_dict("records"), "pen_state": pen_tab.to_dict("records"),
    "exclusions": excl_tab.to_dict("records"), "end_ref": [float(tv[-1] - C.END_REF_MIN), float(tv[-1])],
    "level": float(level),
}
(OUT / "results_cold.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
(OUT / "cold_log.txt").write_text("\n".join(LOG), encoding="utf-8")
