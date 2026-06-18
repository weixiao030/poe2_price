# POE2 物价补丁

这是一个给《Path of Exile 2》国际服/繁中客户端使用的物品名物价补丁工具。

程序会读取游戏 `Content.ggpk` 里的物品名表，联网抓取 poe2scout 价格，把价格标记追加到物品名中，并提供一键还原。

> 重要提醒：本工具会修改游戏文件，存在封号风险。使用前请确认自己能接受风险，并关闭游戏后再运行。
效果图:
<img width="600" height="600" alt="f5ee90e72b57c57e41479e6dfa85c222" src="https://github.com/user-attachments/assets/fa84867b-a49e-43a9-8247-884cd320649c" />
<img width="600" height="600" alt="bf27e347f661be4ac3c4ba045612a0e2" src="https://github.com/user-attachments/assets/3b31063d-1289-4fbf-94da-0e6f5345ec23" />


## 使用方法

1. 在 GitHub Releases 下载 `POE2物价补丁-发布版.zip`。
2. 解压压缩包，得到 `物价补丁` 文件夹。
3. 把整个 `物价补丁` 文件夹放到 POE2 游戏根目录，和 `Content.ggpk` 同级。
4. 关闭游戏。
5. 双击 `一键更新物价补丁.exe`，等待程序自动抓取价格、生成补丁并写入游戏文件。
6. 如果需要恢复原版物品名，双击 `一键还原物价补丁.exe`。

目录示例：

```text
D:\Path of Exile 2\Content.ggpk
D:\Path of Exile 2\物价补丁\一键更新物价补丁.exe
D:\Path of Exile 2\物价补丁\一键还原物价补丁.exe
```

发布版已内置 .NET 8、Python 3.10 和所需依赖，普通用户不需要另外安装运行环境。

## 源码说明

本仓库包含 POE2 物价补丁的源码和打包脚本。

## 目录结构

- `物价补丁/tools`：PowerShell 和 Python 核心脚本。
- `物价补丁/tools/GGPKExtractor`：从 `Content.ggpk` 提取数据的工具。
- `物价补丁/一键安装特殊补丁工具`：把补丁 zip 写回 `Content.ggpk` 的工具。
- `build/Poe2PatchLauncher`：一键更新/还原 exe 的 C# 启动器源码。
- `build/PayloadPacker`：把脚本 payload 加密进启动器的辅助工具。
- `build/make_release.ps1`：完整发布版打包脚本。
- `build/create_release_doc.py`：生成 `使用文档.docx` 的脚本。

## 构建要求

- Windows 10/11 x64
- .NET SDK 8.x
- Python 3.10 或更高版本
- Python 包：`python-docx`，用于生成 Word 使用文档
- 构建时需要联网下载 Python embeddable 包和固定版本依赖

运行时发布版不需要用户再下载 Python 或 .NET。

## 打包发布版

在 `物价补丁源代码` 目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build\make_release.ps1
```

生成结果：

```text
物价补丁源代码\发布版\物价补丁
```

如果只想跳过 Word 文档生成：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build\make_release.ps1 -SkipDoc
```

## 开发调试

发布版 exe 支持把参数透传给脚本，例如：

```powershell
.\发布版\物价补丁\一键更新物价补丁.exe -SkipExtract -NoInstall
```

常用参数：

- `-SkipExtract`：跳过从 `Content.ggpk` 提取数据，使用已有缓存。
- `-NoInstall`：只生成补丁 zip，不写入 `Content.ggpk`。
- `-NoPoe2dbFallback`：不请求 poe2db 兜底翻译。

## 风险提示

本工具会修改游戏文件，存在封号风险。源码仅供学习和自用，请自行承担使用后果。

## 使用许可

本项目禁止商业使用、收费分发、未经授权转载搬运和重新打包发布。完整条款见 [使用许可.md](./使用许可.md)。
