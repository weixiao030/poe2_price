# 物价补丁源代码

这里是 POE2 物价补丁的源码和打包脚本。

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
