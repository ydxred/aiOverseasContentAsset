# 反馈闭环

视频发布后回收平台数据，回写到选题打分权重。下一轮选题自动倾向已验证的方向。

## 数据流

```
publish_board.py
   ↓
publish_tasks.json
   ↓ (手动 / 平台 API)
likes / comments / completion_rate / shares / saves
   ↓
feedback_analysis.py
   ↓
data/feedback_report.json
   ↓
source_feedback.py
   ↓
data/source_feedback_report.json
   ↓ (可选)
sources.yaml weight 写回
```

## 1. 发布后录入数据

### 手动录入（Web 控制台）
- 打开 `/feedback` 面板
- 选发布的视频，填 likes / comments / completion / shares
- 提交 → 写到 `data/feedback_report.json`

### 命令行批量录入

```bash
python -m app.feedback_collector --content-id <id> \
    --platform douyin \
    --likes 1234 \
    --comments 56 \
    --completion 0.42 \
    --shares 78
```

### 自动收集（roadmap）
- 接抖音 / B站 / 视频号 开放 API（需要绿色商业账号）
- 定时 cron 拉数据，自动写入

## 2. 反馈分析

`app/feedback_analysis.py` 输入：
- 视频元数据（content_type / topic / source / TTS provider）
- 平台数据（likes / completion / etc.）
- 历史 baseline（同期同类视频的均值）

输出：
- 每条视频 `vector_score`（实际表现 / 预测表现）
- 维度归因：题目得分 / 标题点击率 / 完播率 / 互动率

写到 `data/feedback_report.json`。

## 3. 源反馈回写

`app/source_feedback.py` 把每条视频的表现归因到 source：

```yaml
# data/sources.yaml
- source_id: github_trending_ai
  url_template: "https://github.com/trending?since=daily&q=ai"
  weight: 1.0  # ← 自动调
  recent_videos: [browser_use, langgraph_studio, ...]
  avg_score_30d: 0.85
```

跑量好的 source → weight 提升；连续翻车 → 降权。

## 4. 选题打分用上反馈

`app/scorer.py` 计算 opportunity_dimensions 时，从 `source_feedback_report.json` 读 source 的最近表现，把它作为 `historical_traction` 维度加权。

## 5. 反馈数据安全

`data/feedback_report.json` 是 **gitignored**（包含发布数据）。
要在 CI / 团队共享时单独同步。

## 6. 简易 dashboard

```bash
python -c "
from app.feedback_analysis import summarize
print(summarize('data/feedback_report.json'))
"
```

输出：
```
Total videos: 47
Avg completion: 38.2%
Top 5 by likes:
  1. browser-use 拆解         8.2k
  2. Cursor 1.0 新功能        5.7k
  ...
Worst 5 (recent 30d):
  1. AWS Bedrock 介绍         412
  ...
```

