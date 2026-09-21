# 物价补丁桌面应用

当前版本 v0.8.8。使用说明、目录结构及核心迁移记录见[项目 README](../README.md)。

```powershell
npm ci
npm run prepare:runtime
npm run dev
npm run dist
```

`test:migration` 校验原项目核心与打包文件一致；`test:desktop` 在隔离环境检查窗口、进程取消与状态；`test:package` 读取本机实际客户端并检查打包资源。CI 使用 `node scripts/verify-package.mjs --ci`，不要求安装游戏。

发行物为 Setup 安装版和完整文件夹 ZIP 免安装版，解压后运行 `物价补丁.exe`。`verify-no-install.mjs` 校验 ZIP 的全部应用文件并从独立中文目录启动；`verify-compatibility.mjs` 覆盖 POE1/POE2 的官服、Steam、WeGame 客户端夹具。加 `--live` 检查四组实时赛季，随后运行 `python -X utf8 scripts/verify-selected-sources.py` 可按桌面所选赛季只读审计全部物价源。实时检查不进入 CI，以免将外部数据源波动误当作打包失败。

`test-real-games.mjs` 和 `verify-real-controls.mjs` 会实际修改明确指定的游戏目录，只在需要实机验证时手动执行，不启动游戏可执行文件。原始实机证据与四份可重建/回滚材料保存在本地 `verification/desktop-v0.7.0`，不进入发行包。

设置位于 Electron 用户配置目录。可用 `POE_DESKTOP_DATA` 指定隔离目录。首次运行将内置引擎校验后释放到该目录，后续更新与还原继续使用原项目的客户端专属基线。
