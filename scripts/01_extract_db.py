"""第 1 步：从采集软件数据库（只读副本）读出光谱，与已有 CSV 导出逐帧校验，再导出全段存档 CSV。

用法： python -I scripts/01_extract_db.py
输出： data/IEP-IEP_O2N9DA-2-DN_full_20261022.csv   （与采集软件 DN 导出同结构）
       data/IEP-IEP_O2N9DA-2-PHY_full_20261022.csv
       data/frames_index.csv                        （每帧一行：时间、积分时间、模式）
       out/db_check.txt                             （库结构与校验结果）
"""
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "raw" / "2026-10-22_readonly_copy.db"
# raw/ 下所有采集软件导出的 CSV 都参与校验（例如补来的 1162 帧文件，放进 raw/ 即可）
CHECK_CSVS = [("DN", p) for p in sorted((ROOT / "raw").glob("IEP-IEP_O2N9DA-2-DN_*.csv"))] + \
             [("PHY", p) for p in sorted((ROOT / "raw").glob("IEP-IEP_O2N9DA-2-PHY_*.csv"))]
SERIAL = "IEP_O2N9DA"
T_START, T_END = "2026-10-22T12:40:00", "2026-10-22T15:59:59.999"  # UTC

(ROOT / "data").mkdir(exist_ok=True)
(ROOT / "out").mkdir(exist_ok=True)
log_lines = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    log_lines.append(s)


con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)

log("== 数据库表结构 ==")
for name, sql in con.execute("select name, sql from sqlite_master where type='table'"):
    n = con.execute(f'select count(*) from "{name}"').fetchone()[0]
    log(f"-- {name}  ({n} 行)")
    log(sql)

probes = pd.read_sql("select * from probes", con)
log("\nprobes:\n" + probes.to_string())
cal = pd.read_sql("select calibration_id, probe_id, calibration_date, calibration_paths, info, "
                  "start_index, dn_num, physical_quantity, unit, is_active from calibrations", con)
log("\ncalibrations:\n" + cal.to_string())

probe_id = int(probes.loc[probes.serial_number == SERIAL, "probe_id"].iloc[0])

q = """
select c.capture_id, c.timestamp, c.probe_id, d.calibration_id, d.integration_time_ms,
       d.dn_capture_mode, d.dn_values, p.phy_values
from captures c
join spectra_dn d on d.spectra_dn_id = c.spectra_dn_id
left join spectra_phy p on p.spectra_phy_id = c.spectra_phy_id
where c.probe_id = ?
order by c.timestamp
"""
rows = pd.read_sql(q, con, params=(probe_id,))
log(f"\n探头 {SERIAL} 全部帧数: {len(rows)}；时间 {rows.timestamp.min()} – {rows.timestamp.max()}")
log("各积分时间/模式帧数:\n" + rows.groupby(["calibration_id", "integration_time_ms", "dn_capture_mode"])
    .size().to_string())

wl_json = con.execute("select wavelengths from calibrations where calibration_id=2").fetchone()[0]
wl = json.loads(wl_json)
chans = sorted(int(k) for k in wl)
wavel = np.array([wl[str(k)] for k in chans])


def parse(js):
    # 库里 PHY 用 NaN 字面量，json 模块可直接解析
    d = json.loads(js)
    return np.array([d[str(k)] for k in chans], dtype=float)


dn = np.vstack([parse(s) for s in rows.dn_values])
phy = np.vstack([parse(s) if s is not None else np.full(len(chans), np.nan) for s in rows.phy_values])
ts = pd.to_datetime(rows.timestamp, utc=True)

# ---------- 用已有 CSV 校验 ----------
log("\n== 与 CSV 导出逐帧校验 ==")
ok_all = True
for kind, path in CHECK_CSVS:
    if not path.exists():
        log(f"{kind}: 缺少 {path.name}，跳过")
        continue
    c = pd.read_csv(path, comment="#", encoding="utf-8-sig")
    frame_cols = list(c.columns[2:])
    c_ts = pd.to_datetime(frame_cols, utc=True)
    c_it = c.iloc[0, 2:].astype(float).values
    c_mode = c.iloc[1, 2:].values
    c_val = c.iloc[2:, 2:].astype(float).values.T  # 帧 × 通道
    c_wl = c.iloc[2:, 1].astype(float).values
    idx = [int(np.where(ts == t)[0][0]) if (ts == t).any() else -1 for t in c_ts]
    missing = sum(i < 0 for i in idx)
    db_val = (dn if kind == "DN" else phy)[[i for i in idx if i >= 0]]
    same_wl = np.allclose(c_wl, wavel, rtol=0, atol=1e-9)
    same_it = np.array_equal(c_it, rows.integration_time_ms.values[[i for i in idx if i >= 0]])
    same_mode = (kind == "PHY") or np.array_equal(c_mode, rows.dn_capture_mode.values[[i for i in idx if i >= 0]])
    if kind == "DN":
        same_val = np.array_equal(c_val, db_val)
        maxdiff = np.nanmax(np.abs(c_val - db_val))
    else:
        both_nan = np.isnan(c_val) & np.isnan(db_val)
        same_val = bool(np.all(both_nan | np.isclose(c_val, db_val, rtol=1e-9, atol=0)))
        maxdiff = np.nanmax(np.abs(c_val - db_val))
    ok = missing == 0 and same_wl and same_it and same_mode and same_val
    ok_all &= ok
    log(f"{kind} {path.name}: CSV {len(frame_cols)} 帧，时间 {frame_cols[0]} – {frame_cols[-1]}；库中缺 {missing} 帧；"
        f"波长一致={same_wl}；积分时间一致={same_it}；模式一致={same_mode}；数值完全一致={same_val}（最大差 {maxdiff}）"
        f" → {'通过' if ok else '不通过'}")
if not ok_all:
    (ROOT / "out" / "db_check.txt").write_text("\n".join(log_lines), encoding="utf-8")
    sys.exit("数据库读取与 CSV 不一致，停止。")

# ---------- 选时段并导出 ----------
sel = (ts >= pd.Timestamp(T_START, tz="UTC")) & (ts <= pd.Timestamp(T_END, tz="UTC"))
log(f"\n== 导出 UTC {T_START} – {T_END} ==  帧数 {sel.sum()}")
log("其中各积分时间/模式帧数:\n" + rows[sel.values].groupby(["integration_time_ms", "dn_capture_mode"]).size().to_string())

dts = ts[sel].diff().dt.total_seconds().values[1:]
gap_idx = np.where(dts > 10)[0]
log("相邻帧间隔 > 10 s 的空档（北京时间）:")
for g in gap_idx:
    a, b = ts[sel].iloc[g], ts[sel].iloc[g + 1]
    log(f"  {(a + pd.Timedelta(hours=8)).strftime('%H:%M:%S.%f')[:-3]} → "
        f"{(b + pd.Timedelta(hours=8)).strftime('%H:%M:%S.%f')[:-3]}  （{(b - a).total_seconds():.1f} s）")


def write_csv(kind, values, path):
    cols = [t.isoformat(timespec="microseconds") for t in ts[sel]]
    header = (f"# FileType: {kind}_Data\n# ProbeType: IEP\n# SerialNumber: {SERIAL}\n# CalibrationID: 2\n"
              f"# ExportTimestamp: from {DB.name} (sqlite, read-only) by 01_extract_db.py\n#\n")
    body = pd.DataFrame(values[sel.values].T, columns=cols)
    body.insert(0, "Wavelength_nm", wavel)
    body.insert(0, "ItemName", [f"CH_{k}" for k in chans])
    it_row = ["IntegrationTime_ms", ""] + list(rows.integration_time_ms.values[sel.values])
    md_row = ["CaptureMode", ""] + list(rows.dn_capture_mode.values[sel.values])
    top = pd.DataFrame([it_row, md_row], columns=body.columns)
    if kind == "DN":
        body[cols] = body[cols].astype(int)
    out = pd.concat([top, body], ignore_index=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(header)
        out.to_csv(f, index=False)


write_csv("DN", dn, ROOT / "data" / "IEP-IEP_O2N9DA-2-DN_full_20261022.csv")
write_csv("PHY", phy, ROOT / "data" / "IEP-IEP_O2N9DA-2-PHY_full_20261022.csv")
pd.DataFrame({
    "utc": [t.isoformat(timespec="microseconds") for t in ts[sel]],
    "beijing": [(t + pd.Timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] for t in ts[sel]],
    "integration_time_ms": rows.integration_time_ms.values[sel.values],
    "mode": rows.dn_capture_mode.values[sel.values],
}).to_csv(ROOT / "data" / "frames_index.csv", index=False, encoding="utf-8-sig")
(ROOT / "out" / "db_check.txt").write_text("\n".join(log_lines), encoding="utf-8")
log("已写出 data/ 下存档 CSV。")
