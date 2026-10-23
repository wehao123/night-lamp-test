from pathlib import Path
from docx import Document
from zipfile import ZipFile, ZIP_DEFLATED
from lxml import etree

base=Path(__file__).resolve().parent.parent
source=base/'室内分项实验综合报告_按立项报告整理.docx'
target=base/'室内分项实验综合报告_420–720nm修订版.docx'
old='报告以立项报告第8.2节规定的420–700 nm作为首期验收目标波段的对照范围。立项材料其他位置出现的420–720 nm及约415–739 nm作为扩展验证范围单列考虑；正式验收前应统一冻结口径。本报告不据扩展范围改变首期目标，也不将探头单侧的连续候选波段等同于水体与参考板共同有效波段。'
new='本项目正式目标波段统一为420–720 nm，室内性能评价、后续水体与参考板配对测量及样机验收均以该范围为准。既有冷启动实验的420–700 nm统计结果保留其实际计算范围，不能直接代表完整目标波段，700–720 nm的稳定性仍需补充评价。探头单侧的连续候选波段也不等同于水体与参考板共同有效波段。'
phrases=[('完整420–700 nm目标波段','完整420–720 nm目标波段'),('最低档仍未覆盖420–700 nm','最低档仍未覆盖420–720 nm'),('覆盖420–700 nm对照范围','覆盖420–720 nm目标范围'),('仍不足以覆盖420–700 nm','仍不足以覆盖420–720 nm')]
ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
count=0
with ZipFile(source) as zin, ZipFile(target,'w',ZIP_DEFLATED) as zout:
    for item in zin.infolist():
        data=zin.read(item.filename)
        if item.filename=='word/document.xml':
            root=etree.fromstring(data)
            for p in root.xpath('//w:body//w:p',namespaces=ns):
                nodes=p.xpath('.//w:t',namespaces=ns)
                text=''.join(n.text or '' for n in nodes)
                changed=text.replace(old,new)
                for a,b in phrases: changed=changed.replace(a,b)
                if changed!=text:
                    nodes[0].text=changed
                    for node in nodes[1:]: node.text=''
                    count+=1
            data=etree.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True)
        zout.writestr(item,data)
assert count==5,count
print('Updated paragraphs:',count)
print(target)
