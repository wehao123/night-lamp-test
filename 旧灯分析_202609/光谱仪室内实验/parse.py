"""OCR 光谱仪 DN 导出 CSV 的通用解析器。"""
import numpy as np
from datetime import datetime


def load_dn_csv(path):
    """解析一个 OCR 光谱仪 DN 导出 CSV。

    返回 dict:
      wavelength     (n_channels,)          各通道中心波长 nm
      integration_ms float                  文件内实际记录的积分时间
      capture_mode   str                    'N' 去暗码值 / 'L' 亮值 / 'D' 暗值
      data           (n_channels, n_frames) 原始导出码值
      elapsed_s      (n_frames,)            相对第一帧的经过时间，来自列时间戳
      n_frames       int
    """
    with open(path, 'r', encoding='utf-8-sig') as f:
        lines = f.readlines()

    header_idx = next(i for i, line in enumerate(lines) if line.startswith('ItemName,'))

    header = lines[header_idx].rstrip('\n').split(',')
    stamps = [datetime.fromisoformat(s.strip()) for s in header[2:] if s.strip()]

    it_row = lines[header_idx + 1].rstrip('\n').split(',')
    integration_ms = float(it_row[2])

    cm_row = lines[header_idx + 2].rstrip('\n').split(',')
    capture_mode = cm_row[2].strip()

    wavelengths, data_rows = [], []
    for line in lines[header_idx + 3:]:
        line = line.strip()
        if not line or not line.startswith('CH_'):
            continue
        parts = line.split(',')
        wavelengths.append(float(parts[1]))
        # 空单元格保留为 NaN 占位，不能直接丢弃——丢弃会导致该行后续帧
        # 相对列头时间戳整体错位（如果空值出现在中间而非末尾）
        data_rows.append([float(x) if x != '' else np.nan for x in parts[2:]])

    max_len = max(len(r) for r in data_rows)
    data = np.full((len(data_rows), max_len), np.nan)
    for i, r in enumerate(data_rows):
        data[i, :len(r)] = r

    t0 = stamps[0]
    elapsed_s = np.array([(s - t0).total_seconds() for s in stamps[:max_len]])

    return {
        'wavelength': np.array(wavelengths),
        'integration_ms': integration_ms,
        'capture_mode': capture_mode,
        'data': data,
        'elapsed_s': elapsed_s,
        'n_frames': max_len,
    }
