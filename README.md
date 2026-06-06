# 自动报价系统

定制软包 BOM 智能自动报价系统（报价客服工作台 + 管理后台）。

本项目现在包含两部分：

- 本地报价工作台：生成“明细数据表”和“三档数量报价”，效果对齐你给的图二。
- 反馈学习脚本：把“AI 成本价”和“人工成本价”做对比，沉淀成可投喂知识库的增量资料。

它不会直接改变大模型参数，但可以让旧 agent 的知识库越来越完整：每次人工修正都会沉淀为规则、案例和注意事项。

## 启动可视化页面

Web **只有这一份**：`python server.py` 同时负责静态页面和 `/api/*`（无前、后端拆分端口）。

```bash
python server.py
```

默认在浏览器打开（仅开发机本机监听；**本项目默认 8776，避免与其它占用 8765 的本地程序混淆**）：

```text
http://127.0.0.1:8776
```

若 **8776** 已被占用，可显式换一个 **数字端口**（下例换成 9000，仅作占位；请改成你实际需要且未被占用的端口）：

```bash
python server.py 9000
```

或在 PowerShell 里用环境变量（同样不是默认端口，只是可选配置）：

```powershell
$env:QUOTE_SERVER_PORT="9000"
python server.py
```

**注意**：下面的 `python main.py`（反馈学习脚本）**不启动任何 HTTP 端口**，不要被名字里的「端口」混在一起。

打不开页面、浏览器显示 **127.0.0.1 拒绝连接**：常见原因有两点——① 没有把地址写全（必须用 `http://127.0.0.1:8776/` ，不能只填 `127.0.0.1` ，后者会去找 80 端口）；② **`server.py` 没在所选端口成功启动**。

若上一次异常退出，`acquireKnowledge\自报项目\.server.lock` 卡死可能导致无法启动可运行：

```bash
python server.py --force-unlock
```

再打开 **http://127.0.0.1:8776/** （若改过端口则用终端里打印的端口）。若 `--force-unlock` 也无法删除锁文件，请在任务管理器结束仍在运行的 `python server.py`，或注销/重启后再试。

页面会展示：

- 明细数据表（物料名称 / 规格 / 用量 / 单价）
- AI补全字段会在数据后显示 `(AI)`
- 三档数量报价（固定为 `300件 / 500件 / 1000件`）
- 报价公式：`成本 / (1 - 预计毛利率) = EXW`，`FOB = EXW + 4元/个`
- 报价阶梯可视化
- 客服聊天式前端模板（OpenClaw 风格结果卡）
- 数据完整度提醒（提示规格/用量缺失行）
- 上传表格绿色成功状态
- 人工修正保存入口

## 接入 Kimi 2.6

默认已接入 `kimi-k2.6`（Moonshot 接口）。不写死密钥，走环境变量：

```powershell
$env:KIMI_API_KEY="你的密钥"
$env:KIMI_MODEL="kimi-k2.6"
python server.py
```

可选参数：

- `KIMI_BASE_URL`：默认 `https://api.moonshot.ai/v1`
- `KIMI_TIMEOUT_SECONDS`：默认 `25`

启动后页面会显示“模型状态”，并在有缺失字段时自动调用 Kimi 补全。

### 改用 DeepSeek（例如 `deepseek-v4-pro`）

使用官方 OpenAI 兼容接口：`https://api.deepseek.com/v1`。请勿把密钥写进仓库，仅在当前终端或系统环境变量中设置：

```powershell
$env:DEEPSEEK_API_KEY="（在 DeepSeek 控制台生成的密钥）"
$env:KIMI_BASE_URL="https://api.deepseek.com/v1"
$env:KIMI_MODEL="deepseek-v4-pro"
python server.py
```

也可使用 `OPENCLAW_API_KEY` / `OPENCLAW_BASE_URL`（与 Kimi 变量二选一覆盖）。DeepSeek 走兼容接口时会自动去掉 Moonshot 专有的 `thinking` 字段。

打开界面：浏览器访问终端里打印的 **`http://127.0.0.1:(端口)/`**（本仓库 README 所称「OpenClaw 风格」即此工作台前端，并非单独安装的应用）。

## 运行反馈学习

```bash
python main.py
```

运行后会生成：

- `reports/latest_report.md`：报价误差分析报告
- `knowledge_updates/pending_knowledge.jsonl`：可投喂知识库的增量知识

## 运行测试

```bash
python -m unittest discover -s tests
```

## 输入数据格式

默认读取 `data/sample_quotes.csv`。你可以换成自己的 CSV：

```bash
python main.py --input data/your_quotes.csv
```

CSV 字段：

- `quote_id`：报价记录编号
- `product_name`：产品名称
- `category`：产品分类
- `material`：材料
- `process`：工艺
- `quantity`：数量
- `ai_cost`：AI 算出的成本价
- `manual_cost`：人工核算的成本价
- `ai_reason`：AI 报价依据
- `manual_reason`：人工修正依据

## 怎么让它越用越聪明

每次报价后追加一行记录到 CSV：

- AI 原始成本价
- 人工最终成本价
- 人工为什么改价

脚本会把中高误差案例写入 `knowledge_updates/pending_knowledge.jsonl`。旧 agent 的知识库系统可以定时读取这个文件，把这些“报价教训”作为新增知识入库。

## 后续可扩展

- 接入真实报价数据库
- 接入旧 agent 的向量库或文件知识库
- 增加审批门禁，避免错误知识自动入库
- 按产品分类生成专属报价规则
- 做成定时任务，每天自动分析前一天报价

### 自动回流与防脏库

生产环境建议采用“先审后写”模式：

1. `KNOWLEDGE_AUTO_LEARN=1`：允许 miss 后走回流候选流程（异步 judge）。
2. `KNOWLEDGE_AUTO_WRITE=0`（默认）：不直接写入 `data/price_kb.xlsx`，而是写入待审核文件 `knowledge_updates/pending_auto_learn.jsonl`。
3. `KNOWLEDGE_AUTO_LEARN_MIN_CONFIDENCE=0.8`（可选）：低于阈值不入队。
4. `KNOWLEDGE_PENDING_AUTO_APPLY=1`（可选）：启动服务后自动消费 `pending_auto_learn.jsonl`，将达标候选写入 `data/price_kb.xlsx` 并刷新内存 KB/embedding。默认关闭。

手动消费待审核队列：

```bash
python tools/apply_pending_auto_learn.py
```

只预览不写库：

```bash
python tools/apply_pending_auto_learn.py --dry-run
```

离线测试或只验证写表时可跳过 embedding 重建：

```bash
python tools/apply_pending_auto_learn.py --skip-reload
```

手工开关：

1. 需要自动落库时，临时设置 `KNOWLEDGE_AUTO_WRITE=1`（尽量在灰度环境先验证）。
2. 需要把待审核队列自动注入知识库时，设置 `KNOWLEDGE_PENDING_AUTO_APPLY=1`。
3. 每次变更建议清理或归档 `pending_auto_learn.jsonl`，并保留人工复核痕迹。
