# 备份与恢复指南

这个项目不能只依赖某一台电脑保存。下面三类内容一定要安全保存：

- 源代码：保存到私有 Git 远程仓库。
- 数据库备份：保存到项目目录之外的位置。
- 运行密钥：保存到密码管理器或其他加密存储中。

## 需要备份什么

- 代码：本仓库中除忽略文件以外的所有内容。
- 数据库：PostgreSQL 中的产品、红人、采集任务、候选数据、邮件记录和系统设置等数据。
- 密钥：`.env`、`apps/api/.env`、`apps/web/.env.local`、API Key、SMTP 邮箱凭据和数据库密码。

不要把真实密钥或数据库备份文件提交到 Git。

## 推荐备份习惯

- 每完成一个确认通过的功能或修复后，提交一次代码。
- 把代码推送到私有 GitHub、Gitee 或 GitLab 仓库。
- 数据库至少每天备份一次。
- 把备份文件复制到云盘、NAS 或移动硬盘。
- 至少保留最近 7 天的每日备份，以及最近 4 周的每周备份。

建议备份文件名：

```text
influencer-intel-YYYYMMDD-HHMMSS.dump
```

## 环境变量文件

`.env.example` 可以保存在 Git 中，但真实的 `.env` 文件不要提交到 Git。

数据库备份至少需要下面这些变量：

```text
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:PORT/DB_NAME
```

或者：

```text
POSTGRES_USER=USER
POSTGRES_PASSWORD=PASSWORD
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=influencer_intel
```

## 手动备份数据库

在 Windows PowerShell 中，从项目根目录执行：

```powershell
.\scripts\backup_db.ps1
```

也可以指定输出目录：

```powershell
.\scripts\backup_db.ps1 -OutputDir "D:\safe-backups\influencer-intel"
```

也可以导出为普通 SQL 文件：

```powershell
.\scripts\backup_db.ps1 -PlainSql
```

这个脚本需要电脑已经安装 PostgreSQL 客户端工具，尤其是 `pg_dump`，并且 `pg_dump` 可以在 `PATH` 中被找到。

如果 `.env` 中使用的是 Docker 内部主机名 `postgres`，PowerShell 脚本会通过 `localhost` 连接数据库。这样在 Windows 上运行脚本时，也可以连接 Docker Compose 暴露出来的 `5432` 端口。

## Docker Compose 备份方式

如果项目是通过 Docker Compose 运行的，并且 Windows 上没有安装 `pg_dump`，可以使用：

```powershell
.\scripts\backup_db_docker.ps1
```

也可以在项目根目录手动执行下面命令：

```powershell
$name = "influencer-intel-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".dump"
New-Item -ItemType Directory -Path backups -Force | Out-Null
docker compose exec -T postgres pg_dump -U $env:POSTGRES_USER -d $env:POSTGRES_DB --format=custom --blobs --no-owner --no-privileges > "backups\$name"
```

如果当前 PowerShell 中没有设置 `POSTGRES_USER` 或 `POSTGRES_DB`，就使用 `.env` 文件里的值。

## 在新电脑上恢复项目

1. 安装 Git、Node.js、Python、Docker Desktop 和 PostgreSQL 客户端工具。
2. 克隆私有代码仓库。
3. 从安全存储中复制真实环境变量文件：

```text
.env
apps/api/.env
apps/web/.env.local
```

4. 安装前端依赖：

```powershell
cd apps\web
npm install
```

5. 安装后端依赖：

```powershell
cd ..\api
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

6. 启动 PostgreSQL，可以使用 Docker Compose，也可以使用本地 PostgreSQL 服务。
7. 把最新的数据库备份恢复到一个空数据库中：

```powershell
pg_restore --clean --if-exists --no-owner --no-privileges --dbname="postgresql://USER:PASSWORD@HOST:PORT/DB_NAME" "D:\safe-backups\influencer-intel-YYYYMMDD-HHMMSS.dump"
```

8. 执行数据库迁移：

```powershell
cd apps\api
.\.venv\Scripts\alembic upgrade head
```

9. 使用项目正常启动命令或 Docker Compose 启动后端和前端。

## 恢复时的安全规则

- 只恢复到空数据库，或确认可以被覆盖的数据库。
- 在确认目标数据库名称之前，不要对生产数据库执行恢复命令。
- 保留原始备份文件，不要直接修改备份文件。
- 恢复完成后，先检查产品、红人、采集任务和候选数据数量，再正式使用系统。

## 快速恢复检查清单

- 已从私有远程仓库克隆代码。
- 已从安全存储恢复 `.env` 文件。
- 已恢复最新数据库备份。
- 已执行数据库迁移。
- 前端页面可以打开。
- 后端健康检查/API 接口有响应。
- 产品选择器能显示真实产品。
- 采集任务和红人库能显示预期数据。

## Git 远程仓库设置

先在 GitHub、Gitee 或 GitLab 创建一个私有仓库，然后在项目根目录执行：

```powershell
git remote add origin YOUR_PRIVATE_REPO_URL
git push -u origin main
```

如果当前分支不是 `main`，可以用下面命令查看当前分支：

```powershell
git branch --show-current
```

然后推送当前实际分支即可。
