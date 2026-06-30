<p align="center">
  <h1 align="center">⚗️ POE2 物价补丁 v0.4.8</h1>
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

这次修复了 `oo2core.dll` 在部分机器上因缺少 VC++ 运行库而无法启动提取器的问题，发布版现在会一并携带所需运行库；GUI 标题栏会显示补丁版本 `v0.4.8`。

实时物价指的是打入补丁那一刻的物价，刷新物价需要自己手动更新，也就是得重新打补丁。

英文客户端因为底层问题使用的话会影响到过滤器正常使用,其他客户端没影响.

---

---

## 后续开发计划
同步高价值底材如82卓越白装
更新国服传奇装备价格

---

## 更新日志

完整更新记录见 [更新日志.md](更新日志.md)。

### 26/7/1 更新

- 修复 `oo2core.dll` 在部分机器上因缺少 VC++ 运行库导致提取器启动失败的问题，发布版会一并携带所需运行库。

- 更新失败提示增强：遇到 `oo2core` / `VCRUNTIME140` / `api-ms-win-crt` 相关错误时，会提示检查工具目录和 Microsoft Visual C++ 2015-2022 x64 运行库。

- GUI 窗口标题显示补丁版本 `v0.4.8`；补丁范围选择正文标题不再重复显示版本号。

- 已同步 `build/payload`、`payload.zip`、`payload.enc` 和发布校验逻辑，确保一键启动器内嵌脚本也是最新版本。

---

### 26/6/29 更新

- 国际服价格源升级为多源合并：会先抓取 `poe2scout` 主数据源，再抓取 `poe.ninja` 备用源；两者都可用时按物品英文名去重合并，优先保留 `poe2scout` 价格，`poe.ninja` 补齐缺失项。

- 国际服兜底链路调整：如果 `poe2scout` 访问失败但 `poe.ninja` 成功，会直接使用 `poe.ninja` 数据；如果 `poe2scout` 和 `poe.ninja` 都失败，才继续尝试 `Poe2DB Economy`。

- `poe.ninja` 备用源已改为抓取全分类数据，不再只抓 Currency 页面；现在包含通货、碎片、符文、精华、灵魂核心、先祖石板，以及传奇武器、防具、饰品、药剂、护符、珠宝、圣所圣物、石板等分类。

- `poe2scout` 传奇装备抓取已改为按分类读取完整分页，避免只拿第一页导致传奇装备数据不全。

- 价格获取过程新增实时进度输出：窗口会显示当前正在抓取哪个数据源、分类完成数、传奇分页进度、请求失败后的重试次数，以及匹配本地物品、写 CSV、生成补丁包等阶段，避免网络慢时看起来像卡死。

- Python 调用方式改为实时透传输出，同时仍会保留完整日志；默认网络请求会自动重试，遇到超时、429、5xx 等临时错误时会显示重试提示。

- 已同步 `build/payload`、`payload.zip`、`payload.enc` 和一键启动器 exe，发布版双击运行也能看到新的进度提示。

---

### 26/6/28 更新

- 修复国服 `poecurrency.top` 价格异常处理：当接口返回 `error=true` 时，不再直接使用可能 OCR 错位的 `latest_buy1` / `latest_sell1` / `prev_buy1`，会优先使用 `buy_avg` / `sell_avg` 计算出的今日均价，均价不可用时才使用 `prev_buy1` 兜底，避免“梦魇拟像”等物品被标成几百 D。

- 修复国服 D 单位小数点错位：自动识别 `2.3 / 225D`、`2.6 / 242D` 这类 100 倍 OCR 错位并折回正常 D 价格；同时给“神圣石”D/E 汇率增加异常防抖，避免汇率小数点识别错误导致所有 D 价格整体放大 10 倍。

- 优化国服最新买卖价差过大的取价策略：`latest_buy1` / `latest_sell1` 差距超过 5 倍时，会参考今日均价选择更可信的一侧，必要时回退到均价，不再简单固定取较低一侧，减少明显低估和高估。

- 已用当前全量 `summary?version=2` 数据做对比验证：532 个源物品中 521 个可出价，49 个 `error=true` 异常条目均可正常提取价格，异常条目中没有残留 50D 以上离谱高价；最终显示价格发生变化 59 个，其中 46 个来自异常条目修正。

- 修复国服更新时备用参考源网络异常会导致整个物价补丁失败的问题：`poecurrency.top` 主价格源成功时，`poe2scout` 或 `Poe2DB Economy` 参考源失败会改为警告并继续生成主价格补丁。

- 更新失败排查信息增强：价格获取或补丁生成阶段的输出会写入 `output\poe2_price_patch_latest\price_patch_build.log`，失败提示会显示日志路径，方便把真实错误一起反馈。

- 生成摘要新增 `cn_reference_status` 和 `cn_reference_warnings`，可用于判断国服参考源是否正常参与了本次价格生成。

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
- 💰 **联网抓取** 国际服 poe2scout + poe.ninja 多源价格 / 国服 poecurrency.top 实时价格数据
- 🛟 **备用兜底** 国际服优先合并 poe2scout 与 poe.ninja，二者都失败时再使用 Poe2DB Economy；国服主源成功时参考源失败也会继续生成
- 📡 **实时进度** 抓价、重试、分类分页、匹配和生成补丁包都会在窗口中显示进度
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
3. 在弹窗中选择本次要写入的补丁范围；“岛屿传言提示”默认勾选，如本次不需要可取消
4. 等待程序自动抓取价格并写入游戏；窗口中的 `[进度]` 会显示当前数据源、分类分页、重试和生成补丁包状态
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
