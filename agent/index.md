> **本文件夹内容用于 vibe coding，AI 快速学习本项目基础内容，以及索引模块相关更改和知识，由 AI 自主维护，轻易勿动！**

---

# POE2 价格补丁工具

## 项目设计目的

POE2 价格补丁工具是一个用于 Path of Exile 2（流亡黯道2）的物品价格显示补丁生成和管理系统。该工具的主要功能是：

1. **自动获取物品价格**：国际服以 poe2scout 为主，国服以 poecurrency.top 为主，并按数据健康度使用兼容缓存和兜底源
2. **生成补丁文件**：将价格信息嵌入游戏数据文件中，使物品名称后显示价格（如 `Exalted Orb = 150D`）
3. **支持三类客户端**：兼容国服 WeGame、国际服官方版（GGPK 格式）和国际服 Steam/Epic（Bundles2 格式）
4. **一键安装/还原**：更新与还原共用游戏目录校验，可自动识别、复用最近目录或由用户手动选择

## 项目架构简介

### 1. 物价补丁（物价补丁）

项目核心模块，包含价格补丁的生成、安装、还原全部业务逻辑。

**目录结构：**
```
物价补丁/
├── tools/                           # 主工具目录
│   ├── update_price_patch.ps1        # 安装/更新价格补丁
│   ├── restore_price_patch.ps1       # 还原原始文件
│   ├── poe2_patch_common.ps1         # 公共函数库（模式检测、路径函数等）
│   ├── build_poe2scout_price_patch.py # 价格数据获取脚本
│   ├── poe2_name_price_patch.py      # 补丁生成脚本
│   ├── BundleExtractor/              # Steam 版文件提取工具
│   │   ├── BundleExtractor.exe       # 主程序（引用 build/BundleExtractor 项目）
│   │   └── oo2core.dll               # Oodle 解压缩库
│   └── GGPKExtractor/                # 官方版文件提取工具
│       ├── GGPKExtractor.exe         # 主程序
│       ├── LibGGPK3.dll              # GGPK 处理库
│       └── oo2core.dll               # Oodle 解压缩库
└── 一键安装特殊补丁工具/             # 发布打包工具
    ├── PatchBundledGGPK3.dll         # 官方版补丁安装工具
    ├── PatchBundledGGPK3.runtimeconfig.json
    ├── PatchBundle3.exe              # Steam 版补丁安装工具
    ├── PatchBundle3.dll
    ├── PatchBundle3.runtimeconfig.json
    ├── LibGGPK3.dll                  # GGPK 处理库
    ├── LibBundledGGPK3.dll           # 综合处理库
    ├── LibBundle3.dll                # Bundle 处理库
    ├── SystemExtensions.dll
    └── oo2core.dll                   # Oodle 解压缩库
```

**工具来源：**
- 所有工具均来自 [LibGGPK3](https://github.com/aianlinb/LibGGPK3) 社区项目
- 工具已预置在项目中，无需额外下载
- 如需更新工具，请从 LibGGPK3 发布页获取最新版本

**工作流程：**
```
┌─────────────────────────────────────────────────────────────┐
│ 1. 游戏目录选择与客户端识别                                 │
│    自动检查最近目录、安装信息及 WeGame/Steam/Epic 游戏库     │
│    多客户端时拒绝猜测，要求手动选择                          │
│    官方版：Content.ggpk → GGPK 模式                          │
│    国服/Steam/Epic：Bundles2\_.index.bin → Bundles2 模式     │
├─────────────────────────────────────────────────────────────┤
│ 2. 提取游戏数据                                             │
│    GGPK模式：GGPKExtractor.exe 从 Content.ggpk 提取         │
│    Bundles2模式：BundleExtractor.exe 从 bundle 提取         │
├─────────────────────────────────────────────────────────────┤
│ 3. 生成补丁                                                 │
│    Python 脚本获取价格 → 修改 BaseItemTypes.datc64           │
├─────────────────────────────────────────────────────────────┤
│ 4. 安装或还原                                               │
│    GGPK模式：PatchBundledGGPK3.dll 写入 Content.ggpk        │
│    Bundles2模式：PatchBundle3.exe 写入 bundle 文件           │
│    以真实游戏目录加锁，写入失败时使用持久备份自动恢复         │
└─────────────────────────────────────────────────────────────┘
```

### 2. build/BundleExtractor（Bundle 提取工具）

独立的 C# 项目，为支持 Steam/Epic 版本（Bundles2 格式）而开发，位于 `build/` 目录下。

| 项目 | 说明 |
|------|------|
| **功能** | 从 Steam 版 `.bundle.bin` 文件中提取指定文件 |
| **依赖** | LibBundle3.dll（社区开源库）、oo2core.dll（Oodle 压缩） |
| **部署** | 编译后复制到 `物价补丁/tools/` 供主项目调用 |
| **源码** | `build/BundleExtractor/Program.cs` |
| **发布** | `build/BundleExtractor/publish/BundleExtractor.exe` |

### 3. Agent（AI 助手目录）

AI 助手学习项目结构和变更记录的专用目录。

| 文件 | 说明 |
|------|------|
| **index.md** | 项目主索引文档，概述设计目的和架构模块 |
| **模块子目录/** | 与 `index.md` 中的模块名称一一对应，存放变更记录 |

### 4. build（构建工具目录）

发布打包相关的 C# 项目，用于生成独立 exe 启动器。

| 项目 | 说明 |
|------|------|
| **BundleExtractor** | Steam 版 bundle 文件提取工具 |
| **PayloadPacker** | 加密 payload.zip → payload.enc（嵌入 exe） |
| **Poe2PatchLauncher** | 独立 exe 启动器，解密并运行嵌入的脚本 |

**发布流程：**
```
1. PayloadPacker.exe 加密 物价补丁.zip → payload.enc
2. Poe2PatchLauncher.exe 嵌入 payload.enc
3. 用户运行 exe → 自动解密 → 提取脚本 → 执行 PowerShell
```

### 5. .gitignore（版本控制忽略规则）

控制 Git 忽略的文件和目录，避免上传不必要的文件。

| 忽略内容 | 说明 |
|----------|------|
| `**/bin/`, `**/obj/` | .NET 编译输出和中间目录（历史上已跟踪的文件不受规则影响） |
| `发布版/`, `三服合一物价补丁构建版/` | 本地发布输出目录 |
| `build/downloads/*.zip` | 构建时下载并可重新获取的运行时缓存 |
| `__pycache__/`, `*.py[cod]` | Python 缓存 |
| `*.tmp`, `*.log` | 临时文件和日志 |

---

## 重要规则

**模块变更记录规范**：每当对架构中的任意模块进行增删改操作时，必须在 `agent` 文件夹下找到对应模块的子文件夹（通过 `index.md` 中的模块名称定位），并在该文件夹内新建一个以 `YYYY-MM-DD-变更摘要.md` 格式命名的变更记录文件。
