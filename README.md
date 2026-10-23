# 夜间水质测量系统：照明灯室内测试

杆式夜间水体遥感反射率测量系统的照明灯测试数据、处理代码与报告。

- **新灯**：耀乾 FL05 泛光灯（50 W，DC 24 V），2026-10-22 室内测试，探头 IEP_O2N9DA。
- **旧灯**：窄角探照灯，2026-09 室内测试（旧分析代码与报告在 `旧灯分析_202609/`）。

## 报告

| 文件 | 内容 |
|---|---|
| `新灯FL05测试简报_20261022.docx` | 简报（3 页），给别人看用这份 |
| `新灯FL05室内实验报告_20261022_v2.docx` | 完整技术报告：方法、全部表格、数据质量 |
| `旧灯分析_202609/旧报告/` | 旧灯《室内分项实验报告》及精简版 |

## 目录

| 目录 | 内容 |
|---|---|
| `raw/` | 新灯原始数据：采集软件数据库只读副本 `2026-10-22_readonly_copy.db`（LFS）、操作记录 CSV、新探头 Lamp2501 定标文件、用于校验的 4 帧 CSV 导出 |
| `raw_old/` | 旧灯原始数据：`2026-09-11`（距离实验，探头 OCR 25F01830）、`2026-09-20`（冷启动，OCR 25F02100）数据库只读副本（LFS），OCR-25F02100 的 Lamp2501 定标文件 |
| `data/` | 从数据库导出的全段 CSV（DN、PHY，LFS）与逐帧索引 |
| `scripts/` | 处理代码，`config.py` 集中了所有剔除、替代、阈值设定 |
| `out/` | 结果表（CSV/JSON）、运行日志；`out/fig/` 为全部图 |
| `旧灯分析_202609/` | 旧灯实验的分析代码、说明与小结果表（`灯光距离实验/`、`光谱仪室内实验/`），以及旧报告 |

## 复现

需要 Python 3（numpy、pandas、matplotlib、python-docx）。克隆后先 `git lfs pull` 取回数据库和大 CSV，然后在本目录依次运行：

```bash
python scripts/01_extract_db.py    # 读数据库、与 CSV 校验、导出 data/
python scripts/02_cold_start.py    # 冷启动
python scripts/03_distance.py      # 距离与横向光斑
python scripts/04_snr.py           # 信噪比与水面外推
python scripts/06_lamp_compare.py  # 新旧灯辐亮度对比
python scripts/05_report.py        # 完整技术报告
python scripts/07_brief.py         # 简报
```

## 说明

- 数据库是采集软件（IES-SpecCheck）的 SQLite 文件，时间为 UTC；表结构见技术报告附录 B。
- 旧灯分析代码按原样收录，其中引用的路径指向原电脑上的位置，未作修改。
