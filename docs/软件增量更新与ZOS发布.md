# 软件增量更新与 ZOS 发布

正式主应用版本为 0.9.2；0.9.3 仅用于升级功能测试。软件更新和每小时物价更新是两个独立功能。

更新包按文件比较 SHA-256，只包含相对指定旧版发生变化的文件。它不是二进制差分：如果重新构建改变了 EXE 的版本资源，整个 EXE 都会进入增量包；仅更新界面代码时通常只需新的 `app.asar`。

## 0.9.3 轻量测试

2026-09-22 已完成原样 0.9.2 基线从对象存储公开 HTTPS 地址下载、校验、安装并自动重启到测试版 0.9.3 的验证。下载包为 **841,168 字节（约 821 KiB / 0.84 MB）**，仅替换两个文件：

| 文件 | 内容 |
| --- | --- |
| `resources/app.asar` | 归档内只有 `package.json` 的版本号从 0.9.2 改为 0.9.3 |
| `resources/current-release.json` | 测试版本号和说明 |

ZIP 另含 `update.json` 安装清单。EXE、运行库、物价引擎保持 0.9.2；没有新增业务功能。Windows EXE 文件属性仍为 0.9.2，应用内版本为 0.9.3，因此不能将测试目录当作正式发行物。

测试使用独立的测试清单目录，正式下载清单保持 0.9.2。测试安装结果为 `completed`，新版界面返回 0.9.3 健康回执，355 个目标文件校验通过，原基线和额外放入的玩家文件完整。私有测试材料保存在已忽略的 `release-desktop/zos-final-v092-r3-test/` 和 `desktop/test-results/zos-final-v092-r3/`，不进入源码仓库或正式发行包。

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
npm run updates:build -- --from $UpdateOldBuild --to $UpdateNewBuild --out $UpdateOutput --base-url $UpdateDownloadBase --key '.\.release-keys\update-private.pem' --notes '.\resources\current-release.json'
```

输出包括对应基线的 `*-delta.zip`、完整更新用的 `*-full.zip`、签名 `latest.json` 和维护者使用的 `release-info.json`。只测试指定旧版时增加 `--delta-only`，必须同时提供 `--from`；此时没有匹配基线的客户端将无包可用。省略 `--from` 只生成完整包。

## 上传与公布

先上传版本 ZIP，核对大小和 SHA-256，并确认匿名 HTTPS 可以下载；**最后上传 `latest.json`**。清单包含 `schema`、`payload`、`signature`，不能手动改内容。发布工具默认拒绝用不同内容覆盖同名版本包。

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

客户端验证清单签名、下载大小、SHA-256、ZIP 路径和文件清单；增量包还要核验全部旧发行文件。基线不符会停止安装。无匹配增量时只能使用清单中已公布的完整更新包。

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

真实 ZOS 测试使用保存在本机的 0.9.2 基线和轻量目标，执行 `node --import tsx scripts/verify-zos-software-updates.ts`。脚本从基线配置读取公网地址，并在隔离副本安装；未准备基线和目标时不会自行构造正式发布。
