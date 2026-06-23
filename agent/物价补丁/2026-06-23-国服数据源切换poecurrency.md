# 国服数据源切换 poecurrency.top

## 背景

国服此前沿用国际服 poe2scout 价格，和国服市场存在偏差。现在新增国服专用数据源 `https://poecurrency.top/api/summary?version=2`，只在检测到国服 WeGame 客户端时启用。

## 改动

- `update_price_patch.ps1` 根据 `InstallInfo.IsChina` / `CN-*` 安装类型传入 `--price-source poecurrency-cn`。
- 国际服仍保持默认 `poe2scout` 数据源和现有抓取流程。
- `build_poe2scout_price_patch.py` 新增 poecurrency.top summary 解析逻辑，按中文物品名匹配国服简体中文 `BaseItemTypes.datc64`。
- D/E 换算比例不写死：国服从 poecurrency.top 返回的“神圣石”当前价格推导，国际服仍从 poe2scout 实时数据推导；无法推导时中止生成。
- 国服 `buy_avg` / `sell_avg` 不直接算术平均：两边都有值且价差不超过 5 倍时取几何均值，价差超过 5 倍时取较低一侧；只有单边有效时使用单边价格。
- 国服不再抓取 poe2scout 的国际服传奇物品列表，只标注 poecurrency.top 返回的中文名物品。

## 验证

- Python 语法检查通过。
- PowerShell 脚本解析通过。
- 轻量接口解析测试确认 poecurrency.top 返回 27 个分类，并能从“神圣石”实时读取 D/E 比例。
