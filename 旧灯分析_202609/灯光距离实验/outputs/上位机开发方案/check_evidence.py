from pathlib import Path
import pypdfium2 as pdfium, sqlite3, json
base=Path(r'C:\Users\haowei\Desktop\夜间水质资料\夜间水质资料')
out=Path('outputs/上位机开发方案/资料摘录')
for pattern,pages,label in [('ZH*.pdf',[5,6,7],'meter'),('*LH*.pdf',[14,15,27],'relay')]:
 p=next(base.glob(pattern)); doc=pdfium.PdfDocument(p)
 for page in pages:
  doc[page].render(scale=1.3).to_pil().save(out/f'{label}-{page+1}.png')
for p in (base/'标定上位机V3/标定上位机V3/data').glob('*.db'):
 con=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True)
 tables=[r[0] for r in con.execute("select name from sqlite_master where type='table'")]
 print(p.name,tables)
 if 'probes' in tables: print(con.execute('select * from probes limit 10').fetchall())
 con.close()

