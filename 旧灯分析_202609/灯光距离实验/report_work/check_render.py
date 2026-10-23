from pathlib import Path
from pdf2image import convert_from_path
from PIL import Image, ImageOps, ImageDraw
import pdfplumber
b=Path(__file__).parent
out=b/'render'; out.mkdir(exist_ok=True)
pages=convert_from_path(str(b/'report.pdf'),dpi=100,poppler_path=r'C:/Users/haowei/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin',output_folder=str(out),fmt='png',paths_only=True,thread_count=4)
for i,path in enumerate(pages,1):
    p=Path(path); target=out/f'page-{i}.png'
    if p!=target: p.replace(target)
for start in range(0,len(pages),4):
    ims=[Image.open(out/f'page-{j+1}.png').convert('RGB') for j in range(start,min(start+4,len(pages)))]
    w,h=ims[0].size
    canvas=Image.new('RGB',(w*2,(h+28)*2),'#c6c6c6')
    draw=ImageDraw.Draw(canvas)
    for k,im in enumerate(ims):
        x=(k%2)*w;y=(k//2)*(h+28)
        draw.text((x+10,y+7),f'PAGE {start+k+1}',fill='black')
        canvas.paste(im,(x,y+28))
    canvas.save(out/f'sheet-{start//4+1}.png')
with pdfplumber.open(b/'report.pdf') as pdf:
    texts=[]
    for i,page in enumerate(pdf.pages,1):
        text=page.extract_text() or ''; texts.append(f'PAGE {i}\n{text}')
        print(i,len(text),text[:70].replace('\n',' / '))
    (b/'render_text.txt').write_text('\n\n'.join(texts),encoding='utf-8')
print('PAGES',len(pages))
