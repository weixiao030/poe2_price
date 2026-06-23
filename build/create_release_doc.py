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
TEMPLATE_DOC = ROOT / "docs" / "使用文档.docx"


def copy_template_doc() -> bool:
    if not TEMPLATE_DOC.exists():
        return False

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    targets = [OUT_DIR / "使用文档.docx", *DOC_PATHS]
    for path in targets:
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(TEMPLATE_DOC, path)
        print(path)
    return True


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
    if copy_template_doc():
        return

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
    r = title.add_run("POE2 三服合一物价补丁使用文档")
    set_font(r)
    r.font.size = Pt(20)
    r.font.bold = True

    for line in [
        "重要提示：打补丁会修改游戏文件，存在封号或校验风险。",
        "请在关闭游戏后运行，并自行确认可以接受风险。",
        "程序会自动识别国服 WeGame、国际服官方 GGPK、国际服 Steam/Epic Bundles2。",
    ]:
        para(doc, line, 14, True, (192, 0, 0), WD_ALIGN_PARAGRAPH.CENTER, 2, 1.0)

    para(doc, "一、发布版怎么放", 13, True, after=4)
    para(doc, "把整个“物价补丁”文件夹放到 POE2 游戏根目录。脚本会自动识别上一级目录，不写死盘符。")
    bullets(
        doc,
        [
            r"<POE2游戏根目录>\Content.ggpk",
            r"<POE2游戏根目录>\Bundles2\_.index.bin",
            r"<POE2游戏根目录>\物价补丁\一键更新物价补丁.exe",
            r"<POE2游戏根目录>\物价补丁\一键还原物价补丁.exe",
        ],
    )

    para(doc, "二、自动识别", 13, True, after=4)
    bullets(
        doc,
        [
            "检测到 Content.ggpk：按国际服官方 GGPK 处理。",
            "检测到 Bundles2 且有 WeGame/腾讯文件特征：按国服 WeGame Bundles2 处理。",
            "检测到 Bundles2 且没有 WeGame/腾讯文件特征：按国际服 Steam/Epic Bundles2 处理。",
            "国际服会读取当前游戏 language 设置，自动写入对应语言的 BaseItemTypes。",
        ],
    )

    para(doc, "三、一键更新", 13, True, after=4)
    nums(
        doc,
        [
            "关闭游戏。",
            "双击“一键更新物价补丁.exe”。",
            "程序会提取英文表和当前客户端目标语言表。",
            "程序会按客户端类型抓取价格：国际服使用 poe2scout，国服使用 poecurrency.top，并把价格追加为“=数字D/E”。",
            "D/E 换算比例会从当前价格源实时读取，不使用固定比例。",
            "国服 buy_avg / sell_avg 差距正常时取几何均值，差距过大时取较低一侧以降低 OCR 异常价影响。",
            "程序会生成“物价补丁.zip”和“还原物价补丁.zip”。Bundles2 模式还会生成“真实还原物价补丁.zip”。",
            "程序会把补丁写回对应游戏包。",
        ],
    )

    para(doc, "四、一键还原", 13, True, after=4)
    nums(
        doc,
        [
            "关闭游戏。",
            "双击“一键还原物价补丁.exe”。",
            "Bundles2 模式会使用“真实还原物价补丁.zip”恢复打补丁前的物理文件。",
            "GGPK 模式会使用“还原物价补丁.zip”写回当前客户端对应的 BaseItemTypes。",
            "如果没有可用还原包，程序会拒绝做不完整还原。",
        ],
    )

    para(doc, "五、补丁范围", 13, True, after=4)
    bullets(
        doc,
        [
            "国服 WeGame：data/balance/simplified chinese/baseitemtypes.datc64。",
            "国际服官方 / Steam / Epic：按当前游戏语言写入，例如繁中为 data/balance/traditional chinese/baseitemtypes.datc64，英文为 data/balance/baseitemtypes.datc64。",
            "需要手动指定语言时，可设置 POE2_PATCH_LANGUAGE，例如 zh-TW、en、ja。",
            "Bundles2 模式不覆盖完整 _.index.bin 或 Tiny*.bundle.bin。",
            "Bundles2 还原会恢复安装前备份的 _.index.bin 和 LibGGPK3 状态。",
            "如果其他补丁没有改同一个 BaseItemTypes 资源，通常不会被本工具影响。",
            "如果其他补丁也改了同一个 BaseItemTypes 资源，最后写入者会覆盖同资源内对应字段。",
        ],
    )

    para(doc, "六、文件说明", 13, True, after=4)
    bullets(
        doc,
        [
            "一键更新物价补丁.exe：抓价、生成补丁并写入游戏包。",
            "一键还原物价补丁.exe：还原对应 BaseItemTypes。",
            "物价补丁.zip：运行时生成的当前物价补丁包。",
            "还原物价补丁.zip：运行时生成或保存的恢复包。",
            "真实还原物价补丁.zip：Bundles2 模式的物理级恢复包。",
            r"tools\dotnet-runtime：内置 .NET 8 runtime，不要删除。",
            r"tools\python：内置 Python 和依赖，不要删除。",
            "一键安装特殊补丁工具：底层写入工具目录，不要删除。",
        ],
    )

    para(doc, "七、常见问题", 13, True, after=4)
    bullets(
        doc,
        [
            "提示找不到游戏目录：请确认物价补丁文件夹放在 POE2 游戏根目录。",
            "提取或写入失败：请先关闭游戏和可能占用文件的工具。",
            "缺少价格：可能是当前价格源暂无该物品数据，或物品名无法匹配本地物品表。",
            "杀软报毒：自制 exe、加密脚本和修改游戏文件都可能触发敏感提示，需要自行判断风险。",
        ],
    )

    footer = sec.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fr = footer.add_run("POE2 三服合一物价补丁")
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
