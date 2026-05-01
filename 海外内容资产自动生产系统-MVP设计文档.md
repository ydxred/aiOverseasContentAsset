# 海外内容资产自动生产系统 MVP 设计文档

> 版本：v0.1  
> 定位：海外内容机会发现 + 中文内容脚本生产  
> 原则：先验证内容质量，再扩展视频合成和批量分发  
> 默认模式：自动生成草稿，人工审核发布

---

## 1. 核心判断

这个项目第一阶段不应该先做成“自动视频生产系统”，而应该先做成：

```text
海外内容链接
→ 自动转写
→ 自动理解
→ 自动评分
→ 自动风控
→ 中文脚本草稿
→ 人工审核
```

原因很简单：系统能不能成立，关键不在于能不能把视频合出来，而在于能不能稳定产出“值得中文用户看”的内容草稿。

如果脚本本身不可用，后面的 TTS、字幕、视频模板、批量发布都会放大低质量内容；如果脚本质量成立，视频合成只是工程扩展。

---

## 2. MVP 不做什么

第一版暂时不做：

```text
自动发布
复杂视频合成
AI 数字人
自动混剪原视频
多平台全量分发
大规模频道监控
复杂内容库沉淀
```

第一版也不以外部分发数据作为核心成功指标。早期只验证两件事：

```text
1. 能不能发现值得做的海外内容
2. 能不能重构成可审核、可发布的中文脚本
```

---

## 3. 第一版目标

### 3.1 输入

```text
一个海外内容 URL
```

优先支持：

```text
YouTube 视频链接
```

后续再扩展：

```text
RSS
博客文章
Twitter/X 链接
Reddit 帖子
```

### 3.2 输出

```text
output/{content_id}/
├── meta.json
├── transcript.json
├── analysis.json
├── score.json
├── risk_report.json
├── chinese_script.md
├── title_options.md
└── review_notes.md
```

### 3.3 成功标准

一条链接处理完成后，人工审核者可以直接判断：

```text
这个选题值不值得做
脚本是否有中文平台表达感
是否存在版权、事实或平台风险
需要修改哪些地方才能发布
```

---

## 4. MVP 总链路

```text
URL 输入
  ↓
元数据抓取
  ↓
音频 / 字幕获取
  ↓
ASR 转写
  ↓
转写清洗
  ↓
内容理解
  ↓
选题评分
  ↓
风险检测
  ↓
中文脚本重构
  ↓
质量检查
  ↓
输出审核包
```

---

## 5. 最终架构预留

MVP 功能要克制，但系统边界要按最终产品预留。第一版不能写成一次性脚本，而应该写成可插拔流水线。

最终系统分为 8 层：

```text
Source Layer：内容源层
Opportunity Layer：选题机会层
Content Intelligence Layer：内容理解层
Asset Generation Layer：内容资产生成层
Media Production Layer：媒体生产层
Review Layer：人工审核层
Distribution Layer：分发层
Feedback Layer：反馈学习层
```

### 5.1 Source Layer：内容源层

当前实现：

```text
手动输入 YouTube URL
抓取元数据、字幕、音频
```

预留能力：

```text
YouTube 频道监控
RSS / Newsletter 监控
博客文章抓取
Reddit / Hacker News / Product Hunt 发现
Twitter/X 高质量账号监控
来源可信度评分
```

### 5.2 Opportunity Layer：选题机会层

当前实现：

```text
对单条内容做分析和评分
```

预留能力：

```text
sources.yaml 源池
topic_clusters.yaml 主题簇
国内缺口检测
国外热度检测
机会分 opportunity_score
人工反馈校准评分规则
```

这个层是未来系统能不能持续产出好选题的关键。第一版可以不全自动，但数据结构必须能记录来源、主题、评分理由和人工反馈。

### 5.3 Content Intelligence Layer：内容理解层

当前实现：

```text
转写
清洗
内容理解
选题评分
风险检测
```

预留能力：

```text
事实核查
多来源交叉验证
竞品内容对照
热点聚合
同主题内容合并
```

### 5.4 Asset Generation Layer：内容资产生成层

当前实现：

```text
中文短视频脚本
标题候选
审核说明
```

预留能力：

```text
小红书笔记
B站简介
公众号文章
社群帖
知识卡片
课程素材
多平台版本改写
```

### 5.5 Media Production Layer：媒体生产层

当前实现：

```text
不生成正式视频
只保留分镜建议和屏幕文字
```

预留能力：

```text
TTS 配音
字幕生成
视频模板合成
封面生成
网页截图
图表和流程图生成
BGM / 音效
不同平台比例适配
```

第一版可以把媒体生产模块实现为 skipped，但接口要存在。后面接入 TTS、字幕和视频模板时，不应该影响前面的分析、评分和重写链路。

### 5.6 Review Layer：审核层

当前实现：

```text
输出 markdown / json 审核包
人工在线下判断是否继续制作
```

预留能力：

```text
审核后台
人工评分
修改意见记录
发布批准
退回重写
风险确认
```

### 5.7 Distribution Layer：分发层

当前实现：

```text
不自动发布
不接平台账号
```

预留能力：

```text
发布队列
平台适配
账号矩阵
定时发布
发布状态回写
失败重试
```

### 5.8 Feedback Layer：反馈学习层

当前实现：

```text
人工记录脚本是否可用
人工记录主要修改点
```

预留能力：

```text
播放、点赞、收藏、评论等数据回写
选题评分校准
来源质量校准
主题簇权重调整
脚本质量反馈
视频风格反馈
```

---

## 6. MVP 实现边界

第一版实现的是内容生产内核，不是完整自动视频工厂。

必须实现：

```text
URL 输入
元数据抓取
音频 / 字幕获取
ASR 转写
转写清洗
内容理解
选题评分
风险检测
中文脚本重构
质量检查
审核包输出
```

只预留接口，暂不完整实现：

```text
选题机会引擎
视频合成
自动发布
数据反馈
审核后台
多平台资产生成
```

架构约束：

```text
模块之间通过 artifact/json 传递数据
每一步都要有输入、输出、状态和错误记录
所有模型调用都记录 provider、model、prompt_version 和成本估算
暂不实现的模块也要有明确接口和 skipped 状态
不要让 main.py 直接写死所有业务逻辑
```

---

## 7. 模块设计

### 7.1 Downloader：内容获取

负责获取视频基础信息、音频、已有字幕和缩略图。

输入：

```json
{
  "url": "https://youtube.com/watch?v=xxx"
}
```

输出：

```text
workspace/{content_id}/
├── meta.json
├── source_audio.mp3
├── original_subtitle.vtt
└── thumbnail.jpg
```

推荐工具：

```text
yt-dlp
ffmpeg
```

原则：

```text
原视频画面只允许用于内部理解和人工参考
第一版不直接复用原视频画面作为发布素材
```

---

### 7.2 Transcriber：转写

负责把音频转成带时间戳的文本。

第一版建议：

```text
OpenAI Whisper API
```

后续成本优化：

```text
faster-whisper 本地部署
```

输出：

```json
{
  "language": "en",
  "segments": [
    {
      "start": 0.0,
      "end": 4.8,
      "text": "Today I want to talk about..."
    }
  ]
}
```

---

### 7.3 Cleaner：转写清洗

负责清理 ASR 噪声，但不改变事实含义。

处理内容：

```text
去除明显重复
修复断句
合并过短片段
标记听不清或不确定内容
保留时间戳
```

输出：

```text
transcript_clean.json
```

---

### 7.4 Analyzer：内容理解

负责判断原内容讲了什么，以及它对中文用户是否有价值。

输出：

```json
{
  "core_topic": "",
  "summary": "",
  "main_points": [],
  "interesting_angles": [],
  "domestic_value": 0,
  "commercial_value": 0,
  "short_video_suitability": 0,
  "content_formats": [],
  "facts_to_check": [],
  "risk_points": []
}
```

推荐模型：

```text
Gemini Pro
```

原因：

```text
长上下文成本较低，适合读取完整转写
```

---

### 7.5 Scorer：选题评分

负责判断这条内容是否值得继续加工。

评分维度：

```text
国内稀缺度：0-10
商业价值：0-10
传播性：0-10
实操性：0-10
内容新鲜度：0-10
风险等级：0-10，分数越高风险越大
```

总分建议：

```text
总分 =
国内稀缺度 × 0.25
+ 商业价值 × 0.25
+ 传播性 × 0.20
+ 实操性 × 0.15
+ 内容新鲜度 × 0.10
+ 风险反向分 × 0.05
```

输出：

```json
{
  "total_score": 0,
  "decision": "process / review / archive / discard",
  "reason": "",
  "best_format": ["short_video"],
  "must_review": true
}
```

分数策略：

```text
85+：优先进入脚本生成
70-85：生成草稿，但必须人工审核
50-70：只保留摘要和分析
50 以下：归档或丢弃
```

---

### 7.6 Risk Checker：风险检测

这是 MVP 必须做的模块，不能后置。

检测项：

```text
是否像逐字翻译
是否保留过多原作者表达结构
是否依赖原视频画面才能成立
是否涉及收入承诺
是否涉及医疗、法律、金融建议
是否有未经核查的数据或结论
是否有平台敏感表达
是否可能被判断为低质搬运
```

输出：

```json
{
  "pass": false,
  "risk_level": "low / medium / high",
  "copyright_risk": 0,
  "factual_risk": 0,
  "platform_risk": 0,
  "issues": [],
  "must_fix": [],
  "must_review": true
}
```

强制人工审核条件：

```text
风险等级为 medium 或 high
包含收入、医疗、法律、金融内容
存在未核查事实
脚本被判断为翻译感明显
需要使用原视频截图或画面解释
```

---

### 7.7 Rewriter：中文脚本重构

目标不是翻译，而是重构成中文用户能看懂、愿意看、且不明显依赖原视频表达的内容。

要求：

```text
不逐字翻译
不沿用原视频叙事结构
保留核心观点
补充中文用户需要的背景
删除寒暄、重复和自嗨内容
开头 5 秒有明确钩子
每句话适合口播
涉及不确定事实时标记【待核查】
```

输出：

```md
# 标题

# 口播稿

# 分镜建议

# 屏幕文字

# 风险点

# 待核查内容
```

推荐模型：

```text
Claude Sonnet
```

备选：

```text
GPT-5.4
Qwen Max
DeepSeek Pro
```

---

### 7.8 Quality Checker：质量检查

负责在输出前做最后一轮自动检查。

检查项：

```text
脚本是否完整
是否还有明显翻译腔
是否出现“原视频说”“这个博主说”
是否有未标记的事实风险
标题是否过度承诺
是否符合中文平台表达习惯
是否有明确修改建议
```

输出：

```json
{
  "pass": false,
  "quality_score": 0,
  "issues": [],
  "fix_suggestions": [],
  "ready_for_human_review": true
}
```

---

### 7.9 Opportunity Engine：选题机会引擎

第一版不做完整自动选题系统，但要保留模块边界。

当前实现：

```text
读取单条 URL 的内容分析结果
生成基础 score.json
输出是否值得继续处理
```

预留输入：

```json
{
  "source_url": "",
  "source_trust_score": 0,
  "topic_cluster": "",
  "foreign_heat": 0,
  "domestic_gap": 0,
  "user_value": 0,
  "content_rebuildability": 0,
  "risk_score": 0
}
```

预留输出：

```json
{
  "opportunity_score": 0,
  "decision": "process / review / archive / discard",
  "reason": "",
  "recommended_asset_types": ["short_video_script"],
  "review_required": true
}
```

后续完整能力：

```text
维护高质量海外源池
维护主题簇
检测国内内容缺口
根据人工反馈校准机会分
每天输出候选选题队列
```

---

### 7.10 Media Producer：媒体生产预留

第一版不生成正式视频，但必须定义媒体生产接口。

当前实现：

```text
接收 chinese_script.md
读取分镜建议和屏幕文字
返回 skipped 状态
```

预留输入：

```json
{
  "content_id": "",
  "script_path": "",
  "voice_style": "default",
  "video_template": "default_explainer",
  "platform": "draft"
}
```

预留输出：

```json
{
  "status": "skipped / generated / failed",
  "voice_path": "",
  "subtitle_path": "",
  "video_path": "",
  "cover_path": "",
  "issues": []
}
```

后续完整能力：

```text
TTS 配音
字幕生成
视频模板合成
封面生成
质量检测
```

---

### 7.11 Distribution Adapter：分发预留

第一版不接平台账号，不做自动发布。

当前实现：

```text
不发布
只把审核包放入 output 目录
```

预留能力：

```text
发布候选队列
平台字段适配
定时发布
发布结果回写
失败重试
```

---

### 7.12 Feedback Collector：反馈预留

第一版至少要能记录人工判断，后续再接平台数据。

当前实现：

```text
review_notes.md 中保留人工审核字段
```

预留字段：

```text
选题是否值得做
脚本是否可用
主要修改原因
风险判断是否准确
视频风格是否合适
发布后表现
```

---

## 8. 视频风格与质量预留

视频风格不能等到视频合成阶段才想。即使第一版只输出脚本，也要提前定义目标视频形态，否则后面容易做成低质模板号。

### 8.1 第一版目标视频风格

建议先采用“专业讲解型”模板：

```text
清晰标题页
统一字体和配色
中文口播
大字幕
关键词高亮
简单背景图或背景视频
必要时插入网页截图
少量信息卡片
节奏稳定，不做复杂特效
```

第一版不追求炫，但必须避免廉价感。

### 8.2 视频质量标准

后续生成视频时，至少检查这些项：

```text
前 5 秒是否有明确钩子
画面是否和脚本内容相关
字幕是否清晰可读
字幕是否明显错位
语音是否自然
语速是否适合中文用户
画面是否有统一品牌感
是否存在大段无信息画面
是否使用了高风险原视频素材
是否有明显搬运感
```

### 8.3 视频模板接口

媒体生产模块未来应支持模板化，而不是每次临时拼视频。

预留模板配置：

```yaml
template_id: default_explainer
aspect_ratio: "9:16"
font_family: "default"
primary_color: "#FFFFFF"
accent_color: "#FFD166"
background_type: "image_or_video"
subtitle_style: "large_center_bottom"
keyword_highlight: true
progress_bar: true
bgm_enabled: false
```

### 8.4 视频质量评分

预留视频质量评分输出：

```json
{
  "visual_quality": 0,
  "audio_quality": 0,
  "subtitle_quality": 0,
  "pace_score": 0,
  "brand_consistency": 0,
  "platform_fit": 0,
  "risk_score": 0,
  "pass": false,
  "issues": []
}
```

---

## 9. 第一版模型配置

第一版不要接太多模型供应商，建议控制在 2-3 个。

推荐组合：

```text
ASR：OpenAI Whisper API
内容理解：Gemini Pro
选题评分：GPT-5.4
风险检测：GPT-5.4
中文脚本重构：Claude Sonnet
标题生成：GPT-5 mini 或 DeepSeek Flash
```

如果想进一步简化：

```text
ASR：OpenAI Whisper API
分析 / 评分 / 风控：GPT-5.4
脚本重构：Claude Sonnet
```

---

## 10. 数据库设计

第一版直接使用 PostgreSQL 作为唯一数据库。

原因：

```text
任务状态、模型调用、反馈数据后续都会持续增长
需要更可靠的并发写入和查询能力
后面接审核后台、发布队列、数据反馈时不用迁移
```

推荐连接配置：

```env
DATABASE_URL=postgresql://content_asset:password@localhost:5432/content_asset_mvp
```

### 10.1 contents 表

```sql
CREATE TABLE contents (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  content_id TEXT UNIQUE NOT NULL,
  source_url TEXT NOT NULL,
  source_type TEXT NOT NULL,
  title TEXT,
  author TEXT,
  published_at TEXT,
  duration INTEGER,
  language TEXT,
  status TEXT NOT NULL,
  total_score INTEGER,
  risk_level TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

### 10.2 tasks 表

```sql
CREATE TABLE tasks (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  content_id TEXT NOT NULL,
  task_type TEXT NOT NULL,
  status TEXT NOT NULL,
  retry_count INTEGER DEFAULT 0,
  error_message TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

### 10.3 artifacts 表

```sql
CREATE TABLE artifacts (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  content_id TEXT NOT NULL,
  artifact_type TEXT NOT NULL,
  file_path TEXT NOT NULL,
  version TEXT,
  created_at TEXT NOT NULL
);
```

### 10.4 model_runs 表

```sql
CREATE TABLE model_runs (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  content_id TEXT NOT NULL,
  task_type TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  prompt_version TEXT,
  input_tokens INTEGER,
  output_tokens INTEGER,
  cost_estimate REAL,
  status TEXT NOT NULL,
  error_message TEXT,
  created_at TEXT NOT NULL
);
```

这个表很重要。后续要调质量、控成本、排查失败，都依赖模型调用记录。

### 10.5 sources 表

```sql
CREATE TABLE sources (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  source_id TEXT UNIQUE NOT NULL,
  source_type TEXT NOT NULL,
  name TEXT NOT NULL,
  url TEXT NOT NULL,
  category TEXT,
  trust_score INTEGER DEFAULT 0,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

第一版可以不启用自动监控，但要能保存后续源池数据。

### 10.6 topic_opportunities 表

```sql
CREATE TABLE topic_opportunities (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  content_id TEXT NOT NULL,
  topic_cluster TEXT,
  foreign_heat INTEGER,
  domestic_gap INTEGER,
  user_value INTEGER,
  content_rebuildability INTEGER,
  risk_score INTEGER,
  opportunity_score INTEGER,
  decision TEXT NOT NULL,
  reason TEXT,
  created_at TEXT NOT NULL
);
```

这个表用于把“选题方法论”沉淀成可复盘的数据。

### 10.7 media_jobs 表

```sql
CREATE TABLE media_jobs (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  content_id TEXT NOT NULL,
  job_type TEXT NOT NULL,
  status TEXT NOT NULL,
  template_id TEXT,
  platform TEXT,
  output_path TEXT,
  error_message TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

第一版媒体任务可以统一写入 skipped，后续接 TTS、字幕和视频合成。

### 10.8 feedback 表

```sql
CREATE TABLE feedback (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  content_id TEXT NOT NULL,
  feedback_type TEXT NOT NULL,
  reviewer TEXT,
  is_topic_useful INTEGER,
  is_script_usable INTEGER,
  main_issues TEXT,
  notes TEXT,
  created_at TEXT NOT NULL
);
```

反馈表用于校准来源质量、选题评分、脚本质量和视频风格。

---

## 11. 项目目录

```text
content_asset_mvp/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── db.py
│   ├── logger.py
│   ├── downloader.py
│   ├── transcriber.py
│   ├── cleaner.py
│   ├── analyzer.py
│   ├── scorer.py
│   ├── risk_checker.py
│   ├── rewriter.py
│   ├── quality_checker.py
│   ├── opportunity_engine.py
│   ├── media_producer.py
│   ├── distribution_adapter.py
│   ├── feedback_collector.py
│   └── artifact_writer.py
├── prompts/
│   ├── analyze_content.md
│   ├── score_topic.md
│   ├── risk_check.md
│   ├── rewrite_short_script.md
│   ├── title_generator.md
│   └── final_quality_check.md
├── data/
│   ├── sample_urls.txt
│   ├── sources.yaml
│   ├── topic_clusters.yaml
│   └── video_templates.yaml
├── workspace/
├── output/
├── logs/
├── tests/
├── migrations/
├── requirements.txt
├── .env.example
└── README.md
```

---

## 12. 命令行设计

### 12.1 单链接处理

```bash
python app/main.py --url "https://youtube.com/watch?v=xxx"
```

### 12.2 指定输出目录

```bash
python app/main.py --url "https://youtube.com/watch?v=xxx" --output-dir output
```

### 12.3 只跑到分析

```bash
python app/main.py --url "https://youtube.com/watch?v=xxx" --stage analysis
```

### 12.4 重新生成脚本

```bash
python app/main.py --content-id "xxx" --rerun rewrite
```

---

## 13. 失败重试

常见失败：

```text
视频无法下载
字幕不存在
ASR 超时
LLM 输出不是 JSON
模型限流
模型拒绝处理
脚本质量检查不通过
```

处理策略：

```text
每个任务最多重试 3 次
每一步都落盘
失败保留中间文件
LLM JSON 失败进入 JSON 修复链
长音频切片转写
模型限流时指数退避
```

---

## 14. 开发顺序

### Day 1：项目骨架 + 下载

目标：

```text
输入 YouTube URL
生成 meta.json 和 source_audio.mp3
```

### Day 2：转写

目标：

```text
生成 transcript.json
支持失败重试
```

### Day 3：分析 + 评分

目标：

```text
生成 analysis.json
生成 score.json
能判断是否值得继续处理
```

### Day 4：风险检测

目标：

```text
生成 risk_report.json
能标记强制人工审核原因
```

### Day 5：中文脚本重构

目标：

```text
生成 chinese_script.md
包含标题、口播稿、分镜建议、屏幕文字、风险点
```

### Day 6：质量检查 + 审核包

目标：

```text
生成 review_notes.md
输出完整审核包
```

### Day 7：小批量验证

目标：

```text
用 10 条不同类型链接测试
统计成功率、脚本可用率、人工修改点
```

---

## 15. 验收标准

第一版验收不看自动化有多酷，只看产出是否可用。

核心指标：

```text
单链接处理成功率 >= 80%
转写结果可读
分析结果能说清楚内容价值
评分理由能被人工认可
风险点能拦住明显问题
中文脚本有发布前修改价值
人工审核者能在 10 分钟内判断是否继续制作
```

人工评估项：

```text
这个选题是否值得做
脚本是否像中文原创表达
是否存在明显搬运感
是否有事实风险
是否需要重写
```

---

## 16. 后续扩展

只有当 MVP 证明脚本质量稳定后，再进入下一阶段。

扩展顺序：

```text
TTS 配音
字幕生成
简单视频模板合成
批量 URL 处理
频道监控
多平台文案生成
自动发布候选队列
```

自动发布放到最后，并且必须满足：

```text
连续一批人工审核无严重问题
低风险内容占比稳定
事实核查流程可靠
平台违规率可控
```

---

## 17. 立即执行清单

第一步先创建最小工程：

```bash
mkdir content_asset_mvp
cd content_asset_mvp

mkdir app prompts data workspace output logs tests
mkdir migrations
touch app/main.py app/config.py app/db.py app/logger.py
touch app/downloader.py app/transcriber.py app/cleaner.py
touch app/analyzer.py app/scorer.py app/risk_checker.py
touch app/rewriter.py app/quality_checker.py app/opportunity_engine.py
touch app/media_producer.py app/distribution_adapter.py app/feedback_collector.py
touch app/artifact_writer.py
touch data/sources.yaml data/topic_clusters.yaml data/video_templates.yaml
touch requirements.txt .env.example README.md
```

第二步安装最少依赖：

```bash
pip install yt-dlp openai anthropic google-generativeai python-dotenv pydub pyyaml psycopg[binary]
sudo apt update
sudo apt install ffmpeg postgresql postgresql-contrib -y
```

第三步准备 PostgreSQL：

```bash
sudo -u postgres createuser content_asset
sudo -u postgres createdb content_asset_mvp -O content_asset
```

`.env.example` 至少包含：

```env
DATABASE_URL=postgresql://content_asset:password@localhost:5432/content_asset_mvp
```

第四步只跑通最短链路：

```text
YouTube URL
→ source_audio.mp3
→ transcript.json
→ analysis.json
→ chinese_script.md
```

做到这一步，再决定是否进入 TTS 和视频合成。
