# 世界地图只读模块

来源：`https://github.com/weixiao030/poe_Plugin`，固定提交 `7dde80bf90d38eae5773c82de4797999c1008cf1`。
仅选择 Atlas 节点读取、元数据翻译、路径规划及其所需内存读取代码。上游许可见 `licenses/POE2GPS-MIT.txt`，不迁入其他游戏辅助功能。

`Program.cs` 通过标准输入输出逐行 JSON 接收 read/reset/search/route 请求。进程仅使用查询与读取权限，限制请求大小、坐标范围，异常时清空快照。`ClientGate.cs` 与 `GameReader.cs` 校验所选目录、实际运行进程及国际服标识；拒绝国服、不匹配目录与无法确认的客户端。

Electron 主进程持有会话、风险授权和轮询计时器；独立 .NET 进程采样地图，独立 PowerShell 子进程执行补丁。地图无需取得补丁任务锁，补丁自身仍执行运行中游戏检查和目录互斥。应用页面生命周期不控制后台会话。

屏幕坐标由只读 Atlas 对象得到，Win32 客户区物理像素转换为 Electron DIP。覆盖层不抢焦点、鼠标穿透，非前台或超过 1 秒无更新即隐藏。所有地图信息仅描述当前已物化并通过校验的节点，不承诺固定数量。

构建：`npm --prefix desktop run build:world-map`。离线测试：`npm --prefix desktop run test:world-map`。真实读取需用户授权且打开所选国际服的世界地图：`node desktop/scripts/probe-world-map.mjs D:\poe2`。覆盖层验证：`node desktop/scripts/verify-world-map-overlay.mjs D:\poe2`。
