# 采集任务多用户并发设计（方案 A）

## 目标

支持至少 10 个业务员同时创建与运行采集任务；全局最多 10、每用户最多 3、每平台最多 3；超额排队；任务结束后自动泵队列；worker 崩溃/重启不永久占槽。

## 架构

- **队列真相源**：PostgreSQL `collection_tasks.status`（`queued` / `running` / …）
- **领取**：`SELECT … FOR UPDATE SKIP LOCKED` 原子领取，避免多 worker 重复执行
- **槽位**：DB 中非 stale 的 `running` 行计数（全局 / 用户 / 平台）
- **租约**：`worker_id`、`heartbeat_at`、`run_started_at`
- **Worker**：可配置 pool（嵌入 API 进程 + 可选独立 `collection-worker` 服务）
- **调度公平**：排队时按「用户当前运行数升序 → queued_at → id」挑选，避免单一业务员占满

## 配置

| 环境变量 | 默认 | 说明 |
|----------|------|------|
| `COLLECTION_MAX_CONCURRENCY`（兼容 `COLLECTION_MAX_RUNNING_TASKS`） | 10 | 全局并发 |
| `COLLECTION_MAX_CONCURRENCY_PER_USER` | 3 | 每业务员 |
| `COLLECTION_MAX_CONCURRENCY_PER_PLATFORM` | 3 | 每平台 |
| `COLLECTION_WORKER_COUNT` | 4 | worker 槽位/进程内协程数 |
| `COLLECTION_RUNNING_STALE_SECONDS` | 180 | 无 heartbeat 视为 stale |
| `COLLECTION_HEARTBEAT_INTERVAL_SECONDS` | 30 | heartbeat 周期 |

## 状态与前端

准确展示：排队中、运行中、平台限流等待、暂停、停止中、完成、失败、超时、stale 回收。

汇总：`运行中 global_running/global_cap`、用户 `user_running/user_cap`、排队数、排队位置、原因、最近 heartbeat。

## 非目标

不删除权限校验；不取消平台 API 限流；不设无限并发；不让单用户占满全局；不用 setTimeout 掩盖问题。
