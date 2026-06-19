# 添加 GitHub Actions 发布打包

## 变更时间
2026-06-19

## 变更内容
- 新增 `.github/workflows/build-release.yml`。
- workflow 使用 `windows-latest` 和 `.NET 8.x`，调用现有 `build/make_release.ps1 -SkipDoc` 生成发布版。
- 构建完成后将 `发布版/物价补丁` 压缩为 `poe2-economy-display-mod.zip`。
- 通过 `actions/upload-artifact@v4` 上传发布包，供没有本地 Windows 构建环境时下载使用。
- workflow 在手动运行、推送 `v*` tag 或推送到 `main` 时会创建 GitHub Release，并上传 `poe2-economy-display-mod.zip`。
- `main` 推送和未填写 tag 的手动运行使用 `build-<run-number>` 作为 release tag；如果 release 已存在，会覆盖上传 zip，方便重跑 workflow。
- `push main` 触发自动发布时保留 `paths` 限制，只在 `.github/workflows/build-release.yml`、`build/**`、`物价补丁/**`、`restore-seeds/**` 变更时运行；README、agent 记录等纯文案改动不会触发打包发布。
- README 顶部 `26/6/19 更新` 不展示发布构建流程，相关内容仅保留在 agent 记录和 workflow 中。

## 变更原因
本地 macOS 环境不适合完整打包 Windows `.exe` 发布版；改用 GitHub Actions 的 Windows runner 构建，可以复用现有发布脚本并避免用户本地配置 .NET、Python 和 PowerShell 构建环境。
