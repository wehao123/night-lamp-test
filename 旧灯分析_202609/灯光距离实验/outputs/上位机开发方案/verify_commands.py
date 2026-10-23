from pathlib import Path
import pypdfium2 as pdfium
p=next(Path(r'C:\Users\haowei\Desktop\夜间水质资料\夜间水质资料').glob('*LH*.pdf'))
doc=pdfium.PdfDocument(p)
doc[28].render(scale=1.3).to_pil().save('outputs/上位机开发方案/资料摘录/relay-29.png')
def crc(b):
 c=65535
 for x in b:
  c ^= x
  for _ in range(8): c=(c>>1)^0xA001 if c&1 else c>>1
 return c.to_bytes(2,'little')
frames=['FE 05 00 00 FF 00 98 35','FE 05 00 00 00 00 D9 C5','FE 05 00 01 FF 00 C9 F5','FE 05 00 01 00 00 88 05','FE 01 00 00 00 02 A9 C4','02 03 00 00 00 09 85 FF','28 03 20 01 00 01 D9 F3','28 03 20 02 00 02 69 F2']
for f in frames:
 b=bytes.fromhex(f); print(f,crc(b[:-2])==b[-2:])
for f in ['02 03 00 53 00 02','02 03 00 00 00 02','02 03 00 04 00 05']:
 b=bytes.fromhex(f);print('Derived', (b+crc(b)).hex(' ').upper())
