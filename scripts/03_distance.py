"""第 3 步：距离响应与横向光斑（方法与旧报告第 3 章一致）。

输出： out/dist_*.csv、out/results_dist.json、out/fig/dist_*.png
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


t, it, mode, wl, dn = load_dn()
ok = (it == C.INTEGRATION_MS) & (mode == C.MODE)
pm = pen_metric(wl, dn)
b = bias(wl, dn)
DN = {"main": laser_interp(wl, dn, C.LASER_INTERP_MAIN), "wide": laser_interp(wl, dn, C.LASER_INTERP_WIDE)}
tot = band_integral(wl, DN["main"] - b[:, None], 420, 700)   # 分类用（逐帧扣偏置，减小共模起伏）
_, seg, notes = read_records()
seg = seg.set_index("序号")
sum_m = (wl >= C.SUM_BAND[0]) & (wl <= C.SUM_BAND[1])
log(f"净通道和波段 {C.SUM_BAND}：{sum_m.sum()} 个通道，{wl[sum_m][0]:.2f}–{wl[sum_m][-1]:.2f} nm")

# 亮场 → 遮挡 的配对（反查遮挡对应的亮场参考水平）
occl_to_bright = {}
for d, pts in C.PAIRS.items():
    for pos, (bi, oi) in pts.items():
        occl_to_bright.setdefault(oi, bi)


def win_frames(k):
    r = seg.loc[k]
    return np.where(ok & (t >= r.t0) & (t <= r.t1))[0]


SEL = {}       # 段号 → 选中的帧下标
QA = []


def select_bright(k):
    i = win_frames(k)
    if len(i) == 0:
        return np.array([], int), {"段": k, "窗口帧数": 0}
    med = np.median(tot[i])
    keep = i[np.abs(tot[i] / med - 1) <= 0.02]
    used = keep[C.EDGE_DROP_FRAMES:len(keep) - C.EDGE_DROP_FRAMES]
    q = tot[used]
    return used, {"段": k, "类型": "亮场", "窗口帧数": len(i), "水平帧数": len(keep), "使用帧数": len(used),
                  "逐帧CV%": q.std(ddof=1) / q.mean() * 100, "定位笔指标中位": float(np.median(pm[used]))}


def select_occl(k, bright_level):
    i = win_frames(k)
    if len(i) == 0:
        return np.array([], int), np.array([], int), {"段": k, "窗口帧数": 0}
    cand = i[tot[i] < 0.15 * bright_level]
    if len(cand) == 0:
        return np.array([], int), np.array([], int), {"段": k, "类型": "遮挡", "窗口帧数": len(i), "候选帧数": 0, "使用帧数": 0}
    L = np.percentile(tot[cand], 25)
    keep = cand[tot[cand] <= 1.35 * L]
    used = keep[C.EDGE_DROP_FRAMES:len(keep) - C.EDGE_DROP_FRAMES]
    cand_used = cand[C.EDGE_DROP_FRAMES:len(cand) - C.EDGE_DROP_FRAMES]
    q = tot[used] if len(used) else np.array([np.nan])
    return used, cand_used, {"段": k, "类型": "遮挡", "窗口帧数": len(i), "候选帧数": len(cand), "平台帧数": len(keep),
                             "使用帧数": len(used), "占亮场%": np.median(q) / bright_level * 100,
                             "逐帧CV%": np.std(q, ddof=1) / np.mean(q) * 100 if len(used) > 2 else np.nan,
                             "被排除的偏高候选帧": int(len(cand) - len(keep)),
                             "定位笔指标中位": float(np.median(pm[used])) if len(used) else np.nan}


# ---------------- 逐段选帧 ----------------
bright_ids = sorted({bi for pts in C.PAIRS.values() for bi, _ in pts.values()} | {79, 80})
occl_ids = sorted({oi for pts in C.PAIRS.values() for _, oi in pts.values()} | {62, 68, 76, 78})
BRIGHT_LEVEL = {}
for k in bright_ids:
    used, q = select_bright(k)
    SEL[k] = used
    BRIGHT_LEVEL[k] = float(np.median(tot[used]))
    QA.append(q)
SEL_ALLCAND = {}
for k in occl_ids:
    bi = occl_to_bright.get(k)
    used, cand_used, q = select_occl(k, BRIGHT_LEVEL[bi])
    SEL[k] = used
    SEL_ALLCAND[k] = cand_used
    q["参照亮场段"] = bi
    QA.append(q)
qa = pd.DataFrame(QA)
for k in qa["段"]:
    r = seg.loc[k]
    qa.loc[qa["段"] == k, "距离"] = r["设定距离m"]
    qa.loc[qa["段"] == k, "位置"] = r["位置"]
    qa.loc[qa["段"] == k, "记录窗口(北京)"] = f"{(r.t0 + BJ).strftime('%H:%M:%S')}–{(r.t1 + BJ).strftime('%H:%M:%S')}"
qa = qa.sort_values("段")
MIN_OCCL = 3
invalid_occl = [int(k) for k in qa[(qa["类型"] == "遮挡") & (qa["使用帧数"] < MIN_OCCL)]["段"]]
few_occl = [int(k) for k in qa[(qa["类型"] == "遮挡") & (qa["使用帧数"] >= MIN_OCCL) & (qa["使用帧数"] < 10)]["段"]]
log("\n逐段选帧 QA：\n" + qa.round(3).to_string(index=False))
log(f"\n无可用遮挡帧（使用帧数 < {MIN_OCCL}）的遮挡段：{invalid_occl}")
log(f"可用但帧数 < 10 的遮挡段：{few_occl}")
qa.to_csv(OUT / "dist_segment_qa.csv", index=False, encoding="utf-8-sig")

# ---------------- 代表光谱与净响应 ----------------


def med_spec(k, variant="main", frames=None):
    f = SEL[k] if frames is None else frames
    return np.median(DN[variant][f], axis=0)


def net(bk, ok_, variant="main", occl_frames=None):
    return med_spec(bk, variant) - med_spec(ok_, variant, occl_frames)


def R_of(S, band="sum"):
    if band == "sum":
        return float(S[sum_m].sum())
    if band == "trapz":
        return float(band_integral(wl, S[None, :], *C.TRAPZ_BAND)[0])
    if band == "400-640":
        m = (wl >= 400) & (wl <= 640)
        return float(S[m].sum())


# 实际使用的遮挡（替代规则 + 72 无效时的处理）
occl_for = {}
notes_subst = []
for d, pts in C.PAIRS.items():
    for pos, (bi, oi) in pts.items():
        occl_for[bi] = oi
for bi, oi in C.SUBST_MAIN.items():
    occl_for[bi] = oi
PROVISIONAL = {}
for bi, oi in list(occl_for.items()):
    if oi in invalid_occl:
        alt = 74 if bi in (70, 71) else None
        PROVISIONAL[bi] = (oi, alt)
        notes_subst.append(f"亮场 {bi} 规定/配对的遮挡 {oi} 无可用遮挡帧 → 暂用 {alt}（待操作人确认）")
        occl_for[bi] = alt
for s in notes_subst:
    log(s)

SENS = dict(C.SUBST_SENS)
SENS[70] = [x for x in SENS.get(70, []) if x not in invalid_occl and x != occl_for[70]] + [78]
SENS[71] = [76, 78]

rows = []
NET = {}
for d, pts in C.PAIRS.items():
    for pos, (bi, _) in pts.items():
        oi = occl_for[bi]
        S = net(bi, oi)
        NET[(d, pos)] = S
        rows.append({"距离": d, "实测距离m": C.DIST_M[d], "位置": pos, "亮场段": bi, "遮挡段": oi,
                     "R_sum": R_of(S), "R_trapz": R_of(S, "trapz"), "R_400_640": R_of(S, "400-640"),
                     "R_sum_宽插值": R_of(net(bi, oi, "wide")),
                     "R_sum_遮挡全部候选帧": R_of(net(bi, oi, occl_frames=SEL_ALLCAND[oi])),
                     "遮挡占亮场%": float(np.median(tot[SEL[oi]]) / BRIGHT_LEVEL[bi] * 100),
                     "亮场-遮挡定位笔指标差": float(np.median(pm[SEL[bi]]) - np.median(pm[SEL[oi]])),
                     "替代": "是" if (bi in C.SUBST_MAIN or bi in PROVISIONAL) else ""})
R = pd.DataFrame(rows)
R["遮挡选帧影响%"] = (R["R_sum_遮挡全部候选帧"] / R["R_sum"] - 1) * 100
R["宽插值影响%"] = (R["R_sum_宽插值"] / R["R_sum"] - 1) * 100
R.to_csv(OUT / "dist_net_response.csv", index=False, encoding="utf-8-sig")
log("\n各点净响应：\n" + R.round(3).to_string(index=False))

# ---------------- 中心响应与幂律 ----------------
cen = []
for d in sorted(C.PAIRS):
    r1 = R[(R["距离"] == d) & (R["位置"] == "中心1")].iloc[0]
    r2 = R[(R["距离"] == d) & (R["位置"] == "中心2")].iloc[0]
    row = {"距离": d, "实测距离m": C.DIST_M[d]}
    for col in ["R_sum", "R_trapz", "R_400_640", "R_sum_宽插值"]:
        row[col] = (r1[col] + r2[col]) / 2
    row["中心1"] = r1["R_sum"]
    row["中心2"] = r2["R_sum"]
    row["中心重复差%"] = abs(r1["R_sum"] - r2["R_sum"]) / row["R_sum"] * 100
    cen.append(row)
cen = pd.DataFrame(cen)
cen["相对1.5m%"] = cen["R_sum"] / cen["R_sum"].iloc[0] * 100


def powerfit(r, y):
    X = np.log(r)
    Y = np.log(y)
    k, c = np.polyfit(X, Y, 1)
    pred = c + k * X
    r2 = 1 - ((Y - pred) ** 2).sum() / ((Y - Y.mean()) ** 2).sum()
    return -k, np.exp(c), r2, (y / np.exp(pred) - 1) * 100


n_, A_, r2_, dev_ = powerfit(cen["实测距离m"].values, cen["R_sum"].values)
cen["相对拟合偏差%"] = dev_
fits = {"R_sum": (n_, A_, r2_)}
for col in ["R_trapz", "R_400_640", "R_sum_宽插值"]:
    n2, A2, r22, _ = powerfit(cen["实测距离m"].values, cen[col].values)
    fits[col] = (n2, A2, r22)
m_no2 = cen["距离"] != 2.0
n3, A3, r23, _ = powerfit(cen["实测距离m"].values[m_no2], cen["R_sum"].values[m_no2])
fits["R_sum_不含2m"] = (n3, A3, r23)
log("\n中心响应：\n" + cen.round(3).to_string(index=False))
log("幂律拟合 R = A·r^(−n)：" + "；".join(f"{k}: n={v[0]:.4f}, R²={v[2]:.5f}" for k, v in fits.items()))
cen.to_csv(OUT / "dist_center.csv", index=False, encoding="utf-8-sig")

# ---------------- 横向归一化与均匀性 ----------------
POS = ["左40", "左20", "中心", "右20", "右40"]


def lateral(Rtab, col):
    out = {}
    for d in sorted(C.PAIRS):
        sub = Rtab[Rtab["距离"] == d].set_index("位置")[col]
        rc = (sub["中心1"] + sub["中心2"]) / 2
        out[d] = {"左40": sub["左40"] / rc, "左20": sub["左20"] / rc, "中心": 1.0, "右20": sub["右20"] / rc, "右40": sub["右40"] / rc}
    return pd.DataFrame(out).T[POS]


def side_cross(p20, p40, T_):
    if p40 >= T_:
        return np.inf
    if p20 >= T_:
        return 20 + 20 * (p20 - T_) / (p20 - p40)
    return 20 * (1 - T_) / (1 - p20)          # 阈值落在中心与 20 cm 之间


def uniformity(P):
    rows = []
    for d, p in P.iterrows():
        pl25 = p["左20"] + 0.25 * (p["左40"] - p["左20"])
        pr25 = p["右20"] + 0.25 * (p["右40"] - p["右20"])
        row = {"距离": d, "实测距离m": C.DIST_M[d], "±20最低%": min(p["左20"], p["右20"]) * 100,
               "±40最低%": min(p["左40"], p["右40"]) * 100, "±25估算最低%": min(pl25, pr25) * 100,
               "±20不对称%": abs(p["左20"] - p["右20"]) / ((p["左20"] + p["右20"]) / 2) * 100,
               "±40不对称%": abs(p["左40"] - p["右40"]) / ((p["左40"] + p["右40"]) / 2) * 100}
        for T_ in (0.8, 0.5):
            xl = side_cross(p["左20"], p["左40"], T_)
            xr = side_cross(p["右20"], p["右40"], T_)
            if np.isinf(xl) and np.isinf(xr):
                s = "> 80 cm"
            elif np.isinf(xl) or np.isinf(xr):
                s = f"> {40 + (xr if np.isinf(xl) else xl):.1f} cm"
            else:
                s = f"{xl + xr:.1f} cm"
            row[f"{int(T_ * 100)}%宽度"] = s
        rows.append(row)
    return pd.DataFrame(rows)


P = lateral(R, "R_sum")
U = uniformity(P)
U = U.merge(cen[["距离", "中心重复差%"]], on="距离")
log("\n横向归一化（R_sum）：\n" + (P * 100).round(1).to_string())
log("\n均匀性、宽度、不对称度：\n" + U.round(2).to_string(index=False))
P.to_csv(OUT / "dist_lateral.csv", encoding="utf-8-sig")
U.to_csv(OUT / "dist_uniformity.csv", index=False, encoding="utf-8-sig")

# 敏感性：不同波段定义/插值
P_sens = {}
for col in ["R_trapz", "R_400_640", "R_sum_宽插值", "R_sum_遮挡全部候选帧"]:
    P_sens[col] = lateral(R, col)
sens_rows = []
for col, Pp in P_sens.items():
    dmax = ((Pp - P) * 100).abs().max().max()
    sens_rows.append({"变体": col, "横向归一化最大差(百分点)": dmax})
sens_tab = pd.DataFrame(sens_rows)
log("\n横向归一化对处理方式的敏感性：\n" + sens_tab.round(3).to_string(index=False))

# ---------------- 替代遮挡敏感性 ----------------
sub_rows = []
for bi in sorted(set(C.SUBST_MAIN) | set(PROVISIONAL)):
    main_o = occl_for[bi]
    R0 = R_of(net(bi, main_o))
    for alt in SENS.get(bi, []):
        if alt in invalid_occl:
            sub_rows.append({"亮场": bi, "主分析遮挡": main_o, "对比遮挡": alt, "差异%": np.nan, "说明": "对比遮挡无可用帧"})
            continue
        R1 = R_of(net(bi, alt))
        sub_rows.append({"亮场": bi, "主分析遮挡": main_o, "对比遮挡": alt, "差异%": (R1 / R0 - 1) * 100,
                         "说明": "超过 1%" if abs(R1 / R0 - 1) * 100 > C.SUBST_FLAG_PCT else ""})
sub_tab = pd.DataFrame(sub_rows)
log("\n替代遮挡敏感性：\n" + sub_tab.round(3).to_string(index=False))
sub_tab.to_csv(OUT / "dist_substitution_sensitivity.csv", index=False, encoding="utf-8-sig")

# 70、71 用不同遮挡时的横向归一化
alt_P = {}
for alt in [74, 76, 78]:
    R2 = R.copy()
    for bi in (70, 71):
        R2.loc[R2["亮场段"] == bi, "R_sum"] = R_of(net(bi, alt))
    alt_P[alt] = lateral(R2, "R_sum").loc[2.0]
alt_P = pd.DataFrame(alt_P).T * 100
log("\n2 m 右20/右40 用不同遮挡时的横向归一化（%）：\n" + alt_P.round(2).to_string())

# ---------------- 2 m 复测、5 m 重复性（79） ----------------
rep = []
for bi in C.REPEATS_2M + [79]:
    oi = 74
    S = net(bi, oi)
    rep.append({"亮场段": bi, "记录": f"{seg.loc[bi, '设定距离m']} m {seg.loc[bi, '位置']}",
                "时间(北京)": (seg.loc[bi, "t0"] + BJ).strftime("%H:%M:%S"), "遮挡": oi, "R_sum": R_of(S),
                "亮场水平(420-700积分)": BRIGHT_LEVEL[bi]})
rep = pd.DataFrame(rep)
rep["相对69%"] = (rep["R_sum"] / rep["R_sum"].iloc[0] - 1) * 100
log("\n2 m 中心复测（均扣 74 遮挡）：\n" + rep.round(3).to_string(index=False))
R79_68 = R_of(net(79, 68))
R67 = R[(R["亮场段"] == 67)]["R_sum"].iloc[0]
lvl = {k: BRIGHT_LEVEL[k] for k in (61, 67, 69, 73, 79, 80)}
rep5 = {"R79_扣68": R79_68, "R67": R67, "79相对67%": (R79_68 / R67 - 1) * 100,
        "R79_扣62": R_of(net(79, 62)), "亮场水平": lvl,
        "79相对80亮场水平%": (BRIGHT_LEVEL[79] / BRIGHT_LEVEL[80] - 1) * 100}
log("5 m 中心补测（79）检查：" + json.dumps(rep5, ensure_ascii=False, default=float))

# 5 m 中心1：遮挡 62 偏高（部分漏光？）时的敏感性
R61 = {o: R_of(net(61, o)) for o in (62, 58, 64, 66, 68)}
R67m = R[R["亮场段"] == 67]["R_sum"].iloc[0]
c5 = {f"中心1扣{o}": v for o, v in R61.items()}
c5["中心重复差%_扣62"] = abs(R61[62] - R67m) / ((R61[62] + R67m) / 2) * 100
c5["中心重复差%_扣68"] = abs(R61[68] - R67m) / ((R61[68] + R67m) / 2) * 100
c5["中心重复差%_亮场水平"] = abs(BRIGHT_LEVEL[61] - BRIGHT_LEVEL[67]) / ((BRIGHT_LEVEL[61] + BRIGHT_LEVEL[67]) / 2) * 100
R5 = R.copy()
R5.loc[R5["亮场段"] == 61, "R_sum"] = R61[68]
P5_alt = lateral(R5, "R_sum").loc[5.0] * 100
c5["P_5m_中心1扣68"] = P5_alt.to_dict()
log("5 m 中心1 遮挡敏感性：" + json.dumps(c5, ensure_ascii=False, default=float))

# 2 m：中心响应取不同复测时的横向归一化
P2_alt = {}
r2m = {k: R_of(net(k, 74)) for k in (69, 73, 80)}
sub2 = R[R["距离"] == 2.0].set_index("位置")["R_sum"]
for name, rc in {"69与73平均（主）": (r2m[69] + r2m[73]) / 2, "69、73、80平均": np.mean(list(r2m.values())),
                 "仅69": r2m[69], "仅80": r2m[80]}.items():
    P2_alt[name] = {p: sub2[p] / rc * 100 for p in ["左40", "左20", "右20", "右40"]}
P2_alt = pd.DataFrame(P2_alt).T
log("\n2 m 横向归一化对中心取值的敏感性（%）：\n" + P2_alt.round(2).to_string())
rep.to_csv(OUT / "dist_repeat_2m.csv", index=False, encoding="utf-8-sig")

# ---------------- 光谱形状 ----------------
band_m = sum_m


def peaknorm(S):
    return S[band_m] / S[band_m].max()


shape_rows = []
for d in sorted(C.PAIRS):
    tmpl = (peaknorm(NET[(d, "中心1")]) + peaknorm(NET[(d, "中心2")])) / 2
    for pos in ["左40", "左20", "中心1", "中心2", "右20", "右40"]:
        s = peaknorm(NET[(d, pos)])
        cos = float(s @ tmpl / np.linalg.norm(s) / np.linalg.norm(tmpl))
        shape_rows.append({"距离": d, "位置": pos, "余弦相似度": cos,
                           "峰值波长nm": float(wl[band_m][np.argmax(NET[(d, pos)][band_m])])})
shape = pd.DataFrame(shape_rows)
tmpl15 = (peaknorm(NET[(1.5, "中心1")]) + peaknorm(NET[(1.5, "中心2")])) / 2
cross = {d: float(((peaknorm(NET[(d, "中心1")]) + peaknorm(NET[(d, "中心2")])) / 2) @ tmpl15 /
                  np.linalg.norm((peaknorm(NET[(d, "中心1")]) + peaknorm(NET[(d, "中心2")])) / 2) / np.linalg.norm(tmpl15))
         for d in sorted(C.PAIRS)}
log("\n谱形余弦相似度：最小 %.5f（%s）" % (shape["余弦相似度"].min(),
                                       shape.loc[shape["余弦相似度"].idxmin(), ["距离", "位置"]].tolist()))
log("各距离中心谱形 vs 1.5 m 中心谱形：" + json.dumps(cross))
shape.to_csv(OUT / "dist_spectral_shape.csv", index=False, encoding="utf-8-sig")

# ---------------- 定位笔核实 ----------------
pen_rows = []
for k in sorted(SEL):
    if len(SEL[k]) == 0:
        continue
    pen_rows.append({"段": k, "定位笔指标最小": float(pm[SEL[k]].min()), "中位": float(np.median(pm[SEL[k]]))})
pen_tab = pd.DataFrame(pen_rows)
pen_tab["笔开"] = pen_tab["定位笔指标最小"] > C.PEN_THRESHOLD
log(f"\n定位笔：{int(pen_tab['笔开'].sum())}/{len(pen_tab)} 个段所有使用帧均判为笔开；未全开的段："
    + str(pen_tab[~pen_tab['笔开']].to_dict('records')))

# ---------------- 图 ----------------
OLD = {"r": [1.507, 2.032, 3.016, 3.995, 5.013], "R": [1952252.5, 1179421.0, 563178.8, 326419.3, 207294.0], "n": 1.8706,
       "P": {1.507: [19.8, 24.7, 100, 49.3, 8.0], 2.032: [6.8, 55.7, 100, 57.1, 7.7], 3.016: [26.4, 75.5, 100, 74.2, 24.6],
             3.995: [58.9, 88.7, 100, 79.1, 38.8], 5.013: [73.4, 97.1, 100, 85.5, 54.4]}}
fig, ax = plt.subplots(1, 2, figsize=(11, 4.3))
r = cen["实测距离m"].values
y = cen["R_sum"].values
rr = np.linspace(1.4, 5.3, 100)
ax[0].loglog(r, y, "o", color="#d9452b", label=f"新灯（512 ms）n={n_:.3f}")
ax[0].loglog(rr, A_ * rr ** -n_, "-", color="#d9452b", lw=1)
ax[0].loglog(OLD["r"], OLD["R"], "s", color="#2a6fdb", label=f"旧灯（0.4 ms，旧探头）n={OLD['n']:.3f}")
ax[0].set_xlabel("距离 / m")
ax[0].set_ylabel("中心净响应 / DN·channel")
ax[0].set_title("中心净响应随距离衰减（绝对值不可直接比较）", fontsize=10)
ax[0].legend(fontsize=8)
ax[0].grid(alpha=0.3, which="both")
ax[1].plot(r, y / y[0] * 100, "o-", color="#d9452b", label="新灯")
ax[1].plot(OLD["r"], np.array(OLD["R"]) / OLD["R"][0] * 100, "s-", color="#2a6fdb", label="旧灯")
ax[1].plot(rr, (rr / 1.5) ** -2 * 100, ":", color="0.4", label="平方反比（1.5 m=100%）")
ax[1].set_xlabel("距离 / m")
ax[1].set_ylabel("相对 1.5 m / %")
ax[1].legend(fontsize=8)
ax[1].grid(alpha=0.3)
fig.tight_layout()
fig.savefig(FIG / "dist_attenuation.png")

xs = [-40, -20, 0, 20, 40]
fig, ax = plt.subplots(1, 2, figsize=(11, 4.3), sharey=True)
cmap = plt.get_cmap("viridis")
for j, d in enumerate(sorted(C.PAIRS)):
    ax[0].plot(xs, P.loc[d].values * 100, "o-", color=cmap(j / 4.5), label=f"{C.DIST_M[d]:.3f} m")
for j, (d, v) in enumerate(OLD["P"].items()):
    ax[1].plot(xs, v, "s-", color=cmap(j / 4.5), label=f"{d:.3f} m")
for a_, title in zip(ax, ["新灯 FL05（泛光）", "旧灯（窄角探照）"]):
    a_.axhline(80, color="r", ls="--", lw=0.8)
    a_.axhline(50, color="0.5", ls=":", lw=0.8)
    a_.axvspan(-25, 25, color="#f2c94c", alpha=0.15)
    a_.set_xticks(xs)
    a_.set_xticklabels(["左40", "左20", "中心", "右20", "右40"])
    a_.set_title(title, fontsize=10)
    a_.grid(alpha=0.3)
    a_.legend(fontsize=8)
ax[0].set_ylabel("相对同距离中心 / %")
fig.suptitle("横向归一化光斑剖面（黄色=±25 cm，红虚线=80%）", fontsize=10)
fig.tight_layout()
fig.savefig(FIG / "dist_lateral.png")

fig, ax = plt.subplots(1, 2, figsize=(11, 4.2))
k1, k2 = 7, 8
ax[0].plot(wl, med_spec(k1) - 1000, label="亮场中位谱（1.5 m 中心2）", lw=1)
ax[0].plot(wl, med_spec(k2) - 1000, label="遮挡中位谱", lw=1)
ax[0].plot(wl, NET[(1.5, "中心2")], label="净光谱", lw=1)
ax[0].set_xlim(380, 760)
ax[0].set_xlabel("波长 / nm")
ax[0].set_ylabel("DN（扣约 1000 偏置）")
ax[0].legend(fontsize=8)
ax[0].grid(alpha=0.3)
ax[0].set_title("亮场、遮挡与净光谱示例（655–672 nm 已插值）", fontsize=10)
for j, d in enumerate(sorted(C.PAIRS)):
    S = (NET[(d, "中心1")] + NET[(d, "中心2")]) / 2
    ax[1].plot(wl[band_m], S[band_m] / S[band_m].max(), color=cmap(j / 4.5), lw=1, label=f"{C.DIST_M[d]:.3f} m")
ax[1].set_xlabel("波长 / nm")
ax[1].set_ylabel("峰值归一化")
ax[1].legend(fontsize=8)
ax[1].grid(alpha=0.3)
ax[1].set_title("各距离中心净光谱形状", fontsize=10)
fig.tight_layout()
fig.savefig(FIG / "dist_spectra.png")

res = {"n_channels": int(sum_m.sum()), "wl_range": [float(wl[sum_m][0]), float(wl[sum_m][-1])],
       "center": cen.to_dict("records"), "fits": {k: list(v) for k, v in fits.items()},
       "P": {str(d): v for d, v in (P * 100).T.to_dict().items()}, "U": U.to_dict("records"),
       "sens": sens_tab.to_dict("records"), "subst": sub_tab.to_dict("records"),
       "alt_P_2m": {str(k): v for k, v in alt_P.T.to_dict().items()},
       "invalid_occl": invalid_occl, "few_occl": few_occl, "provisional": {str(k): v for k, v in PROVISIONAL.items()},
       "repeat2m": rep.to_dict("records"), "rep5": rep5, "c5": c5, "P2_alt": P2_alt.to_dict("index"), "shape_min": float(shape["余弦相似度"].min()),
       "shape_min_at": shape.loc[shape["余弦相似度"].idxmin(), ["距离", "位置"]].tolist(), "shape_cross": cross,
       "qa": qa.to_dict("records"), "R": R.to_dict("records"), "pen_all_on": bool(pen_tab["笔开"].all()),
       "occl_ratio_by_dist": R.groupby("距离")["遮挡占亮场%"].agg(["min", "max"]).to_dict("index")}
(OUT / "results_dist.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
(OUT / "dist_log.txt").write_text("\n".join(LOG), encoding="utf-8")
