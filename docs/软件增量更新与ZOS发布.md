# 安装版在线更新与 GitHub / ZOS 发布

1.0.0 起只发布 NSIS 安装版。客户端使用 electron-updater，按国内 GitHub 镜像顺序尝试，全部失败后回退 ZOS。软件更新与每小时物价更新是独立功能。完整设计及联网参考见 [1.0.0 安装版与在线更新设计](1.0.0安装版与在线更新设计.md)。

0.x 用户运行一次 1.0.0 Setup 完成迁移；旧 latest.json 和历史发行文件不需要删除。从 1.0.0 起只维护最新版标准元数据，不生成 old-to-new ZIP，不传入旧版目录，不要求逐版升级。

## 构建和校验

同步 package.json、package-lock.json 和 resources/current-release.json 的版本与说明。在 desktop 目录执行：

```powershell
npm ci
python -m pip install cryptography
npm test
npm run dist
node scripts/verify-installer.mjs
npm run test:software-updates
npm run updates:build
node --import tsx scripts/verify-update-release.ts dist/update-publish
```

updates:build 从本次 NSIS 构建读取 Setup、blockmap 和 latest.yml，填入本次说明并签名。默认使用本机 .release-keys/update-private.pem；私钥必须独立备份，不提交或分发。输出位于 dist/update-publish，只含 Setup、blockmap、latest.yml、latest.yml.sig、SHA256SUMS.txt。同一输出目录已有不同内容时会拒绝覆盖。尚未发布的候选构建需要重做时，使用 --out 指定新的输出目录；已发布版本必须递增版本号。

所有来源必须使用同一份最终文件。签名后不得改写 latest.yml，修改更新说明也必须重新签名。Setup 内置公钥必须与签名私钥对应。Windows Authenticode 尚未配置，Ed25519 验证用于软件内更新来源校验；两种签名不能混称。

## 客户端下载配置

resources/update-config.json 保存公开镜像配置、ZOS 清单 URL 和公钥。默认镜像依次为 ghfast.top、gh-proxy.com、ghproxy.it、gh-proxy.org、ghproxy.net、gh.llkk.cc、ghproxy.imciel.com、ghfile.geekertao.top。不使用 GitHub 直连回退。

检查时通过镜像读取 GitHub releases/latest/download/latest.yml 与 latest.yml.sig。安装包及 blockmap 使用已确认版本的 releases/download/v版本号/地址；源切换保持版本与校验值不变。ZOS 使用 poe-updates/installer/目录。各版本完整 Setup 始终可直接下载，差分失败由框架回退全量。

检查每个源限时 20 秒；下载连续 60 秒没有进度或单个源超过 30 分钟时切源。用户取消立即终止，不继续备用源。普通退出、关闭到托盘和关机不自动安装；用户发起更新且后台任务结束后才安装。

更换公开备用下载目录时执行以下命令，同时更新客户端和 builder 配置。已经发布的客户端仍使用原地址，需要保持旧地址可访问。

```powershell
$UpdateDownloadBase = Read-Host '公开 HTTPS 下载目录（以 / 结尾）'
npm run updates:configure -- --base-url $UpdateDownloadBase
```

## 上传与公布

从项目根目录上传到 ZOS；Python 只在发布机需要 boto3，签名及文件校验复用 Node 工具：

```powershell
$UpdateUploadEndpoint = Read-Host 'ZOS 上传 Endpoint'
$UpdateBucket = Read-Host 'Bucket 名称'
$UpdateCredentials = Read-Host '本地凭据文件路径'
python desktop/scripts/upload-zos-update.py --endpoint $UpdateUploadEndpoint --bucket $UpdateBucket --credentials $UpdateCredentials --directory desktop/dist/update-publish
```

上传工具先验证签名和全部文件，拒绝覆盖同名不同内容的安装包或 blockmap。上传版本文件并通过匿名 HTTPS 回读验证完整哈希后，保存按版本归档的元数据，最后更新公开 latest.yml.sig 和 latest.yml。两次写入之间短暂不匹配时，客户端会拒绝该组合并重试其他源。版本文件使用 immutable 缓存，最新元数据使用 no-cache。

ZOS 完整校验成功后，将 update-publish 内五个文件原样上传到 GitHub v版本号 Release。普通用户只需下载 Setup。不要上传 win-unpacked、测试证据、密钥或上传配置。

发布通道更新前会验签当前线上元数据，拒绝旧版本覆盖新版，以及同版本不同元数据。CI 串行发布 stable 通道，手动发布也应串行执行。需要撤回故障版本时发布更高版本的修复。

GitHub Actions 标签发布流程自动执行以上顺序。必须配置 UPDATE_PRIVATE_KEY、ZOS_ENDPOINT、ZOS_BUCKET、ZOS_CREDENTIALS；其中 ZOS_CREDENTIALS 为本地凭据文件支持的 JSON 或带标签文本。CI 临时密钥文件在完成后删除，私钥不作为构建产物保存。已有 Release（含草稿）的资产和状态不被重建覆盖。

## 故障处理

下载错误不会替换程序文件，可以重新检查更新。安装前重新校验完整 Setup；后台写入、查询或清理未结束时拒绝安装。安装回执位于用户数据目录 software-updates/installer-result.json；目标界面启动后记为 completed。

NSIS 不提供新版业务启动失败后的通用自动回滚。安装中断或软件无法启动时使用完整 Setup 修复，用户设置及游戏备份保存在程序目录以外。线上发现异常应暂停推广并发布更高版本的修复，避免依赖自动降级。历史 0.x 的事务恢复说明以对应版本文档为准。
