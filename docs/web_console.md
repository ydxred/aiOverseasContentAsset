# Web 控制台

## 启动

```bash
cd content_asset_mvp
source .venv/bin/activate
python -m app.web --host 0.0.0.0 --port 8000
```

WSL2 主机用浏览器访问 `http://127.0.0.1:8000`。

## 主要面板

### `/`（首页）
- 系统状态总览
- 当前 mock 模式 / DB 状态 / TTS 配置

### `/videos`（成片库）
- 列出所有 `output/<content_id>/07_render_output/final_video*.mp4`
- 内嵌播放器，可直接听
- 点开看完整 QC 报告（LUFS / LRA / shot_count / score）
- 关键：**A/B 不同 TTS 版本**最快的入口

### `/sources`（选题板）
- `data/sources.yaml` 正式源池（read-only）
- `data/candidate_sources.json` 待批准候选
- 「approve」按钮把候选移到正式池
- 显示历史发布表现（带反馈权重）

### `/feedback`（反馈板）
- 已发布视频的点赞 / 评论 / 完播率收集
- 手动录入 → 自动算分 → 回写 source weight

### `/reviews`（审核板）
- 当前 `publish_review.json` status="pending" 的内容
- 看脚本 + 风险报告 + QC 后手动 approve / reject

## API 端点

```
GET  /api/health                    # 健康检查
GET  /api/videos                    # 成片列表 JSON
GET  /api/videos/{content_id}       # 单个视频详情 + QC
GET  /api/sources                   # 源池
POST /api/sources/approve_candidate # 候选 → 正式
POST /api/reviews/{content_id}      # 推 publish_review 状态
GET  /api/feedback/{content_id}     # 反馈记录
POST /api/feedback/{content_id}     # 录入新反馈
```

## Mock 模式

`CONTENT_ASSET_MOCK=true` 时所有 API 返回固定数据，Web 控制台仍能跑——
适合开发调试 UI 时不想触发真实流水线。

## 跨设备访问

WSL2 默认 `127.0.0.1:8000` 在 Windows 主机浏览器能通。
不通的话用 WSL IP：

```bash
hostname -I | awk '{print $1}'
# → 172.28.245.54
# 浏览器开 http://172.28.245.54:8000
```

WSL2 IP 重启后会变，不要在 Windows 收藏栏写死。

## 故障

| 现象 | 原因 / 解决 |
|---|---|
| Connection refused | server 没启 — `ps -ef \| grep "app.web"` 看进程 |
| 视频列表为空 | `output/` 目录权限或文件不存在 |
| 视频播放卡 | 浏览器不支持 HEVC / 文件路径中文乱码 — 改用 H.264 base profile |
| `psycopg.OperationalError` | DB 没启，控制台仍跑（DB 部分降级）|

