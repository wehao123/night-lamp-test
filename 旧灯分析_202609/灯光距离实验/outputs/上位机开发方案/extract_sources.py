from pathlib import Path
from pypdf import PdfReader
import zipfile, xml.etree.ElementTree as ET
base=Path(r'C:\Users\haowei\Desktop\夜间水质资料\夜间水质资料')
out=Path('outputs/上位机开发方案/资料摘录')
for p in base.rglob('*.pdf'):
 if 'cal' in p.parts: continue
 reader=PdfReader(p)
 text='\n'.join(f'\n--- PAGE {i+1} ---\n'+(page.extract_text() or '') for i,page in enumerate(reader.pages))
 (out/(p.stem+'.txt')).write_text(text,encoding='utf-8')
 print(p.name,len(reader.pages),len(text))
for p in [base/'现场设备系统联调与操作配置说明书_V1.0.docx',Path(r'C:\Users\haowei\Documents\WXWork\1688857512881647\Cache\File\2026-08\杆式夜间水体遥感反射率测量系统-立项报告-0826-v5.docx')]:
 with zipfile.ZipFile(p) as z: root=ET.fromstring(z.read('word/document.xml'))
 ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main','m':'http://schemas.openxmlformats.org/officeDocument/2006/math'}
 lines=[''.join(n.text or '' for n in para.iter() if n.tag in ('{'+ns['w']+'}t','{'+ns['m']+'}t')) for para in root.findall('.//w:p',ns)]
 (out/(p.stem+'.txt')).write_text('\n'.join(lines),encoding='utf-8')
