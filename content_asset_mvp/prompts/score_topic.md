# Score Topic Prompt

Score the topic for Chinese narrative video assets about overseas AI business opportunities and AI tool/CLI/open-source project explainers.

Use dimensions:
- why_now / 为什么火
- problem_intensity / 解决问题强度
- china_gap / 中文稀缺度
- narrative_value / 叙事价值
- video_potential / 视频化潜力
- business_insight / 商业启发
- audience_fit / 受众匹配
- evidence_completeness / 资料完整度
- risk_control / 风险控制

Keep legacy compatibility fields when available: domestic_scarcity, commercial_value, spreadability, practicality, freshness, risk_level.

Return JSON with total_score, decision, reason, content_type, opportunity_dimensions, best_format, and must_review.

