# pairwise-vignette-grain

## 领域

游戏、图形与多媒体

## 主题

暗角与胶片颗粒

## 说明

按画幅暗角、时域稳定颗粒与导出匹配。

初始状态下 `render/vignette_grain.py` 中所有函数抛出 `NotImplementedError`，测试全部失败。
修复实现后运行：

```bash
python -m pytest -q
```

期望全部通过。
