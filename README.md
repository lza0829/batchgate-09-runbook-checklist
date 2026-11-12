# 02-batchgate（闸序）

Batchgate — 离线作业依赖编排：作业定义 → 依赖就绪检查 → 执行/失败重试 → 产出水位与对账。

与 Feedstitch（多源 Feed 归并）主链路不同，禁止做成 Feed 解析/冲突/回看换皮。

## 启动

```bash
docker compose up --build
```

| 入口 | 地址 |
| --- | --- |
| 前端 | http://localhost:5200 |
| API | http://localhost:10200 |

## 主链

配置作业与依赖 → 触发一次编排 Run → 按依赖顺序执行夹具作业 → 写入尝试记录与产出水位 → 报告对账

## 编排前 Runbook 闸门

开跑前必须先过步骤队列：必做步骤（`success`）全部完成后才允许启动编排；可选步骤可 `skipped`。

- **步骤定义**：标题、是否必做、状态（`pending` / `success` / `failed` / `skipped`），有序（`seq`）。
- **待办队列**：编排台逐项标「完成 / 失败」；必做步骤不允许标「跳过」（API 返回 400）。
- **拦截**：仍有 pending/failed/skipped 的必做步骤时，`POST /api/orchestrations` 返回 **409**，带 `decision=blocked`、拒绝原因、`batch_no` 与当时的步骤快照；不会创建编排。
- **放行**：必做全成功时创建编排，编排行写入 `runbook_batch_id` / `runbook_batch_no`，报告内嵌 `report.runbook.snapshot` 与计数，可追溯当时步骤快照。
- **账实一致**：`gate.counts` 直接由步骤列表重算（success + failed + skipped + pending == total），`gate.consistent` 校验；`skipped` 只允许来自可选步骤。
- **不入业务主数据**：步骤状态、变更事件（`runbook_step_events`）、开跑批次（`runbook_batches`）均为闸门自身留痕，不写水位/尝试记录；也不监视落盘文件触发编排。

接口：`GET /api/runbook`（步骤 + gate + 批次 + 变更事件）、`GET /api/runbook/gate`、`POST /api/runbook/steps`、
`PATCH /api/runbook/steps/{id}`、`DELETE /api/runbook/steps/{id}`、`POST /api/orchestrations`（受闸门约束）。

## 种子说明

- **ingest_orders**：无依赖，写出订单水位。
- **dim_customer**：无依赖，写出客户维表水位。
- **fact_order_daily**：依赖上两者成功且水位推进后才可执行（底座仅做“上游成功”检查，严格水位闸与重试预算留给 0-1 题）。

## 技术栈

Python 3.12 + FastAPI + SQLite；Vue 3 + Vite + Nginx。

## 0-1 切口（未实现）

`dep_gate` / `retry_budget` / `watermark_reconcile` / `sla_breach`
