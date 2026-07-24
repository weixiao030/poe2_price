from pathlib import Path
import shutil

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
PATCH_VERSION = "v0.4.9.7"
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
    doc = Document(TEMPLATE_DOC)
    replacements = {
        "POE2 三服合一物价补丁使用文档": (
            f"POE2 三服合一物价补丁使用文档 {PATCH_VERSION}"
        ),
        "程序会自动识别国服 WeGame、国际服官方 GGPK、国际服 Steam/Epic Bundles2。": (
            "更新和还原都会自动识别国服 WeGame、国际服官方 GGPK、国际服 Steam/Epic Bundles2，也可以手动选择游戏目录。"
        ),
        "把整个“物价补丁”文件夹放到 POE2 游戏根目录。脚本会自动识别上一级目录，不写死盘符。": (
            "“物价补丁”文件夹可以放在任意位置。放在游戏根目录下仍可最快识别；放在其它位置时，程序会检查最近目录和各平台游戏库，也可以手动浏览。"
        ),
        "二、自动识别": "二、选择与自动识别游戏目录",
        "检测到 Content.ggpk：按国际服官方 GGPK 处理。": (
            "自动模式依次检查补丁文件夹上一级、环境变量、最近有效目录、已安装程序、WeGame/Steam 游戏库、Epic 清单和常见位置。"
        ),
        "检测到 Bundles2 且有 WeGame/腾讯文件特征：按国服 WeGame Bundles2 处理。": (
            "国服会匹配“流放之路：降临”和 WeGameApps\\rail_apps 游戏库；目录还必须包含 Bundles2\\_.index.bin，并通过 WeGame/Rail/Tencent 特征确认。"
        ),
        "检测到 Bundles2 且没有 WeGame/腾讯文件特征：按国际服 Steam/Epic Bundles2 处理。": (
            "检测到 Content.ggpk 时按国际服官方 GGPK 处理；检测到非国服特征的 Bundles2 时按国际服 Steam/Epic 处理。"
        ),
        "国际服会读取当前游戏 language 设置，自动写入对应语言的 BaseItemTypes。": (
            "如果发现多个客户端，程序不会猜测，请切换到手动选择。确认后的有效目录会保存，更新与还原下次可复用。国际服仍会读取 language 设置。"
        ),
        "3. 程序会提取英文表和当前客户端目标语言表。": (
            "3. 在窗口中确认自动识别的路径和客户端类型，或切换到手动选择；更新器还需选择补丁范围。随后程序提取英文表和当前客户端目标语言表。"
        ),
        "2. 双击“一键还原物价补丁.exe”。": (
            "2. 双击“一键还原物价补丁.exe”，在还原窗口中确认自动识别的路径和客户端类型，或手动选择要还原的游戏目录。"
        ),
        "4. 程序会抓取 poe2scout 国际服价格，并把价格追加为“=数字D/E”。": (
            "4. 程序会按客户端类型抓取价格：国际服优先 poe2scout，国服优先 poecurrency.top；"
            "异常分类会自动降级，D/E 比例使用当前数据源实时值。"
            "同一个显示名对应多个游戏元数据路径时会为全部别名写入价格；国服翻译重名时使用 engname 英文别名消歧，避免漏价或串价。"
        ),
        "5. 程序会生成“物价补丁.zip”和“还原物价补丁.zip”。Bundles2 模式还会生成“真实还原物价补丁.zip”。": (
            "5. 程序会生成“物价补丁.zip”和“还原物价补丁.zip”。Bundles2 模式还会生成“真实还原物价补丁.zip”，"
            "并在游戏根目录的 .poe2-price-patch 文件夹保存持久副本。旧版备份丢失时，会先在临时沙盒清理并校验，成功前不修改真实游戏。"
        ),
        "6. 程序会把补丁写回对应游戏包。": (
            "6. 价格文件会先在隔离目录生成并校验；实时数据失败时仅使用当前范围和模式的兼容核心缓存。"
            "写入前复核游戏文件未被并发修改，写入后读回核对；失败会自动恢复。没有安全候选时只停止本次更新，不覆盖当前游戏。"
        ),
        "3. Bundles2 模式会使用“真实还原物价补丁.zip”恢复打补丁前的物理文件。": (
            "3. Bundles2 模式优先验证并使用“真实还原物价补丁.zip”，无需先准备 .NET；替换后核对精确文件集合，失败会恢复操作前状态。"
        ),
        "4. GGPK 模式会使用“还原物价补丁.zip”写回当前客户端对应的 BaseItemTypes。": (
            "4. GGPK 模式会使用“还原物价补丁.zip”写回当前语言目标，随后逐条读回校验；写入或校验失败会自动重试一次。"
        ),
        "5. 如果没有可用还原包，程序会拒绝做不完整还原。": (
            "5. 如果没有物理还原包，程序会验证逻辑还原包，并以当前 Bundles2 的 Words/EndgameMaps 为底板只清理本工具标记；没有安全兼容路径时才会拒绝还原。"
        ),
        "Bundles2 模式不覆盖完整 _.index.bin 或 Tiny*.bundle.bin。": (
            "Bundles2 模式会更新 _.index.bin 并向 LibGGPK3 写入增量内容，不会直接覆盖 Tiny*.bundle.bin。"
        ),
        "Bundles2 还原会恢复安装前备份的 _.index.bin 和 LibGGPK3 状态。": (
            "Bundles2 还原优先恢复安装前备份的 _.index.bin 和 LibGGPK3；迁移基线则恢复到语义上干净的物价层。"
        ),
        "真实还原物价补丁.zip：Bundles2 模式的物理级恢复包。": (
            "真实还原物价补丁.zip：Bundles2 模式的恢复包；持久副本位于 <游戏根目录>\\.poe2-price-patch。"
        ),
        r"tools\dotnet-runtime：内置 .NET 8 runtime，不要删除。": (
            r"tools\dotnet-runtime：内置 .NET 8.0.28 runtime，不要删除；发布包另含校验过的离线修复包，只有两者都不可用时才访问 Microsoft 备用源。"
        ),
        r"tools\python：内置 Python 和依赖，不要删除。": (
            r"tools\python：内置 Python 和依赖，不要删除；自动修复时依次尝试华为云、阿里云、南京大学镜像和 Python 官方备用源。"
        ),
        "提示找不到游戏目录：请确认物价补丁文件夹放在 POE2 游戏根目录。": (
            "提示找不到游戏目录：改用手动选择，并选择直接包含 Content.ggpk 或 Bundles2\\_.index.bin 的游戏根目录；不要选择物价补丁文件夹。多个客户端必须明确选择。若旧补丁有标记但备份丢失，新版会搜索旧文件夹并尝试离线沙盒迁移；失败时真实游戏不会被修改。"
        ),
        "提取或写入失败：请先关闭游戏和可能占用文件的工具。": (
            "提取或写入失败：程序会等待短暂占用并在写入失败时自动恢复；仍失败时请关闭游戏和可能占用文件的工具后重试。"
        ),
        "缺少价格：可能是 poe2scout 暂无该物品数据，或英文名无法匹配本地物品表。": (
            "缺少价格：可能是当前数据源暂无该物品，或名称无法匹配本地表。低匹配会保留未命中的旧价格；数据源完全不可用时保留当前补丁。"
        ),
    }
    matched: set[str] = set()
    title_key = "POE2 三服合一物价补丁使用文档"
    for paragraph in doc.paragraphs:
        original = paragraph.text.strip()
        if original == title_key or original.startswith(f"{title_key} v"):
            replacement = f"{title_key} {PATCH_VERSION}"
            matched.add(title_key)
        else:
            replacement = replacements.get(original)
        if replacement is None:
            continue
        if original != title_key and not original.startswith(f"{title_key} v"):
            matched.add(original)
        if paragraph.runs:
            paragraph.runs[0].text = replacement
            for run in paragraph.runs[1:]:
                run.text = ""
        else:
            paragraph.add_run(replacement)
    current_text = {paragraph.text.strip() for paragraph in doc.paragraphs}
    missing = sorted(
        original
        for original, replacement in replacements.items()
        if original not in matched and replacement not in current_text
    )
    if missing:
        raise RuntimeError(
            "release document template no longer contains expected paragraphs: "
            + " | ".join(missing)
        )

    # The WPS-authored template's contextualSpacing flag makes some
    # LibreOffice versions overlap consecutive list paragraphs after wrapping.
    list_style_ppr = doc.styles["List Bullet"]._element.get_or_add_pPr()
    for node in list_style_ppr.findall(qn("w:contextualSpacing")):
        list_style_ppr.remove(node)

    # Keep the compact path examples unchanged; only the long Bundles2 note
    # needs extra separation from the following bullet after it wraps.
    for paragraph in doc.paragraphs:
        if paragraph.style.name == "List Bullet":
            paragraph.paragraph_format.space_after = Pt(
                6 if paragraph.text.startswith("Bundles2 模式会更新") else 3
            )

    for section in doc.sections:
        for paragraph in section.footer.paragraphs:
            if paragraph.text.strip().startswith("POE2 三服合一物价补丁"):
                if paragraph.runs:
                    paragraph.runs[0].text = f"POE2 三服合一物价补丁 {PATCH_VERSION}"
                    for run in paragraph.runs[1:]:
                        run.text = ""
                else:
                    paragraph.add_run(f"POE2 三服合一物价补丁 {PATCH_VERSION}")

    generated = OUT_DIR / "使用文档.docx"
    doc.save(generated)
    targets = [*DOC_PATHS]
    for path in targets:
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(generated, path)
        print(path)
    print(generated)
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
    r = title.add_run(f"POE2 三服合一物价补丁使用文档 {PATCH_VERSION}")
    set_font(r)
    r.font.size = Pt(20)
    r.font.bold = True

    for line in [
        "重要提示：打补丁会修改游戏文件，存在封号或校验风险。",
        "请在关闭游戏后运行，并自行确认可以接受风险。",
        "更新和还原都会自动识别国服 WeGame、国际服官方 GGPK、国际服 Steam/Epic Bundles2，也可以手动选择游戏目录。",
    ]:
        para(doc, line, 14, True, (192, 0, 0), WD_ALIGN_PARAGRAPH.CENTER, 2, 1.0)

    para(doc, "一、发布版怎么放", 13, True, after=4)
    para(doc, "“物价补丁”文件夹可以放在任意位置。放在游戏根目录下仍可最快识别；放在其它位置时，程序会检查最近目录和各平台游戏库，也可以手动浏览。")
    bullets(
        doc,
        [
            r"<POE2游戏根目录>\Content.ggpk",
            r"<POE2游戏根目录>\Bundles2\_.index.bin",
            r"<POE2游戏根目录>\物价补丁\一键更新物价补丁.exe",
            r"<POE2游戏根目录>\物价补丁\一键还原物价补丁.exe",
        ],
    )

    para(doc, "二、选择与自动识别游戏目录", 13, True, after=4)
    bullets(
        doc,
        [
            "自动模式依次检查补丁文件夹上一级、环境变量、最近有效目录、已安装程序、WeGame/Steam 游戏库、Epic 清单和常见位置。",
            "国服会匹配“流放之路：降临”和 WeGameApps\\rail_apps 游戏库；目录还必须包含 Bundles2\\_.index.bin，并通过 WeGame/Rail/Tencent 特征确认。",
            "检测到 Content.ggpk 时按国际服官方 GGPK 处理；检测到非国服特征的 Bundles2 时按国际服 Steam/Epic 处理。",
            "如果发现多个客户端，程序不会猜测，请切换到手动选择。确认后的有效目录会保存，更新与还原下次可复用。国际服仍会读取 language 设置。",
        ],
    )

    para(doc, "三、一键更新", 13, True, after=4)
    nums(
        doc,
        [
            "关闭游戏。",
            "双击“一键更新物价补丁.exe”。",
            "在窗口中确认自动识别的路径和客户端类型，或切换到手动选择；更新器还需选择补丁范围。随后程序提取英文表和当前客户端目标语言表。",
            "程序会按客户端类型抓取价格：国际服使用 poe2scout，国服优先使用 poecurrency.top；没有国服数据时使用 poe2scout 兜底，并把价格追加为“=数字D/E”。",
            "D/E 换算比例会从当前价格源实时读取，不使用固定比例。",
            "国服优先使用 latest_buy1 / latest_sell1 最新盘口价，缺失时回退到 buy_avg / sell_avg；双边价差正常时取几何均值，差距过大时取较低一侧以降低过期均价和 OCR 异常价影响。",
            "同一个显示名对应多个游戏元数据路径时会为全部别名写入价格；国服翻译重名时使用 engname 英文别名消歧，避免漏价或串价。",
            "程序会生成“物价补丁.zip”和“还原物价补丁.zip”。Bundles2 模式还会生成“真实还原物价补丁.zip”，并在游戏根目录的 .poe2-price-patch 文件夹保存持久副本。",
            "Bundles2 模式会以当前游戏包为底板刷新物价；如果已经先安装功能/词缀补丁，会尽量保留这些补丁，只清理并替换本工具写入的物价标记。",
            "旧版已写入物价层但真实还原包丢失时，程序会先在临时沙盒清理旧物价层、写入沙盒索引并读回校验；成功前不会修改真实游戏。",
            "价格文件会先在隔离目录生成并校验；实时数据异常时自动尝试核心价格或当前范围和模式的兼容核心缓存。没有任何安全候选时只停止本次更新，不覆盖当前游戏。",
            "写入前会复核游戏文件未被并发修改，写入后读回目标数据核对；写入或校验失败时自动使用已验证还原包恢复。",
        ],
    )

    para(doc, "四、一键还原", 13, True, after=4)
    nums(
        doc,
        [
            "关闭游戏。",
            "双击“一键还原物价补丁.exe”，在还原窗口中确认自动识别的路径和客户端类型，或手动选择要还原的游戏目录。",
            "Bundles2 模式会优先验证并使用“真实还原物价补丁.zip”恢复打补丁前的物理文件，不要求先准备 .NET。",
            "GGPK 模式会使用“还原物价补丁.zip”写回当前客户端对应的 BaseItemTypes。",
            "如果没有物理还原包，程序会验证兼容的逻辑还原包；Bundles2 的 Words 和 EndgameMaps 会以当前游戏版本为底板只清理本工具标记。没有安全兼容路径时才会拒绝还原。",
            "还原写入后会读回目标数据校验；逻辑还原失败会自动重试一次，物理还原失败会恢复操作前状态。",
        ],
    )

    para(doc, "五、补丁范围", 13, True, after=4)
    bullets(
        doc,
        [
            "国服 WeGame：data/balance/simplified chinese/baseitemtypes.datc64。",
            "国际服官方 / Steam / Epic：按当前游戏语言写入，例如繁中为 data/balance/traditional chinese/baseitemtypes.datc64，英文为 data/balance/baseitemtypes.datc64。",
            "需要手动指定语言时，可设置 POE2_PATCH_LANGUAGE，例如 zh-TW、en、ja。",
            "Bundles2 模式会更新 _.index.bin 并写入 LibGGPK3 增量包；_.index.bin 更新时间变化是正常现象。",
            "Bundles2 模式不会直接覆盖 Tiny*.bundle.bin。",
            "Bundles2 还原优先恢复安装物价补丁前备份的 _.index.bin 和 LibGGPK3 状态；旧版本迁移生成的基线会恢复到清除本工具价格/岛屿标记且保留其它兼容补丁的状态。",
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
            "真实还原物价补丁.zip：Bundles2 模式的恢复包；持久副本位于 <游戏根目录>\\.poe2-price-patch。",
            r"tools\dotnet-runtime：内置 .NET 8.0.28 runtime，不要删除；发布包另含校验过的离线修复包，只有两者都不可用时才访问 Microsoft 备用源。",
            r"tools\python：内置 Python 和依赖，不要删除；自动修复时依次尝试华为云、阿里云、南京大学镜像和 Python 官方备用源。",
            "一键安装特殊补丁工具：底层写入工具目录，不要删除。",
        ],
    )

    para(doc, "七、常见问题", 13, True, after=4)
    bullets(
        doc,
        [
            "提示找不到游戏目录：改用手动选择，并选择直接包含 Content.ggpk 或 Bundles2\\_.index.bin 的游戏根目录；不要选择物价补丁文件夹。多个客户端必须明确选择。",
            "提取或写入失败：请先关闭游戏和可能占用文件的工具。",
            "提示当前 Bundles2 已含标记但找不到还原包：新版会自动搜索旧补丁文件夹和持久目录，并尝试离线沙盒迁移；若迁移失败，真实游戏不会被修改，请先用游戏平台验证或修复。",
            "缺少价格：可能是当前价格源暂无该物品数据，或物品名无法匹配本地物品表。",
            "价格源暂时不可用：程序会优先继续使用兼容缓存；如果没有安全缓存，会保留当前补丁并停止本次更新，可稍后重试。",
            "杀软报毒：自制 exe、加密脚本和修改游戏文件都可能触发敏感提示，需要自行判断风险。",
        ],
    )

    footer = sec.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fr = footer.add_run(f"POE2 三服合一物价补丁 {PATCH_VERSION}")
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
