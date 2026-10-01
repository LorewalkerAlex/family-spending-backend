# Mapping Recommendation Evaluation

`mapping-ensemble-v2` 从 `spending-mapping-lab` 的实验实现演进而来，服务于人工分类预填，不执行自动分类。

## Current design

- 先处理 exact reviewed key 和唯一 normalized core，避免为渠道包装变化执行模糊搜索。
- 历史候选按结构证据、Merchant-level IDF 字符二元组、字符序列和 Jaccard 融合排序。
- `strong` 同时要求 `rank_score >= 0.70` 和 top-1/top-2 `score_margin >= 0.05`；高分但候选接近时降为 `weak`。
- 无可信历史候选时只起草 Merchant 名称；Category 仅在当前家庭已有 Category 与保守关键词一致时预填。
- 建议返回匹配 description、解释信号、结构化备选和算法版本，并在 Mapping 实例不变时复用索引与结果缓存。

## Verified baseline

2026-10-01 对旧生产 Mapping 副本执行全量 merchant-variant leave-one-out：每次移除被测 description，只使用剩余 reviewed Mapping 推荐。128 个存在同 Merchant 历史兄弟的样本结果如下：

| Metric | Result |
| --- | ---: |
| Top-1 Merchant | 97/128 (75.8%) |
| Top-3 Merchant | 117/128 (91.4%) |
| Exact or <=3-character-edit pre-fill | 113/128 (88.3%) |
| `strong` suggestions | 63/128 |
| Correct among `strong` in this corpus | 63/63 |

同一实现的固定随机 80 条样本得到 top-1 62/80、top-3 74/80、可用预填 72/80，42 条 `strong` 全部正确。完整 128 条评估约 1.5 秒，包括为每个留一案例重建索引；正常后端会按 Mapping 实例缓存索引，因此不承担这一评估开销。

## Interpretation and limits

这些数字用于回归守卫，不能解释为概率或未来准确率。融合权重来自同一历史语料的研究，leave-one-out 也只覆盖已有 Merchant 的描述变体；全新 Merchant、时间漂移、没有字面关联的历史别名和家庭 Category 变化仍需人工判断。`strong` 的 63/63 是当前语料结果，不是无错误保证，因此后端禁止推荐自动写入 Mapping 或 Enrichment Decision。
