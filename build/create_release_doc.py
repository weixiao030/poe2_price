from pathlib import Path
import shutil

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
DOC_PATHS = [
    ROOT / "物价补丁" / "使用文档.docx",
    ROOT / "发布版" / "物价补丁" / "使用文档.docx",
]
OUT_DIR = ROOT / "output" / "doc"


def set_font(run, name="Microsoft YaHei"):
    run.font.name = name
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), name)


def para(doc, text="", size=11, bold=False, color=None, align=None, after=6, line=1.2):
    p = doc.add_paragraph()
    if align is not None:
        p.alignment = align
    p.paragraph_format.space_after = Pt(after)
    p.paragraph_format.line_spacing = line
    r = p.add_run(text)
    set_font(r)
    r.font.size = Pt(size)
    r.font.bold = bold
    if color:
        r.font.color.rgb = RGBColor(*color)
    return p


def bullets(doc, items):
    for item in items:
        p = doc.add_paragraph(style="List Bullet")
        p.paragraph_format.space_after = Pt(3)
        p.paragraph_format.line_spacing = 1.15
        r = p.add_run(item)
        set_font(r)
        r.font.size = Pt(11)


def nums(doc, items):
    for i, item in enumerate(items, 1):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.line_spacing = 1.15
        r = p.add_run(f"{i}. {item}")
        set_font(r)
        r.font.size = Pt(11)


def build():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    doc = Document()
    sec = doc.sections[0]
    sec.top_margin = Inches(0.75)
    sec.bottom_margin = Inches(0.75)
    sec.left_margin = Inches(0.85)
    sec.right_margin = Inches(0.85)

    normal = doc.styles["Normal"]
    normal.font.name = "Microsoft YaHei"
    normal.font.size = Pt(11)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = title.add_run("POE2 物价补丁使用文档")
    set_font(r)
    r.font.size = Pt(20)
    r.font.bold = True

    for line in [
        "温馨提示：打补丁=修改游戏文件=有被封号的风险！！！",
        "打补丁=修改游戏文件=有被封号的风险！！！",
        "打补丁=修改游戏文件=有被封号的风险！！！",
        "重要的事情说三遍。",
    ]:
        para(doc, line, 18, True, (192, 0, 0), WD_ALIGN_PARAGRAPH.CENTER, 2, 1.0)

    para(doc, "一、发布版怎么放", 13, True, after=4)
    para(doc, "把整个“物价补丁”文件夹放到游戏根目录，和 Content.ggpk 同级。脚本会自动识别上一级目录，不写死盘符。")
    bullets(
        doc,
        [
            "D:\\poe2\\Content.ggpk",
            "D:\\poe2\\物价补丁\\一键更新物价补丁.exe",
            "D:\\poe2\\物价补丁\\一键还原物价补丁.exe",
        ],
    )

    para(doc, "二、一键更新", 13, True, after=4)
    nums(
        doc,
        [
            "关闭游戏。",
            "双击“一键更新物价补丁.exe”。",
            "程序会直接使用发布版内置的 .NET 8 运行时和 Python 3.10，不再下载运行环境。",
            "如果发布包缺文件，程序会直接提示“发布包不完整”。",
            "程序会导出最新物品名表，抓取 poe2scout 价格，生成并打入 物价补丁.zip。",
        ],
    )

    para(doc, "三、一键还原", 13, True, after=4)
    nums(
        doc,
        [
            "关闭游戏。",
            "双击“一键还原物价补丁.exe”。",
            "程序会使用 还原物价补丁.zip，把原版 baseitemtypes.datc64 打回 Content.ggpk。",
        ],
    )

    para(doc, "四、发布版文件说明", 13, True, after=4)
    bullets(
        doc,
        [
            "一键更新物价补丁.exe：生成最新价格并自动打补丁。",
            "一键还原物价补丁.exe：还原原版物品名。",
            "物价补丁.zip：当前生成的物价补丁包。",
            "还原物价补丁.zip：用于恢复的补丁包。",
            "tools\\dotnet-runtime：内置 .NET 8 运行时，不要删除。",
            "tools\\python：内置 Python 3.10 运行时和依赖，不要删除。",
            "tools：运行时工具目录，不要删除。",
            "一键安装特殊补丁工具：底层打入 Content.ggpk 的工具目录，不要删除。",
        ],
    )

    para(doc, "五、关于代码封装", 13, True, after=4)
    para(doc, "发布版不再放 bat，也不直接暴露 ps1/py 明文脚本。脚本代码已加密封装在 exe 内，运行时临时解密执行，结束后自动清理。")
    para(doc, "这不是安全承诺，只是防止普通用户误删、误改脚本。真正使用前仍然要确认上面的封号风险。")

    para(doc, "六、常见问题", 13, True, after=4)
    bullets(
        doc,
        [
            "导出失败：通常是游戏还在运行，关闭游戏后再运行。",
            "缺少价格：可能是 poe2scout 暂无数据，或游戏里存在同名不同路径条目。",
            "运行时报毒：自制 exe、加密脚本和修改游戏文件都可能触发杀软敏感提示，需要用户自行判断风险。",
        ],
    )

    footer = sec.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fr = footer.add_run("POE2 物价补丁发布版")
    set_font(fr)
    fr.font.size = Pt(9)
    fr.font.color.rgb = RGBColor(128, 128, 128)

    temp = OUT_DIR / "使用文档.docx"
    if temp.exists():
        temp.unlink()
    doc.save(temp)
    for path in DOC_PATHS:
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(temp, path)
        print(path)


if __name__ == "__main__":
    build()
