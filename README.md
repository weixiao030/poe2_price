<p align="center">
  <h1 align="center">⚗️ POE1/2 物价补丁 v0.9.2</h1>
  <p align="center">为《Path of Exile 1/2》官服、Steam 服和国服自动抓取物价、标注物品名的补丁工具</p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/平台-Windows%2010%2F11-blue?logo=windows" />
  <img src="https://img.shields.io/badge/Electron-Vue%203-47848f?logo=electron" />
  <img src="https://img.shields.io/badge/.NET-8.x-purple?logo=dotnet" />
  <img src="https://img.shields.io/badge/Python-3.13.14-yellow?logo=python" />
  <img src="https://img.shields.io/badge/许可-禁止商业使用-red" />
</p>

---

> ⚠️ **重要提示：** 本工具会修改游戏文件，和其他补丁一样**存在封号风险**。使用前请确认自己能接受风险，并在**关闭游戏后**再运行。

---

## 📌 当前版本说明

本补丁主要将通货和传奇装备价值显示在物品名上，项目已开源，可访问 GitHub 查看。

当前版本还是实验阶段，有 bug 请见谅。

`v0.9.2` 修复内置 Python 校验器加载失败被误报为 BaseItemTypes 结构不兼容的问题，保留碑牌构建依赖，并显示实际校验错误。

碑牌词缀分别使用魔法、稀有样本中位价：接近时合并，其余按从低到高显示，E/C/D 和合并标准随当前市场动态变化。提供“检查更新”、当前版本说明、赞赏码及聊天/bug反馈群:168887742；支持签名增量包下载、自动重启安装和失败回退。客户端通过公开 HTTPS 地址检查签名更新；上传配置和密钥不随软件分发。保留通货、传奇、岛屿传言、每小时物价更新及还原功能。

[下载最新版](https://github.com/weixiao030/poe2_price/releases/latest) · [本次发布说明](docs/release-notes.md) · [ZOS 增量发布配置](docs/软件增量更新与ZOS发布.md) · [社区交流](https://www.caimogu.cc/post/2403703.html)

提供 **Setup 安装版**和 **ZIP 免安装版**，两种版本都内置运行环境。免安装版只需将压缩包完整解压到一个文件夹，双击其中的 `物价补丁.exe` 即可运行，后续启动无需重复解包；不要只取出 EXE 或直接在压缩包内运行。

---

---

## 数据源

当前**没有**使用官方 Trade 接口。

- POE2 国际服：通货和可交易分类继续使用 poe2scout（全量 SnapshotPairs）并保留 poe.ninja / poe2db 补缺；碑牌词缀使用 [碑牌报价 API](http://125.122.32.215:2083/api-docs)，先行者碑牌目录使用 [poe.ninja PrecursorTablets](https://poe.ninja/poe2/economy/forbiddenrites/precursor-tablets)；传奇护甲单独优先使用 [poe.ninja UniqueArmours](https://poe.ninja/poe2/economy/forbiddenrites/unique-armours) 对应的 JSON 接口。
- POE2 国服：当前赛季主源 `poecurrency.top/api/summary?version=2`，历史赛季追加 `&season=<所选赛季>`，没有国服价的条目再用可用的国际参考源补。
- POE1 国际服：主源 poe.ninja，备用 poe2scout / poedb。
- POE1 国服：当前赛季主源 `poecurrency.top/api/summary?version=1`，历史赛季追加 `&season=<所选赛季>`，再用可用的国际参考源补缺。
- 国服 OCR 校验在本地完成：按同一物品分侧检查历史报价，校验 D/E、D/C 汇率与小数点修正依据；不依赖 Token 或额外历史接口。汇总中的当前价与全部历史价同时错误时仍可能漏判，真实行情突变也可能暂时采用历史估值。
- 构建时会对照 poe2scout `Items/Categories` 做分类健康检查：新分类只报警并继续抓取，不会默默丢掉。
- 只读契约审计见 `物价补丁/tools/audit_price_sources.py`，覆盖 POE1/POE2。
- 默认“自动跟随最新赛季”，更新时重新解析当前赛季；也可在下拉框固定选择历史赛季。选择按 POE1 / POE2、国服 / 国际服分别保存，重启后保留。已有自动更新任务继续保留原先的固定赛季，成功手动执行一次自动模式后才改为跟随最新。
- 国际服目录使用 Scout 与 Ninja 独立接口：POE2 优先 `https://api.poe2scout.com/poe2/Leagues`，POE1 优先 `https://poe.ninja/poe1/api/data/index-state`，目录故障时尝试另一来源。国服使用 `https://poecurrency.top/api/season_list?version=poe1|poe2`；价格接口的 `version` 则是数字 `1` / `2`，当前赛季省略 `season`，历史赛季才传该参数。
- 打开工具或手动刷新时联网获取目录，执行任务可复用 5 分钟内的目录缓存；联网失败可回退到 7 天内的记录。固定选择不会因刷新失败切换赛季，历史赛季补丁缓存独立。国服自动模式无法确认赛季名称时仍尝试当前价格接口，但不读写赛季补丁缓存、不附带猜测的国际参考赛季。价格不可用时保留已有补丁。
- 国际参考源只补缺，不覆盖国服已有价格；国服历史赛季按名称对应国际赛季，当前赛季没有同名项时独立使用国际服当前赛季参考。没有可用参考时继续尝试国服主价。
- poe.ninja 请求使用站点专用的低并发和 403/429 退避重试；核心分类仍需成功返回，失败时只进入同赛季备用源，不会回退到其它赛季。
- UniqueArmours 读取 `core.primary`、`primaryValue`、`listingCount` 和 `corrupted` 字段：接口声明 Exalted 时不再乘 Divine 汇率，腐化、零挂牌和无效价格行会被过滤；同名多底材优先保留挂牌更多、价格更低的稳定行。

## 后续开发计划

- 国服碑牌词缀价格

---

## 更新日志

完整更新记录见 [更新日志.md](更新日志.md)。

### 26/9/21 更新（v0.8.8）

- 碑牌与暗金装备复用同一名称格式和旧价清理函数，替换旧的 `名称=价格`。
- 名称优先使用普通底材价，缺普通报价时取已有品质中的最低有效报价；补齐总督碑牌，并在报告中记录来源品质。
- 修复深渊“每个已关闭坑洞增加效用，最多100%”漏价：按游戏 `{0}` 识别变量，固定数字逐项核对。
- 从真实游戏 Mods、Stats、Tags 反查 90 个词缀、254 个底材与词缀组合，检查所有整数数值、魔法/稀有与两种中文，共 12,964 项。

### 26/9/21 更新（v0.8.7）

- 按 8 类碑牌的底材标识匹配名称，追加 poe.ninja 普通底材价；没有普通报价时保留原名，不混用魔法或稀有整件报价。
- 删除使用次数下面的“底材参考”行；魔法和稀有物品继续逐条显示所有有数据的词缀价格。
- 清理游戏繁中裂痕描述原有的多余 `]`，保留成对的游戏文字链接。
- 更新、跳过、关闭和还原同时清理中英文碑牌旧名称价；缺词缀模板时仍可独立更新底材名称价。

### 26/9/21 更新（v0.8.6）

- 修复 GGPK 模板提取与新资源索引写入，安装后逐项读回验证。
- 按词缀数值范围匹配市场报价，修复稀有度标记、分支语法和 Divine 换算；词缀价为市场参考，不可相加作为整件价格。
- poe.ninja 先行者碑牌按普通、魔法、稀有分列底材参考价。
- 关闭、跳过、缓存回退及还原会清理已知旧测试引用，避免固定 `2D` 残留。
- 两个碑牌数据源独立失败处理，部分成功会明确记录缺失来源。

### 26/9/21 更新（v0.8.5）

- POE2 通货更新范围新增碑牌词缀标价，按现有 D/E 格式在繁体中文和简体中文描述中紧贴原词条追加价格。
- 使用自定义碑牌词缀报价 API 与 poe.ninja `PrecursorTablets` 目录；请求自动重试，数据或模板失败时独立跳过碑牌层，不影响通货、传奇和岛屿传言。
- 为每种碑牌生成独立 `.it` / `.csd` 资源并重定向对应 BaseItemTypes，保留共用模板和负面词缀。

### 26/9/18 更新（v0.8.4）

- POE1 / POE2 国服共用本地 OCR 报价校验，继续使用普通汇总接口，无需 Token 或额外操作。
- 分别对照买卖两侧的历史均价、上一笔报价，处理双边同时错价、单边极端值及受污染的均价；重复均价字段不重复计票。
- 修复 D 单位价格提前绕过校验、单边神圣石异常污染汇率及派生 E 价格直接覆盖的问题；国服换算不借用国际汇率。
- 网站错误标记作为辅助信号，正常跨位数涨跌仍可使用；小数点修正需要报价依据，持续宽价差不再一律取低价。
- 国际参考仅补缺和记录差异，不因差价大就覆盖已有国服价格；日志增加校验、回退及宽价差原因。
- 增加异常报价、汇率、数值边界及发行文件一致性回归检查。

### 26/9/18 更新（v0.8.3）

- 新增“自动跟随最新赛季”，更新时自动解析当前赛季；手动选择可固定赛季，重启后仍保留，POE1 / POE2 和国服 / 国际服互不影响。
- 修复国服当前赛季请求：价格接口使用数字版本 `1` / `2`，当前赛季不传 `season`，历史赛季才携带对应参数。
- 国际服赛季目录增加 Scout / Ninja 备用来源；目录不可用时使用有效缓存，刷新失败保留选择，取消“请核实后执行”的提示。
- 不再使用写死的旧赛季兜底；修复补充源找不到固定赛季时切到其他赛季、历史项误标最新及损坏缓存混用的问题。
- 历史赛季缓存独立；价格与兼容缓存都不可用时保留已有补丁并报告失败，供自动更新稍后重试。
- 修复手动赛季选择保存失败；已有每小时任务仍保留原固定赛季，选择自动模式并成功手动更新一次后，后续任务跟随最新赛季。

### 26/9/17 更新（v0.8.2）

- 自动更新保存下一次执行时间；重启和唤醒不会把已到期任务再推迟一小时。
- 游戏运行或目录占用时每 2 分钟检查；普通失败按 1、5、15 分钟退避，成功后恢复一小时间隔。
- 启动时核对并修复当前自启路径；关闭自启会清除移动免安装文件夹留下的旧路径。Windows 禁用状态会显示在设置页。
- 重复后台启动不弹窗；写盘失败暂停本次运行中的自动调度，修复磁盘空间后重新开启即可恢复。
- 损坏的自动更新确认配置不会触发还原或汉化；保留开关并等待一次成功手动更新。任务中关闭开关、还原、设置变更不破坏既有规则。

### 26/9/17 更新（v0.8.1）

- 底部“一键汉化 POE1”独立于物价更新，保留确认弹窗，无需价格赛季。
- 识别或切换客户端时禁止发起汉化，执行时显示加载状态。
- 增加独立汉化入口、取消确认、禁用状态及紧凑窗口布局的自动检查。

### 26/9/16 更新（v0.8.0）

- 更新技术栈，重构了整个项目，如果有问题或者哪里需要改进请留言告诉我。
- 优化了UI，添加自启动，自动更新，这些都是默认关闭，需要去设置自行开启
- 压缩界面资源，背景图片异步加载，不再阻塞工作台显示。
- 后台自启仅驻留托盘，不创建隐藏窗口或预热渲染进程，不自动扫描游戏或加载背景；打开工作台时按需加载。
- 关闭到托盘后释放界面，保留任务、运行记录与每小时更新。重新打开、最小化恢复和关闭退出均保留。
- 保留外观设置、源码与社区链接、旧缓存和日志清理；只清理 7 天前的白名单文件，保留当前日志、近期文件和还原备份。
- 物价、DAT、汉化、岛屿提示、还原和客户端保护沿用原核心；每小时自动更新仅在手动关闭时停用。

### 26/9/16 更新（v0.7.3）

- 修复还原操作关闭每小时自动更新的问题；其他设置不再推迟原定检查时间，任务执行中仍可手动关闭自动更新。

### 26/9/16 更新（v0.7.0）

- 桌面入口迁移到 Electron、TypeScript 和 Vue 3，增加独立运行记录、主题、自定义背景与日志导出。
- 价格、汉化与还原继续使用原核心，增加安装版和免安装版，保留客户端互斥、游戏运行保护和进程树取消。

### 26/9/16 更新（v0.6.6）

- 新增 Windows 托盘常驻模式，支持开机自动启动、每小时自动更新物价、立即更新、最近结果查看和安全退出。
- 自动更新使用最近一次成功手动补丁的游戏版本、路径、服务器、语言和更新范围；游戏运行时跳过本轮，失败只记录日志并提示托盘。
- 修复新旧赛季交接期间服务端同时标记多个当前软核赛季导致更新中止的问题，按服务端顺序选择最新赛季。
- 该接口的 `primaryValue` 在 `core.primary=exalted` 时已经是 Exalted 单位，构建器会直接读取；只接受正价格和有效挂牌数，过滤腐化行，并对同名多底材行按挂牌数和价格做确定性去重。
- 合并价格时，poe.ninja 的 UniqueArmours 行优先覆盖 poe2scout 同名护甲传奇；通货、碎片、武器和其它来源仍保留原有顺序和补缺逻辑。
- 同步更新 PowerShell Worker、明文 `tools` 发布目录、启动器元数据、使用文档和完整更新日志，版本号统一保持 `0.6.6`；发布包不再加密脚本。

### 26/8/23 更新（v0.5.9）


- 国服 POE1 圣甲虫恢复国际服回填：`poecurrency-cn` 缺价时仍可用 ninja / scout / poedb 补上圣甲虫价。
- 只读数据源审计补上 POE1（poe.ninja、poecurrency version=1、poe2scout PC、poedb），并刷新契约 baseline。
- poe2scout 分类清单纳入构建健康项：新传奇分类不再默默丢弃；ninja 未覆盖的通货分类写入告警。
- 修复部分电脑启动内置 Python 时要求提权（Win32 740）的问题：以 `RunAsInvoker` 调用，并优先使用 `poe_python.exe`。成功构建后不再把 dat size 中的 2740570 误判成提权失败。
- 修复发布包 `payload.zip` 与源脚本换行不一致导致 Windows Release 检查失败的问题。

### 26/8/13 更新（v0.5.8）

- 传奇标签改为按游戏代数生成：POE1 使用 `传奇名[<<价格>>]`，POE2 使用 `[价格|传奇名]`。当前两套易刷解析器和 PoE Overlay II 都会得到不带价格标记的精确传奇名。

- 修复 POE2 后缀格式残留 `<>` 后查不到精确传奇、继而按“荣耀战铠”等底材误选“背信弃义”等其它传奇的问题；已有 v0.5.6/v0.5.7 补丁可直接更新迁移，不需要先手动还原。

- POE1 国际服一键汉化改为隐藏子进程轮询：GUI 持续刷新运行时间和最新阶段输出，运行期间阻止重复点击或关闭；超时会终止整棵子进程树，失败时回显汉化脚本诊断信息。下载链扩展为 `ghfast.top`、`gh-proxy.com`、`gh.ddlc.top`、`ghproxy.it`、`github.boki.moe`、`ghproxy.net`、`gh.jasonzeng.dev`、`gh.monlor.com` 与 GitHub 官方源，执行前严格核对最新正式 Release 的大小和 SHA256；同时移除对几十 GB 游戏包的前后整包哈希，解决下载完成后长时间无输出的假卡死。

### 26/8/12 更新（v0.5.7）

- POE2 逻辑/物理还原包改为 `POE2 + InstallKind + 语言` 独立命名，输出目录再按游戏绝对路径哈希隔离；游戏根目录的 `.poe2-price-patch` 是唯一权威副本。修复官方 GGPK 与 Steam/Epic 共用 `国际服还原补丁.zip`，后运行的客户端覆盖前者底板并导致还原被拒绝的问题。

- POE1 逻辑还原 manifest 升级到 v2，强制核对客户端类型、GGPK/Bundles2 模式、目标语言、资源路径、结构签名及每个条目的长度/SHA256；POE1/POE2 旧包只读校验后迁移，不再写回共享通用文件名。

- 当游戏已经打过本工具补丁但专属基线丢失或过期时，更新器和还原器都会在临时目录清除可确认的 BaseItemTypes、Words 与 EndgameMaps 标记，验证结构和零残留后再建立基线。清理模式不访问价格网络；只有 DAT 损坏、结构无法解析、存在未知改动或平台并发写入时才拒绝并提示修复。

- 新增跨客户端作用域、防篡改、重复更新不覆盖基线和真实 GGPK 自愈验证；连续更新两次以上仍使用第一次验证的干净底板，还原不会回到第二次补丁状态。

### 26/8/12 更新（v0.5.6）

- POE1、POE2 的传奇装备曾统一改用 `传奇名[<<价格>>]`。后来通过易刷实际运行模块确认：当前 POE1 能正确清理该格式，但 POE2 会先剥离方括号、再删除内部 `<价格>`，最终残留 `<>`。

- 此版本加入的简化易刷模拟只覆盖了一套清洗顺序，没有发现两代解析器的差异；v0.5.8 已分别锁定 POE1 与 POE2 的真实规则。

- v0.5.8 继续把后缀格式作为 POE1 默认值，并将 POE2 默认值恢复为竖线标记；更新、还原和 Words 状态检查仍兼容全部历史格式。

### 26/8/11 更新（v0.5.5）

- 修复 POE1/POE2 国服与国际服 Bundles2 客户端连续更新时误报并发变化；成功写入并读回后记录与真实还原包绑定的现场指纹，旧版本状态或平台更新则在不修改真实游戏的离线沙盒中刷新干净还原基线。

- POE1 逻辑还原写入前会剥离校验 manifest，仅向 `PatchBundle3` 传入 BaseItemTypes/Words；同时统一 Windows 8.3 短路径和长路径，避免临时目录中误报 `_.index.bin` 不存在。

- 当前 POE1 国服 WeGame、POE1 国际服 Steam 与 POE2 国服 WeGame 均已使用真实 `PatchBundle3 v2.7.5` 在隔离副本中连续写入两次并逐次读回，真实游戏目录完整指纹前后不变。

### 26/8/10 更新（v0.5.4）

- 修复 POE1 Steam Bundles2 更新器先提取繁中 DAT、再单独提取英文 DAT 时重复加载数百万条索引的问题；现在以当前游戏 DAT 为底板，将必需英文表和本地化表一次批量提取，对短暂文件占用有限重试。游戏更新会覆盖补丁，但不再依赖固定赛季资源，更新完成并关闭游戏后重新点击更新即可重建并安装。

- 统一 GUI 在选择 POE1 国际服后提供“一键汉化POE1国际服”。每次点击都会从 [PoEDB 中文化说明](https://poedb.tw/cn/chinese) 指向的 [LibGGPK3 最新 Release](https://github.com/aianlinb/LibGGPK3/releases/latest) 下载 `PoeChinese3_win-x64.exe`。下载按 `ghfast.top`、`gh-proxy.com`、`gh.ddlc.top`、`ghproxy.it`、`github.boki.moe`、`ghproxy.net`、`gh.jasonzeng.dev`、`gh.monlor.com`、GitHub 官方源依次切换；执行前校验官方文件大小、SHA256、PE、产品信息和版本号，不会复用旧下载文件。GUI 会持续显示当前阶段和已运行秒数，超时会清理整个子进程树；不再对几十 GB 的完整游戏包做前后 SHA256，避免被误判为卡死。

- 汉化完成后请在 POE1 选择第二个（法文）国旗；程序会尝试写入 `production_Config.ini` 的 `language=fr`。此功能仅支持 POE1 国际服 Steam/Epic Bundles2 和官方 GGPK，修改游戏文件仍有校验、封号和启动风险。

### 26/8/4 更新（v0.5.3）

- 自动识别新增 GGG 官服注册表安装目录，支持从 `HKCU\Software\GrindingGearGames\Path of Exile 2\InstallLocation` 找到 `D:\poe2` 等非默认 GGPK 路径；POE1 官服使用相同规则。

- 候选仍会校验目录实际包含 `Content.ggpk` 或 `Bundles2\_.index.bin`，无效或残留注册表路径会被忽略；补充 POE1/POE2 首次运行回归测试并重新生成统一启动器。

### 26/8/4 更新（v0.5.2）

- POE1 国际服从单一 poe.ninja 主数据升级为 `poe.ninja → poe2scout → PoEDB` 逐物品补缺；POE1 国服使用 `poecurrency.top → poe.ninja → poe2scout → PoEDB`，国服已有价格不会被国际服来源覆盖。

- 新接入 poe2scout 的 POE1 `pc` realm，使用 `BaseItemTypeId` 精确匹配 DAT 元数据路径；PoEDB 使用 `/us/Economy` 国际服价格和 `/cn/Economy` 简中名称，并按 Chaos/Divine 换算，不混入 `/tw/Economy` 台湾服价格。

- poe.ninja 新增 Runegrafts、Djinn Coins、Ducats、Enshrouding Crystals、Astrolabes、Invitations、Vials 等可安全映射分类；变体决定价格的分类继续排除。2026-08-04 最终真实客户端验证快照中，Steam 基础价格覆盖为 829 条，国服为 840 条；覆盖数会随赛季市场数据和各来源当前可用条目变化。

### 26/8/4 更新（v0.5.1）

- 修复 POE1 Steam 客户端配置为法语等非中文语言、但第三方汉化补丁实际显示繁中资源时，价格被写入原配置语言表而游戏内不可见的问题。

- GUI 新增“POE1 显示语言”：支持自动识别、汉化补丁、简体中文、繁体中文、跟随游戏配置，并将选择保存到 `%LOCALAPPDATA%\PoePricePatch\settings.json`。

- 自动模式下国服固定简中；国际服配置已是中文时直接使用，非中文时检查最新客户端日志中的区域名，检测到中文区域则写入繁中表。`POE1_PATCH_LANGUAGE` 仅在自动模式下继续兼容。

- POE1 缓存、逻辑还原包和 Bundles2 物理还原包按实际写入语言隔离；更新与还原显式传递同一语言模式，并兼容查找旧版物理还原包文件名。
---
## 📸 效果预览

<p align="center">
  <img width="900" alt="效果图1" src="https://github.com/user-attachments/assets/fa84867b-a49e-43a9-8247-884cd320649c" />
  <br/>
  <img width="900" alt="效果图2" src="https://github.com/user-attachments/assets/3b31063d-1289-4fbf-94da-0e6f5345ec23" />
</p>

---

## ✨ 功能特点

- 🔍 **自动读取** 游戏 `Content.ggpk`（官服）或 `Bundles2`（Steam/Epic/国服）中的物品名表
- 🎮 **双版本 GUI** 统一选择 POE1、POE2，再自动识别或手动选择目录，POE1 与 POE2 的输出、缓存和还原包彼此隔离
- 🌐 **汉化兼容** POE1 可自动识别第三方汉化补丁，也可固定简中/繁中或严格跟随 `production_Config.ini`
- 💰 **POE1 多源价格** 国际服按 poe.ninja → poe2scout → PoEDB 补缺；国服按 poecurrency.top v1 → poe.ninja → poe2scout → PoEDB 补缺
- 🛟 **独立降级** 各来源并行抓取并独立失败，后续来源只补空缺；POE2 继续使用原有 poe2scout、poe.ninja、PoEDB / poecurrency.top v2 链路
- 📡 **实时进度** 抓价、重试、分类分页、匹配和生成补丁包都会在窗口中显示进度
- 🏷️ **自动标注** 将价格追加到物品名中；POE1 传奇使用 `传奇名[<<价格>>]`，POE2 使用 `[价格|传奇名]`，易刷与 PoE Overlay II 都能还原为精确传奇名
- 🧭 **岛屿提示** 可选给岛屿传言追加对应地图提示，方便跑图时判断目标
- 🎛️ **范围选择** 可只更新通货、只更新传奇装备，或两者都更新
- 📁 **目录选择** 更新与还原均支持自动识别、最近目录复用和手动浏览
- ▶️ **统一入口** 打开 `POE 物价补丁`，在工作台底部点击“开始更新物价”或“还原补丁”
- 🎮 **三服支持** POE1/POE2 均兼容官服（GGPK 格式）、Steam/Epic 版（Bundles2 格式）和国服 WeGame（Bundles2 格式）
- 📦 **免环境** 发布版内置 .NET 8 + Python 3.13.14，且会检查运行时完整性，普通用户开箱即用

---

## 🚀 快速上手

### 1. 下载

前往 [GitHub Releases](https://github.com/weixiao030/poe2_price/releases/latest) 下载：

- `POE-Price-Patch-0.8.8-x64-Setup.exe`：安装版，推荐日常使用。
- `POE-Price-Patch-0.8.8-x64-NoInstall.zip`：免安装版，完整解压后双击 `物价补丁.exe`；EXE、DLL、`resources` 等文件必须保留在同一文件夹中。
- `SHA256SUMS.txt`：发行文件校验值。

### 2. 安装

安装版按提示选择安装位置；免安装版可放在任意可写目录。无需放进游戏根目录，也无需另装 Python 或 .NET。应用内选择包含 `Content.ggpk` 或 `Bundles2\\_.index.bin` 的游戏目录。

从旧版迁移或移动免安装版文件夹后，先运行新位置的 `物价补丁.exe`；已开启自启时会自动核对当前路径。若设置页提示被 Windows 禁用，请在任务管理器的“启动应用”中启用。

> 💡 **提示：** 自动识别会检查已安装程序、注册表、WeGame/Steam 游戏库与 Epic 清单；未识别到或有多个客户端时，请手动选择并核对游戏版本、服区和目录。

### 3. 使用

1. **关闭游戏**，打开 `POE 物价补丁`。
2. 在“物价补丁”选择 POE1 或 POE2，选择游戏目录并核对客户端。
3. 选择语言、赛季和更新范围。POE2 可单独启用岛屿传言提示；POE1 国际服可执行一键汉化，汉化后在游戏中使用法文入口。
4. 点击“开始更新物价”并确认；实时日志显示数据源、下载、校验和生成状态。需要还原时点击“还原补丁”。
5. “运行记录”查看最近 50 次结果；“引用设置”管理背景、主题、托盘、开机自启与每小时自动更新。
6. 每小时更新沿用最近成功手动更新的配置；游戏运行时每 2 分钟重查，失败按 1、5、15 分钟重试，成功后间隔一小时。还原不会关闭开关，手动关闭会停止后续调度；写盘异常会暂停并在设置页提示。

**请保留游戏目录中的 `.poe1-price-patch` / `.poe2-price-patch` 专属还原备份。** 关闭到托盘仍可执行后台更新；从托盘选择退出后才完全停止。后台自启不显示窗口，双击托盘图标即可打开。

发行包内置明文 PowerShell / Python 核心与运行环境；没有旧版加密 payload 或临时解密入口。

---

## 🛠️ 开发者指南

### Vibe Coding 指南

开发前阅读本 README、[开发说明](docs/开发说明.md)、[核心迁移核对](docs/核心迁移核对.md) 和 [desktop/README.md](desktop/README.md)。先核对核心指纹与回归测试，避免只改界面时影响物价、汉化或还原流程。

### 构建要求

| 依赖 | 版本要求 |
|------|---------|
| 操作系统 | Windows 10/11 x64 |
| Node.js | 22 |
| Python | 3.10+；测试需要 pytest |
| .NET SDK | 8.x，仅重新编译 BundleExtractor 时需要 |

> 发布包内置 .NET 8.0.28 与 Python 3.13.14，普通用户无需额外安装。运行时使用固定版本下载并校验 SHA256。

### 目录结构

```text
.
├── desktop/                       # Electron 主进程、preload、Vue 界面与打包
├── 物价补丁/
│   ├── tools/                     # 原 PowerShell / Python 物价与还原核心
│   │   ├── GGPKExtractor/          # 官方 GGPK 资源提取
│   │   └── BundleExtractor/        # Steam/Epic/国服 Bundles2 提取
│   └── 一键安装特殊补丁工具/       # GGPK / Bundle 写入工具
├── build/
│   ├── BundleExtractor/           # 提取器 C# 源码
│   └── prepare_runtime.ps1        # 固定版本运行时下载与校验
├── restore-seeds/                 # 需通过兼容校验的还原种子
├── tests/                         # 核心算法、数据源与恢复回归
└── docs/                          # 开发、迁移、许可和发布说明
```

### 打包发布版

```powershell
npm ci --prefix desktop
npm --prefix desktop run prepare:runtime
npm --prefix desktop run test:migration
python -m pip install pytest
python -m pytest tests -q
npm --prefix desktop test
npm --prefix desktop run dist
node desktop/scripts/verify-startup.mjs --packaged
node desktop/scripts/verify-no-install.mjs
node desktop/scripts/verify-compatibility.mjs
```

输出目录：`desktop/dist`，包含 Setup 安装版、免安装版 ZIP 和未压缩应用目录。推送 main 执行构建与验证；只有与应用版本一致的标签才发布 Release，发布附带 SHA256 校验值。发行包暂未配置项目代码签名。

### 调试参数

`npm --prefix desktop run dev` 启动开发界面。`POE_DESKTOP_DATA` 可指定隔离配置目录；桌面程序的 `--hidden` 参数仅启动托盘。

以下为物价核心脚本参数，不是桌面 EXE 参数；使用前请阅读 [开发说明](docs/开发说明.md)，并在隔离副本中验证。

| 参数 | 说明 |
|------|------|
| `-SkipExtract` | 使用已有游戏数据缓存 |
| `-NoInstall` | 只生成补丁，不写入游戏文件 |
| `-NoPoe2dbFallback` | 不请求 poe2db 兜底翻译 |
| `-PatchScope all/currency/uniques` | 全量、通货或传奇 |
| `-IslandRumourHints` | 额外生成岛屿传言提示 |
| `-Poe1Dir <路径>` / `-Poe2Dir <路径>` | 明确指定对应游戏根目录 |
| `-Poe1LanguageMode <模式>` | auto、localization、zh-CN、zh-TW 或 config |

---

## ⚖️ 使用许可

本项目**禁止**商业使用、收费分发、未经授权转载搬运和重新打包发布。

完整条款见 [使用许可.md](./使用许可.md)

---

## ⭐ Star 历史

<img width="1374" height="1098" alt="star-history-2026619" src="https://github.com/user-attachments/assets/e6361bd8-a214-40f1-b145-37f86e842d8e" />
