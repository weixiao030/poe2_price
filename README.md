<p align="center">
  <h1 align="center">⚗️ POE1/2 物价补丁 v0.5.3</h1>
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

`v0.5.3` 修复官服 GGPK 安装在 `D:\poe2` 等非默认目录时，首次运行无法自动识别的问题。程序现在会读取 GGG 官方注册表中的 `InstallLocation`，同时覆盖 POE1 与 POE2；已有 Steam、WeGame、Epic、环境变量和最近目录规则保持不变。

poe.ninja 页面上依赖等级、品质、词缀或具体变体定价的 Skill Gems、Base Types、Cluster Jewels、Valdo Maps、Forbidden Jewels、Wombgifts 等分类不会写成一个固定物品名价格，避免把不同变体串成同一价格。

POE2 同名元数据仍会全部写入价格，国服翻译重名时继续使用 `engname` 精确消歧。

实时物价指的是打入补丁那一刻的物价，刷新物价需要自己手动更新，也就是得重新打补丁。

英文客户端因为底层问题使用的话会影响到过滤器正常使用,其他客户端没影响.

---

---

## 后续开发计划
待定

---

## 更新日志

完整更新记录见 [更新日志.md](更新日志.md)。

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

### 26/8/4 更新（v0.5.0）

- 新增 POE1 物价补丁，支持 poe.ninja 当前软核赛季与国服 `poecurrency.top/api/summary?version=1`，价格单位为 C/D，并为普通物品和传奇装备生成独立补丁包。

- 统一 GUI 可选择 POE1、POE2 或自动识别；自动发现覆盖国际服官方 GGPK、Steam/Epic Bundles2 和 WeGame 国服目录，手动选择会校验实际客户端类型。

- POE1 使用独立输出、缓存、逻辑还原包和 Bundles2 物理还原包；POE2 继续使用原有脚本和 E/D 价格规则，两个版本不会互相覆盖。

- BundleExtractor 新增 GGPK/游戏版本识别和批量提取命令；发布 payload、启动器与测试同步更新。

### 26/7/25 更新（v0.4.9.7）

- 修复 [Issue #23](https://github.com/weixiao030/poe2_price/issues/23)：国际服同显示名的多个 BaseItemTypes 元数据别名不再因字典覆盖而漏写价格，国服翻译重名时使用 engname 进行精确消歧。

- 同步源脚本、发布 payload、启动器和测试，并使用最新版官服 Content.ggpk 验证巅峰门票、君王之颅、骷髅马克等同名别名均能生成价格。

### 26/7/19 更新（v0.4.9.6）

- 更新和还原入口统一支持“自动识别游戏文件夹”和“手动选择游戏文件夹”；最近一次有效目录会保存在当前 Windows 用户的本地设置中，补丁文件夹无需放在游戏根目录。

- 国服自动识别新增 WeGame 注册信息、各磁盘 `WeGameApps\rail_apps` 游戏库以及“流放之路：降临”名称匹配；选中后仍会校验 `Bundles2\_.index.bin` 与 WeGame/Rail/Tencent 客户端特征。

- 自动发现多个 POE2 客户端时停止并要求手动选择，避免更新或还原到错误客户端；GUI 会明确显示“国服 WeGame Bundles2”等安装类型。

- 启动器和 PowerShell 入口增加真实游戏目录级互斥保护；还原错误改为简洁提示，不再把临时解包目录误判为游戏目录并输出整段堆栈。

- 修复 [Issue #23](https://github.com/weixiao030/poe2_price/issues/23)：国际服同显示名的多个 `BaseItemTypes` 元数据别名不再因字典覆盖而漏写价格，国服翻译重名时使用 `engname` 进行精确消歧。

- 同步源脚本、发布 payload、启动器和测试，并使用最新版官服 `Content.ggpk` 验证巅峰门票、君王之颅、骷髅马克等同名别名均能生成价格。

### 26/7/11 更新（v0.4.9.5）

- 发布包新增经过 SHA512 校验的 .NET 8.0.28 离线修复包；内置运行时损坏时直接本地恢复，本地修复包也丢失时才使用 Microsoft CDN/官方源。

- Python 下载顺序调整为华为云、阿里云、南京大学镜像、Python 官方备用源。

- 国内镜像和官方源使用相同固定 SHA 校验；镜像返回错误页、文件不完整或内容不一致时自动清理临时文件并尝试下一个来源。

- Python 国内源采用较短超时和两次重试，官方备用源保留更长超时，避免单个不可用镜像长时间阻塞全部用户。

### 26/7/11 更新（v0.4.9.4）

- 价格补丁改为隔离构建、完整校验后原子发布；实时数据源失败时依次尝试核心价格和当前范围、构建模式匹配的兼容核心缓存，不再用空包、半成品或其它勾选范围的旧包覆盖用户当前补丁。

- Bundles2 与 GGPK 写入增加写前并发指纹、写后读回校验和自动回滚；统一入口的还原操作优先使用无需运行时的物理备份，逻辑还原失败会自动重试并复核。

- 修复零匹配、低匹配、同名不同物品串价、价格源异常值优先级、干净 Words 无输出、路径大小写和岛屿 DAT 布局误判等边界问题；旧 Words 清理不可用时保留当前文件，不阻断核心价格层。

- 下载的 .NET 与嵌入式 Python 包新增固定哈希校验；临时 ZIP、DAT、还原包和缓存均改为原子替换，避免中断后留下损坏文件。

### 26/7/11 更新（v0.4.9.3）

- 修复“当前 Bundles2 已包含补丁标记，但找不到安全真实还原包”导致的升级自锁：在临时沙盒中生成、写入并校验干净迁移基线，成功前不修改真实游戏。

- 真实还原包新增游戏目录侧持久副本，并会发现旧同级补丁文件夹中的有效备份；多个内容不同的有效备份会拒绝静默选取。

- Words 标记检测改为解析当前有效行，检测器异常会报告“无法判断”而不是误报“已打补丁”；逻辑还原会校验 Words，并在旧还原包缺少 EndgameMaps 时清理当前旧岛屿提示。

- 移除更新阶段对全部现有 `LibGGPK3` 条目的重复合并。`PatchBundle3` 会保留未触碰的 FileRecord，重复合并只会放大增量包并造成长时间无输出。

### 26/7/10 更新（v0.4.9.2）

- 赛季从 poe2scout 当前软核记录自动发现；显式 `--league` / `--poe-ninja-league` 仍优先，发现失败时使用已知可用值，不阻断所有用户。

- poe.ninja、poe2scout 传奇和 Poe2DB 均支持可选分类级降级；核心 Currency / 参考汇率不兼容时才切换数据源。

- 修复 Poe2DB 单链接单元格导致的 5 个漏价，仅在 divine/exalted、两个正数和行 slug 严格匹配时接受，避免猜价。

- poecurrency 增加 `engname` 英文别名补匹配，保留时间戳、昨日均价、比例、异常与错误字段；过期/异常默认只报告，不改变正常当前价。

- 摘要新增统一健康状态、结构指纹、请求耗时/响应大小和分类统计；新增只读实时审计，不读写游戏文件、不触发发布。

- 价格源共享模型、HTTP 客户端、赛季和健康契约已渐进拆分为独立模块，主入口保留原 CLI 和公共名称兼容。

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
- 🏷️ **自动标注** 将价格追加到物品名中，游戏内一目了然
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
