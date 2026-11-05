# 智巡 InspectAgent · 端云接口契约 v2.0

> 云端实现与本文档同步（2026-11-04）。字段命名规则：**小驼峰**，DB 列名 / JSON key / ArkTS 字段三者同名。
> 时间格式统一 `YYYY-MM-DD HH:mm:ss`。全局主纲见 `d:\d\未来杯\智巡InspectAgent_数据与接口总体规划.md`，冲突时以主纲为准。

- Base URL：`http://<云端IP>:8000`
- 在线调试：<http://localhost:8000/docs>
- WS 地址：`ws://<云端IP>:8000/ws/agent/{sessionId}`

---

## 0. 接口总表

共 **39** 个端点（含静态资源与 WS）。

| # | 方法 | 路径 | 用途 | 端侧调用 |
|---|---|---|---|---|
| 1 | GET | `/` | 跳转 Web 测试台 | — |
| 2 | GET | `/health` | 健康检查 / mock 判定 | 可选 |
| 3 | GET | `/docs` | Swagger 交互文档 | — |
| 4 | GET | `/media/{fileName}` | 现场图片/缩略图访问（**需 token**） | 报告页 |
| 5 | GET | `/web/` | Web 测试台静态页 | — |
| 6 | GET | `/api/v1/config` | 拉取阈值与开关 | 启动时 |
| 7 | GET | `/api/v1/tasks` | 任务列表 | 任务页 |
| 8 | GET | `/api/v1/tasks/{taskId}` | 任务详情 | 任务页 |
| 9 | PATCH | `/api/v1/tasks/{taskId}/status` | 改任务状态 | 任务页 |
| 10 | GET | `/api/v1/devices` | 设备台账列表 | 设备页 |
| 11 | GET | `/api/v1/devices/{deviceId}` | 设备档案 | 设备页 / 巡检页 |
| 12 | GET | `/api/v1/workorders` | 工单列表 | 工单页 |
| 13 | GET | `/api/v1/workorders/{woId}` | 工单详情 | 工单页 |
| 14 | PATCH | `/api/v1/workorders/{woId}/status` | 工单流转 | 工单页 |
| 15 | POST | `/api/v1/inspections/upload` | **巡检上报（带图，推荐）** | 巡检页 |
| 16 | POST | `/api/v1/inspections` | 巡检上报（纯 JSON） | 兜底 |
| 17 | GET | `/api/v1/inspections` | 巡检记录列表 | 新增：历史页 |
| 18 | GET | `/api/v1/inspections/{id}` | 巡检详情 | 新增：历史页 / 报告页 |
| 19 | GET | `/api/v1/kb/stats` | 知识库状态 | — |
| 20 | POST | `/api/v1/kb/rebuild` | 后台重建索引 | — |
| 21 | WS | `/ws/agent/{sessionId}` | Agent 流式事件 | 巡检页 |
| 22 | GET | `/api/v1/traces` | Trace 列表 | 新增：回放页 |
| 23 | GET | `/api/v1/traces/{traceId}` | Trace 详情（可回放） | 新增：回放页 |
| 24 | POST | `/api/v1/admin/archive` | 触发归档 | 运维 |
| 25 | DELETE | `/api/v1/admin/archive` | 清理过期数据 | 运维 |
| 26 | GET | `/api/v1/alerts` | 告警列表 | 新增：告警中心 |
| 27 | POST | `/api/v1/alerts/{alertId}/resolve` | 告警处理 | 新增：告警中心 |
| 28 | GET | `/api/v1/stats/tokens` | Token 用量 / 成本 | 新增：运维页 |
| 29 | GET | `/api/v1/sync/snapshot` | 端侧全量 / 增量同步 | 新增：启动时 |
| 30 | POST | `/api/v1/sync/conflict` | 冲突仲裁 | 新增：同步 |
| 31 | POST | `/api/v1/auth/login` | 登录换 token | 启动时 |
| 32 | POST | `/api/v1/auth/refresh` | 刷新 token | 401 时 |
| 33 | POST | `/api/v1/auth/logout` | 登出 | 我的页 |
| 34 | GET | `/api/v1/auth/me` | 当前用户 | 我的页 |
| 35 | GET | `/api/v1/device-types` | 设备类型 + 检查项模板 | 任务页 |
| 36 | GET | `/api/v1/device-types/{deviceType}/checklist` | 单类型检查项模板 | 任务页 |
| 37 | GET | `/api/v1/system/media-policy` | 媒体生命周期策略 | 运维 |
| 38 | DELETE | `/api/v1/inspections/{id}` | 删除巡检（admin，连带删媒体） | 新增：历史页 |
| 39 | GET | `/api/v1/inspections/{id}/report.pdf` | 导出巡检报告 PDF | 新增：报告页 |

图例：**端侧调用**列中标注"新增"的，表示端侧 `HttpService.ets` 目前尚未封装。

---

## 1. 通用

### `GET /health`

```json
{ "ok": true, "env": "dev", "mock": false, "llm": true, "vision": true }
```

`mock: true` 表示云端未配置任何模型 Key，返回确定性假数据。**录屏前必须为 false。**

### `GET /api/v1/config` → `ServerConfig`

```json
{ "confidenceThreshold": 0.6, "wsEnabled": true, "maxImageMb": 10,
  "mock": false, "llm": true, "vision": true, "serverTime": "2026-11-04 16:20:00" }
```

`confidenceThreshold` 用于端侧同步展示"低于该值转人工"的判定线。

---

## 2. 任务 / 设备 / 工单

### `GET /api/v1/tasks` → `TaskItem[]` 或分页信封

可选参数：`page`、`pageSize`（默认 20，上限 200）、`status`、`deviceId`。

- 不传 `page` → 返回数组（旧客户端零改动）
- 传 `page` → `{ "items": [...], "total": 6, "page": 1, "pageSize": 20 }`

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | `T-1001` |
| deviceId | string | 关联设备 |
| title | string | 任务标题 |
| deviceName / location | string | 设备名 / 位置 |
| status | string | 待巡检 / 进行中 / 已完成 |
| priority | string | 高 / 中 / 低 |
| deadline | string | 截止日期 |
| assignee | string | 指派人 |
| updatedAt | string | 服务端版本时间（冲突上报时填 `cloud_version`） |
| checklist / checklistTotal / checklistDone / inspectionId / isCurrent | — | v6 新增，见 11.3 |

`GET /api/v1/tasks/{taskId}` 返回单个；不存在 → 404（统一错误结构，见第 9 节）。

`PATCH /api/v1/tasks/{taskId}/status`

```json
{ "status": "已完成", "inspectionId": "IN-20261104-f980" }
```

### `GET /api/v1/devices` → `DeviceProfile[]` 或分页信封

可选参数：`page`、`pageSize`、`type`（如 `低压配电柜`）。

```json
{ "id": "D-3001", "name": "1号低压配电柜", "type": "低压配电柜",
  "location": "配电房A区", "ratedTemp": 70.0, "ratedHumidity": 80.0,
  "installDate": "2023-06-01", "lastInspectAt": "2026-11-04 16:30:00",
  "history": "2026-08-12 接头温度 66℃（偏高）；2026-09-20 正常", "qrCode": "D-3001" }
```

`GET /api/v1/devices/{deviceId}` 返回单个；设备不存在返回空档案（不 404）。

### `GET /api/v1/workorders` → `WorkOrder[]` 或分页信封

可选参数：`page`、`pageSize`、`status`、`level`、`deviceId`。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | `WO-9F2A1C` |
| inspectionId / taskId / deviceId / deviceName | string | 关联 |
| level | string | 正常 / 关注 / 异常 / 紧急 |
| description | string | 故障描述 |
| assignee | string | 处理人 |
| status | string | 待处理 / 处理中 / 已闭环 |
| handleNote | string | 处理说明 |
| createdAt / closedAt | string | 时间 |
| updatedAt | string | 服务端版本时间（冲突上报时填 `cloud_version`） |

`PATCH /api/v1/workorders/{woId}/status`

```json
{ "status": "已闭环", "handleNote": "已紧固接头并复测 42℃" }
```

---

## 3. 巡检上报（核心）

### `POST /api/v1/inspections/upload`（带图，推荐）

`multipart/form-data`：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| image | file | 否 | JPEG / PNG，**≤10MB** |
| audio | file | 否 | 录音留证，初赛不转写 |
| payload | text | 是 | **JSON 字符串**（结构 = `InspectReq`） |

`payload` 示例：

```json
{
  "taskId": "T-1001",
  "deviceId": "D-3001",
  "deviceName": "1号低压配电柜",
  "deviceType": "低压配电柜",
  "voiceText": "A相母线接头红外测温85度，闻到轻微焦味，指示灯正常",
  "location": "配电房A区",
  "operator": "张三",
  "capturedAt": "2026-11-04 16:20:00",
  "mode": "detailed",
  "sensor": { "temperature": 78.5, "humidity": 62, "noise": 55, "simulated": false },
  "clarifications": null
}
```

| 字段 | 说明 |
|---|---|
| deviceType | 视觉分派依据，六选一：低压配电柜 / 高压柜 / 干式变压器 / 直流屏 / 电缆沟 / 消防器材 |
| mode | `quick`（单次视觉判读） / `detailed`（四工具精判） |
| capturedAt | 端侧采集时刻，离线补传时用于还原时间线 |
| sensor.simulated | 板子无真实传感器时为 `true`，**必须如实传** |
| clarifications | 第二轮补答，`{"answers": ["...", "..."]}` |

> 字段名必须是 `image` / `audio` / `payload`；把业务字段平铺成独立 form 字段会导致
> `voiceText` 等全部为空（会写入脏记录）。

### `POST /api/v1/inspections`（纯 JSON，无图）

Body 直接是 `InspectReq`。

### 响应 `InspectResp`

```json
{
  "sessionId": "a1b2c3d4e5f6",
  "inspectionId": "IN-20261104-f980",
  "imageUrl": "/media/IN-20261104-f980.jpg",
  "level": "紧急",
  "confidence": 0.47,
  "advice": "A相母线接头 85℃ 严重超限（限值 70℃）且伴随焦味，立即停电处理。",
  "findings": [
    { "item": "母线接头温度", "value": "85℃（限值 70℃）", "abnormal": true, "basis": "语音描述·未经视觉确认" },
    { "item": "柜体外观", "value": "无破损、无放电痕迹", "abnormal": false, "basis": "视觉判读" }
  ],
  "voiceSlots": { "rawText": "...", "slots": { "parts": ["A相母线接头"],
                "phenomena": ["焦味"], "readings": [{"item":"温度","value":"85","unit":"℃","approx":false}],
                "sensory": ["嗅觉"], "actions": [] }, "negatives": ["无异响"], "severity": "明显", "confidence": 0.8 },
  "vision": { "scene": "低压配电柜正面", "readable": true, "indicators": [], "defects": [],
              "environment": { "积水": false }, "unreadable": [], "riskHint": "" },
  "steps": [
    { "name": "任务规划", "status": "done", "detail": "检查项：温度/外观/气味/指示灯", "durationMs": 320, "subSteps": [] },
    { "name": "语音解析", "status": "done", "detail": "...", "durationMs": 2100, "subSteps": [] },
    { "name": "视觉判读", "status": "done", "detail": "...", "durationMs": 5200, "subSteps": [] },
    { "name": "台账比对", "status": "done", "detail": "...", "durationMs": 15, "subSteps": [] },
    { "name": "手册检索", "status": "done", "detail": "...", "durationMs": 40, "subSteps": [] },
    { "name": "定级决策", "status": "done", "detail": "紧急（置信度 0.47）", "durationMs": 1800,
      "subSteps": [ { "text": "Round 1: 调 search_manual(...)", "level": 3, "status": "info" } ] }
  ],
  "workOrderId": "WO-9F2A1C",
  "needHuman": true,
  "mock": false,
  "durationMs": 117500,
  "followUpQuestions": ["柜内是否有放电声或异响？", "接头螺栓是否有变色或氧化？", "上次巡检后是否做过紧固处理？"],
  "incompleteFields": ["visual_unreadable", "sensor_missing"],
  "memories": [ { "inspectionId": "IN-20261020-xxxx", "level": "异常", "summary": "接头温度 76℃ 偏高", "capturedAt": "2026-10-20 10:00:00" } ]
}
```

关键字段：

| 字段 | 说明 |
|---|---|
| level | 四档：正常 / 关注 / 异常 / 紧急 |
| confidence | 0~1；**< 0.60 → needHuman = true** |
| findings | 观测事实，渲染成证据卡片 |
| steps | 六步任务流；`subSteps` 为层级化推理细节（level 1/2/3） |
| workOrderId | 仅异常 / 紧急时生成 |
| followUpQuestions | 最多 3 个反问，端侧弹窗补答 |
| incompleteFields | 缺失字段标记，用于 UI 提示 |
| memories | 命中的历史记忆 |
| mock | true 时端侧须显示角标 |

### `GET /api/v1/inspections?limit=50`

可选参数：`page`、`pageSize`、`level`、`deviceId`、`startTime`、`endTime`（时间字符串，含边界）。
不传 `page` 返回数组，传了返回 `{items,total,page,pageSize}`。

返回 **`SyncInspection` 摘要 DTO**（与同步快照同一结构，不含 findings / steps）：

```json
{ "inspectionId": "IN-20261105-5c8e", "taskId": "T-1001", "deviceId": "D-0001",
  "deviceName": "低压配电柜", "location": "配电房A", "operator": "王工",
  "level": "紧急", "confidence": 0.47, "advice": "...",
  "imageUrl": "/media/20261105_093803_f9eb47.jpg",
  "imageAbsoluteUrl": "http://192.168.1.10:8000/media/20261105_093803_f9eb47.jpg",
  "workOrderId": "WO-9F2A1C", "capturedAt": "...", "createdAt": "...",
  "updatedAt": "...", "needHuman": true, "mock": false }
```

### `GET /api/v1/inspections/{inspectionId}`

返回 **`InspectResp`（与 WS `final` 完全同一个 DTO）**，见第 3 节响应定义。
额外稳定字段：`taskId / deviceId / deviceName / location / operator / capturedAt / voiceText /
imageUrl / imageAbsoluteUrl`，端侧报告页可直接绑定，无需再猜字段名。

`step` 元素字段为 `name / status / detail / durationMs / subSteps`（**没有 step / title 字段**）。

不存在 → 404。

---

## 4. 知识库

### `GET /api/v1/kb/stats`

```json
{ "index_built": false, "total": 110, "mode": "keyword",
  "chroma_dir": "data/chroma", "embedding_model": "local-onnx(default)" }
```

`mode` ∈ `vector` / `keyword`。

### `POST /api/v1/kb/rebuild`

```json
{ "started": true, "expected": 110, "message": "向量索引正在后台重建，稍后可用 /kb/stats 查看状态" }
```

后台线程执行，立即返回；重建完成后 `kb/stats` 的 `index_built` 变为 true。

---

## 5. WebSocket 流式

`ws://<云端IP>:8000/ws/agent/{sessionId}`

**端侧发送**（首条必须是 `start`）：

```json
{ "type": "start",
  "payload": { "taskId": "T-1001", "deviceId": "D-3001", "deviceName": "1号低压配电柜",
               "deviceType": "低压配电柜", "voiceText": "接头有点烫", "location": "配电房A区",
               "sensor": { "temperature": 78.5, "humidity": 62, "simulated": false },
               "imageBase64": "<JPEG base64，不带 data: 前缀>" } }
```

**服务端推送事件**：

| type | 载荷 | 端侧动作 |
|---|---|---|
| `step` | `{"step":{"name","status","detail","durationMs","subSteps"}}` | 更新步骤卡片；`subSteps` 按 level 缩进渲染 |
| `sub_step` | `{"stepName":"定级决策","subStep":{"text","level","status"}}` | 追加一行推理细节（可流式追加） |
| `token` | `{"text":"检"}` | 逐字追加建议文本（打字机） |
| `memory_hit` | `{"memories":[...]}` | 展示"我记得上次…"卡片 |
| `final` | `{"data":{...InspectResp}}` | 渲染结论 / 证据 / 工单 |
| `end` | `{}` | 本轮结束，连接可复用 |
| `error` | `{"message":"..."}` | 弹提示，可重试 |

`status` 取值：`pending` / `running` / `done` / `failed`；`subStep.status`：`info` / `ok` / `warn` / `fail`。

> **兜底约定**：WS 连不上或中断时，端侧必须自动降级到
> `POST /api/v1/inspections/upload` 一次拿全量结果，不能因 WS 失败导致功能不可用。

---

## 6. 可观测

### `GET /api/v1/traces?deviceId=D-3001&limit=20`

可选参数：`deviceId`、`level`、`startTime`、`endTime`、`page`、`pageSize`、`limit`。

```json
{ "traces": [ { "id": 5, "sessionId": "a1b2c3d4", "inspectionId": "IN-20261104-f980",
                "deviceId": "D-3001", "deviceName": "1号低压配电柜", "level": "紧急",
                "confidence": 0.47, "durationMs": 117500, "createdAt": "2026-11-04 16:31:00" } ],
  "total": 5, "page": 1, "pageSize": 20 }
```

### `GET /api/v1/traces/{traceId}`

```json
{ "id": 5, "eventCount": 120, "events": [
  { "seq": 1, "type": "sub_step", "timestamp": "2026-11-04 16:31:00",
    "stepName": "任务规划", "payload": { "text": "🔍 命中 3 条历史巡检记忆" } },
  { "seq": 2, "type": "step", "timestamp": "2026-11-04 16:31:00",
    "stepName": "任务规划", "payload": { "name": "任务规划", "status": "running" } } ] }
```

事件已标准化为 `{seq, type, timestamp, stepName, payload}`：`seq` 单调递增可排序回放；
`type` ∈ `step / sub_step / token / memory_hit / final / error`；`payload` 为原事件载荷
（旧数据自动兼容映射，无需端侧区分新旧）。

### `POST /api/v1/admin/archive?days=90`

```json
{ "archived": 3, "cutoff": "2026-08-06 16:20:00" }
```

归档规则：`createdAt < cutoff` 且**没有待处理工单**的巡检才搬走，同时清理其 findings / media / 记忆。

### `DELETE /api/v1/admin/archive?days_memories=180&days_traces=30`

```json
{ "memories_deleted": 12, "traces_deleted": 40 }
```

### `GET /api/v1/alerts?unresolved=true&limit=50`

可选参数：`level`、`category`、`startTime`、`endTime`、`page`、`pageSize`。

```json
{ "alerts": [ { "id": 7, "level": "warn", "category": "rag",
                "message": "Chroma 向量检索不可用，已退化关键词兜底",
                "detail": "...", "resolved": false, "resolvedBy": "", "resolvedAt": "",
                "resolveNote": "", "createdAt": "2026-11-04 16:20:00" } ],
  "total": 2, "page": 1, "pageSize": 20 }
```

### `POST /api/v1/alerts/{alertId}/resolve`

请求体（可选）：`{ "note": "已到现场处理" }`

```json
{ "ok": true, "alert": { "id": 7, "resolved": true, "resolvedBy": "U-0001",
                         "resolvedAt": "2026-11-05 10:00:24", "resolveNote": "已到现场处理" } }
```

`resolvedBy` 取自当前登录 token 的 userId，非前端传参。

### `GET /api/v1/stats/tokens?days=7`

```json
{ "days": 7, "since": "2026-10-28 00:00:00",
  "total": { "promptTokens": 18611, "completionTokens": 16558,
             "totalTokens": 35169, "costCny": 0.1697, "calls": 22 },
  "byDay":    [ { "day": "2026-11-04", "tokens": 35169, "cost": 0.1697, "calls": 22 } ],
  "byCaller": [ { "caller": "react", "tokens": 11795, "cost": 0.07, "calls": 6 } ],
  "byModel":  [ { "model": "deepseek-v4-pro-ga-260813", "tokens": 29644, "cost": 0.09, "calls": 20 } ],
  "byUser":   [ { "userId": "U-0001", "tokens": 12000, "cost": 0.05, "calls": 8 } ],
  "byDevice": [ { "deviceId": "D-3001", "tokens": 9000, "cost": 0.04, "calls": 6 } ],
  "bySession":[ { "sessionId": "a1b2c3d4", "tokens": 9000, "cost": 0.04, "calls": 6 } ] }
```

`caller` 取值：`plan` / `decide` / `react` / `review` / `followup` / `voice` / `vision` / `stream`。
`userId` / `deviceId` 由 `sessionId` 反查填入；老数据可能为空串。

---

## 7. 端侧同步

### `GET /api/v1/sync/snapshot?deviceId=&since=`

端侧 App 启动拉一次全量；之后带 `since` 做增量。

```json
{ "since": "2026-11-01 00:00:00", "sinceField": "updatedAt",
  "serverTime": "2026-11-05 09:58:54",
  "devices": [...], "tasks": [...], "workorders": [...],
  "inspections": [ /* SyncInspection 摘要，见 3.4 */ ],
  "deleted": [] }
```

| 参数 / 字段 | 说明 |
|---|---|
| since | 可选；**统一按 `updatedAt > since`** 过滤（tasks / workorders / inspections 三张表同一规则） |
| sinceField | 固定 `updatedAt`，明确版本依据，不再混用 capturedAt / createdAt |
| serverTime | 客户端存下来作为**下一次** `since`（不是本地时间，避免时钟漂移漏数据） |
| deleted | 预留删除墓碑数组，当前无删除接口，恒为空 |
| 上限 | 每类最多 5000 条 |

`inspections` 固定为 `SyncInspection` 摘要（不含 findings / steps），详情走
`GET /inspections/{id}`。空 `since` = 全量；非空 = 增量。

### `POST /api/v1/sync/conflict`

请求（驼峰与下划线都接受）：

```json
{ "table": "inspections", "id": "IN-xxx",
  "device_version": "2026-11-05 09:59:00", "cloud_version": "2026-11-05 09:59:00",
  "device_changes": { "level": "关注" } }
```

`table` 只能是 `inspections / workorders / tasks`。字段白名单：

| table | 允许端侧改的字段 |
|---|---|
| inspections | `level, confidence, advice, needHuman` |
| workorders | `status, handleNote, assignee` |
| tasks | `status, inspectionId` |

响应：

```json
{ "resolved": true, "winner": "device", "cloudVersion": "2026-11-05 10:01:00",
  "applied": ["level"], "rejected": ["foo"], "final": { /* 最新完整记录 */ }, "message": "" }
```

仲裁规则：

1. 非白名单字段一律进 `rejected`，不落库；
2. `cloud_version` == 服务端当前 `updatedAt` → 云端没被别人改过，接受端侧改动（`winner=device`）；
3. 否则云端记录已变更，以云端为准（`winner=cloud`，`applied=[]`）；
4. 记录不存在 → 视为**云端已删除**：`resolved=false`，`winner=cloud`，`final={}`，
   端侧应删除本地副本（这就是删除冲突的处理规则）。

端侧统一用 `final` 覆盖本地副本，并用响应里的 `cloudVersion` 更新本地版本号。

### `GET /api/v1/system/media-policy`

```json
{ "urlRule": "imageUrl 为 /media/{fileName}；imageAbsoluteUrl 为完整地址（服务端已按当前 token 附加 ?token=，端侧 Image 可直接加载）",
  "retentionDays": 90, "urlExpiresDays": 90, "requiresAuth": true,
  "keepFailedUploads": false, "thumbnailSupported": true, "pdfExportSupported": true,
  "deleteWithInspection": true, "deleteApiSupported": true, "note": "..." }
```

媒体生命周期统一策略（v8 起全部已落地，不只是声明）：

| 问题 | 结论 |
|---|---|
| 原图/录音保留多久 | `MEDIA_RETENTION_DAYS`（默认 90 天） |
| 谁来自动清理 | 服务内置定时任务，每 `CLEANUP_INTERVAL_HOURS`（默认 24）小时执行一次；也可手动 `DELETE /admin/archive` |
| 清理范围 | **只删已归档巡检的媒体**，主表仍在的图片不删 |
| 失败上传是否保留 | 不保留（落盘发生在巡检成功之后） |
| 删除巡检是否删媒体 | 是：`DELETE /inspections/{id}` 同时删原图、缩略图、findings，并写同步墓碑 |
| 缩略图 | 支持：`imageThumbUrl` / `imageThumbAbsoluteUrl`（长边 480px JPEG） |
| PDF 导出 | 支持：`GET /inspections/{id}/report.pdf`（A4，含判读明细与现场照片） |
| 图片鉴权与有效期 | `/media` **校验 token**（`Authorization: Bearer` 或 `?token=`）；不做签名 URL，超过保留期随文件清理失效 |

`imageUrl` 始终是相对路径（不变），跨网访问请读 `imageAbsoluteUrl`（绝对地址，
基址优先取 `PUBLIC_BASE_URL` 环境变量，其次取请求来源）。

---

## 8. 数据契约（枚举速查）

| 名称 | 取值 |
|---|---|
| `level` | 正常 / 关注 / 异常 / 紧急 |
| `task.status` | 待巡检 / 进行中 / 已完成 |
| `task.priority` | 高 / 中 / 低 |
| `workorder.status` | 待处理 / 处理中 / 已闭环 |
| `step.status` | pending / running / done / failed |
| `subStep.status` | info / ok / warn / fail |
| `mode` | quick / detailed |
| `alert.level` | info / warn / error / critical |
| `alert.category` | llm / rag / db / tool / vision |

---

## 9. 错误码（v7 起统一结构）

所有错误（含中间件 401、参数校验 422、未捕获 500）返回**同一个结构**：

```json
{ "code": "NOT_FOUND", "message": "巡检记录不存在", "detail": "", "traceId": "e52a9caac6c3430a" }
```

响应头同时带 `X-Trace-Id`，与服务端日志一致，报障时直接把 `traceId` 发给云端即可定位。

| HTTP | code | 含义 | 端侧处理 |
|---|---|---|---|
| 400 | `BAD_REQUEST` | `payload` JSON 解析失败 | 检查字符串是否转义正确 |
| 401 | `UNAUTHORIZED` | 未登录 / token 过期 | 用 refreshToken 换新 token，失败则跳登录 |
| 403 | `FORBIDDEN` | 无权限 | 提示无权限 |
| 404 | `NOT_FOUND` | 任务 / 设备 / 工单 / 巡检 / Trace / 告警不存在 | 提示并回列表 |
| 409 | `CONFLICT` | 业务状态冲突，如工单已闭环再次回退 | 提示"该工单已闭环"，刷新详情 |
| 413 | `PAYLOAD_TOO_LARGE` | 图片 > 10MB | 先压缩到长边 ≤1280 再传 |
| 422 | `VALIDATION_ERROR` | 请求体字段类型不符（Pydantic 校验） | 按 `/docs` 的定义修正，`detail` 里有具体字段 |
| 500 | `INTERNAL_ERROR` | 云端异常 | 提示"服务暂时不可用"，保留本地缓存，带 `traceId` 反馈 |

---

## 10. 变更规则

1. **改字段必须改本文档**，并同步 `app/schemas.py`、端侧 `ets/model/InspectModels.ets`、主纲 §3/§7
2. 新增字段一律**可选**（给默认值），不许把已有必填字段改没
3. 云端未完成前返回**结构正确的假数据**，字段一个都不能少
4. 新增表 / 端点需同时更新 `docs/database.md` 与第 0 节总表

---

## 11. v6 变更（P0 端侧优化，2026-11）

> **鉴权默认开启**：`AUTH_ENABLED=1` 时，除登录/刷新外的所有 `/api/v1/*` 都必须带
> `Authorization: Bearer <accessToken>`；WS 用 `?token=<accessToken>`。
> 关闭鉴权：`.env` 设 `AUTH_ENABLED=0` 并重启。

### 11.1 登录鉴权（新增 4 个端点）

| 方法 | 路径 | 请求 | 返回 |
|---|---|---|---|
| POST | `/api/v1/auth/login` | `{username, password}` | `TokenPair` |
| POST | `/api/v1/auth/refresh` | `{refreshToken}` | `TokenPair` |
| POST | `/api/v1/auth/logout` | Header Bearer | `{ok: true}` |
| GET | `/api/v1/auth/me` | Header Bearer | `UserInfo` |

`TokenPair`：

```json
{
  "accessToken": "…",
  "refreshToken": "…",
  "tokenType": "Bearer",
  "expiresIn": 7200,
  "user": {"userId": "U-0001", "name": "admin", "role": "admin", "team": "运维中心"}
}
```

- `expiresIn` 单位秒（默认 120 分钟）；refresh 默认 7 天
- token 落库，**服务重启后仍有效**；logout 只吊销当前 access token
- 默认账号（首次建库自动写入）：`admin/admin123`、`inspector/inspector123`
- 401 响应（v7 起统一结构）：`{"code":"UNAUTHORIZED","message":"未登录或 token 已失效","detail":"","traceId":"..."}`

端侧处理：启动时若无 token → 登录页；收到 401 → 用 refreshToken 换新 access；refresh 也 401 → 回登录页。

### 11.2 检查项模板（新增 2 个端点）

| 方法 | 路径 | 返回 |
|---|---|---|
| GET | `/api/v1/device-types` | `[{deviceType, items[]}]`（6 类设备） |
| GET | `/api/v1/device-types/{deviceType}/checklist` | `{deviceType, items[]}` |

`items[]` 元素：`{key, name, required, status}`，`status` ∈ `pending / done / skipped`。
未知设备类型返回 404。

### 11.3 任务新增字段（`GET /tasks`、`GET /tasks/{id}`、`PATCH /tasks/{id}/status` 均返回）

| 字段 | 类型 | 说明 |
|---|---|---|
| `checklist` | array | 检查项，`[{key,name,required,status}]`，默认 6 项 |
| `checklistTotal` | int | 总项数 |
| `checklistDone` | int | 已完成项数（`done` 或 `skipped`） |
| `inspectionId` | string | 该任务对应巡检记录，未巡检为 `""` |
| `isCurrent` | bool | 是否为当前任务（同一 assignee 唯一进行中） |

**服务端强约束**：把某任务置为 `进行中` 时，同 `assignee` 的其他进行中任务自动回到 `待巡检`；
置为 `已完成` 时 `checklist` 全部标记 `done`，并可回传 `inspectionId`。

端侧处理：任务卡进度直接用 `checklistDone/checklistTotal`，不要再本地推导"当前任务"。

### 11.4 上传幂等（`POST /inspections/upload`）

新增可选表单字段 `requestId`（或请求头 `Idempotency-Key`）：

- 同一 `requestId` 重复提交 → **不新建记录**，直接返回首次结果，并带 `"duplicate": true`
- 首次耗时正常（约 2 分钟），重复提交毫秒级返回
- 建议端侧用 `deviceId + 时间戳` 生成，弱网重试时复用同一个值

`InspectResp` 新增字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `duplicate` | bool | true 表示命中幂等、返回的是已有记录 |

---

## 12. v7 变更（P1 / P2 端侧优化，2026-11）

> 本次不新增鉴权逻辑，只补契约稳定性与生产可运维性。所有字段均为**新增可选**，老端侧不改也能跑。

### 12.1 契约稳定化

| 编号 | 改动 | 端侧影响 |
|---|---|---|
| P1-6 | 同步快照 `inspections` 固定为 `SyncInspection` 摘要 DTO；`since` 统一按 `updatedAt > since`；返回 `serverTime` 供下次作 `since`；`deleted` 预留恒空 | 同步逻辑只需认 `SyncInspection` 与 `serverTime` |
| P1-7 | 冲突仲裁加**字段白名单** + 版本比对：`cloud_version == 当前 updatedAt` 时接受端侧改动（`winner=device`），否则云端优先 | 冲突上报按白名单传，读 `winner/final/cloudVersion` |
| P1-9 | 列表接口全部支持 `page/pageSize` + 业务筛选；**不传 page 仍是数组** | 需要分页时传 page，无需改旧解析 |
| P1-10 | 所有巡检出参新增 `imageAbsoluteUrl`（绝对地址）；`imageUrl` 仍是相对路径 | 跨网加载图片直接用 `imageAbsoluteUrl` |
| P1-11 | 历史详情与 WS `final` 共用同一 `InspectResp`；额外稳定字段 `taskId/deviceId/deviceName/location/operator/capturedAt/voiceText` | 报告页字段可直接绑定，不用猜 |
| P1-12 | 新增 `GET /system/media-policy`，统一图片 URL 规则与保留策略（90 天） | 运维/设置页可展示策略 |

### 12.2 生产可运维

| 编号 | 改动 |
|---|---|
| P1-8 | **统一错误结构** `{code,message,detail,traceId}`，含中间件 401 / 校验 422 / 未捕获 500；响应头 `X-Trace-Id` 与日志一致 |
| P2-13 | Trace `events` 标准化为 `{seq,type,timestamp,stepName,payload}`，`seq` 递增可直接回放；新增 `eventCount` |
| P2-14 | 告警新增 `resolvedBy / resolvedAt / resolveNote`；`resolve` 支持备注，处理人取 token 中的 userId |
| P2-15 | Token 统计新增 `byUser / byDevice / bySession` 维度；`token_usage` 新增 `userId/deviceId/traceId` 列 |

### 12.3 新增环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `PUBLIC_BASE_URL` | 空 | 图片绝对地址基址，如 `http://192.168.1.10:8000`；空则用请求来源 |
| `MEDIA_RETENTION_DAYS` | 90 | 原图/录音保留天数 |

### 12.4 角色权限（可验证）

| 能力 | inspector | reviewer | admin |
|---|---|---|---|
| 登录 / me / 刷新 / 登出 | ✅ | ✅ | ✅ |
| 任务、设备、工单、巡检、Trace、Token 统计查询 | ✅ | ✅ | ✅ |
| 改任务状态、上报巡检、工单流转、PDF 导出 | ✅ | ❌ 403 | ✅ |
| 处理告警（`POST /alerts/{id}/resolve`） | ❌ 403 | ✅ | ✅ |
| 删除巡检（`DELETE /inspections/{id}`） | ❌ 403 | ❌ 403 | ✅ |
| 归档 / 清理（`/admin/archive`） | ❌ 403 | ❌ 403 | ✅ |

- 角色来自 `users.role`，随 token 一起校验，**不信任前端传参**
- 权限不足统一返回 `403 FORBIDDEN`（`{code,message,detail,traceId}`）
- v8 默认账号：`admin/admin123`、`inspector/inspector123`、`reviewer/reviewer123`
- 验收命令：inspector 调 `POST /admin/archive` 得 403；reviewer 调 `POST /alerts/{id}/resolve` 得 200

---

## 13. v8 变更（端侧清单收尾，2026-11）

> 本次把端侧清单里此前"暂不做"的 7 项全部补齐。所有改动仍是**新增字段/新增接口**，老端侧不传参也能跑。

### 13.1 新增接口

| 接口 | 说明 |
|---|---|
| `DELETE /api/v1/inspections/{id}` | 删除巡检（admin）：连带删 findings / 原图 / 缩略图，并写 `deleted_records` 墓碑；返回 `{ok, deleted, mediaFiles}` |
| `GET /api/v1/inspections/{id}/report.pdf` | 导出 A4 巡检报告（基本信息 + 结论 + 逐项判读 + 现场照片 + 执行步骤）；`application/pdf` |
| `GET /media/{fileName}` | 由静态挂载改为**鉴权端点**：`Authorization: Bearer` 或 `?token=` 均可 |

### 13.2 新增字段

| DTO | 字段 | 说明 |
|---|---|---|
| `InspectResp` / `SyncInspection` | `imageThumbUrl` | 缩略图相对路径（长边 480px JPEG） |
| 同上 | `imageThumbAbsoluteUrl` | 缩略图完整地址，**已自动附带当前 token**，可直接给 `Image` 组件 |
| `SyncSnapshot.deleted` | `[{tableName,recordId,deviceId,deletedAt}]` | 删除墓碑；增量同步时按 `since` 下发，端侧据此删本地副本 |

> `imageAbsoluteUrl` 同理：服务端会根据当前请求的 token 自动追加 `?token=`，
> 端侧无需自己拼鉴权参数；若把 token 存入日志请自行脱敏。

### 13.3 行为变更

| 项 | 变更 | 端侧注意 |
|---|---|---|
| `/media` 鉴权 | `AUTH_ENABLED=1` 时无 token 返回 `401 UNAUTHORIZED` | 用接口返回的 `imageAbsoluteUrl` / `imageThumbAbsoluteUrl` 即可 |
| Trace 时间戳 | 事件 `timestamp` 与 `createdAt` 精度升到**毫秒**（`...SSS`） | 老数据仍可能是秒级，解析请用宽松格式 |
| 定时清理 | 服务内置后台任务，每 `CLEANUP_INTERVAL_HOURS` 小时清理记忆 / Trace / 已归档媒体 | 无需端侧参与 |
| 图片删除 | 删除巡检会物理删除原图与缩略图 | 删除后旧 `imageAbsoluteUrl` 返回 404 |

### 13.4 新增环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `CLEANUP_INTERVAL_HOURS` | 24 | 定时清理间隔，`0` 关闭 |
| `CLEANUP_DAYS_MEMORIES` | 180 | 历史记忆保留天数 |
| `CLEANUP_DAYS_TRACES` | 30 | Trace 保留天数 |
