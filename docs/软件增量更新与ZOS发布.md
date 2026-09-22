# 软件增量更新与 ZOS 发布

正式主应用版本为 0.9.3。软件更新和每小时物价更新是两个独立功能。

v0.9.3 优先通过 GitHub 国内主源、备用源读取签名清单和专用增量包，全部失败后使用 ZOS。已发布的 v0.9.2 仍按其原配置从 ZOS 升级，升级后采用新的来源顺序。GitHub 提供完整安装包、免安装包和增量包；ZOS 只存放本次增量包及签名更新清单，不上传完整发行包或完整更新包。

## 国内源与 ZOS 的顺序

`resources/update-config.json` 的 `github.repository` 为 `weixiao030/poe2_price`。默认 8 个国内镜像与 POE1 汉化脚本顺序一致：`ghfast.top`、`gh-proxy.com`、`ghproxy.it`、`gh-proxy.org`、`ghproxy.net`、`gh.llkk.cc`、`ghproxy.imciel.com`、`ghfile.geekertao.top`。第一项为主源，其余为备用源；软件更新最后回退 ZOS，不再尝试 GitHub 直连。2026-09-22 实测及复查共移除 4 个异常源（`github.boki.moe` 大包超时、`gh.jasonzeng.dev` TLS 中断、`gh.monlor.com` 和 `gh.ddlc.top` 返回 429），补回 4 个通过内容校验的源（`gh-proxy.org`、`gh.llkk.cc`、`ghproxy.imciel.com`、`ghfile.geekertao.top`），源总数保持 8 个。`ghproxy.it` 会跳转 `ghfast.top`，`ghfile.geekertao.top` 部分请求会跳转 `gh.dpik.top`。检查结果是当时的连通性，不保证第三方源持续可用。

清单通过各镜像访问 GitHub 的 `releases/latest/download/latest.json`。更新 ZIP 通过镜像访问同仓库的 `releases/download/v版本号/文件名`。所有镜像必须提供签名清单指定的同一份文件，大小和 SHA-256 校验失败会删除部分下载并切换下一源；清单还必须通过内置 Ed25519 公钥验证。每个包下载源最多尝试 3 分钟，连续 30 秒无响应也会切源；用户取消时立即结束，不继续尝试备用源。

`manifestUrls` 保留 ZOS 的签名清单地址，签名清单内的包 `url` 仍保留 ZOS 地址。这使原客户端继续可用，新客户端则先尝试 GitHub 国内镜像。修改 GitHub 仓库时同时修改 `github.repository`；需要自定义镜像时可提供 `github.mirrorPrefixes` 数组，地址须使用 HTTPS 并以 `/` 结尾。未配置 `github` 的客户端保持按 `manifestUrls` 下载。

更新包按文件比较 SHA-256，只包含相对指定旧版发生变化的文件。它不是二进制差分：如果重新构建改变了 EXE 的版本资源，整个 EXE 都会进入增量包；仅更新界面代码时通常只需新的 `app.asar`。

## 下载配置与密钥边界

客户端只需要**公开 HTTPS 下载清单地址和 Ed25519 公钥**，不需要对象存储上传 Endpoint、Bucket 管理配置、AK/SK 或签名私钥。公开下载地址是客户端必须知道的信息；上传配置和访问密钥仅保留在发布者本机或 CI Secrets 中。

- 签名私钥保存在 `desktop/.release-keys/update-private.pem`，需要独立备份，不能提交、上传或放入客户端。
- 本地访问密钥文件和 `publisher.local.json` 受 `.gitignore` 保护。发布时仍需检查提交列表和压缩包内容。
- 测试证据、日志、提取的游戏数据和 PDB 调试文件均不作为发行内容。
- 在对象存储中按对象设置匿名读取权限。本次 SDK 默认上传为私有，发布工具显式使用 `public-read`，核对匿名下载成功后才上传清单。
- 客户端使用外网 HTTPS 域名，同资源池内网 IP 不能供玩家下载。下载由主进程完成，不依赖浏览器 CORS。

在 `desktop` 目录配置公开下载地址并生成或复用签名密钥：

```powershell
$UpdateDownloadBase = Read-Host '公开 HTTPS 下载目录（以 / 结尾）'
npm run updates:configure -- --base-url $UpdateDownloadBase
npm run dist
```

`npm run dist` 使用 `--publish never`。首次启用时必须向玩家提供包含正确下载地址和公钥的完整发行版；0.8.8 及更早版本需要手动升级一次。

## 构建正式增量包

保存每个正式版本原样的 `dist/win-unpacked` 作为不可修改的基线。不要使用玩家运行后或改动过的目录。正式发布后不能在相同版本号下更换内容。

1. 同步 `package.json`、`package-lock.json`、`resources/current-release.json` 和相关脚本版本，并填写真实更新说明。
2. 构建新发行目录，保留原发行目录。
3. 在 `desktop` 目录运行以下命令；输入旧版基线、新版目录和新的空输出目录。

```powershell
$UpdateOldBuild = Read-Host '旧版本 win-unpacked 目录'
$UpdateNewBuild = Read-Host '新版本 win-unpacked 目录'
$UpdateOutput = Read-Host '新的更新包输出目录'
$UpdateDownloadBase = Read-Host '公开 HTTPS 下载目录'
npm run updates:build -- --from $UpdateOldBuild --to $UpdateNewBuild --out $UpdateOutput --base-url $UpdateDownloadBase --key '.\.release-keys\update-private.pem' --notes '.\resources\current-release.json' --delta-only
```

正式 v0.9.3 使用 `--delta-only`，必须提供保存的正式 v0.9.2 基线。输出为 `*-delta.zip`、签名 `latest.json` 和维护者使用的 `release-info.json`。不生成或上传 `*-full.zip`。没有匹配基线的旧客户端通过 GitHub 完整安装包或免安装包手动升级。

## 上传与公布

同一个正式版本应在 GitHub `v版本号` Release 和 ZOS 放置**字节完全相同**的签名 `latest.json` 与 `*-delta.zip`。ZOS 不上传 Setup、NoInstall 或 full 更新包。免安装 ZIP 和 Setup EXE 不能代替专用更新包。沿用现有构建命令的 ZOS `--base-url` 即可，无需为镜像重新签名或改写清单。

先用最终签名包完成隔离的真实升级测试，再准备 GitHub 草稿 Release 并上传文件，按下述流程上传和校验 ZOS，最后发布 GitHub 正式 Release。不要覆盖已经发布的版本，也不要复用旧的轻量测试发行目录。新客户端下载时会优先尝试国内镜像；镜像尚未同步时自动使用已经可用的 ZOS。

先上传版本 ZIP，核对大小和 SHA-256，并确认匿名 HTTPS 可以下载；**最后上传 `latest.json`**。清单包含 `schema`、`payload`、`signature`，不能手动改内容。发布工具默认拒绝用不同内容覆盖同名版本包。

上传默认采用 8 MiB 分块、单连接和 180 秒读写超时。链路不稳定时可追加 `--part-size-mib 5 --upload-concurrency 1 --read-timeout 180`，减小失败后需要重传的数据量；客户端发行包与签名不受上传分块配置影响。

从项目根目录执行上传命令。Python 需要 `boto3`；AK/SK 从本地文件读取，不写入命令行：

```powershell
$UpdateUploadEndpoint = Read-Host '对象存储上传 Endpoint'
$UpdateBucket = Read-Host 'Bucket 名称'
$UpdateCredentials = Read-Host '本地凭据文件路径'
$UpdateOutput = Read-Host '包含签名 latest.json 和 ZIP 的目录'
python desktop/scripts/upload-zos-update.py --endpoint $UpdateUploadEndpoint --bucket $UpdateBucket --credentials $UpdateCredentials --directory $UpdateOutput
```

默认对象前缀为 `poe-updates`，可以通过 `--prefix` 修改。`--check-only` 仅验证上传身份。`--replace-unannounced-sha256` 只允许在清单尚不存在时替换已知哈希的失败首次上传，不适用于已经公布的发行包。

| 对象 | Content-Type | Cache-Control |
| --- | --- | --- |
| `latest.json` | `application/json` | `no-cache, max-age=0` |
| 带版本号的 ZIP | `application/zip` | `public, max-age=31536000, immutable` |

Setup 安装包和免安装 ZIP 可单独提供，供首次安装和手动修复使用。客户端读取自定义的 `latest.json`，不使用 electron-updater 的 `latest.yml`。保留历史包，避免中断已开始的下载。

## 安装与失败恢复

客户端验证清单签名、下载大小、SHA-256、ZIP 路径和文件清单；增量包还要核验全部旧发行文件。基线不符会停止安装。v0.9.3 清单只提供 v0.9.2 增量包；无匹配增量时需要手动安装 GitHub 完整发行版。

物价任务或查询未结束时禁止安装软件更新。安装器等待旧程序退出，备份涉及文件、替换并校验完整目标。新版界面初始化成功后回传健康回执；失败会尝试恢复旧文件。游戏文件、用户设置和发行清单外的玩家文件不属于软件替换范围。

事务保存在用户数据目录 `software-updates/<事务 ID>/`。`result.json` 是结果，`journal.json` 是阶段，`backup` 保留被替换的文件；`last-update.json` 指向最近事务。断电导致安装中断时，关闭软件，在对应事务目录运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\recover.ps1
```

恢复脚本只接受安装中或回退失败的事务，正常完成的事务无需恢复。

## 验证

在 `desktop` 目录运行：

```powershell
npm test
npm run build
node --import tsx scripts/verify-software-updates.ts
```

最后一项复制发行目录，在临时 HTTPS 服务上验证签名、下载、自动重启和失败回退。测试证书仅供测试进程使用，生产 TLS 校验保持启用。

发布前可用正式签名包在本地 HTTPS 暂存服务完成真实升级，而不改写基线或公布版本：

```powershell
node --import tsx scripts/verify-zos-software-updates.ts --baseline ../release-desktop/baselines/0.9.2/win-unpacked --target ../release-desktop/v0.9.3-release/win-unpacked --release-dir ../release-desktop/v0.9.3-release/poe-updates --report-dir test-results/release-093-local-upgrade
```

该参数只在隔离测试进程中将两个确切的下载地址转向本地 HTTPS，正式包、签名及基线字节保持原样。发布后去掉 `--release-dir` 并使用单独的报告目录，即可检查生产 ZOS 下载、安装、重启及完整目标文件哈希。
