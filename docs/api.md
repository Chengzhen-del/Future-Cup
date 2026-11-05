# 智巡 InspectAgent · 端云接口契约 v2.0

> 云端实现与本文档同步（2026-11-04）。字段命名规则：**小驼峰**，DB 列名 / JSON key / ArkTS 字段三者同名。
> 时间格式统一 `YYYY-MM-DD HH:mm:ss`。全局主纲见 `d:\d\未来杯\智巡InspectAgent_数据与接口总体规划.md`，冲突时以主纲为准。

- Base URL：`http://<云端IP>:8000`
- 在线调试：<http://localhost:8000/docs>
- WS 地址：`ws://<云端IP>:8000/ws/agent/{sessionId}`

---

## 0. 接口总表

共 **30** 个端点（含静态资源与 WS）。

| # | 方法 | 路径 | 用途 | 端侧调用 |
|---|---|---|---|---|
| 1 | GET | `/` | 跳转 Web 测试台 | — |
| 2 | GET | `/health` | 健康检查 / mock 判定 | 可选 |
| 3 | GET | `/docs` | Swagger 交互文档 | — |
| 4 | GET | `/media/{fileName}` | 现场图片访问 | 报告页 |
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

### `GET /api/v1/tasks` → `TaskItem[]`

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

`GET /api/v1/tasks/{taskId}` 返回单个；不存在 → 404。

`PATCH /api/v1/tasks/{taskId}/status`

```json
{ "status": "已完成", "inspectionId": "IN-20261104-f980" }
```

### `GET /api/v1/devices` → `DeviceProfile[]`

```json
{ "id": "D-3001", "name": "1号低压配电柜", "type": "低压配电柜",
  "location": "配电房A区", "ratedTemp": 70.0, "ratedHumidity": 80.0,
  "installDate": "2023-06-01", "lastInspectAt": "2026-11-04 16:30:00",
  "history": "2026-08-12 接头温度 66℃（偏高）；2026-09-20 正常", "qrCode": "D-3001" }
```

`GET /api/v1/devices/{deviceId}` 返回单个；设备不存在返回空档案（不 404）。

### `GET /api/v1/workorders` → `WorkOrder[]`

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

返回列表（不含 `steps` / `findings` / `memories` 展开），字段：
`id, taskId, deviceId, deviceName, location, operator, voiceText, voiceSlotsJson, visionJson, sensorJson, imageId, level`

### `GET /api/v1/inspections/{inspectionId}`

返回详情，在列表字段基础上追加：
`confidence, advice, needHuman, mock, stepsJson, workOrderId, durationMs, capturedAt, createdAt, findings, voiceSlots, vision, steps, followUpQuestions, incompleteFields, memories`

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

```json
{ "traces": [ { "id": 5, "sessionId": "a1b2c3d4", "inspectionId": "IN-20261104-f980",
                "deviceId": "D-3001", "deviceName": "1号低压配电柜", "level": "紧急",
                "confidence": 0.47, "durationMs": 117500, "createdAt": "2026-11-04 16:31:00" } ] }
```

### `GET /api/v1/traces/{traceId}`

在列表字段基础上追加 `events`（**完整事件流数组**，可直接按帧回放；DB 里存为 `eventsJson`，出参已解析为 `events`）。

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

```json
{ "alerts": [ { "id": 7, "level": "warn", "category": "rag",
                "message": "Chroma 向量检索不可用，已退化关键词兜底",
                "detail": "...", "resolved": 0, "createdAt": "2026-11-04 16:20:00" } ] }
```

### `POST /api/v1/alerts/{alertId}/resolve` → `{"ok": true}`

### `GET /api/v1/stats/tokens?days=7`

```json
{ "days": 7, "since": "2026-10-28 00:00:00",
  "total": { "promptTokens": 18611, "completionTokens": 16558,
             "totalTokens": 35169, "costCny": 0.1697, "calls": 22 },
  "byDay":    [ { "day": "2026-11-04", "tokens": 35169, "cost": 0.1697, "calls": 22 } ],
  "byCaller": [ { "caller": "react", "tokens": 11795, "cost": 0.07, "calls": 6 } ],
  "byModel":  [ { "model": "deepseek-v4-pro-ga-260813", "tokens": 29644, "cost": 0.09, "calls": 20 } ] }
```

`caller` 取值：`plan` / `decide` / `react` / `review` / `followup` / `voice` / `vision` / `stream`。

---

## 7. 端侧同步

### `GET /api/v1/sync/snapshot?deviceId=&since=`

端侧 App 启动拉一次全量；之后带 `since` 做增量。

```json
{ "devices": [...], "tasks": [...], "inspections": [...], "workorders": [...],
  "syncAt": "2026-11-04 16:35:00", "since": "2026-11-01 00:00:00" }
```

| 参数 | 说明 |
|---|---|
| since | 可选；按 `inspections.capturedAt` / `workorders.createdAt` ≥ since 过滤 |
| 上限 | 每类最多 5000 条 |

### `POST /api/v1/sync/conflict`

```json
{ "table": "inspections", "id": "IN-xxx",
  "device_version": "2026-11-04 16:00:00", "cloud_version": "2026-11-04 16:05:00",
  "device_changes": { "level": "关注" } }
```

响应：

```json
{ "resolved": true, "winner": "cloud", "message": "默认云端优先" }
```

当前策略：**云端优先**（简化实现）。端侧收到 `winner: "cloud"` 时用 `final` 覆盖本地副本。

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

## 9. 错误码

| code | 含义 | 端侧处理 |
|---|---|---|
| 400 | `payload` JSON 解析失败 | 检查字符串是否转义正确 |
| 404 | 任务 / 设备 / 工单 / 巡检 / Trace 不存在 | 提示并回列表 |
| 413 | 图片 > 10MB | 先压缩到长边 ≤1280 再传 |
| 422 | 请求体字段类型不符（Pydantic 校验） | 按 `/docs` 的定义修正 |
| 500 | 云端异常 | 提示"服务暂时不可用"，保留本地缓存 |

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
- 401 响应：`{"detail":{"code":"UNAUTHORIZED","message":"未登录或 token 已失效"}}`

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
