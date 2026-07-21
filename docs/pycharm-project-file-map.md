# PyCharm 项目文件梳理说明

## 1. 项目整体说明

这个项目是一个海外红人数据采集与 AI 邮件外联系统，主要由前端后台、后端接口、数据库迁移、业务文档和运维脚本组成。

日常开发和查看时，建议优先关注 `apps/api/app`、`apps/web/src` 和 `docs`。依赖目录、构建目录、缓存目录和备份目录一般不需要在 PyCharm 中展开查看。

## 2. 推荐重点查看目录

| 目录 | 作用 | 建议 |
| --- | --- | --- |
| `apps/api/app` | 后端核心代码，包括接口、模型、服务、采集、邮件、AI、权限等逻辑 | 后端功能主要看这里 |
| `apps/api/app/api/routes` | 后端 API 路由，负责接收前端请求 | 想找接口入口看这里 |
| `apps/api/app/services` | 后端业务逻辑，负责采集、去重、AI、邮件、任务调度等 | 修改业务规则主要看这里 |
| `apps/api/app/models` | 数据库模型 | 想看数据表结构看这里 |
| `apps/api/app/schemas` | 接口输入输出结构 | 想看前后端字段看这里 |
| `apps/api/app/collectors` | 平台采集器入口 | 想看红人采集逻辑看这里 |
| `apps/api/app/workers` | 后台采集任务执行 | 想看自动运行任务看这里 |
| `apps/web/src` | 前端后台页面和组件 | 前端页面主要看这里 |
| `apps/web/src/app` | Next.js 页面路由 | 想找某个页面入口看这里 |
| `apps/web/src/components` | 页面组件 | 想改界面和按钮看这里 |
| `apps/web/src/lib` | 前端工具函数和数据处理逻辑 | 想改前端计算规则看这里 |
| `docs` | 项目说明、方案、计划和背景文档 | 给人看的说明都放这里 |

## 3. 后端目录说明

### `apps/api/app/api/routes`

这里是后端接口入口。例如：

- `collection_tasks.py`：采集任务接口。
- `influencers.py`：红人列表、详情、导出等接口。
- `outreach_campaigns.py`：外联活动接口。
- `outreach_send_queue.py`：邮件发送队列接口。
- `smtp_accounts.py`：发信邮箱账号配置接口。
- `email_logs.py`：邮件发送记录接口。
- `email_inbound.py`：回信接收接口。
- `admin.py`：管理员相关接口。

### `apps/api/app/services`

这里是后端业务逻辑最集中的地方。例如：

- `collection_runner.py`：采集任务运行主流程。
- `collection_auto_outreach.py`：采集完成后自动 AI 发邮件流程。
- `task_influencer.py`：采集任务和红人数据关联逻辑。
- `contact_discovery.py`：联系方式发现逻辑。
- `email.py`、`email_log.py`：邮件发送和日志。
- `outreach_send_scheduler.py`：邮件队列调度。
- `ai_service.py`、`ai_analysis.py`：AI 生成和分析。
- `smtp_account.py`：SMTP/Gmail 发信账号管理。

### `apps/api/app/models`

这里定义数据库表对应的模型。例如：

- `influencer.py`：红人资料。
- `collection_task.py`：采集任务。
- `collection_task_candidate.py`：采集候选数据。
- `email_log.py`：邮件日志。
- `email_reply.py`：邮件回信。
- `message_template.py`：话术模板。
- `user_smtp_account.py`：业务员发信邮箱账号。

### `apps/api/alembic/versions`

这里是数据库迁移文件，用来记录数据库表结构变化。一般不要手动乱改历史迁移，除非明确知道要改数据库结构。

## 4. 前端目录说明

### `apps/web/src/app`

这里是前端页面入口。常见页面包括：

- `collection-tasks`：采集任务页面。
- `influencers`：红人列表和详情页面。
- `message-templates`：话术模板页面。
- `outreach-campaigns`：外联活动页面。
- `outreach-send-queue`：邮件发送队列页面。
- `email-logs`：邮件记录页面。
- `email-replies`：回信中心页面。
- `settings`：系统设置页面。
- `admin`：管理员后台页面。

### `apps/web/src/components`

这里是页面组件。页面中看到的表格、弹窗、按钮、筛选器、表单，通常都在这里。

比较常用的目录：

- `collection-tasks`：采集任务相关组件。
- `influencers`：红人列表和详情组件。
- `message-templates`：话术模板组件。
- `email-logs`：邮件记录和发送队列组件。
- `admin`：管理员后台组件。
- `layout`：后台整体布局。
- `ui`：基础按钮、输入框、卡片等组件。

### `apps/web/src/lib`

这里是前端公共逻辑。比如字段标签、接口请求、数据格式处理、筛选条件处理等。

## 5. 文档目录说明

| 文件 | 说明 |
| --- | --- |
| `docs/project-background.md` | 项目背景说明书 |
| `docs/collection-auto-ai-outreach.md` | 采集后自动 AI 发邮件说明 |
| `docs/backup-and-restore.md` | 备份和恢复说明 |
| `docs/superpowers/specs` | 功能设计方案 |
| `docs/superpowers/plans` | 功能实现计划 |

## 6. 不建议日常展开的目录

| 目录或文件 | 原因 |
| --- | --- |
| `apps/web/node_modules` | 前端依赖，文件很多，不需要看 |
| `apps/web/.next` | 前端构建缓存，可自动生成 |
| `apps/api/.venv` | Python 虚拟环境，不需要看 |
| `.git` | Git 内部目录，不需要手动改 |
| `.codex-logs` | 工具日志，不影响业务 |
| `backups` | 备份文件，删除前必须确认 |
| `output` | 输出文件，通常不是核心代码 |
| `pytest-cache-files-*` | 测试缓存，不是业务代码 |

## 7. PyCharm 查看建议

建议在 PyCharm 中重点展开：

```text
apps
  api
    app
      api/routes
      services
      models
      schemas
      workers
  web
    src
      app
      components
      lib
docs
```

建议把下面这些目录折叠或标记为 excluded：

```text
apps/web/node_modules
apps/web/.next
apps/api/.venv
.git
.codex-logs
pytest-cache-files-*
```

## 8. 修改文件时的简单判断

- 改后端接口：先看 `apps/api/app/api/routes`。
- 改采集、去重、自动发邮件：先看 `apps/api/app/services`。
- 改数据库字段：看 `apps/api/app/models` 和 `apps/api/alembic/versions`。
- 改前端页面：先看 `apps/web/src/app`。
- 改页面里的表格、弹窗、按钮：看 `apps/web/src/components`。
- 改前端字段显示、状态文案、数据处理：看 `apps/web/src/lib`。
- 写业务说明和交接说明：放到 `docs`。

## 9. 本次文件注释规则

为了让 PyCharm 中打开文件时更容易判断用途，本次只给安全范围内的源码文件顶部增加说明注释：

- Python 文件使用 `# 文件说明：...`
- TypeScript / TSX 文件使用 `// 文件说明：...`

不会给 JSON、环境变量、图片、PDF、构建产物、依赖目录和备份文件加注释，避免影响项目运行。
