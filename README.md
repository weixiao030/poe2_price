<p align="center">
  <h1 align="center">⚗️ POE2 物价补丁 v0.4.4</h1>
  <p align="center">为《Path of Exile 2》官服 / Steam 服 / 国服自动抓取物价、标注物品名，并可选添加岛屿传言提示的补丁工具</p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/平台-Windows%2010%2F11-blue?logo=windows" />
  <img src="https://img.shields.io/badge/.NET-8.x-purple?logo=dotnet" />
  <img src="https://img.shields.io/badge/Python-3.10%2B-yellow?logo=python" />
  <img src="https://img.shields.io/badge/许可-禁止商业使用-red" />
</p>

---

> ⚠️ **重要提示：** 本工具会修改游戏文件，和其他补丁一样**存在封号风险**。使用前请确认自己能接受风险，并在**关闭游戏后**再运行。

---

## 📌 当前版本说明

本补丁主要将通货和传奇装备价值显示在物品名上，项目已开源，可访问 GitHub 查看。

当前版本还是实验阶段，有 bug 请见谅。

实时物价指的是打入补丁那一刻的物价，刷新物价需要自己手动更新，也就是得重新打补丁。

英文客户端因为底层问题使用的话会影响到过滤器正常使用,其他客户端没影响.

---

### 26/6/27 更新

- 新增“岛屿传言提示”可选补丁：更新时勾选后，会在 `EndgameMaps.datc64` 的岛屿传言文本后追加目标地图提示，支持简中、繁中、英文、日文、韩文、俄文、法文、德文、西班牙文、葡萄牙文和泰文路径；前 5 个固定奖励岛屿会显示金币图、经验图、独特基底装备、传奇装备、首领战等类型，部分特殊传言会显示“地图 / Boss”。

- 发布版启动时新增补丁范围选择：可以选择“通货 + 传奇装备”“只打通货补丁”或“只打传奇装备补丁”；命令行也可用 `-PatchScope all|currency|uniques` 指定。

- 岛屿传言提示默认关闭；发布版可在弹窗里勾选，也可用 `-IslandRumourHints` 或环境变量 `POE2_PATCH_ISLAND_RUMOUR_HINTS=1` 开启。

- 还原包和真实 Bundles2 还原逻辑已兼容 `EndgameMaps.datc64`：生成岛屿提示前会尽量使用干净底板，真实还原时会恢复到安装本补丁前的 `LibGGPK3` 状态，避免旧增量文件残留。

- 发布链路修复：已同步 `build/payload`、`payload.zip`、`payload.enc` 和一键启动器，避免源码已有新功能但发布版内嵌脚本缺失。

---

## 后续开发计划
同步高价值底材如82卓越白装
更新国服传奇装备价格

---

### 26/6/25 更新

- 适配 `poecurrency.top` 新版 `summary?version=2` 数据结构：现在会识别 `currency_unit` 的 `e` / `d` 单位，`d` 单位会按当前“神圣石”实时汇率折算成 E 后再参与 D/E 显示。

- 如果国服接口后续直接提供 E 计价字段（如 `e` / `price_e`），会优先使用接口给出的 E 值，避免重复换算。

- 已检查国际服 poe2scout 接口，当前 `RelativePrice` / `ValueTraded` 等字段结构未变化，国际服价格逻辑保持兼容。

- 发布版稳定性修复：价格脚本已改用 Python 标准库联网，不再依赖 `requests/urllib3/certifi` 等第三方包；内置 .NET 运行时如果缺少 `System.Collections.dll` 等核心文件，会尝试自动修复。

- Bundles2 还原兼容旧包：旧版还原包缺少 `Words.datc64` 时不再直接报“缺少还原包”，会先还原 BaseItemTypes，并提示在游戏文件干净后重新更新以刷新新版还原包。

---

### 26/6/24 更新

- 进行大量的兼容，包括但不止于兼容A大补丁。
- 修复国服通货计算错误导致价格异常离谱的问题
- 当前国服物价策略为如果 poe2scout 国际服参考价 >= 10D，且国服折算价和国际服偏差超过 5x，就用国际服参考价替换。如果国服数据源缺少的数据将使用国际服代替。传奇装备全部数据都是国际服的数据


### 26/6/23 更新

- 国服数据源已切换为 `poecurrency.top` 优先：检测到国服 WeGame 时先抓取 `https://poecurrency.top/api/summary?version=2`，没有国服数据的普通物品和传奇装备再使用 poe2scout 国际服价格兜底；国际服仍继续直接使用 poe2scout。

- D/E 换算比例改为实时读取：国服从数据源里的“神圣石”当前价格推导，国际服从 poe2scout 实时价格推导，不写死固定比例。

- 国服取价优先使用最新盘口 `latest_buy1` / `latest_sell1`，缺失时才回退到 `buy_avg` / `sell_avg`；双边价差在 5 倍以内取几何均值，差距过大时取较低一侧，降低过期均价和 OCR 异常价影响。

- Bundles2 模式兼容先安装的功能/词缀补丁：更新物价时会保留当前游戏包里的资源底板，只清理并替换本工具写入的物价标记。`_.index.bin` 的更新时间会随写入变化，这是 PatchBundle3 更新索引的正常现象，不代表完整覆盖 `Tiny*.bundle.bin`。

### 26/6/20 更新

- 传奇装备无法查价问题已修复。已经兼容易刷/Overlay查价器，如果别的查价器有问题不兼容请留言。

- 新增传奇物品价格标注：会抓取饰品、防具、武器、珠宝、地图等七种分类等中排名靠前的传奇物品价格。

- 当前传奇物品抓取的市场物品的市场最低价，真实物品价值还得根据词条等多方位判断

- 优化价格显示：低于 1E 的物品不再标注；低于 0.1D 的价格改用 E 显示，避免出现 0.0xD 这种不直观的显示。

- 目前英文客户端因为底层问题使用的话会影响到过滤器正常使用,其他语言客户端没影响.

---

## 📸 效果预览

<p align="center">
  <img width="900" alt="效果图1" src="https://github.com/user-attachments/assets/fa84867b-a49e-43a9-8247-884cd320649c" />
  <br/>
  <img width="900" alt="效果图2" src="https://github.com/user-attachments/assets/3b31063d-1289-4fbf-94da-0e6f5345ec23" />
</p>

---

## ✨ 功能特点

- 🔍 **自动读取** 游戏 `Content.ggpk`（官服）或 `Bundles2`（Steam/Epic/国服）中的物品名表
- 💰 **联网抓取** 国际服 poe2scout / 国服 poecurrency.top 实时价格数据
- 🏷️ **自动标注** 将价格追加到物品名中，游戏内一目了然
- 🧭 **岛屿提示** 可选给岛屿传言追加对应地图提示，方便跑图时判断目标
- 🎛️ **范围选择** 可只更新通货、只更新传奇装备，或两者都更新
- ↩️ **一键还原** 随时恢复原版物品名，安全无残留
- 🎮 **三服支持** 兼容官服（GGPK 格式）、Steam/Epic 版（Bundles2 格式）和国服 WeGame（Bundles2 格式）
- 📦 **免环境** 发布版内置 .NET 8 + Python 3.10，且会检查运行时完整性，普通用户开箱即用

---

## 🚀 快速上手

### 1. 下载

前往 [GitHub Releases](../../releases) 下载 `POE2物价补丁-发布版.zip`

### 2. 安装

解压后将 `物价补丁` 文件夹放到 POE2 **游戏根目录**：

```text
<Path of Exile 2 游戏根目录>\
├── Content.ggpk          # 官服可能有此文件
├── Bundles2\             # Steam/Epic/国服可能有此目录
│   └── _.index.bin
└── 物价补丁\
    ├── 一键更新物价补丁.exe
    └── 一键还原物价补丁.exe
```

> 💡 **提示：** 工具会自动检测游戏版本（官服 GGPK、Steam/Epic Bundles2 或国服 WeGame Bundles2），无需手动选择。

### 3. 使用

1. **关闭游戏**
2. 双击 `一键更新物价补丁.exe`
3. 在弹窗中选择本次要写入的补丁范围；如需要岛屿传言提示，勾选“岛屿传言提示”
4. 等待程序自动抓取价格并写入游戏
5. *(可选)* 需要恢复原版时，双击 `一键还原物价补丁.exe`

---

## 🛠️ 开发者指南

### Vibe Coding 指南

本项目包含 `agent/` 目录，专为 AI 助手（如 Claude、ChatGPT）设计，帮助 AI 快速理解项目结构并协助开发。

**使用方法：**

1. **让 AI 阅读 `agent/index.md`** - 这是项目的主索引文档，包含：
   - 项目设计目的
   - 架构模块简介
   - 各模块的目录结构和功能说明

2. **AI 自动维护变更记录** - 每次对模块进行修改后，AI 会：
   - 在 `agent/<模块名>/` 目录下创建变更记录文件
   - 文件命名格式：`YYYY-MM-DD-变更摘要.md`

3. **快速上手开发** - 告诉 AI：
   ```
   请阅读 agent/index.md，帮我理解项目结构，然后协助我开发 <功能>
   ```

**目录结构：**
```text
agent/
├── index.md                    # 项目主索引（AI 首先阅读此文件）
└── 项目模块/                 # AI自主维护
```

> 💡 **提示：** `agent/` 目录由 AI 自主维护，开发者无需手动编辑。

### 构建要求

| 依赖 | 版本要求 |
|------|---------|
| 操作系统 | Windows 10/11 x64 |
| .NET SDK | 8.x |
| Python | 3.10+ |
| Python 包 | `python-docx` |

> 构建文档时需要 `python-docx`；发布包运行时价格脚本只依赖 Python 标准库。打包脚本会内置 .NET 8 与 Python 3.10，运行时发布版无需用户额外安装。

### 目录结构

```text
.
├── 物价补丁/
│   ├── tools/                      # PowerShell & Python 核心脚本
│   │   ├── GGPKExtractor/          # 从 Content.ggpk 提取数据的工具（官服）
│   │   └── BundleExtractor/        # 从 Bundles2 提取数据的工具（Steam/Epic/国服）
│   └── 一键安装特殊补丁工具/        # 把补丁写入游戏文件
│       ├── PatchBundledGGPK3.dll   # 官服补丁安装工具
│       └── PatchBundle3.exe        # Bundles2 补丁安装工具
└── build/
    ├── BundleExtractor/            # Bundles2 提取工具的 C# 源码
    ├── Poe2PatchLauncher/          # 一键更新/还原 exe 的 C# 启动器源码
    ├── PayloadPacker/              # 把脚本 payload 加密进启动器的工具
    ├── make_release.ps1            # 完整发布版打包脚本
    └── create_release_doc.py       # 生成 使用文档.docx 的脚本
```

### 打包发布版

```powershell
# 完整打包（含 Word 文档）
powershell -NoProfile -ExecutionPolicy Bypass -File .\build\make_release.ps1

# 跳过 Word 文档生成
powershell -NoProfile -ExecutionPolicy Bypass -File .\build\make_release.ps1 -SkipDoc
```

输出目录：

- 仓库内：`发布版\物价补丁`
- 工作区构建版：`三服合一物价补丁构建版\物价补丁`

### 调试参数

发布版 exe 支持透传参数：

```powershell
.\发布版\物价补丁\一键更新物价补丁.exe [参数]
```

| 参数 | 说明 |
|------|------|
| `-SkipExtract` | 跳过从游戏文件提取数据，使用已有缓存 |
| `-NoInstall` | 只生成补丁 zip，不写入游戏文件 |
| `-NoPoe2dbFallback` | 不请求 poe2db 兜底翻译 |
| `-PatchScope all` | 通货和传奇装备都打补丁，默认值 |
| `-PatchScope currency` | 只打通货 / 普通物品价格补丁，并清理旧传奇标价 |
| `-PatchScope uniques` | 只打传奇装备价格补丁，并保留干净 BaseItemTypes |
| `-IslandRumourHints` | 额外生成岛屿传言提示补丁 |
| `-Poe2Dir <路径>` | 手动指定游戏根目录（默认自动检测） |

---

## ⚖️ 使用许可

本项目**禁止**商业使用、收费分发、未经授权转载搬运和重新打包发布。

完整条款见 [使用许可.md](./使用许可.md)

---

## ⭐ Star 历史

<img width="1374" height="1098" alt="star-history-2026619" src="https://github.com/user-attachments/assets/e6361bd8-a214-40f1-b145-37f86e842d8e" />
