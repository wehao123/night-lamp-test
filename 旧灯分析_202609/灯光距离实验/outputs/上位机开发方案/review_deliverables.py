from pathlib import Path
import re,struct
root=Path('outputs/上位机开发方案')
for p in root.glob('0*.md'):
 s=p.read_text(encoding='utf-8')
 print(p.name, 'characters',len(s),'code_fences',s.count('```'),'headings',len(re.findall(r'^#+ ',s,re.M)))
 assert s.count('```')%2==0
 assert '\ufffd' not in s
print('OCR DN struct size:',struct.calcsize('<4s3s4scB3xI288H'))
print('OCR PHY struct size:',struct.calcsize('<4s3s4sB4x288f'))
source=Path(r'C:\Users\haowei\Desktop\夜间水质资料\夜间水质资料\标定上位机V3\标定上位机V3\doc\sensor\OCR协议.md').read_text(encoding='utf-8')
for block in re.findall(r'```\s*\n(.*?)```',source,re.S):
 t=block.strip()
 if re.fullmatch(r'(?:[0-9A-Fa-f]{2}\s+)*[0-9A-Fa-f]{2}',t) and len(t)>500:
  b=bytes.fromhex(t)
  print('OCR example length',len(b),'checksum',sum(b[:-3])&255==b[-3],'tail',b[-2:].hex())
