# 全自动伪录屏与网页自动点滚方案

日期：2026-05-05

目标：让系统在无人手工录制的情况下，自动打开网页、理解页面、规划点击/滚动/聚焦动作，生成“像真实录屏一样”的演示素材，再交给 Remotion 包装成短视频镜头。

这里的“伪录屏”不是伪造事实证据，而是“可控演示录屏”：

```text
真实网页 / 真实页面截图 / 真实 DOM
+ 自动鼠标轨迹
+ 自动点击 ripple
+ 自动滚动
+ 自动聚焦框
+ 自动镜头推拉
= 可解释、可复现、可审查的演示型录屏素材
```

## 结论

不要使用 DeploySentinel Recorder 作为主流程。

DeploySentinel Recorder 的典型用法是“人工录一次，然后生成 Playwright/Puppeteer 脚本”。这和本项目最终要的全自动批量生产不一致。

本项目应该走：

```text
URL / GitHub repo / 产品页
-> 页面理解
-> 动作规划
-> Playwright 自动执行
-> 注入可见鼠标与交互动效
-> 产出 screenflow_capture.mp4 / keyframes / events
-> Remotion 二次包装
```

## 推荐技术组合

| 项目 | 角色 | 用法 |
|---|---|---|
| [Playwright](https://github.com/microsoft/playwright) | 主执行器 | 打开网页、等待、点击、滚动、截图、录制视频 |
| [browser-use](https://github.com/browser-use/browser-use) | 页面理解/网页 Agent | 自动找页面里的关键信息、按钮、证据区域 |
| [Stagehand](https://github.com/browserbase/stagehand) | AI 浏览器动作层 | 用自然语言 `act/extract/observe` 找目标，适合复杂网页 |
| [ghost-cursor](https://github.com/Xetera/ghost-cursor) | 鼠标轨迹算法 | 借鉴贝塞尔曲线、类真人移动、滚动到元素 |
| [rrweb](https://github.com/rrweb-io/rrweb) | DOM 事件记录/回放 | 后续可选，用于事件流级 replay |
| [rrvideo](https://github.com/rrweb-io/rrvideo) | rrweb 转视频 | 后续可选，把 rrweb event JSON 转 mp4 |
| [puppeteer-screen-recorder](https://github.com/prasanaworld/puppeteer-screen-recorder) | Node 侧录屏参考 | 借鉴 Puppeteer/CDP 视频录制方式 |
| [Steel Browser](https://github.com/steel-dev/steel-browser) | 浏览器实例池 | 后续批量跑浏览器任务时参考 |

## 为什么不用人工 Recorder

人工 recorder 工具的问题：

```text
1. 每种页面都要人先录，扩展性差
2. 录出来的是死脚本，页面结构变动容易失效
3. 它知道“你点了什么”，但不知道“为什么这个点值得拍”
4. 不适合候选源批量生产
5. 不方便和 source_discovery / shot_list / visual_asset_pack 打通
```

可借鉴它们的地方只有一个：把交互动作表达成结构化步骤。

本项目应该自己生成这个结构：

```text
screenflow_plan.json
```

## 核心架构

```text
source candidate
    |
    v
page analyzer
    |
    v
screenflow_builder.py
    |
    v
screenflow_plan.json
    |
    v
screenflow_runner.py
    |
    +--> screenflow_events.json
    +--> screenflow_capture.mp4
    +--> screenflow_keyframes/
    +--> screenflow_assets.json
    |
    v
Remotion ScreenflowExplainer
    |
    v
final_video.mp4
```

## 项目内新增模块建议

```text
content_asset_mvp/
├── app/
│   ├── screenflow_builder.py
│   ├── screenflow_runner.py
│   ├── screenflow_targets.py
│   └── screenflow_qc.py
└── video_engine/remotion/src/
    ├── compositions/
    │   └── ScreenflowExplainer.tsx
    └── components/screenflow/
        ├── BrowserChrome.tsx
        ├── CursorLayer.tsx
        ├── ClickRipple.tsx
        ├── ScrollViewport.tsx
        ├── FocusBox.tsx
        ├── ZoomLens.tsx
        └── StepCallout.tsx
```

## screenflow_plan.json 草案

```json
{
  "schema_version": 1,
  "content_id": "github_browser_use_demo",
  "source_url": "https://github.com/browser-use/browser-use",
  "capture": {
    "viewport": {"width": 1440, "height": 900},
    "device_scale_factor": 1,
    "fps": 30,
    "duration_target_seconds": 18,
    "theme": "browser_dark"
  },
  "page_profile": {
    "kind": "github_repo",
    "title": "browser-use/browser-use",
    "primary_goal": "展示这是一个 AI 浏览器代理项目，并找到 quickstart 证据"
  },
  "steps": [
    {
      "id": "open_repo",
      "type": "goto",
      "url": "https://github.com/browser-use/browser-use",
      "duration_ms": 1200
    },
    {
      "id": "focus_header",
      "type": "focus",
      "target": {"strategy": "semantic", "name": "repo header"},
      "label": "项目身份",
      "duration_ms": 1400
    },
    {
      "id": "scroll_readme",
      "type": "scroll_to",
      "target": {"strategy": "text", "contains": "Quickstart"},
      "duration_ms": 1600,
      "easing": "inertial"
    },
    {
      "id": "click_docs",
      "type": "click",
      "target": {"strategy": "text", "contains": "Docs"},
      "duration_ms": 900,
      "cursor": {"style": "human", "click_ripple": true}
    },
    {
      "id": "focus_proof",
      "type": "focus",
      "target": {"strategy": "selector", "value": "article"},
      "label": "README 证据",
      "duration_ms": 1800
    }
  ],
  "safety": {
    "allowed_domains": ["github.com"],
    "read_only": true,
    "no_login": true,
    "no_form_submit": true
  }
}
```

## 页面理解层

页面理解层的任务不是执行操作，而是回答：

```text
这个页面是什么类型？
哪里有视觉证据？
哪里值得停留？
哪里适合点击？
哪里适合滚动展示？
哪些内容不能展示？
```

### GitHub repo 页面

可自动识别：

- repo header
- stars / forks / license
- README 首屏
- install / quickstart
- examples
- releases
- issues / discussions
- README 图片

推荐动作：

```text
打开 repo -> 聚焦标题和 star -> 滚到 README -> 聚焦 install/example -> 点击 releases 或 docs
```

### 产品官网

可自动识别：

- hero title
- primary CTA
- demo / screenshot
- pricing
- docs
- customers / testimonials
- changelog

推荐动作：

```text
打开官网 -> 聚焦 hero -> 点击 docs/demo -> 滚动 feature -> 聚焦 proof point
```

### 文档站

可自动识别：

- quickstart
- installation
- code block
- API reference
- nav tree
- search box

推荐动作：

```text
打开 docs -> 搜索关键词 -> 点击 quickstart -> 聚焦代码块 -> 滚到 API
```

### Product Hunt / 社区页

可自动识别：

- product title
- tagline
- upvotes
- comments
- launch date
- maker profile
- website link

推荐动作：

```text
打开页面 -> 聚焦 title/upvotes -> 滚到 comments -> 聚焦用户反馈 -> 点击官网
```

## 动作规划层

动作规划层应该由规则 + LLM 共同完成。

规则负责稳定性：

```text
github_repo -> 固定优先看 README / stars / releases
docs_site -> 固定优先看 quickstart / install / code block
product_page -> 固定优先看 hero / demo / pricing
```

LLM 负责语义判断：

```text
这个按钮是不是 docs？
这一段是不是 quickstart？
这张图是不是 demo？
这里有没有可做短视频证据的内容？
```

输出只允许结构化 JSON，不允许直接执行浏览器动作。

## 执行层

`screenflow_runner.py` 使用 Playwright 执行 `screenflow_plan.json`。

执行原则：

```text
1. 默认 read-only
2. 不登录
3. 不提交表单
4. 不购买、不关注、不点赞
5. 不越过 robots/平台限制
6. 失败时降级截图，不伪造成成功
```

### 鼠标轨迹

不要用直线瞬移。

建议算法：

```text
起点 -> 控制点 A -> 控制点 B -> 终点
贝塞尔曲线采样
速度先加速后减速
目标附近微抖动
点击后 ripple
滚动有惯性
```

可借鉴 ghost-cursor，但不一定直接引入它。项目可自己实现一个轻量版，输出事件：

```json
{
  "type": "cursor_move",
  "from": {"x": 220, "y": 180},
  "to": {"x": 840, "y": 430},
  "duration_ms": 760,
  "points": [
    {"t": 0, "x": 220, "y": 180},
    {"t": 0.5, "x": 510, "y": 310},
    {"t": 1, "x": 840, "y": 430}
  ]
}
```

### 滚动

滚动要有“看起来像人”的节奏：

```text
短停顿 -> 滚一段 -> 减速 -> 停留阅读 -> 再滚
```

不要匀速滚到底。匀速滚动很像脚本，短视频观感也差。

建议：

```json
{
  "type": "scroll",
  "deltaY": 680,
  "duration_ms": 1300,
  "profile": "inertial",
  "pause_after_ms": 500
}
```

## 录制方式

有两条路线。

### A. Playwright 录制真实浏览器视频

优点：

- 最真实。
- DOM、图片、字体、布局都是原网页。
- 适合网页证据镜头。

缺点：

- 鼠标可见性要额外注入。
- 截图质量和页面加载受网络影响。
- 批量跑时浏览器资源消耗大。

输出：

```text
screenflow_capture.mp4
screenflow_events.json
screenflow_keyframes/*.png
```

### B. 截图 + Remotion 合成伪录屏

优点：

- 稳定、可控、便于加电影感。
- 鼠标、点击、滚动、聚焦都能由 Remotion 精确控制。
- 适合批量生产。

缺点：

- 如果只用静态截图，真实网页内部细节变化不如真录屏。

推荐本项目主用 B，必要时补 A。

```text
Playwright full-page screenshot / element screenshot
+ DOM bbox
+ screenflow_events.json
-> Remotion 合成滚动视窗、鼠标、点击、聚焦框
```

## 与 Remotion 的衔接

Remotion 不应该负责打开网页。Remotion 只负责包装素材和动效。

输入：

```text
screenflow_capture.mp4
screenflow_events.json
screenflow_keyframes/
subtitle_plan.json
director_plan.json
```

输出：

```text
ScreenflowExplainer shot
```

推荐 props：

```json
{
  "mode": "synthetic_browser_recording",
  "captureVideo": "render_inputs/demo/screenflow_capture.mp4",
  "events": [],
  "keyframes": [],
  "browserChrome": {
    "url": "github.com/browser-use/browser-use",
    "theme": "dark"
  },
  "overlays": {
    "cursor": true,
    "clickRipple": true,
    "focusBox": true,
    "callout": true
  }
}
```

## 质量标准

自动伪录屏必须满足：

```text
1. 画面来源可追溯
2. 每个点击/滚动都有事件记录
3. 字幕不遮挡关键 UI
4. 光标不挡标题/按钮
5. 页面加载失败不能伪造成成功
6. 不展示敏感 cookie/token/session
7. 不对外部网站做写操作
8. 片中如为模拟界面，应在内部 metadata 标记 simulated
```

## 输出文件结构

建议每个内容包新增：

```text
output/<content_id>/
├── 03_visual/
│   ├── screenflow_plan.json
│   ├── screenflow_events.json
│   ├── screenflow_assets.json
│   └── screenflow_keyframes/
│       ├── step_01_open_repo.png
│       ├── step_02_focus_header.png
│       └── step_03_scroll_readme.png
└── 07_render_output/
    └── screenflow_capture.mp4
```

## MVP 实现顺序

### 第 1 步：GitHub repo 自动录屏

只支持 GitHub repo 页面。

能力：

```text
打开 repo
聚焦 header
读取 stars/license/description
滚到 README
聚焦 install/example
截 3-5 张关键帧
生成 screenflow_events.json
```

### 第 2 步：Remotion 合成鼠标与聚焦框

不急着做真录屏。先让 Remotion 基于截图合成：

```text
浏览器壳
滚动视窗
鼠标移动
点击 ripple
聚焦框
字幕避让
```

### 第 3 步：产品官网和文档站

新增页面 profile：

```text
product_homepage
docs_site
product_hunt_launch
```

### 第 4 步：browser-use / Stagehand 语义找目标

当规则找不到目标时才调用 Agent。

```text
优先规则
规则失败 -> browser-use/Stagehand
Agent 只返回目标，不直接决定最终剪辑
```

### 第 5 步：批量化与 QC

加：

```text
screenflow_qc.json
加载成功率
目标命中率
关键帧清晰度
字幕遮挡检测
敏感信息检测
```

## CLI 草案

```bash
python -m app.main --screenflow-capture "<content_id>"

python -m app.main \
  --screenflow-url "https://github.com/browser-use/browser-use" \
  --screenflow-profile github_repo \
  --mock
```

也可以作为 `--render-video` 的前置步骤：

```bash
python -m app.main --render-video "<content_id>" --with-screenflow
```

## 安全边界

必须坚持：

```text
1. 不登录第三方账号
2. 不绕验证码
3. 不自动点赞/评论/关注/购买
4. 不读取或展示 cookie/token
5. 不把模拟界面说成真实产品截图
6. 外部网页只做 read-only 研究和展示
```

推荐在 plan 里强制写：

```json
{
  "safety": {
    "read_only": true,
    "no_login": true,
    "no_form_submit": true,
    "no_payment": true,
    "no_social_action": true
  }
}
```

## 最终判断

本项目最适合的不是“录屏工具”，而是“自动 screenflow 生成器”。

主线应该是：

```text
Playwright 执行动作
browser-use / Stagehand 找语义目标
ghost-cursor 思路生成鼠标手感
Remotion 做电影感包装
screenflow_qc 保证不翻车
```

这样能做到全自动、可批量、可追溯，也能接入当前已有的 `browser_agent_assets.json`、`visual_asset_pack`、`director_plan` 和 `shot_list`。

