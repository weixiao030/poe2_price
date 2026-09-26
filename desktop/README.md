# 物价补丁桌面应用

当前源码版本 v1.0.6。使用说明、目录结构及核心迁移记录见[项目 README](../README.md)。

```powershell
npm ci
npm run prepare:runtime
npm run dev
npm run dist
```

`test:migration` 校验原项目核心与打包文件一致；`test:desktop` 在隔离环境检查窗口、进程取消与状态；`test:package` 读取本机实际客户端并检查打包资源。CI 使用 `node scripts/verify-package.mjs --ci`，不要求安装游戏。

发行物只保留 Windows x64 Setup 安装版。`verify-installer.mjs` 校验真实 NSIS 载荷并从中文目录启动；`test:software-updates` 使用独立应用 ID 验证真实安装、跨版本更新和重启。`verify-compatibility.mjs` 覆盖 POE1/POE2 的官服、Steam、WeGame 客户端夹具。加 `--live` 检查四组实时赛季，随后运行 `python -X utf8 scripts/verify-selected-sources.py` 可按桌面所选赛季只读审计全部物价源。实时检查不进入 CI，以免将外部数据源波动误当作打包失败。

`test-real-games.mjs` 使用打包 EXE，会实际修改明确指定的游戏目录，只在需要实机验证时手动执行，不启动游戏可执行文件。证据按当前版本保存在本地 `verification/desktop-v版本号`，不进入发行包。`verify-followup.mjs --packaged` 检查背景导入、主题、紧凑布局和还原确认。

设置位于 Electron 用户配置目录。可用 `POE_DESKTOP_DATA` 指定隔离目录。首次运行将内置引擎校验后释放到该目录，后续更新与还原继续使用原项目的客户端专属基线。

软件更新的签名、GitHub 国内源 / ZOS 配置与发布步骤见[发布指南](../docs/软件增量更新与ZOS发布.md)。检查更新与每小时物价更新为两项独立功能。

真实 NSIS 更新验证需要 Python 的 cryptography 包；CI 自动安装。卸载旧版本后，可用 `node scripts/verify-installed-startup.mjs "已安装程序目录" "旧配置文件路径"` 验证全新配置与旧配置副本，原配置保持不变，副本关闭自动物价任务。

`node scripts/verify-startup-notice.mjs` 使用真实桌面程序及隔离签名源检查启动提示、计时、按版本忽略和无自动下载。`test-real-games.mjs --game-dir "游戏目录" poe2-restore poe2-currency poe2-currency poe2-restore` 可验证指定客户端；会真实写入，请先关闭对应游戏。
