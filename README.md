<p align="center">
  <h1 align="center">⚗️ POE2 物价补丁</h1>
  <p align="center">为《Path of Exile 2》国际服 / 繁中客户端自动抓取物价并标注到物品名的补丁工具</p>
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

## 📸 效果预览

<p align="center">
  <img width="900" alt="效果图1" src="https://github.com/user-attachments/assets/fa84867b-a49e-43a9-8247-884cd320649c" />
  <br/>
  <img width="900" alt="效果图2" src="https://github.com/user-attachments/assets/3b31063d-1289-4fbf-94da-0e6f5345ec23" />
</p>

---

## ✨ 功能特点

- 🔍 **自动读取** 游戏 `Content.ggpk` 中的物品名表
- 💰 **联网抓取** poe2scout 实时价格数据
- 🏷️ **自动标注** 将价格追加到物品名中，游戏内一目了然
- ↩️ **一键还原** 随时恢复原版物品名，安全无残留
- 📦 **免环境** 发布版内置 .NET 8 + Python 3.10，普通用户开箱即用

---

## 🚀 快速上手

### 1. 下载

前往 [GitHub Releases](../../releases) 下载 `POE2物价补丁-发布版.zip`

### 2. 安装

解压后将 `物价补丁` 文件夹放到 POE2 **游戏根目录**，与 `Content.ggpk` 同级：

```text
D:\Path of Exile 2\
├── Content.ggpk
└── 物价补丁\
    ├── 一键更新物价补丁.exe
    └── 一键还原物价补丁.exe
```

### 3. 使用

1. **关闭游戏**
2. 双击 `一键更新物价补丁.exe`，等待程序自动抓取价格并写入游戏
3. *(可选)* 需要恢复原版时，双击 `一键还原物价补丁.exe`

---

## 🛠️ 开发者指南

### 构建要求

| 依赖 | 版本要求 |
|------|---------|
| 操作系统 | Windows 10/11 x64 |
| .NET SDK | 8.x |
| Python | 3.10+ |
| Python 包 | `python-docx` |

> 构建时需联网下载 Python embeddable 包和固定版本依赖；运行时发布版无需用户额外安装。

### 目录结构

```text
.
├── 物价补丁/
│   ├── tools/                      # PowerShell & Python 核心脚本
│   │   └── GGPKExtractor/          # 从 Content.ggpk 提取数据的工具
│   └── 一键安装特殊补丁工具/        # 把补丁 zip 写回 Content.ggpk
└── build/
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

输出目录：`物价补丁源代码\发布版\物价补丁`

### 调试参数

发布版 exe 支持透传参数：

```powershell
.\发布版\物价补丁\一键更新物价补丁.exe [参数]
```

| 参数 | 说明 |
|------|------|
| `-SkipExtract` | 跳过从 `Content.ggpk` 提取数据，使用已有缓存 |
| `-NoInstall` | 只生成补丁 zip，不写入 `Content.ggpk` |
| `-NoPoe2dbFallback` | 不请求 poe2db 兜底翻译 |

---

## ⚖️ 使用许可

本项目**禁止**商业使用、收费分发、未经授权转载搬运和重新打包发布。

完整条款见 [使用许可.md](./使用许可.md)

---

## ⭐ Star 历史

[![Star History Chart](https://api.star-history.com/svg?repos=weixiao030/poe2_price&type=Date)](https://star-history.com/#weixiao030/poe2_price&Date)
