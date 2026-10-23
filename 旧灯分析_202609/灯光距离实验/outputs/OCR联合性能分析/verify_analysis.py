"""用标准库独立复核分析产物；运行 python verify_analysis.py。"""
from pathlib import Path
import csv
import hashlib
import json
import math
import re
import statistics as st
import zipfile

ROOT = Path(__file__).resolve().parent


def table(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def raw(path):
    rows = list(csv.reader(x for x in path.read_text(encoding='utf-8-sig').splitlines()
                           if not x.startswith('#')))
    return {r[0]: list(map(float, r[2:])) for r in rows if r[0].startswith('CH_')}


def main():
    checks = []
    manifest = table(ROOT/'tables/01_input_manifest.csv')
    assert len(manifest) == 32
    for r in manifest:
        assert hashlib.sha256((ROOT/r['file']).read_bytes()).hexdigest() == r['sha256']
    checks.append('32个原始文件与清单SHA-256一致')
    channels = table(ROOT/'tables/03_per_channel_metrics.csv')
    assert len(channels) == 10*288
    # Different conditions and wavelength extremes, no reuse of analysis implementation.
    for v,t,ch in [(60,64,1),(60,128,100),(72,64,180),(76,32,288)]:
        p = ROOT/'raw/snr'/f'OCR-25F02100-1-DN_{v}V-{t}MS-亮值.csv'
        light=raw(p)[f'CH_{ch}']; dark=raw(p.with_name(p.name.replace('亮值','暗值')))[f'CH_{ch}']
        net=st.mean(light)-st.mean(dark); sd=st.stdev(light)
        r=next(x for x in channels if int(x['voltage_label_V'])==v and int(x['integration_ms'])==t and int(x['channel'])==ch)
        for field,expected in [('mean_net_DN',net),('light_temporal_sd_DN',sd),('SNR',net/sd),('CV_pct',100*sd/abs(net))]:
            assert math.isclose(float(r[field]),expected,rel_tol=1e-10,abs_tol=1e-8),(field,expected,r[field])
    checks.append('标准库statistics独立复核4个跨条件/波段样本的扣暗均值、标准差、SNR和CV通过')
    paired=table(ROOT/'tables/06_paired_linearity_channels.csv')
    assert len(paired)==5*288
    for r in paired[::71]:
        expected=100*((float(r['long_net_DN'])/float(r['long_ms']))/(float(r['short_net_DN'])/float(r['short_ms']))-1)
        assert math.isclose(expected,float(r['error_pct']),rel_tol=1e-10,abs_tol=1e-8)
    checks.append('成对积分时间偏差标量复核通过')
    # Correct time ratio must follow metadata, not misleading filenames.
    r=next(x for x in manifest if '64MS-5W-128' in x['file'])
    assert float(r['time_ms'])==62
    checks.append('62ms元数据异常已保留并采用实际时间')
    for extension in ['png','svg']:
        assert len(list((ROOT/'figures').glob('*.'+extension)))==15
    page=(ROOT/'分析报告.html').read_text(encoding='utf-8')
    imgs=re.findall(r'<img src="([^"]+)"',page)
    assert len(imgs)==15 and all((ROOT/p).exists() for p in imgs)
    checks.append('15组PNG/SVG齐全，HTML中15个图像引用均有效')
    with zipfile.ZipFile(ROOT/'OCR联合性能分析_代码与结果.zip') as z:
        assert z.testzip() is None
        assert 'analyze_ocr.py' in z.namelist()
        assert len([x for x in z.namelist() if x.startswith('raw/') and x.endswith('.csv')])==32
    checks.append('交付ZIP完整且含分析代码及32个原始CSV')
    result={'status':'passed','checks':checks}
    (ROOT/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
