# Claude/Opus 接入改造 — 代码快照变更清单

> 项目当前非 git 仓库；本清单记录本次 Claude/Opus 接入与 Codex 验收相关改动，便于打包/回滚对照。

## 核心逻辑

| 文件 | 改动目的 |
|------|----------|
| `kimi_client.py` | Anthropic 原生 `/v1/messages` 适配（`x-api-key`、`anthropic-version`）；统一 `_base_llm_status` 的 provider/model；模型 `amount` 仅写入 `llm_suggested_amount`，最终 `row.amount` 由本地公式计算；可选 `build_llm_health_report` 健康探测 |
| `llm_audit.py` | **新增** — 报价流程 LLM 参与审计（`accepted_fields` / `rejected_fields`，含 `final_amount_must_be_local_formula`） |
| `quote_engine.py` | 恢复/保留既有报价输出字段（`cost_bridge`、`tax_rate`、`taxed_price`、`sales_sheet_checkpoints`、`kb_auto_learned`、包装/对账提示、USD 列等）；`material_total` 仅汇总本地 `row.amount` |
| `server.py` | 报价响应写入 `llm_audit`；`GET /api/llm/status?probe=1`；**新增** `GET /api/llm/health` 手动健康检查 |

## 配置与前端

| 文件 | 改动目的 |
|------|----------|
| `.env.example` | Anthropic / Moonshot 双方案环境变量说明与探测提示 |
| `static/app.js` | 前台展示 LLM provider/model 与本次报价 `llm_audit` 摘要 |

## 测试（不强制真实 API）

| 文件 | 改动目的 |
|------|----------|
| `tests/test_kimi_client.py` | Anthropic 请求形态、provider 状态、模型 amount 拒绝、audit 字段、本地 material_total |
| `tests/test_quote_engine.py` | 既有报价结构与字段回归（27 项） |

## 运维脚本（可选）

| 文件 | 改动目的 |
|------|----------|
| `scripts/llm_health_probe.py` | **新增** — 命令行手动探测真实 API Key（默认 live probe；`--config-only` 仅读配置） |

## 未改动的业务边界

- 最终报价真值仍由 `quote_engine.calculate_quote` 本地公式决定
- 模型不得覆盖 KB 命中单价
- 普通 `pytest` 不发起真实 LLM 请求
