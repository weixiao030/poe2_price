<p align="center">
  <h1 align="center">⚗️ POE1/2 物价补丁 v0.5.7</h1>
  <p align="center">为《Path of Exile 1/2》官服、Steam 服和国服自动抓取物价、标注物品名的补丁工具</p>
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

`v0.5.7` 重做 POE1/POE2 还原底板：每个游戏目录按游戏代数、客户端类型和语言保存专属基线，POE2 官方 GGPK、Steam/Epic 与国服不会再互相覆盖同名还原包。连续更新只复用已经验证的干净基线；旧共享包仅作为只读迁移输入。专属包丢失或游戏版本变化时，程序会先在临时目录只清除本工具能确认的价格/岛屿标记并严格读回，无法证明安全时才要求平台修复。

`v0.5.6` 将 POE1、POE2 的传奇价格标签统一为 `传奇名[<<价格>>]`。旧版 `[价格|传奇名]` 会被当前易刷整行删除，导致传奇名为空并按底材误选其它传奇；新格式在易刷和 PoE Overlay II 中都会还原为精确传奇名，同时保留旧格式、旧 Overlay 格式和独立行格式的迁移清理能力。

`v0.5.5` 修复 POE1/POE2 国服与国际服 Bundles2 客户端在官方更新或连续刷新物价后，把本工具上次成功写入误报为“文件数量/SHA256 并发变化”的问题。成功写入并读回后会持久记录安装现场，重复更新可安全复用干净还原包；旧状态或平台更新则在离线沙盒中刷新还原基线，最终写入前仍会复核本次现场，真正的平台并发更新不会被放行。POE1 同时修复逻辑还原包 manifest 写入异常和 Windows 8.3 短路径误判。

---

---

## 后续开发计划
待定

---

## 更新日志

完整更新记录见 [更新日志.md](更新日志.md)。

### 26/8/12 更新（v0.5.7）

- POE2 逻辑/物理还原包改为 `POE2 + InstallKind + 语言` 独立命名，输出目录再按游戏绝对路径哈希隔离；游戏根目录的 `.poe2-price-patch` 是唯一权威副本。修复官方 GGPK 与 Steam/Epic 共用 `国际服还原补丁.zip`，后运行的客户端覆盖前者底板并导致还原被拒绝的问题。

- POE1 逻辑还原 manifest 升级到 v2，强制核对客户端类型、GGPK/Bundles2 模式、目标语言、资源路径、结构签名及每个条目的长度/SHA256；POE1/POE2 旧包只读校验后迁移，不再写回共享通用文件名。

- 当游戏已经打过本工具补丁但专属基线丢失或过期时，更新器和还原器都会在临时目录清除可确认的 BaseItemTypes、Words 与 EndgameMaps 标记，验证结构和零残留后再建立基线。清理模式不访问价格网络；只有 DAT 损坏、结构无法解析、存在未知改动或平台并发写入时才拒绝并提示修复。

- 新增跨客户端作用域、防篡改、重复更新不覆盖基线和真实 GGPK 自愈验证；连续更新两次以上仍使用第一次验证的干净底板，还原不会回到第二次补丁状态。

### 26/8/12 更新（v0.5.6）

- POE1、POE2 的传奇装备默认统一使用 `传奇名[<<价格>>]`，例如 `冈姆的壮志[<<0.25D>>]`、`三龙战纪[<<1.00E>>]`。易刷会删除行尾方括号标记，PoE Overlay II 会展开方括号后删除双尖括号标记，两者最终都使用精确传奇名查询。

- 修复旧版 `[价格|传奇名]` 被当前易刷清理成空名称后，按底材候选回退并误查其它传奇的问题；旧标记仍可被更新和还原流程识别、清理并迁移到新格式。

- 新增 POE1/POE2 默认模式、低价 `<1` 标记、易刷及 PoE Overlay II 清理规则回归测试，并同步发布载荷与统一启动器。

### 26/8/11 更新（v0.5.5）

- 修复 POE1/POE2 国服与国际服 Bundles2 客户端连续更新时误报并发变化；成功写入并读回后记录与真实还原包绑定的现场指纹，旧版本状态或平台更新则在不修改真实游戏的离线沙盒中刷新干净还原基线。

- POE1 逻辑还原写入前会剥离校验 manifest，仅向 `PatchBundle3` 传入 BaseItemTypes/Words；同时统一 Windows 8.3 短路径和长路径，避免临时目录中误报 `_.index.bin` 不存在。

- 当前 POE1 国服 WeGame、POE1 国际服 Steam 与 POE2 国服 WeGame 均已使用真实 `PatchBundle3 v2.7.5` 在隔离副本中连续写入两次并逐次读回，真实游戏目录完整指纹前后不变。

### 26/8/10 更新（v0.5.4）

- 修复 POE1 Steam Bundles2 更新器先提取繁中 DAT、再单独提取英文 DAT 时重复加载数百万条索引的问题；现在以当前游戏 DAT 为底板，将必需英文表和本地化表一次批量提取，对短暂文件占用有限重试。游戏更新会覆盖补丁，但不再依赖固定赛季资源，更新完成并关闭游戏后重新点击更新即可重建并安装。

- 统一 GUI 在选择 POE1 国际服后新增“一键汉化POE1国际服”。每次点击都会从 [PoEDB 中文化说明](https://poedb.tw/cn/chinese) 指向的 [LibGGPK3 最新 Release](https://github.com/aianlinb/LibGGPK3/releases/latest) 下载 `PoeChinese3_win-x64.exe`，元数据与程序均按国内加速源 `ghfast.top`、`gh-proxy.com`、GitHub 官方源的顺序尝试；执行前校验 PE、产品信息、版本号，并将文件 SHA256 与最新 Release 公布值逐字节比对，不会复用旧下载文件。

- 汉化完成后请在 POE1 选择第二个（法文）国旗；程序会尝试写入 `production_Config.ini` 的 `language=fr`。此功能仅支持 POE1 国际服 Steam/Epic Bundles2 和官方 GGPK，修改游戏文件仍有校验、封号和启动风险。

### 26/8/4 更新（v0.5.3）

- 自动识别新增 GGG 官服注册表安装目录，支持从 `HKCU\Software\GrindingGearGames\Path of Exile 2\InstallLocation` 找到 `D:\poe2` 等非默认 GGPK 路径；POE1 官服使用相同规则。

- 候选仍会校验目录实际包含 `Content.ggpk` 或 `Bundles2\_.index.bin`，无效或残留注册表路径会被忽略；补充 POE1/POE2 首次运行回归测试并重新生成统一启动器。

### 26/8/4 更新（v0.5.2）

- POE1 国际服从单一 poe.ninja 主数据升级为 `poe.ninja → poe2scout → PoEDB` 逐物品补缺；POE1 国服使用 `poecurrency.top → poe.ninja → poe2scout → PoEDB`，国服已有价格不会被国际服来源覆盖。

- 新接入 poe2scout 的 POE1 `pc` realm，使用 `BaseItemTypeId` 精确匹配 DAT 元数据路径；PoEDB 使用 `/us/Economy` 国际服价格和 `/cn/Economy` 简中名称，并按 Chaos/Divine 换算，不混入 `/tw/Economy` 台湾服价格。

- poe.ninja 新增 Runegrafts、Djinn Coins、Ducats、Enshrouding Crystals、Astrolabes、Invitations、Vials 等可安全映射分类；变体决定价格的分类继续排除。2026-08-04 最终真实客户端验证快照中，Steam 基础价格覆盖为 829 条，国服为 840 条；覆盖数会随赛季市场数据和各来源当前可用条目变化。

### 26/8/4 更新（v0.5.1）

- 修复 POE1 Steam 客户端配置为法语等非中文语言、但第三方汉化补丁实际显示繁中资源时，价格被写入原配置语言表而游戏内不可见的问题。

- GUI 新增“POE1 显示语言”：支持自动识别、汉化补丁、简体中文、繁体中文、跟随游戏配置，并将选择保存到 `%LOCALAPPDATA%\PoePricePatch\settings.json`。

- 自动模式下国服固定简中；国际服配置已是中文时直接使用，非中文时检查最新客户端日志中的区域名，检测到中文区域则写入繁中表。`POE1_PATCH_LANGUAGE` 仅在自动模式下继续兼容。

- POE1 缓存、逻辑还原包和 Bundles2 物理还原包按实际写入语言隔离；更新与还原显式传递同一语言模式，并兼容查找旧版物理还原包文件名。
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
- 🎮 **双版本 GUI** 统一选择 POE1、POE2 或自动识别，POE1 与 POE2 的输出、缓存和还原包彼此隔离
- 🌐 **汉化兼容** POE1 可自动识别第三方汉化补丁，也可固定简中/繁中或严格跟随 `production_Config.ini`
- 💰 **POE1 多源价格** 国际服按 poe.ninja → poe2scout → PoEDB 补缺；国服按 poecurrency.top v1 → poe.ninja → poe2scout → PoEDB 补缺
- 🛟 **独立降级** 各来源并行抓取并独立失败，后续来源只补空缺；POE2 继续使用原有 poe2scout、poe.ninja、PoEDB / poecurrency.top v2 链路
- 📡 **实时进度** 抓价、重试、分类分页、匹配和生成补丁包都会在窗口中显示进度
- 🏷️ **自动标注** 将价格追加到物品名中；POE1、POE2 传奇统一使用 `传奇名[<<价格>>]`，兼容易刷与 PoE Overlay II 精确查价
- 🧭 **岛屿提示** 可选给岛屿传言追加对应地图提示，方便跑图时判断目标
- 🎛️ **范围选择** 可只更新通货、只更新传奇装备，或两者都更新
- 📁 **目录选择** 更新与还原均支持自动识别、最近目录复用和手动浏览
- ▶️ **统一入口** 运行 `物价补丁.exe`，在 GUI 底部点击“开始/更新物价补丁”或“还原物价补丁”
- 🎮 **三服支持** POE1/POE2 均兼容官服（GGPK 格式）、Steam/Epic 版（Bundles2 格式）和国服 WeGame（Bundles2 格式）
- 📦 **免环境** 发布版内置 .NET 8 + Python 3.13.14，且会检查运行时完整性，普通用户开箱即用

---

## 🚀 快速上手

### 1. 下载

前往 [GitHub Releases](../../releases) 下载 `poe2-economy-display-mod.zip`

### 2. 安装

解压 `物价补丁` 文件夹即可使用。放到 POE2 **游戏根目录**仍是最简单的方式，但现在也可以放在其它目录，并在统一窗口里自动识别或手动选择游戏文件夹：

```text
<Path of Exile 2 游戏根目录>\
├── Content.ggpk          # 官服可能有此文件
├── Bundles2\             # Steam/Epic/国服可能有此目录
│   └── _.index.bin
└── 物价补丁\
    └── 物价补丁.exe
```

> 💡 **提示：** “自动识别”会依次检查补丁文件夹上一级、环境变量、最近一次有效目录、已安装程序、WeGame/Steam 游戏库、Epic 清单和常见安装位置。国服会匹配“流放之路：降临”及 `WeGameApps\rail_apps`。未识别到或电脑上有多个客户端时，程序不会猜测，请切换到“手动选择游戏文件夹”。

### 3. 使用

1. **关闭游戏**
2. 双击 `物价补丁.exe`
3. 在统一 GUI 中选择 POE1、POE2 或自动识别，确认客户端路径和服区正确；POE1 如安装汉化补丁，保留“自动识别”或选择“汉化补丁”，更新时还需选择更新范围
4. 点击底部“开始/更新物价补丁”执行更新，或点击旁边的“还原物价补丁”恢复原版文件。窗口中的 `[进度]` 会显示当前数据源、分类分页、重试和生成补丁包状态

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

> 构建文档时需要 `python-docx`；发布包运行时价格脚本只依赖 Python 标准库。打包脚本会内置 .NET 8 与 Python 3.13.14，运行时发布版无需用户额外安装。

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
    ├── Poe2PatchLauncher/          # 统一入口 exe 的 C# 启动器源码
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
.\发布版\物价补丁\物价补丁.exe [参数]
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
| `-Poe1Dir <路径>` | 手动指定 POE1 游戏根目录（默认自动检测） |
| `-Poe1LanguageMode <模式>` | POE1 显示语言：`auto`、`localization`、`zh-CN`、`zh-TW` 或 `config` |
| `-Poe2Dir <路径>` | 手动指定游戏根目录（默认自动检测） |

---

## ⚖️ 使用许可

本项目**禁止**商业使用、收费分发、未经授权转载搬运和重新打包发布。

完整条款见 [使用许可.md](./使用许可.md)

---

## ⭐ Star 历史

<img width="1374" height="1098" alt="star-history-2026619" src="https://github.com/user-attachments/assets/e6361bd8-a214-40f1-b145-37f86e842d8e" />
