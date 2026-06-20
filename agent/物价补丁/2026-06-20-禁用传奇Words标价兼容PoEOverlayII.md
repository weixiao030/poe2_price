# 禁用传奇 Words 标价兼容 PoE Overlay II

> 后续已被 `2026-06-20-传奇价格兼容PoEOverlayII和易刷.md` 取代。本文记录的是 PoE Overlay II 解析失败后的临时止血方案，不是最终兼容方案。

## 背景

PoE Overlay II 的物品解析会从 `Ctrl+C` 复制文本的标题区提取 `name` / `typeLine` / `rarity`，再用这些字段构造官方 `/api/trade2/search` 查询。

旧版传奇价格标注把 `Words.datc64` 中的传奇名改成：

```text
传奇名
[1.00E]
底材名
```

这会让 PoE Overlay II 把 `[1.00E]` 当成标题区的一部分，生成带价格文本的交易查询，官方 trade API 返回 `Invalid query`，游戏内表现为“解析项目失败”。

## 变更

- `build_poe2scout_price_patch.py` 新增 `--unique-price-label-mode`：
  - 默认 `off`：不再把传奇价格写进 `Words.datc64`。
  - 可选 `newline`：保留旧版独立行标价格式，便于本地对比。
- 默认模式会把干净的目标语言 `Words.datc64` 写入补丁 zip，用来覆盖旧版留下的传奇价格行。
- 更新脚本新增 `Words.datc64` 旧传奇价格行检测：
  - 检测到 `\n[1.00E]` 这类旧格式时，从还原包恢复干净 Words。
  - 创建或刷新还原包时拒绝带旧价格行的 Words，避免还原材料被污染。
- 同步更新源码脚本和 `build/payload` 脚本。

## 验证

- 已通过 `py_compile` 检查源码脚本和 payload 脚本。
- 已通过 PowerShell 解析器检查源码更新脚本和 payload 更新脚本。
