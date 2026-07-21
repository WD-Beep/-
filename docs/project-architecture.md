# 海外红人数据采集与 AI 邮件外联系统架构说明书

## 1. 架构总览

本项目是一个前后端分离的内部业务系统，核心目标是把海外红人开发流程系统化：从红人采集、联系方式提取、去重筛选、AI 分析、AI 邮件生成，到邮件发送、回信管理和数据导出。

系统整体由四个主要部分组成：

| 模块 | 作用 |
| --- | --- |
| Web 前端 | 提供业务员和管理员使用的后台界面 |
| API 后端 | 提供业务接口、采集任务管理、AI、邮件和数据处理能力 |
| Collection Worker | 独立后台采集进程，负责执行采集任务 |
| PostgreSQL | 存储红人、任务、邮件、回信、模板、租户、产品等数据 |

整体流程可以理解为：

```text
业务员/管理员
  -> Web 前端
  -> API 后端
  -> PostgreSQL 数据库
  -> Collection Worker 执行采集
  -> AI 生成分析/邮件
  -> SMTP/Gmail 发送
  -> 邮件日志/回信中心
```

## 2. 技术栈

| 层级 | 技术 |
| --- | --- |
| 前端 | Next.js、React、TypeScript、Tailwind CSS |
| 后端 | FastAPI、SQLAlchemy、Alembic、Pydantic |
| 数据库 | PostgreSQL |
| 后台任务 | APScheduler、独立 collection worker |
| AI | OpenAI 兼容接口，支持 Kimi、DeepSeek 等模型配置 |
| 采集 | Apify、API Direct、平台采集 provider |
| 邮件 | SMTP、Gmail/企业邮箱发信配置、IMAP 回信拉取 |
| 部署 | Docker Compose |
| 测试 | Pytest、前端测试脚本 |

## 3. 顶层目录结构

```text
influencer-intel/
├─ apps/
│  ├─ api/                  # FastAPI 后端
│  └─ web/                  # Next.js 前端
├─ docs/                    # 项目说明、设计方案、计划文档
├─ scripts/                 # 项目级维护脚本
├─ backups/                 # 备份文件
├─ docker-compose.yml       # 本地/服务器 Docker 编排
├─ .env                     # 本地环境变量
├─ .env.example             # 环境变量模板
└─ README.md                # 项目启动和使用说明
```

日常查看项目时，最重要的是：

- 后端业务逻辑：`apps/api/app/services`
- 后端接口入口：`apps/api/app/api/routes`
- 数据库模型：`apps/api/app/models`
- 前端页面：`apps/web/src/app`
- 前端组件：`apps/web/src/components`
- 前端工具函数：`apps/web/src/lib`
- 项目说明文档：`docs`

## 4. 部署架构

`docker-compose.yml` 中定义了四个主要服务：

| 服务 | 容器名 | 作用 |
| --- | --- | --- |
| `postgres` | `influencer-postgres` | PostgreSQL 数据库 |
| `api` | `influencer-api` | FastAPI 后端服务 |
| `collection-worker` | `influencer-collection-worker` | 独立采集任务执行进程 |
| `web` | `influencer-web` | Next.js 前端服务 |

### 4.1 服务关系

```text
web
  -> api
      -> postgres
      -> AI API
      -> SMTP/IMAP
      -> Apify/API Direct

collection-worker
  -> api 启动健康后运行
  -> postgres 获取待执行采集任务
  -> Apify/API Direct 获取红人数据
```

### 4.2 端口

| 服务 | 默认端口 |
| --- | --- |
| Web 前端 | `3000` |
| API 后端 | `8000` |
| PostgreSQL | `5432` |

### 4.3 Worker 设计

采集任务可以由 API 内嵌 worker 或独立 `collection-worker` 执行。当前 compose 中保留了独立 worker 服务，适合把接口请求和采集执行分开，避免长时间采集影响 API 响应。

并发控制依赖环境变量：

| 变量 | 说明 |
| --- | --- |
| `COLLECTION_MAX_CONCURRENCY` | 全局最大采集并发 |
| `COLLECTION_MAX_CONCURRENCY_PER_USER` | 单用户最大采集并发 |
| `COLLECTION_MAX_CONCURRENCY_PER_PLATFORM` | 单平台最大采集并发 |
| `COLLECTION_WORKER_COUNT` | worker 数量 |
| `COLLECTION_API_EMBEDDED_WORKER_ENABLED` | 是否启用 API 内嵌 worker |

## 5. 前端架构

前端位于 `apps/web`，使用 Next.js App Router。

### 5.1 页面入口

页面目录位于 `apps/web/src/app`。

| 页面目录 | 作用 |
| --- | --- |
| `collection-tasks` | 采集任务页面 |
| `influencers` | 红人列表和红人详情 |
| `message-templates` | 话术模板管理 |
| `outreach-campaigns` | 外联活动管理 |
| `outreach-send-queue` | 邮件发送队列 |
| `email-logs` | 邮件发送记录 |
| `email-replies` | 回信中心 |
| `knowledge-bases` | 知识库 |
| `link-import` | 链接导入 |
| `link-knowledge-bases` | 链接知识库 |
| `settings` | 系统设置 |
| `admin` | 管理员后台 |

### 5.2 组件层

组件目录位于 `apps/web/src/components`。

| 组件目录 | 作用 |
| --- | --- |
| `collection-tasks` | 采集任务列表、任务表单、候选数据弹窗 |
| `influencers` | 红人列表、详情、批量外联、话术推荐 |
| `message-templates` | 话术模板列表和编辑弹窗 |
| `email-logs` | 邮件日志、发送队列、保存为模板 |
| `email-replies` | 回信中心 |
| `outreach-campaigns` | 外联活动列表和详情 |
| `knowledge-bases` | 知识库管理 |
| `admin` | 管理员后台、用户、产品、月报、销售工作台 |
| `layout` | 业务后台布局、侧边栏、产品切换 |
| `ui` | 基础按钮、输入框、卡片、标签等 UI 组件 |

### 5.3 前端公共逻辑

公共逻辑位于 `apps/web/src/lib`。

| 文件类型 | 作用 |
| --- | --- |
| `api.ts` | 前端请求后端接口的基础封装 |
| `auth*.ts` | 登录、会话、权限相关逻辑 |
| `labels.ts` | 页面显示文案、字段标签 |
| `collection-*.ts` | 采集任务状态、来源、进度等辅助逻辑 |
| `outreach-*.ts` | 邮件外联、活动、队列相关辅助逻辑 |
| `email-*.ts` | 邮件地址、邮件日志、回信显示逻辑 |
| `product-*.ts` | 产品选择、产品权限、产品状态 |

### 5.4 前端请求路径

前端通过两类方式访问后端：

- 浏览器侧通过 `NEXT_PUBLIC_API_URL` 或 `/api-proxy` 请求 API。
- 长耗时请求可通过 `NEXT_PUBLIC_LONG_RUNNING_API_URL` 或 `/api-long` 转发。

这样可以在本地开发和 Docker 部署中使用不同的后端地址，同时保持前端代码统一。

## 6. 后端架构

后端位于 `apps/api`，核心代码在 `apps/api/app`。

```text
apps/api/app/
├─ api/routes/        # API 路由入口
├─ services/          # 业务服务层
├─ models/            # 数据库模型
├─ schemas/           # 请求和响应结构
├─ collectors/        # 采集器入口
├─ workers/           # 后台采集 worker
├─ scheduler/         # 调度器
├─ core/              # 配置和异常
├─ db/                # 数据库连接
├─ deps/              # 接口依赖
├─ data/              # 内置业务数据
└─ main.py            # FastAPI 应用入口
```

### 6.1 API 路由层

路由层位于 `apps/api/app/api/routes`，主要负责：

- 接收前端请求。
- 校验请求参数。
- 调用 service 层业务逻辑。
- 返回统一响应结构。

主要路由包括：

| 路由文件 | 业务 |
| --- | --- |
| `collection_tasks.py` | 采集任务创建、运行、暂停、恢复、候选数据查看 |
| `influencers.py` | 红人列表、详情、编辑、导出 |
| `message_templates.py` | 话术模板 |
| `outreach_campaigns.py` | 外联活动 |
| `outreach_send_queue.py` | 邮件发送队列 |
| `outreach_records.py` | 外联记录 |
| `email_logs.py` | 邮件日志 |
| `email_inbound.py` | 回信接收 |
| `smtp_accounts.py` | SMTP/Gmail 发信账号 |
| `knowledge.py` | 知识库 |
| `link_import.py` | 链接导入 |
| `admin.py` | 管理员后台 |
| `auth.py` | 登录认证 |
| `tenant.py` | 租户相关 |
| `settings.py` | 系统配置状态 |

### 6.2 Service 业务层

业务层位于 `apps/api/app/services`，是后端最重要的目录。

核心服务包括：

| 服务文件 | 作用 |
| --- | --- |
| `collection_runner.py` | 采集任务运行主流程 |
| `collection_queue.py` | 采集任务队列 |
| `collection_lease.py` | 采集任务锁和领取机制 |
| `collection_auto_outreach.py` | 采集完成后自动 AI 发邮件 |
| `collection_filters.py` | 采集筛选规则 |
| `collection_funnel.py` | 采集漏斗和候选数据管理 |
| `task_influencer.py` | 采集任务与红人关系 |
| `contact_discovery.py` | 联系方式发现 |
| `contact_signals.py` | 联系方式信号判断 |
| `ai_service.py` | AI 生成服务 |
| `ai_analysis.py` | AI 红人分析 |
| `email.py` | 邮件发送 |
| `email_log.py` | 邮件日志 |
| `outreach_send_queue_service.py` | 邮件发送队列 |
| `outreach_send_scheduler.py` | 邮件队列调度发送 |
| `email_reply_service.py` | 回信处理 |
| `imap_reply_client.py` | IMAP 回信拉取 |
| `message_template.py` | 话术模板 |
| `smtp_account.py` | 发信邮箱账号 |
| `tenant_scope.py` | 租户数据隔离 |
| `product_visibility.py` | 产品可见性 |

### 6.3 数据模型层

模型层位于 `apps/api/app/models`，对应数据库表结构。

主要模型包括：

| 模型 | 作用 |
| --- | --- |
| `influencer.py` | 红人基础资料、联系方式、平台信息、评分等 |
| `global_influencer_profile.py` | 跨租户或全局红人资料 |
| `collection_task.py` | 采集任务配置和状态 |
| `collection_task_candidate.py` | 采集候选数据和运行过程数据 |
| `message_template.py` | 邮件话术模板 |
| `email_log.py` | 邮件发送记录 |
| `email_reply.py` | 邮件回信 |
| `outreach_email_campaign.py` | 外联活动 |
| `outreach_campaign_recipient.py` | 外联活动收件人 |
| `outreach_send_queue.py` | 待发送邮件队列 |
| `manual_outreach_email.py` | 手动外联邮件 |
| `user_smtp_account.py` | 用户 SMTP/Gmail 发信账号 |
| `tenant.py` | 租户 |
| `product_influencer.py` | 产品和红人的关联 |
| `product_influencer_source.py` | 产品红人来源 |
| `knowledge.py` | 知识库资料 |
| `link_import_batch.py` | 链接导入批次 |
| `link_knowledge_base.py` | 链接知识库 |
| `admin_audit_log.py` | 管理员操作日志 |

### 6.4 Schema 层

`apps/api/app/schemas` 定义接口的输入输出结构。它把数据库模型和前端请求隔离开，避免前端直接依赖数据库内部字段。

例如：

- 创建采集任务时使用 collection task schema。
- 邮件发送记录使用 email log schema。
- 红人列表和详情使用 influencer schema。
- SMTP 账号配置使用 smtp account schema。

## 7. 数据库与迁移

项目使用 PostgreSQL 作为主数据库，使用 Alembic 管理表结构变化。

迁移文件位于：

```text
apps/api/alembic/versions
```

数据库升级命令：

```bash
cd apps/api
alembic upgrade head
```

迁移文件编号从 `001_initial_schema.py` 开始，后续逐步增加了：

- 红人扩展资料。
- 采集任务模式。
- 链接导入。
- AI 评分。
- 联系方式发现。
- 多租户隔离。
- 邮件日志。
- 外联发送队列。
- 回信中心。
- 产品成员权限。
- 自动 AI 外联。
- SMTP 账号。
- 采集任务租约和并发控制。

## 8. 红人采集架构

### 8.1 采集入口

业务员在前端 `Collection Tasks` 页面创建采集任务，后端保存为 `collection_task` 记录。

任务通常包含：

- 平台。
- 关键词。
- 链接列表。
- 国家、类目等筛选条件。
- 采集数量。
- 是否自动 AI 发邮件。
- 邮件模板、产品卖点、合作方式。

### 8.2 任务运行

任务运行后，核心流程由 `collection_runner.py` 负责。

大致流程：

```text
创建任务
  -> 保存任务配置
  -> 加入采集队列
  -> worker 领取任务
  -> 根据平台和模式选择采集 provider
  -> 获取候选红人
  -> 去重和质量筛选
  -> 保存红人和候选数据
  -> 提取联系方式
  -> AI 分析
  -> 更新任务进度和结果
```

### 8.3 采集来源

采集能力主要分布在：

| 目录或文件 | 作用 |
| --- | --- |
| `collectors` | 采集器统一入口 |
| `platform_providers` | 不同平台 provider |
| `apify_client.py` | Apify 调用基础封装 |
| `apify_instagram.py` | Instagram Apify 采集 |
| `api_direct_provider.py` | API Direct 采集统一入口 |
| `youtube_email_enrichment.py` | YouTube 邮箱补充 |
| `instagram_pipeline.py` | Instagram 采集流水线 |

### 8.4 暂停和续跑

采集任务支持暂停、恢复和进度保存。任务进度、候选池、已插入红人、计数器等会保留，恢复时尽量从上次位置继续，而不是完全从头开始。

## 9. 去重与筛选架构

### 9.1 去重目的

去重的目标不是减少采集，而是避免同一个红人被重复保存、重复发信、重复统计。

如果同一个关键词第二次继续采集，新增数量变少，常见原因是：

- 第一次已经采到同一批红人。
- 第二次采集结果与历史红人重复。
- 部分红人没有邮箱或联系方式不满足发送条件。
- 采集平台返回的数据本身重复。
- 系统根据平台唯一 ID、主页链接、邮箱等规则过滤重复数据。

### 9.2 去重维度

系统可能使用以下维度进行判断：

- 平台。
- 平台唯一 ID。
- 红人主页 URL。
- 用户名或 handle。
- 邮箱。
- 任务候选记录。
- 已发送记录。
- 租户和产品范围。

### 9.3 筛选维度

筛选通常包括：

- 是否有邮箱。
- 邮箱是否有效。
- 是否可联系。
- 粉丝量和互动率。
- 内容方向是否匹配产品。
- 是否为测试邮箱。
- 是否已经发送过。
- 是否属于当前用户或产品可见范围。

## 10. AI 架构

AI 能力主要用于两个地方：

1. 红人分析：判断红人内容、匹配度、合作价值。
2. 邮件生成：根据模板和红人资料生成定制化外联邮件。

### 10.1 AI 调用层

AI 相关代码主要在：

| 文件 | 作用 |
| --- | --- |
| `services/ai/openai_client.py` | OpenAI 兼容客户端 |
| `services/ai_service.py` | AI 文本生成服务 |
| `services/ai_analysis.py` | 红人 AI 分析 |
| `api/routes/ai.py` | AI 接口入口 |

系统通过环境变量配置模型服务，例如 API Key、Base URL、模型名等。

### 10.2 AI 邮件生成

AI 邮件生成不会直接复制模板，而是把业务员填写的模板当作规则和素材。

输入通常包括：

- 邮件主题模板。
- 邮件正文要求。
- 产品名称。
- 产品卖点。
- 合作方式。
- 备注。
- 红人昵称。
- 平台。
- 粉丝量。
- 互动率。
- 简介。
- 内容方向。
- 采集关键词。

输出通常包括：

- 邮件主题。
- 邮件正文。
- 对应红人。
- 生成状态。
- 失败原因。

## 11. 自动 AI 发邮件架构

自动 AI 发邮件主要由 `collection_auto_outreach.py` 承担。

### 11.1 自动流程

```text
采集任务完成
  -> 检查任务是否开启自动 AI 发邮件
  -> 读取任务内的话术模板和产品信息
  -> 筛选本次采集到的红人
  -> 跳过无邮箱、重复、已发送、无效对象
  -> 为每个红人调用 AI 生成定制邮件
  -> 写入发送队列
  -> 调度器按频率发送
  -> 记录邮件日志
```

### 11.2 和 AI 批量发邮箱的关系

两者核心生成逻辑相似，区别在触发方式：

| 功能 | 触发方式 | 适用场景 |
| --- | --- | --- |
| AI 批量发邮箱 | 人工先选择红人，再生成并发送 | 已经有红人名单 |
| 采集后自动 AI 发邮箱 | 采集完成后自动筛选、生成、发送 | 创建任务后希望系统自动处理 |

### 11.3 风控控制

自动发信不能一次性无限发送，需要依赖：

- 每日发送上限。
- 每小时发送上限。
- SMTP/Gmail 账号状态。
- 队列分批发送。
- 已发送去重。
- 邮箱有效性过滤。

## 12. 邮件发送与回信架构

### 12.1 发信账号

发信账号由 `user_smtp_account.py` 和 `smtp_account.py` 相关逻辑管理。

业务员可以配置：

- SMTP Host。
- SMTP Port。
- SMTP 用户名。
- SMTP 密码或授权码。
- 发件邮箱。
- TLS/SSL 配置。

### 12.2 发送队列

邮件不会全部立刻一次性发出，而是进入 `outreach_send_queue`。

队列的作用：

- 控制发送速度。
- 避免重复发送。
- 记录待发送、发送中、成功、失败状态。
- 方便失败重试和问题排查。

### 12.3 邮件日志

邮件发送结果保存到 `email_log`，常见信息包括：

- 收件人邮箱。
- 邮件主题。
- 邮件正文。
- 对应红人。
- 发送账号。
- 发送时间。
- 成功或失败状态。
- 失败原因。

### 12.4 回信中心

回信能力由 IMAP 和回信匹配逻辑组成。

相关服务包括：

- `imap_reply_client.py`
- `email_reply_service.py`
- `email_reply_matcher.py`
- `email_reply_utils.py`

系统会尽量把红人的回信匹配到原邮件、原红人和原业务员，方便后续继续沟通。

## 13. 权限、租户和产品隔离

项目支持多租户、用户、产品可见性和管理员角色。

相关模块包括：

| 模块 | 作用 |
| --- | --- |
| `tenant.py` | 租户模型和租户接口 |
| `tenant_scope.py` | 后端数据范围限制 |
| `product_visibility.py` | 产品可见性 |
| `product_member_access` 相关测试 | 产品成员访问控制 |
| `admin.py` | 管理员用户、产品、业务员管理 |
| `auth_service.py` | 登录认证 |

权限设计的目的：

- 业务员只能看到自己或被授权产品的数据。
- 管理员可以管理用户、产品、任务和统计。
- 不同租户之间的数据需要隔离。
- 发信账号和发送记录应归属到具体用户或租户。

## 14. 知识库和链接导入

### 14.1 知识库

知识库用于保存产品资料、品牌信息、卖点、合作说明等内容，供 AI 生成邮件或业务员查看。

相关目录：

```text
apps/api/app/services/knowledge
apps/web/src/components/knowledge-bases
apps/web/src/app/knowledge-bases
```

### 14.2 链接导入

链接导入用于业务员批量粘贴红人主页或内容链接，系统解析并导入。

相关模块：

- `link_import.py`
- `link_import_url.py`
- `link_import_batch.py`
- `link-knowledge-bases`
- `link-import`

链接导入适合运营人员已经从外部渠道拿到红人链接后批量导入系统。

## 15. 关键业务数据流

### 15.1 采集到红人的数据流

```text
前端创建任务
  -> API 保存 collection_task
  -> worker 领取任务
  -> provider 采集平台数据
  -> candidate_pool 保存候选数据
  -> influencer_persistence 保存红人
  -> contact_discovery 提取联系方式
  -> scoring / ai_analysis 评分分析
  -> 前端展示红人和任务结果
```

### 15.2 自动发信数据流

```text
采集任务完成
  -> collection_auto_outreach 筛选可发送红人
  -> ai_service 生成邮件
  -> outreach_send_queue_service 写入队列
  -> outreach_send_scheduler 分批发送
  -> email_log 记录结果
  -> email_reply_service 匹配回信
```

### 15.3 管理员查看数据流

```text
管理员登录
  -> admin 页面
  -> admin 路由请求后端
  -> tenant/product/user 权限过滤
  -> dashboard/report 服务汇总数据
  -> 前端展示任务、红人、邮件和月报
```

## 16. 配置架构

主要环境变量放在 `.env`，模板在 `.env.example`。

常见配置类型：

| 类型 | 示例 |
| --- | --- |
| 数据库 | `DATABASE_URL`、`POSTGRES_USER`、`POSTGRES_PASSWORD` |
| 前后端地址 | `API_PORT`、`WEB_PORT`、`NEXT_PUBLIC_API_URL` |
| 跨域 | `CORS_ORIGINS` |
| AI | API Key、Base URL、模型名 |
| 采集 | `APIFY_TOKEN`、采集模式、平台 actor |
| 邮件 | SMTP Host、Port、User、Password、TLS |
| 并发 | 采集全局并发、用户并发、平台并发 |

注意：`.env` 是敏感配置文件，不应提交到公开仓库。

## 17. 测试架构

### 17.1 后端测试

后端测试位于：

```text
apps/api/tests
```

覆盖内容包括：

- 采集任务。
- 去重和候选数据。
- 联系方式提取。
- AI 邮件生成。
- 自动外联。
- 邮件发送队列。
- SMTP 配置。
- 权限和租户隔离。
- 产品可见性。
- 链接导入。
- YouTube、Instagram、TikTok 等平台采集逻辑。

### 17.2 前端测试

前端测试位于：

```text
apps/web/tests
```

覆盖内容包括：

- 采集任务进度展示。
- 外联活动。
- 任务表单。
- 筛选器。
- 产品选择。
- 邮件相关辅助逻辑。
- 管理后台辅助逻辑。

## 18. 常见修改入口

| 想修改的内容 | 优先查看 |
| --- | --- |
| 采集任务创建表单 | `apps/web/src/components/collection-tasks/task-form-dialog.tsx` |
| 采集任务列表 | `apps/web/src/components/collection-tasks/collection-tasks-panel.tsx` |
| 采集执行流程 | `apps/api/app/services/collection_runner.py` |
| 采集后自动 AI 发邮件 | `apps/api/app/services/collection_auto_outreach.py` |
| 任务和红人关联 | `apps/api/app/services/task_influencer.py` |
| 邮件发送队列 | `apps/api/app/services/outreach_send_queue_service.py` |
| 邮件调度发送 | `apps/api/app/services/outreach_send_scheduler.py` |
| SMTP/Gmail 账号 | `apps/api/app/services/smtp_account.py` |
| AI 生成逻辑 | `apps/api/app/services/ai_service.py` |
| 红人列表前端 | `apps/web/src/components/influencers/influencers-panel.tsx` |
| 邮件记录前端 | `apps/web/src/components/email-logs/email-logs-panel.tsx` |
| 回信中心前端 | `apps/web/src/components/email-replies/email-replies-panel.tsx` |
| 管理员后台 | `apps/web/src/components/admin` |

## 19. 架构优势

当前架构的主要优势：

- 前后端分离，界面和后端业务逻辑边界清晰。
- 采集 worker 可独立运行，适合长时间任务。
- 数据库迁移完整，便于持续扩展字段和表结构。
- service 层承载核心业务，方便定位采集、AI、邮件等流程。
- 邮件发送通过队列处理，便于限速、重试和记录。
- 支持租户、产品、用户隔离，适合团队内部多业务线使用。
- 文档、设计方案和测试文件比较完整，后续接手有依据。

## 20. 后续扩展建议

后续如果继续优化，可以优先考虑：

- 增强采集续跑能力，让重复关键词能更主动扩展新红人。
- 优化跨平台红人合并，减少同一红人在多个平台重复出现。
- 增加邮箱健康度监控，避免 Gmail/SMTP 账号进入风控。
- 增加发送效果统计，例如发送量、失败率、回复率、合作转化率。
- 增加 AI 生成质量评分，筛掉过长、太广告化或信息不完整的邮件。
- 增加采集任务成本统计，方便评估 Apify/API Direct 使用效果。
- 优化管理员月报，把采集、发信、回信、成交线索串起来。

## 21. 总结

本系统不是单一的采集脚本，而是一套围绕海外红人开发业务建立的完整工作台。

从架构上看，它通过前端后台承载业务操作，通过 FastAPI 后端承载业务逻辑，通过 PostgreSQL 保存业务数据，通过 worker 执行长时间采集任务，通过 AI 生成分析和邮件，通过 SMTP/IMAP 完成发信和回信管理。

对业务员来说，系统的核心价值是减少重复劳动，提高红人开发效率。对管理员来说，系统的核心价值是统一管理数据、账号、产品、任务和业务结果。对开发者来说，系统的核心结构可以从 `apps/api/app/services` 和 `apps/web/src/components` 两条线开始理解。
