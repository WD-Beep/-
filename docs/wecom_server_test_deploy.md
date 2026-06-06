# 企业微信服务器测试部署方案

本文说明如何将自动报价系统部署到**公网服务器 + 测试域名**，供业务员在企业微信中真实试用。  
**不使用**本地 `127.0.0.1` 或内网穿透；正式上线时**只替换域名与环境变量**，无需改代码。

---

## 一、服务器测试部署目标

| 目标 | 说明 |
|------|------|
| 真实试用 | 业务员在企微自建应用中上传 Excel、生成报价、查看「我的报价」与审批状态 |
| 测试域名 | 先用临时域名（如 `test-quote.example.com`），稳定后再换正式域名 |
| 零代码切换 | 换域名时只改 DNS、`.env`、企微管理后台配置，然后重启服务 |
| 身份隔离 | `WECOM_ENABLED=1` 时须企微 OAuth 登录；`sales_user_id=wecom:{userid}`，A/B 业务员数据隔离 |

---

## 二、服务器要求

### Python 版本

- 推荐 **Python 3.11+**（项目已在 3.14 下测试通过）
- 安装依赖：

```bash
cd /path/to/自报项目
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

可选：PostgreSQL 归档、`sentence-transformers` 语义检索等按现有 README 配置；企微 OAuth 本身不依赖 GPU。

### 项目启动方式

```bash
# 复制并编辑环境变量
cp .env.example .env
# 填写 WECOM_* 与 QUOTE_SERVER_HOST 等（见第四节）

# 前台 + 后台同进程启动（默认前台 8776、后台 8080）
python server.py --force-unlock
```

常用环境变量：

| 变量 | 说明 | 测试部署建议 |
|------|------|----------------|
| `QUOTE_SERVER_HOST` | 前台监听地址 | `0.0.0.0` |
| `QUOTE_SERVER_PORT` | 前台端口 | `8776`（默认） |
| `QUOTE_ADMIN_SERVER_HOST` | 后台监听地址 | `127.0.0.1`（仅本机/VPN） |
| `QUOTE_ADMIN_HTTP_PORT` | 后台端口 | `8080`（默认） |

### 端口说明

| 端口 | 站点 | 公网暴露 |
|------|------|----------|
| 8776 | 前台（业务员报价、企微 OAuth） | 通过反向代理暴露为 HTTPS 443 |
| 8080 | 后台（管理员审批、价格库） | **不要**直接暴露公网；内网/VPN/SSH 隧道访问 |

企微自建应用「主页」只需指向前台 HTTPS 域名根路径。

### 反向代理（必须 HTTPS）

企业微信 OAuth **必须 HTTPS**。推荐 Nginx 或 Caddy 终止 TLS，反代到 `127.0.0.1:8776`。

**Nginx 示例**（域名替换为你的测试域名）：

```nginx
server {
    listen 443 ssl http2;
    server_name test-quote.example.com;

    ssl_certificate     /etc/letsencrypt/live/test-quote.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/test-quote.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8776;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        client_max_body_size 50m;   # Excel 上传
    }
}
```

**Caddy 示例**（自动 HTTPS）：

```caddy
test-quote.example.com {
    reverse_proxy 127.0.0.1:8776
    request_body {
        max_size 50MB
    }
}
```

证书可用 Let's Encrypt、云厂商免费证书或企业证书。

---

## 三、测试域名配置

### 1. DNS

将测试域名 **A 记录** 指向服务器公网 IP，例如：

```
test-quote.example.com  →  203.0.113.10
```

### 2. HTTPS

- 在反向代理层配置有效证书
- 浏览器访问 `https://test-quote.example.com/` 应无证书警告

### 3. 企业微信管理后台

路径：**应用管理 → 自建应用 → 你的应用**

| 配置项 | 填写内容 |
|--------|----------|
| 应用主页 | `https://test-quote.example.com/` |
| 网页授权回调域名 / 可信域名 | `test-quote.example.com`（仅域名，无协议、无路径） |
| （隐含）OAuth 回调路径 | `https://test-quote.example.com/api/auth/wecom/callback` |

须与 `.env` 中 `WECOM_OAUTH_REDIRECT_URI` **完全一致**（含 `https`、路径）。

获取 **CorpID、AgentId、Secret**：同一应用详情页 → 企业 ID、AgentId、Secret。

---

## 四、.env 示例

复制 `.env.example` 为 `.env`，测试部署最小集如下（**勿提交真实 Secret**）：

```env
QUOTE_DOTENV_WINS=1
QUOTE_SERVER_HOST=0.0.0.0
QUOTE_SERVER_PORT=8776
QUOTE_ADMIN_SERVER_HOST=127.0.0.1
QUOTE_ADMIN_HTTP_PORT=8080

WECOM_ENABLED=1
WECOM_CORP_ID=wwxxxx
WECOM_AGENT_ID=1000001
WECOM_CORP_SECRET=xxxx
WECOM_PUBLIC_BASE_URL=https://test-quote.example.com
WECOM_OAUTH_REDIRECT_URI=https://test-quote.example.com/api/auth/wecom/callback
WECOM_COOKIE_SECURE=1
```

说明：

- 所有对外 URL **只来自环境变量**，代码中无写死域名
- 未设置 `WECOM_OAUTH_REDIRECT_URI` 时，会由 `WECOM_PUBLIC_BASE_URL` + `/api/auth/wecom/callback` 自动拼接
- `WECOM_COOKIE_SECURE=1` 或 `COOKIE_SECURE=1`：HTTPS 下 Cookie 带 `Secure`；SameSite 默认 `Lax`
- 本地开发保持 `WECOM_ENABLED=0`，**不要**开 `WECOM_COOKIE_SECURE`

---

## 五、业务员测试流程

1. **打开应用**  
   企业微信 → 工作台 → 自建应用（主页为测试域名）

2. **授权登录**  
   - 首次进入会跳转企微 OAuth  
   - 回调后写入 Cookie：`aq_sales_user_id=wecom:{userid}`  
   - 页面顶部应显示「已登录：企微-xxx」或姓名

3. **上传 Excel**  
   在对话区上传报价 Excel，确认结构后生成报价

4. **生成报价**  
   完成结构确认与报价计算，保存到归档

5. **我的报价**  
   打开「我的报价」列表，应只看到**当前业务员**的记录

6. **管理员审批**（后台 8080，内网访问）  
   管理员登录后台 → 对待审报价执行通过/驳回

7. **查看审批状态**（前台）  
   业务员刷新或重新打开报价，通过 `GET /api/quotes/{id}/approval` 看到 `approval_status` / `approval_note`

8. **A/B 隔离验证**  
   - 业务员 A、B 分别登录，各生成一条报价  
   - A 的「我的报价」中不应出现 B 的记录  
   - B 无法读取 A 的审批详情（403/404）

---

## 六、正式域名切换流程

系统稳定后，例如从 `test-quote.example.com` 换为 `quote.yourcompany.com`：

1. **DNS**  
   新域名 A 记录指向同一服务器（或新服务器）

2. **HTTPS**  
   为新域名申请/部署证书，更新 Nginx/Caddy `server_name`

3. **修改 `.env`**（无需改代码）  
   ```env
   WECOM_PUBLIC_BASE_URL=https://quote.yourcompany.com
   WECOM_OAUTH_REDIRECT_URI=https://quote.yourcompany.com/api/auth/wecom/callback
   ```

4. **企业微信后台**  
   - 应用主页 → 新 HTTPS 根 URL  
   - 网页授权回调域名 → 新主机名  
   - 确认 OAuth 回调与新 `WECOM_OAUTH_REDIRECT_URI` 一致

5. **重启服务**  
   ```bash
   python server.py --force-unlock
   ```

6. **回归测试**  
   - 企微内打开新域名 → OAuth 登录成功  
   - `/api/auth/status` → `authenticated: true`  
   - 「我的报价」数据仍在（`wecom:{userid}` 未变则数据连续）

---

## 七、常见问题

### 企业微信提示「回调域名不可信」

- 检查后台「网页授权回调域名」是否**只填主机名**（如 `test-quote.example.com`），不要带 `https://` 或路径
- 检查 `WECOM_OAUTH_REDIRECT_URI` 的域名与后台一致
- 域名须已备案且 HTTPS 可访问（视企业微信当前政策）

### 登录后仍未认证

- 访问 `GET https://<域名>/api/auth/status`，看 `wecom_enabled`、`wecom_configured`、`authenticated`
- 若 `wecom_configured: false`：检查 CorpID / AgentId / Secret 与 `WECOM_OAUTH_REDIRECT_URI` 是否齐全
- OAuth 回调若 400：查看响应 `message`（常见为 code 过期、Secret 错误）

### Cookie 丢失

- HTTPS 部署必须 `WECOM_COOKIE_SECURE=1`（或 `COOKIE_SECURE=1`）
- 若用 HTTP 访问却开了 Secure，浏览器不会保存 Cookie
- 确认反向代理未剥离 `Set-Cookie` 头
- SameSite 默认 Lax，企微内置浏览器打开同源链接一般正常

### HTTPS 证书错误

- 企微客户端对证书较严格，避免自签证书
- 确保证书链完整、域名与访问 URL 一致

### 域名换了但 `.env` 没更新

- OAuth 仍指向旧域名 → 授权失败或回调 404
- 改 DNS 后必须同步改 `WECOM_PUBLIC_BASE_URL` 与 `WECOM_OAUTH_REDIRECT_URI`

### 企业微信后台可信域名没同步

- 换域名后**必须**在企微后台更新回调域名与应用主页
- 旧域名与新 `.env` 混用会导致「不可信」或登录循环

### 普通浏览器访问 `/api/my/quotes` 返回 401

- `WECOM_ENABLED=1` 时，接口要求 Cookie 中 `aq_sales_user_id` 以 `wecom:` 开头
- 普通浏览器未走企微 OAuth，无有效 Cookie，返回 401 与 `auth_required` 是**预期行为**
- 测试请在企微内置浏览器或完成 OAuth 后再访问

---

## 相关文件

| 文件 | 作用 |
|------|------|
| `.env.example` | 环境变量模板（含测试部署段） |
| `wecom_auth.py` | OAuth URL、Token、`wecom:{userid}` 格式化 |
| `session_quote_context.py` | Cookie Secure / SameSite |
| `server.py` | `/api/auth/wecom/*`、前台身份校验 |
| `static/app.js` | 企微浏览器识别、登录条、401 提示 |
