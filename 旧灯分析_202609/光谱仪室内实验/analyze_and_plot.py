"""生成《OCR-25F02100_室内实验分析报告.md》配图。

运行方式：在本文件所在目录下执行
    python analyze_and_plot.py
输出：figures/01_*.png ~ 06_*.png，六张图，dpi=150。

依赖：numpy, matplotlib（与 parse.py 同目录）
"""
import os
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from parse import load_dn_csv

HERE = os.path.dirname(os.path.abspath(__file__))
LIN_DIR = os.path.join(HERE, '二代OCR模组线性度')
SNR_DIR = os.path.join(HERE, '信噪比')
FIG_DIR = os.path.join(HERE, 'figures')
os.makedirs(FIG_DIR, exist_ok=True)

OFFSET = 1000.0     # N 模式文档默认防下溢偏置
SNR_GATE = 20.0
DN_FS = 65535.0
DN_LIMIT_80 = 0.8 * DN_FS
DRIFT_LIMIT = 2.0

plt.rcParams.update({
    'figure.dpi': 150,
    'savefig.dpi': 150,
    'font.size': 10,
    'font.family': 'Microsoft YaHei',   # 支持中文；Windows 自带
    'axes.unicode_minus': False,        # 避免中文字体下负号显示异常
    'axes.grid': True,
    'grid.alpha': 0.25,
    'axes.axisbelow': True,
})

PAIR_COLOR = {32: '#2a78d6', 64: '#eb6834', 62: '#eb6834'}   # 按短积分时间上色
SHAPES = {3: 'o', 4: 's', 5: '^'}
BAND_DEFS = [(0, 400, '≤400nm', '#2a78d6'), (400, 480, '400-480nm', '#eb6834'),
             (480, 560, '480-560nm', '#1baf7a'), (560, 9999, '≥560nm', '#eda100')]
SEQ_BLUE = ['#9ec5f4', '#6da7ec', '#3987e5', '#1c5cab', '#0d366b']

# ---------------------------------------------------------------- 线性度部分

def load_pair(path):
    try:
        return load_dn_csv(path)
    except FileNotFoundError:
        return load_dn_csv(path.replace('MS', 'ms'))


def frame_snr(data, offset):
    net = data - offset
    mean = np.nanmean(net, axis=1)
    std = np.nanstd(net, axis=1, ddof=1)
    with np.errstate(divide='ignore', invalid='ignore'):
        snr = np.where(std > 0, mean / std, np.nan)
    return mean, snr


PAIRS = [
    ("OCR-25F02100-1-DN_32MS-{w}W-64.csv", "OCR-25F02100-1-DN_64MS-{w}W-64.csv"),
    ("OCR-25F02100-1-DN_64MS-{w}W-128.csv", "OCR-25F02100-1-DN_128MS-{w}W-128.csv"),
]


def analyse_linearity():
    groups = []
    for short_tpl, long_tpl in PAIRS:
        for w in (3, 4, 5):
            s = load_pair(os.path.join(LIN_DIR, short_tpl.format(w=w)))
            l = load_pair(os.path.join(LIN_DIR, long_tpl.format(w=w)))
            k = l['integration_ms'] / s['integration_ms']

            s_mean, s_snr = frame_snr(s['data'], OFFSET)
            l_mean, l_snr = frame_snr(l['data'], OFFSET)
            theory_long = s_mean * k
            with np.errstate(divide='ignore', invalid='ignore'):
                gamma = np.where(l_mean != 0, theory_long / l_mean, np.nan)
                delta = np.where(theory_long != 0, (l_mean - theory_long) / theory_long * 100.0, np.nan)
            gate = (s_mean > 0) & (l_mean > 0) & (s_snr >= SNR_GATE) & (l_snr >= SNR_GATE)

            groups.append({
                'label': f"{int(round(s['integration_ms']))}→{int(round(l['integration_ms']))}ms · {w}W",
                'short_ms': s['integration_ms'], 'w': w,
                'wavelength': s['wavelength'],
                'long_mean': l_mean, 'gamma': gamma, 'delta': delta, 'gate': gate,
            })
    return groups


DN_BINS = [(0, 4000), (4000, 8000), (8000, 15000), (15000, 25000),
           (25000, 35000), (35000, 45000), (45000, 55000)]


def bin_stats(groups):
    out = []
    for lo, hi in DN_BINS:
        vals = []
        for g in groups:
            m = g['gate'] & np.isfinite(g['delta']) & (g['long_mean'] >= lo) & (g['long_mean'] < hi)
            if m.any():
                vals.append(g['delta'][m])
        if vals:
            v = np.concatenate(vals)
            out.append((f"[{lo//1000}k,{hi//1000}k)", float(np.median(v)), float(np.percentile(np.abs(v), 95))))
        else:
            out.append((f"[{lo//1000}k,{hi//1000}k)", np.nan, np.nan))
    return out


def fig01_linearity_scatter(groups):
    fig, ax = plt.subplots(figsize=(8, 5.5))
    for g in groups:
        m = g['gate'] & np.isfinite(g['gamma'])
        color = PAIR_COLOR[round(g['short_ms'])]
        ax.scatter(g['long_mean'][m], g['gamma'][m], s=14, alpha=0.65,
                   c=color, marker=SHAPES[g['w']], label=g['label'], linewidths=0)
    xmax = max(g['long_mean'][g['gate']].max() for g in groups if g['gate'].any())
    ax.axhline(1.0, color='#666', ls='--', lw=1.2, zorder=0)
    ax.set_xlim(0, xmax * 1.03)
    ax.set_ylim(0.9, 1.15)
    ax.set_xlabel('长积分实测净光码值 NDN')
    ax.set_ylabel('γ = 理论 / 实测')
    ax.set_title('图1　六组倍频对比：γ 随码值的变化')
    ax.legend(fontsize=8, ncol=2, loc='upper left')
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, '01_linearity_scatter.png'))
    plt.close(fig)


def fig02_delta_by_bin(groups):
    bins = bin_stats(groups)
    labels = [b[0] for b in bins]
    medians = [b[1] for b in bins]
    p95 = [b[2] for b in bins]
    x = np.arange(len(labels))

    fig, ax1 = plt.subplots(figsize=(8, 5))
    ax1.bar(x, p95, width=0.55, color='#2a78d6', alpha=0.75, label='|δ| 95分位')
    ax1.set_ylabel('|δ| 95分位 (%)')
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=20)
    ax2 = ax1.twinx()
    ax2.plot(x, medians, color='#eb6834', marker='o', lw=2, label='δ 中位数')
    ax2.axhline(0, color='#999', lw=0.8)
    ax2.set_ylabel('δ 中位数 (%)')
    lines1, labs1 = ax1.get_legend_handles_labels()
    lines2, labs2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labs1 + labs2, loc='upper right', fontsize=9)
    ax1.set_title('图2　按码值分段的偏差统计')
    ax1.grid(axis='y', alpha=0.25)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, '02_delta_by_bin.png'))
    plt.close(fig)


def fig03_band_split(groups):
    fig, ax = plt.subplots(figsize=(8, 5.5))
    for lo, hi, label, color in BAND_DEFS:
        xs, ys = [], []
        for g in groups:
            m = g['gate'] & np.isfinite(g['gamma']) & (g['wavelength'] >= lo) & (g['wavelength'] < hi)
            xs.append(g['long_mean'][m]); ys.append(g['gamma'][m])
        xs, ys = np.concatenate(xs), np.concatenate(ys)
        ax.scatter(xs, ys, s=12, alpha=0.55, c=color, label=label, linewidths=0)
    xmax = max(g['long_mean'][g['gate']].max() for g in groups if g['gate'].any())
    ax.axhline(1.0, color='#666', ls='--', lw=1.2, zorder=0)
    ax.set_xlim(0, xmax * 1.03)
    ax.set_ylim(0.95, 1.08)
    ax.set_xlabel('长积分实测净光码值 NDN')
    ax.set_ylabel('γ')
    ax.set_title('图3　不同波段的 γ–码值分布')
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, '03_band_split.png'))
    plt.close(fig)


# ---------------------------------------------------------------- 信噪比部分

def fit_drift(signal, elapsed):
    n = signal.shape[1]
    tau = elapsed[:n]
    span = tau[-1] - tau[0]
    tc = tau - tau.mean()
    denom = np.sum(tc ** 2)
    mean = np.nanmean(signal, axis=1)
    k = np.nansum((signal - mean[:, None]) * tc[None, :], axis=1) / denom if denom > 0 else np.zeros(signal.shape[0])
    with np.errstate(divide='ignore', invalid='ignore'):
        dfit = np.where(mean != 0, k * span / np.abs(mean) * 100.0, np.nan)
    return dfit


def analyse_snr():
    combos = []
    for bf in sorted(f for f in os.listdir(SNR_DIR) if '亮值' in f):
        df = bf.replace('亮值', '暗值')
        tail = bf.replace('.csv', '').split('_')[-1]
        tag, ms_tag, _ = tail.split('-')
        voltage = int(tag.replace('V', ''))

        b = load_dn_csv(os.path.join(SNR_DIR, bf))
        d = load_dn_csv(os.path.join(SNR_DIR, df))
        wl = b['wavelength']
        dark_mean = np.nanmean(d['data'], axis=1)
        signal = b['data'] - dark_mean[:, None]
        s_mean = np.nanmean(signal, axis=1)
        s_std = np.nanstd(signal, axis=1, ddof=1)
        with np.errstate(divide='ignore', invalid='ignore'):
            snr = np.where(s_std > 0, s_mean / s_std, np.nan)
            cv = np.where(s_mean != 0, s_std / np.abs(s_mean) * 100.0, np.nan)

        # 满量程判据要用扣除固定偏置(1000 DN)后的真实光信号，不能直接拿含偏置的导出值比
        raw_max = np.nanmax(b['data'], axis=1) - OFFSET
        over_80 = raw_max > DN_LIMIT_80
        dfit = fit_drift(signal, b['elapsed_s'])
        drift_over = np.abs(dfit) > DRIFT_LIMIT
        positive = s_mean > 0
        basic = positive & (snr >= 20) & (cv <= 5)
        work = basic & ~over_80 & ~drift_over

        combos.append({
            'voltage': voltage, 'integration_ms': round(b['integration_ms'], 1),
            'wavelength': wl, 'signal_mean': s_mean, 'snr': snr, 'cv': cv, 'work': work,
        })
    combos.sort(key=lambda c: (c['voltage'], c['integration_ms']))
    return combos


def voltage_color(combos, v):
    vs = sorted(set(c['voltage'] for c in combos))
    i = vs.index(v)
    return SEQ_BLUE[round(i / (len(vs) - 1) * (len(SEQ_BLUE) - 1))]


def fig_spectral(combos, field, thresholds, ylabel, title, fname, unit='', logy=True):
    fig, ax = plt.subplots(figsize=(8.5, 5.7))
    by_v = {}
    for c in combos:
        by_v.setdefault(c['voltage'], []).append(c)
    for arr in by_v.values():
        arr.sort(key=lambda c: c['integration_ms'])

    for c in combos:
        sib = by_v[c['voltage']]
        is_long = len(sib) > 1 and c['integration_ms'] == sib[-1]['integration_ms']
        vals = c[field]
        m = np.isfinite(vals) & (vals > 0)
        ax.plot(c['wavelength'][m], vals[m], color=voltage_color(combos, c['voltage']),
                ls='--' if is_long else '-', lw=1.4,
                label=f"{c['voltage']}V·{c['integration_ms']:.0f}ms")
    ax.axhline(thresholds[0], color='#d03b3b', ls=':', lw=1.2, label=f'判据 {thresholds[0]}{unit}')
    ax.axhline(thresholds[1], color='#888', ls=':', lw=1.2, label=f'推荐 {thresholds[1]}{unit}')
    if logy:
        ax.set_yscale('log')
    ax.set_xlabel('波长 (nm)')
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend(fontsize=7.5, ncol=3, loc='best')
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, fname))
    plt.close(fig)


def fig06_lowlight_scaling(combos):
    pts = []
    for c in combos:
        if c['integration_ms'] != 64:
            continue
        wl = c['wavelength']
        mid = (wl >= 500) & (wl <= 800) & (c['signal_mean'] > 0)
        s = np.median(c['signal_mean'][mid])
        n = np.median(c['snr'][mid])
        pts.append((c['voltage'], s, n))
    pts.sort()
    s_arr = np.array([p[1] for p in pts])
    n_arr = np.array([p[2] for p in pts])
    a, b = np.polyfit(np.log(s_arr), np.log(n_arr), 1)

    fig, ax = plt.subplots(figsize=(6.8, 5.8))
    s20 = np.exp((np.log(20) - b) / a)

    # 实测范围内用实线（内插），实测范围外用虚线（外推）——两者是同一条拟合线，
    # 只是线型不同，避免读者把外推段误当成已验证的实测结果
    x_meas = np.geomspace(s_arr.min(), s_arr.max(), 60)
    x_extrap = np.geomspace(s20 / 2, s_arr.min(), 60)
    ax.plot(x_meas, np.exp(b) * x_meas ** a, color='#eb6834', ls='-', lw=2, zorder=2,
            label=f'拟合线（实测范围内）SNR ∝ 信号^{a:.3f}')
    ax.plot(x_extrap, np.exp(b) * x_extrap ** a, color='#eb6834', ls='--', lw=1.5, zorder=2,
            label='同一拟合线的外推段（未经实测验证）')
    ax.axvspan(s_arr.min(), s_arr.max(), color='#2a78d6', alpha=0.06, zorder=0, label='实测范围')

    ax.scatter(s_arr, n_arr, s=55, color='#2a78d6', zorder=3, label='实测点（固定64ms）')
    for v, s, n in pts:
        ax.annotate(f'{v}V', (s, n), textcoords='offset points', xytext=(6, 4), fontsize=9)

    ax.axhline(20, color='#d03b3b', ls=':', lw=1.2, label='判据 SNR=20')
    ax.axvline(s20, color='#999', ls=':', lw=1)
    ax.set_xscale('log'); ax.set_yscale('log')
    ax.set_xlabel('中段(500-800nm)信号中位 DN')
    ax.set_ylabel('中段信噪比中位')
    ax.set_title('图6　弱光标度关系与外推')
    ax.legend(fontsize=8, loc='lower right')
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, '06_lowlight_scaling.png'))
    plt.close(fig)
    print(f"拟合: SNR ∝ 信号^{a:.3f}；外推 SNR=20 对应信号 {s20:.0f} DN，"
          f"最暗档(60V)信号 {s_arr[0]:.0f} DN，余量 {s_arr[0]/s20:.1f} 倍")


if __name__ == '__main__':
    print('生成线性度相关图...')
    groups = analyse_linearity()
    fig01_linearity_scatter(groups)
    fig02_delta_by_bin(groups)
    fig03_band_split(groups)

    print('生成信噪比/弱光相关图...')
    combos = analyse_snr()
    fig_spectral(combos, 'snr', (20, 50), 'SNR(λ)', '图4　10 个条件的逐波长信噪比', '04_snr_curves.png', unit='')
    fig_spectral(combos, 'cv', (5, 2), 'CV(λ) %', '图5　10 个条件的逐波长变异系数', '05_cv_curves.png', unit='%')
    fig06_lowlight_scaling(combos)

    print(f'\n完成，图片输出至: {FIG_DIR}')
