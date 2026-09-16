# POE1/2 物价补丁 v0.7.3

Windows 桌面应用，统一管理 POE1 / POE2 物价标注、岛屿传言提示、汉化与还原。使用 Electron、TypeScript、Vue 3、Naive UI 和 Pinia；价格与游戏数据处理继续使用经过验证的原项目引擎。

[下载最新版](https://github.com/weixiao030/poe2_price/releases/latest) · [核心迁移核对](docs/核心迁移核对.md) · [使用许可](使用许可.md)

## 开始使用

- **Setup.exe**：安装版，推荐日常使用。
- **Portable.exe**：免安装版，双击运行；启动时会先解包。
- 运行要求：Windows 10/11 x64。已内置 Python 3.13.14、.NET 8.0.28，无需自行安装开发环境。

1. 关闭游戏，选择 POE1 或 POE2，再选择游戏目录。
2. 核对客户端、语言和价格赛季，选择通货、传奇或两者。POE2 可选择岛屿提示。
3. 点击底部“开始更新物价”，确认后查看实时日志。
4. 需要还原时，点击始终可见的“还原补丁”。成功后会保留每小时自动更新开关；只有你手动关闭时才会停用。
5. “应用设置”可选择 JPG/PNG 背景、调节浓度、切换主题、设置托盘和自动更新。

POE1 一键汉化沿用原项目的 PoeChinese3 流程。国际服没有简体资源时，会自动汉化并改用繁体资源更新；后续自动更新沿用成功配置。汉化显示繁体中文，使用法文入口。

## 保留的核心功能

| 功能 | 行为 |
| --- | --- |
| 客户端 | POE1 / POE2；国际服 GGPK、Steam/Epic Bundles2、国服 WeGame |
| 价格 | 国际服 poe.ninja、poe2scout 及原有后备链；国服 poecurrency |
| 标注 | POE1 C/D、POE2 E/D；传奇 Words、价格清理、精确名称与查价器兼容 |
| 赛季 | 当前与历史赛季独立选择、缓存隔离，保留历史赛季布尔参数 |
| 更新 | 通货、传奇、全量；POE2 独立岛屿提示；实时进度与错误报告 |
| 还原 | 客户端、语言和结构匹配；逻辑 / 物理基线、旧价格清理、写后读回 |
| 稳定性 | 单任务、游戏目录互斥、运行中的游戏保护、超时与进程树取消 |
| 后台 | 托盘、每小时自动更新、开机启动、最近 50 次历史和日志导出 |

界面关闭到托盘后释放渲染窗口。日志、历史和前端输出有容量限制；背景最长边限制为 2560 像素。物价源需要联网，已有专属还原包可在本地使用。

**游戏目录内的 `.poe1-price-patch` / `.poe2-price-patch` 是还原依据，请保留。** 内置还原种子仍经过原引擎的结构兼容校验，不能跨客户端或跨版本强行套用。修改游戏文件可能违反游戏规则，使用前请阅读许可及相关规则。

## 开发与验证

```powershell
npm ci --prefix desktop
npm --prefix desktop run prepare:runtime
npm --prefix desktop run test:migration
python -m pip install pytest
python -m pytest tests -q
npm --prefix desktop test
npm --prefix desktop run build
npm --prefix desktop run dev
```

生成安装版与免安装版：`npm --prefix desktop run dist`，输出位于 `desktop/dist`。运行时从固定版本的镜像 / 官方源下载并校验 SHA256；构建不依赖旧“发布版”目录。

- `desktop/`：唯一桌面入口、主进程、preload、Vue 页面、打包与桌面验证。
- `物价补丁/tools/`：当前使用的原项目价格、DAT、汉化与还原引擎。
- `物价补丁/一键安装特殊补丁工具/`：原项目 GGPK / Bundle 写入工具。
- `build/BundleExtractor/`：资源提取器源码；`build/prepare_runtime.ps1`：内置运行时准备。
- `restore-seeds/`：经过原引擎校验使用的还原种子。
- `tests/`：核心算法、数据源和恢复逻辑回归；`docs/`：迁移核对、发布说明与第三方说明。

旧 PowerShell GUI、C# 启动器、重复 Electron 草稿及旧发布产物已从当前树移除；历史源码保留在 Git 历史中。推送 main 执行校验与打包，只有版本标签发布 GitHub Release，不再生成旧版 build-N 发布。

本机已验证 D:\poe1 / D:\poe2 两份国际服官方 GGPK，包含实际更新、汉化、还原与独立 DAT 读回。其他客户端通过原核心回归与源码一致性检查，未声称在本机安装实测。Windows 自启注册已读回，未重启系统测试。发行包未配置项目代码签名。
