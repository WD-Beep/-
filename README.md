# Influencer Intel

公司内部使用的海外红人数据采集与管理系统。支持关键词采集、链接采集、粘贴链接导入、邮箱提取、评分、AI 分析、Excel 导出与 SMTP 邮件。

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Next.js 16、React、TypeScript、Tailwind CSS |
| 后端 | FastAPI、SQLAlchemy、Alembic、PostgreSQL |
| 任务 | APScheduler、openpyxl、aiosmtplib |
| 部署 | Docker Compose |

## 项目结构

```
influencer-intel/
├── apps/web/                 # Next.js 前端
├── apps/api/                 # FastAPI 后端
│   └── app/
│       ├── api/routes/       # API 路由
│       ├── collectors/       # Instagram Apify 采集器
│       ├── services/         # 业务逻辑、邮箱提取、评分
│       └── scripts/seed.py   # 种子数据
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## 本地启动

### 前置要求

- Node.js 20+
- Python 3.12+
- PostgreSQL 16+（或 Docker 仅启动 postgres 服务）

### 1. 配置环境变量

```bash
cp .env.example .env
```

本地开发时，将 `DATABASE_URL` 改为指向本机 PostgreSQL，例如：

```
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/influencer_intel
```

### 2. 启动 PostgreSQL

**方式 A：Docker 只跑数据库**

```bash
docker compose up postgres -d
```

**方式 B：本机已安装 PostgreSQL**

```bash
cd apps/api
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
python -m app.scripts.setup_db  # 可选，创建 influencer_intel 库
```

### 3. 数据库迁移

```bash
cd apps/api
.venv\Scripts\activate
alembic upgrade head
```

### 4. 导入 Seed 数据

```bash
python -m app.scripts.seed
```

脚本幂等：库中已有红人数据时会跳过。Seed 包含 30 条红人、5 个采集任务、若干邮件日志。

若需补全扩展字段（邮箱、评分、product_fit 等），可运行：

```bash
python -m app.scripts.backfill_profile
```

### 5. 启动后端

```bash
cd apps/api
.venv\Scripts\activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- API：http://localhost:8000
- Swagger 文档：http://localhost:8000/docs

### 6. 启动前端

```bash
cd apps/web
npm install
npm run dev
```

- 前端：http://localhost:3000

> Windows 上 Next.js 16 需使用 `--webpack`（已在 `package.json` 的 `dev` / `build` 脚本中配置）。

### Docker Compose 一键启动

```bash
cp .env.example .env
docker compose up --build
```

| 服务 | 地址 |
|------|------|
| 前端 | http://localhost:3000 |
| 后端 | http://localhost:8000 |
| PostgreSQL | localhost:5432 |

API 容器启动时会自动执行 `alembic upgrade head`（见 `docker-entrypoint.sh`）。

Seed 数据：

```bash
docker compose exec api python -m app.scripts.seed
```

或在 `.env` 中设置 `RUN_SEED=true`（仅空库时写入）。

---

## 环境变量说明

完整模板见 [`.env.example`](.env.example)。

| 变量 | 说明 |
|------|------|
| `DATABASE_URL` | PostgreSQL 连接串（asyncpg 驱动） |
| `POSTGRES_*` | Docker Compose 内 PostgreSQL 配置 |
| `API_PORT` / `WEB_PORT` | 后端 / 前端宿主机端口 |
| `CORS_ORIGINS` | 允许的前端来源，逗号分隔 |
| `SMTP_*` | 邮件服务器配置，留空则发信返回友好提示 |
| `KIMI_API_KEY` | Moonshot AI Key，未配置时使用 Mock AI |
| `KIMI_API_BASE` / `KIMI_MODEL` | Kimi API 地址与模型名 |
| `COLLECTOR_MODE` | 采集器模式：`apify` 或 `auto`（均为 Instagram Apify 采集） |
| `APIFY_TOKEN` | Apify Token（Instagram 主页 / Hashtag 采集，必填） |
| `NEXT_PUBLIC_API_URL` | 前端请求后端的 Base URL |
| `RUN_SEED` | Docker 启动时是否尝试 seed（默认 `false`） |

---

## 数据库迁移

```bash
cd apps/api
alembic upgrade head          # 升级到最新
alembic downgrade -1          # 回退一个版本
alembic revision --autogenerate -m "描述"   # 生成新迁移
```

迁移文件位于 `apps/api/alembic/versions/`（001–005：初始表、评分、扩展资料、采集模式、链接导入批次）。

---

## Seed 数据

```bash
cd apps/api
python -m app.scripts.seed
```

包含：

- 若干 Instagram 红人样例（seed 脚本，可选）
- 5 个采集任务（含定时、邮件配置示例）
- 若干邮件发送日志（成功 / 失败样例）

---

## 关键词采集

1. 打开 **Collection Tasks** → 点击「新建任务」
2. 采集模式选择 **关键词采集（keyword）**
3. 填写平台、关键词（逗号分隔）、可选国家/类目
4. 保存后点击 **运行采集**

需配置 `APIFY_TOKEN`。推荐使用 **自动发现（discovery）** 模式填写 hashtag（如 `travelgear`、`amazonfinds`），流水线为：Discovery → Profile Hydration → 质量评分 → AI 分析。

API 示例：

```bash
curl -X POST http://localhost:8000/api/collection-tasks \
  -H "Content-Type: application/json" \
  -d '{"name":"测试发现","platform":"instagram","keywords":["travelgear"],"collection_mode":"discovery"}'

curl -X POST http://localhost:8000/api/collection-tasks/{id}/run
curl -X POST http://localhost:8000/api/collection-tasks/{id}/pause
curl -X POST http://localhost:8000/api/collection-tasks/{id}/resume
```

Collection tasks can be paused and resumed. Pausing keeps the candidate pool, counters, inserted influencers, and saved progress, so resume continues from the last checkpoint instead of collecting from the beginning.

---

## 链接采集

1. **Collection Tasks** → 新建任务
2. 采集模式选择 **链接采集（urls）** 或 **混合（mixed）**
3. 在「链接列表」中每行粘贴一个红人主页 URL
4. 运行采集

通过 Apify Profile Scraper 拉取真实主页数据。

---

## 粘贴链接导入（Link Import）

1. 打开 **Link Import** 页
2. 输入批次名称，粘贴多行 **Instagram** 主页 URL（非 Instagram 链接会标记为无效）
3. 点击「创建批次」→「运行导入」
4. 查看有效/无效链接统计与导入结果

与 Collection Tasks 的链接模式共用 `url_parser` 与 `link_import_collector`，适合运营批量粘贴渠道链接。

---

## 邮箱提取与联系方式

采集或导入完成后，系统会自动：

- 从 bio、Linktree、contact page 等字段提取邮箱（`profile_enrichment`）
- 写入 `public_email` / `business_email` / `final_email`
- 识别 WhatsApp、Telegram、联系页等可联系渠道
- 计算 `contact_score`、`contact_credibility`

在 **Influencers** 页可使用快捷筛选：

| 筛选 | 条件 |
|------|------|
| 有邮箱 | 存在 final_email / email / public_email / business_email |
| 可联系 | 有邮箱或 WhatsApp / Telegram / contact_page / linktree |
| 高匹配 | score ≥ 75 且 product_fit ≥ 70 |

---

## Excel 导出

**API：**

```
GET http://localhost:8000/api/influencers/export/excel
```

支持查询参数：`platform`、`country`、`category`、`follow_status`、`keyword`、`min_score`、`has_email`、`contactable`、`high_match`。

**前端入口：**

- Dashboard → 「导出 Excel」
- Influencers 页 → 「导出 Excel」（会带上当前筛选条件）

导出为 `.xlsx`，包含红人核心字段、联系方式与 AI 分析结果。无符合条件数据时返回 404 及友好提示。

---

## 邮件配置

在 `.env` 中填写 SMTP：

```env
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=your@email.com
SMTP_PASSWORD=your_password
SMTP_FROM=your@email.com
SMTP_USE_TLS=true
```

验证方式：

1. **Settings** → 查看 SMTP 状态 → 发送测试邮件
2. **Collection Tasks** → 对已完成任务点击「发送邮件」（附带 Excel）
3. **Email Logs** → 查看发送记录与失败原因

未配置 SMTP 时，接口返回 `{ "success": false, "message": "..." }`，服务不会崩溃。

---

## 完整业务流程（验收清单）

1. 打开 http://localhost:3000 → **Dashboard** 查看汇总
2. **Influencers** → 查看红人列表；使用「有邮箱 / 可联系 / 高匹配」筛选
3. **Collection Tasks** → 创建**关键词**采集任务 → **运行采集**
4. **Collection Tasks** → 创建**链接**采集任务 → **运行采集**
5. **Link Import** → 粘贴链接 → 创建批次 → **运行导入**
6. 进入红人 **详情页** → 查看资料、邮箱、评分、编辑跟进状态
7. 点击 **AI 分析** → Mock 或 Kimi 生成摘要与建议
8. **导出 Excel**（可带筛选）
9. **Collection Tasks** 或 **Settings** → **发送邮件**
10. **Email Logs** → 查看日志

自动化验收（需 API 已启动且已 migrate + seed）：

```bash
cd apps/api
.venv\Scripts\activate
python -m app.scripts.acceptance
```

---

## 接入 Instagram 采集（Apify）

当前仅支持 **Instagram** 平台，采集模式请使用 `apify` 或 `auto`（等价）。

```env
COLLECTOR_MODE=apify
APIFY_TOKEN=your_apify_token
APIFY_INSTAGRAM_ACTOR_ID=logical_scrapers~instagram-profile-scraper
APIFY_INSTAGRAM_HASHTAG_ACTOR_ID=apify~instagram-hashtag-scraper
```

采集流水线见 `app/services/instagram_pipeline.py`（Discovery → Hydration → Quality → AI）。

| 文件 | 说明 |
|------|------|
| `collectors/apify.py` | Instagram 四步采集入口 |
| `services/apify_instagram.py` | Apify Actor 调用与错误汇总 |
| `services/instagram_quality.py` | 质量评分与 P0–P3 |
| `collectors/__init__.py` | `get_collector()` 工厂（仅 Instagram） |

---

## 定时任务（APScheduler）

后端启动时自动加载 `schedule_enabled=true` 的采集任务。

Cron 格式（5 段，UTC）：

```
分  时  日  月  周
0   9   *   *   1     # 每周一 09:00 UTC
```

手动刷新调度：

```bash
curl -X POST http://localhost:8000/api/collection-tasks/scheduler/refresh
```

---

## API 速查

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/api/dashboard/summary` | Dashboard 汇总 |
| GET/POST | `/api/influencers` | 红人列表 / 创建（支持 has_email、contactable、high_match） |
| GET/PATCH/DELETE | `/api/influencers/{id}` | 详情 / 更新 / 删除 |
| GET | `/api/influencers/export/excel` | Excel 导出 |
| GET/POST | `/api/collection-tasks` | 采集任务 |
| POST | `/api/collection-tasks/{id}/run` | 执行采集 |
| POST | `/api/collection-tasks/{id}/send-email` | 发送邮件 |
| GET/POST | `/api/link-import/batches` | 链接导入批次 |
| POST | `/api/link-import/batches/{id}/run` | 运行链接导入 |
| POST | `/api/ai/analyze-influencer/{id}` | AI 分析 |
| GET | `/api/email-logs` | 邮件日志 |
| POST | `/api/email/test` | 测试邮件 |
| GET | `/api/settings/status` | 系统配置状态 |

完整文档：http://localhost:8000/docs

---

## License

Internal use only.
