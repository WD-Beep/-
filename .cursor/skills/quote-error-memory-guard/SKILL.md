---
name: quote-error-memory-guard
description: >-
  Maintains the quote system error recurrence-prevention memory for 报价客服工作台.
  Use before fixing,验收, or investigating quote calculation, BOM/物料明细, spec/尺寸/用量,
  裁片/部位/片数, admin detail, 客户报价单/PDF, product images, packaging, or front/back
  field mapping. Read historical error patterns first; after each fix append 错误模式+根因+必测项.
---

# Quote Error Memory Guard

## 强制工作流（Agent 必读）

1. **开始前**：本 Skill 为报价相关任务的**第一步**；未阅读「历史错误模式」与「工作原则」不得改代码。
2. **进行中**：匹配历史错误则套用防复发规则；展示修复与计价修复分开。
3. **结束后**：每发现一个新错误/验收问题，必须按模板追加到下文「历史错误模式」，并同步更新：
   - `自报项目/.cursor/skills/quote-error-memory-guard/SKILL.md`
   - `~/.cursor/skills/quote-error-memory-guard/SKILL.md`
4. 项目规则 `.cursor/rules/quote-error-memory-guard.mdc`（`alwaysApply: true`）与本 Skill 同时生效。

## 触发条件

当任务涉及以下任意内容时，必须使用本 Skill：

- 报价计算
- BOM / 物料明细
- 规格 / 尺寸 / 用量
- 裁片 / 部位 / 片数
- 报价客服工作台
- 后台报价详情
- 管理员修正
- 报价记录
- 客户报价单 / PDF
- 产品图片 / 款式图片
- 包装字段
- 前端展示和后端字段映射
- Cursor 修复后的验收

## 工作原则

1. 先查历史错误，再动手
- 修复前必须先阅读本 Skill 里的“历史错误模式”。
- 如果当前问题和历史错误相似，必须优先套用已有防复发规则。
- 不允许只按当前截图临时修一个表面问题。

2. 每次修复后必须沉淀新规则
每次发现新问题，都要追加一条记录，格式如下：

### 错误模式：一句话概括
- 发生场景：
- 错误表现：
- 根因：
- 正确做法：
- 禁止做法：
- 必测项：
- 相关文件/模块：

3. 展示修复和计算修复必须分开
- 展示字段补齐不能改变报价计算。
- 不允许因为 UI/PDF 好看而改动单价、用量、小计、总价。
- 如果必须改计算，必须明确说明并加测试。

4. 原始数据优先
优先级固定为：
管理员修正 > 上传表格/BOM/原始计算表 > 已保存业务数据 > 结构说明/公式/物料名推断 > AI 推断

禁止：
- AI 推断覆盖管理员修正
- AI 推断覆盖原始表格
- 为了“不为空”硬塞错误值

5. 客户报价单必须干净
客户 PDF/报价单不能出现：
- 问题一描述
- 图片说明
- 工作簿嵌入图片
- 背景指向
- 系统估算
- AI估算
- 推断
- ai/kb 来源
- 调试文本
- OCR 残留
- null / undefined / NaN / 单独 “-”

6. 后台可以详细，客户单要简洁
- 后台材料明细可以显示裁片、尺寸、待核、来源等内部信息。
- 客户报价单只显示客户需要看的：产品图、名称、成品尺寸、描述、包装、数量、单价、总价。
- 客户报价单尺寸列只显示成品尺寸，不显示前片/后片/底片/侧片。

7. 图片宁可不放，也不能放错
款式图片只能放产品包本身。
必须过滤：
- 表格截图
- 文字截图
- 尺寸表
- 工艺说明图
- 背景图
- logo
- 二维码
- 工作簿嵌入说明图
- OCR 图
- 不确定来源图片

8. 裁片数量不能模糊
禁止后台材料明细里出现：
- 1组
- 一组
- 组

应改成：
- 前片 1片
- 后片 1片
- 底片 1片
- 侧片 2片
- 拉链盖 无法确定时显示“估算/待核”

如果客户报价单：
- 不显示裁片列表
- 只显示成品尺寸

9. 包装字段不能显示内部口径
客户报价单包装列不能显示：
- 系统估算
- AI估算
- 推断
- 估算

应显示：
- 1个
- 1套
- OPP袋1个
- 纸箱1个

10. 每次验收必须跑验证
至少检查：
- 相关单元测试
- 后台详情显示
- 客户 PDF/报价单显示
- 金额是否变化
- 是否还出现历史禁词
- 图片是否只剩产品图

## 历史错误模式

### 错误模式：客户报价单描述混入内部解析文本
- 发生场景：PDF/报价单描述列
- 错误表现：出现“问题一描述”“图片说明”“工作簿嵌入图片”等文字
- 根因：把解析过程文本直接拼进客户描述
- 正确做法：客户描述必须经过清洗，只保留产品材料、结构、工艺等客户可读内容
- 禁止做法：直接把 AI/OCR/解析原文塞进 PDF
- 必测项：PDF 中搜索“问题一描述/图片说明/工作簿嵌入”
- 相关文件/模块：quote_sheet_content、quote_sheet_prefill、PDF/报价单模板

### 错误模式：款式图片混入表格截图或文字截图
- 发生场景：报价单款式图片列
- 错误表现：产品图列出现小表格截图、文字截图、说明图
- 根因：Excel 嵌入图片没有区分产品图和文档截图
- 正确做法：只接受可信产品图；来源不确定则不放
- 禁止做法：把所有 workbook embedded images 都放进报价单
- 必测项：生成 PDF 后检查款式图片列只显示包本身
- 相关文件/模块：quote_sheet_images、quote_sheet_content、quote_sheet_prefill

### 错误模式：产品图列自动带入包装图/标签图/材料图/银行图
- 发生场景：生成报价单 → 产品明细「图」列自动回填
- 错误表现：出现包装图、吊牌、尺寸说明、材料样卡、二维码、小票、银行信息等非包款图
- 根因：`_best_obvious_product_image_url` 仅按像素面积选图，绕过可信来源；文件名未过滤 packaging/label/material 等关键词
- 正确做法：仅 `product/main/style/bag` 类可信图可自动填入；路径含 packaging/label/material/bank/qrcode 等一律拒绝；多图按 `product_image_score`（含包/主图关键词加分）择优；不确定则「无图」；用户手动上传（`userUploaded`）不受限
- 禁止做法：用 `_best_obvious_product_image_url` 面积 fallback 填未标记嵌入图；把 `image_source=sheet_embed` 当文件名扫关键词
- 必测项：包图+包装图附件只显示包图；仅包装/标签图显示无图；手动换图后页面与 PDF 一致；`pytest tests/test_quote_sheet_content.py tests/test_quote_sheet_prefill.py`
- 相关文件/模块：quote_sheet_content、quote_sheet_prefill、quote_sheet_images、static/quote_sheet.js

### 错误模式：展示补齐规格/用量导致金额变化
- 发生场景：规格/用量补齐
- 错误表现：为了让 UI 不为空，补了默认用量，结果参与计算改了小计/总价
- 根因：展示字段和计价字段没有分离
- 正确做法：展示补齐只影响展示，不影响计算；用 `_spec_display_inferred` / `_usage_display_inferred`，禁止展示补齐触发 `spec_ai` 参与风险闸门
- 禁止做法：用展示推断值重算 amount/material_total；展示补齐设置 `spec_ai=True`
- 必测项：修复前后单价、用量、小计、总价保持一致；`pytest tests/test_material_spec_usage_enricher.py tests/test_quote_validation_gate.py`
- 相关文件/模块：material_spec_usage_enricher、quote_engine、quote_validation_gate

### 错误模式：客户报价单尺寸列混入裁片名称
- 发生场景：客户 PDF/报价单尺寸列
- 错误表现：尺寸列出现“前片；后片；底片；侧片”或 `32×19×45cm / 前片；后片...`
- 根因：后台裁片字段被拼进客户报价单尺寸列（`_compose_size_for_sheet` 拼接 `piece_part`）
- 正确做法：客户报价单尺寸列只显示成品尺寸，例如 32×19×45cm；`quote_sheet.js` 用 `sanitizeCustomerSizeText`
- 禁止做法：把后台裁片明细塞进客户 PDF 尺寸列
- 必测项：PDF 尺寸列不出现前片/后片/底片/侧片；`pytest tests/test_quote_sheet_prefill.py::QuoteSheetPrefillTest::test_size_excludes_piece_names_when_piece_area_present`
- 相关文件/模块：quote_sheet_prefill、material_detail_display、static/quote_sheet.js

### 错误模式：后台裁片数量显示“1组”
- 发生场景：后台材料明细裁片/部位列
- 错误表现：侧片（2片）（1组）、前片后片后面出现 1组
- 根因：`piece_area_table` 侧片 `qty_text` 为“1组”；展示层把 qty 拼进裁片名；或陈旧 `piece_part` 缓存未重建
- 正确做法：裁片按片/个展示；`_piece_name_for_display` 将组换算为片数；admin 优先从 `piece_area_calculation.rows` 重建
- 禁止做法：显示 1组/一组/组；因 `piece_part` 含“待核”子串而跳过 `piece_area` 重建
- 必测项：后台材料明细搜索“1组/一组/组”；`pytest tests/test_material_detail_display.py`
- 相关文件/模块：material_detail_display、piece_area_table、static/admin/admin.js

### 错误模式：客户报价单包装列显示“系统估算”
- 发生场景：客户 PDF/报价单包装列
- 错误表现：包装列显示“系统估算 / 1个”
- 根因：内部估算来源被展示给客户
- 正确做法：客户单只显示包装值，如 1个/1套/OPP袋1个；`_sanitize_pack_fragment` + `sanitizeCustomerPackText`
- 禁止做法：客户单显示系统估算/AI估算/推断
- 必测项：PDF 包装列不出现系统估算/AI估算/推断/估算；`pytest tests/test_quote_sheet_prefill.py`
- 相关文件/模块：quote_sheet_prefill、static/quote_sheet.js

### 错误模式：同裁片主料/里布㎡差异过大或里布占比压低
- 发生场景：报价计算/明细 enrichment 后自动扫描，或人工保存前
- 错误表现：裁片/部位一致但主料 1.13㎡、里布 0.25㎡；calc_note 含「里布占比0.22」
- 根因：`structure_usage` 曾对全包里布 ×0.22；未写入 `quote_anomaly_history` 时仅人工 Skill 提醒
- 正确做法：`quote_anomaly_learning.scan_and_learn_from_quote` 自动检测→`quote_anomaly_history`→候选/晋升规则→高确定性可 `apply_anomaly_auto_fixes`（遵守管理员/BOM 优先）
- 禁止做法：硬编码报价编号/材料固定㎡；未审核的 candidate 直接 enabled=1 改全局价格库 xlsx
- 必测项：`pytest tests/test_quote_anomaly_learning.py tests/test_fabric_lining_usage_parity.py`
- 相关文件/模块：quote_anomaly_learning、structure_usage、quote_correction_learning、material_spec_usage_enricher、quote_engine

### 错误模式：后台裁片/部位只显示名称不带尺寸
- 发生场景：后台材料明细裁片/部位列
- 错误表现：仅 `前片；后片；底片`，无 `10×22` 等尺寸
- 根因：未从 `piece_area_calculation.rows[].size_text` 组装；或未调用 `enrich_quote_material_detail_display`
- 正确做法：展示为 `前片 19×45；侧片（2片）45×19×2`；无尺寸用估算/待核
- 禁止做法：只拼接 `piece` 字段忽略 `size_text`
- 必测项：面料行含 `×`；无孤立 `-`；金额不变
- 相关文件/模块：material_detail_display、quote_upload_storage、static/admin/admin.js

## 每次修复后的更新动作

每次修复或验收完成后，如果发现新错误模式，请把它追加到“历史错误模式”里。

追加时必须写清楚：
- 这次错在哪里
- 为什么会错
- 下次怎么提前发现
- 哪些词/字段/页面/PDF 必须检查
- 哪些测试要补

目标：
这个 Skill 每用一次就更聪明，后续修复同类问题时先预防，而不是等用户截图指出来。

### 错误模式：客户报价单打样费/打样时间未保存或未进 PDF
- 发生场景：生成报价单页客户资料区；中英文 PDF 黄色条下方 sample meta
- 错误表现：打样费/打样时间无法回填；PDF 缺失或显示 null/undefined；被客户历史资料覆盖
- 根因：未纳入 `QUOTE_SHEET_META_KEYS`；未接入 `collectMetaBundle`/prefill；merge 时从 history 灌入
- 正确做法：`sample_fee`/`sample_lead_time` 仅存当前报价 `quote_sheet_meta`；merge 仅 saved>inferred；空值不显示；英文走 `translate_free_text`
- 禁止做法：另起存储；强制数字/日期；改动计价/BOM/价格库
- 必测项：`pytest tests/test_quote_sheet_meta.py tests/test_quote_sheet_i18n.py tests/test_quote_sheet_pdf_layout.py`；保存刷新回填；中英文 PDF 可见
- 相关文件/模块：quote_sheet_meta.py、static/index.html、static/quote_sheet.js、data/i18n/quote_sheet_zh_en.json

### 错误模式：打样「是否需要」未区分导致强制填写或 PDF 空行
- 发生场景：生成报价单导出中文/英文 PDF；一键导出；后台报价详情
- 错误表现：不需打样仍要求填费/时间；PDF 出现空打样费行；未选是否需要时弹窗阻断导出；后台看不到打样三字段
- 根因：导出 gate 强制 `sample_required`；PDF 未按 yes/no/pending/空 分支；后台 BOM 信息表未展示 quote_sheet_meta
- 正确做法：导出不阻断（空/pending/yes缺费时间均允许）；no→「不需要/Not required」；空/pending/yes缺费时间→「待确认/To be confirmed」；yes且费时间齐全→仅显示费/时间；打样费不进产品 total/FOB；后台 `buildBomProductRows` 展示三字段
- 禁止做法：导出弹窗强制选择；yes 缺费时间显示空行或系统估算；改动计价/BOM/价格库
- 必测项：`pytest tests/test_quote_sheet_sample_required.py`；旧报价无字段可 prefill+导出；中英文 PDF 无 null/undefined
- 相关文件/模块：quote_sheet_meta.py、static/quote_sheet.js、static/admin/admin.js、static/index.html

### 错误模式：部署后业务员长时间停留页面收不到审批/管理员修正通知
- 发生场景：企微生产环境；业务员前台长时间不关页；管理员在 8080 审批或驳回
- 错误表现：历史报价/报价卡横幅仍 pending；管理员修正徽标不更新；仅刷新整页才看到
- 根因：前端只在加载/focus/visibility 时拉审批；无 `/api/my/quotes` 与 `/api/my/admin-updates` 轮询；401/网络失败静默吞掉
- 正确做法：`refreshSalesSyncBundle` 每 20s 轮询；focus/visibility/online 立即刷新；静默更新徽标/列表/横幅；401/403 提示重登；跨域 HTTPS 可设 `COOKIE_SAMESITE=none`+`COOKIE_SECURE=1`；审批 lookup 支持 `latest_calc_quote_id`/`approved_calc_quote_id`
- 禁止做法：轮询时弹重复 toast；用户输入时重绘列表；用内存态代替持久化审批结果
- 必测项：`pytest tests/test_front_quote_approval_refresh.py tests/test_quote_approval_front_routes.py tests/test_admin_bom_correction.py`；管理员 approved/rejected 后业务员 GET approval、my-quotes、admin-updates 一致；他人 403/404
- 相关文件/模块：static/app.js、quote_upload_storage.py、session_quote_context.py、sales_auth.py

### 错误模式：价格库自动学习无反应 / 合格材料未入库
- 发生场景：报价完成后价格库后台；待审核数量为 0
- 错误表现：可信新材料只进 suggestions 队列不进正式库；同规格价差被静默跳过；candidate_review 行被整行跳过
- 根因：`sync_quote_detail_rows_to_price_kb` 仅写 `quote_sync_suggestions.jsonl`；`same_key_rows` 冲突直接 skip；`official_kb_write_allowed` 禁止 auto
- 正确做法：可信 `KB_ACTION_AUTO` 调 `_auto_insert_trusted_entries` 写 KB；价差进 `AUTO_PRICE_CONFLICT` 异常队列；裁片/系统估算 DROP；页面展示 `auto_inserted_total`/`pending_review_count`/`ignored_count`
- 禁止做法：测试写 `D:/知识库/...`；非材料进正式库；价差直接覆盖
- 必测项：`pytest tests/test_kb_auto_learn_rules.py tests/test_price_admin_store.py`
- 相关文件/模块：price_admin_store.py、kb_data_quality.py、price_kb_paths.py、static/admin/prices.js

### 错误模式：PDF 描述列材质重复显示
- 发生场景：客户报价单 PDF 产品表「描述」列
- 错误表现：同一材质重复出现，如 `600D牛津布、210D涤纶、600D牛津布`
- 根因：BOM/描述拼接时同一面料多次写入；`sanitizeCustomerDescForPdf` 仅去前缀/宽幅未按分隔符去重
- 正确做法：`dedupePdfDescSegments` 按 `，,、/\n` 拆分→trim→忽略多余空格比较→保留首次顺序→`、` 拼接；仍去掉主料/宽幅/152cm；空则 `-`
- 禁止做法：改动报价计算或原始 desc 数据；误删不同材质
- 必测项：去重后 `600D牛津布、210D涤纶`；`pytest tests/test_quote_sheet_pdf_layout.py::QuoteSheetPdfLayoutTest::test_pdf_desc_dedupes_duplicate_materials`
- 相关文件/模块：static/quote_sheet.js

### 错误模式：PDF 尺寸列末尾字符被裁切
- 发生场景：客户报价单 PDF/打印预览产品表「尺寸」列
- 错误表现：`37×12×17cm` 显示为 `37×12×17c`，末字 `m` 被右侧边框裁掉；或换行后第二行不可见
- 根因：`table-layout:fixed` 下列宽不足；`overflow-wrap:anywhere` 在 `c|m` 处断行且 html2canvas 按单元格边界裁切；`colgroup` 未设宽度；`onclone` 未强制尺寸列可见换行
- 正确做法：尺寸列 14%、描述列 16%；`colgroup`+`td.col-size` 设 `overflow:visible`、`white-space:normal`、`overflow-wrap:break-word`；PDF `onclone` 同步列宽与样式；描述/含税价/黄色条逻辑不改
- 禁止做法：尺寸列 `overflow:hidden` 或 `nowrap`；改回「主料：」「152cm」；删除黄色有效期条；清空含税价
- 必测项：PDF 尺寸完整 `37×12×17cm`；描述仍 `210D涤纶`；黄色条在；含税价有值；`pytest tests/test_quote_sheet_pdf_layout.py`
- 相关文件/模块：static/styles.css、static/quote_sheet.js、static/index.html

### 错误模式：结构说明误生成 BOM / 缺项静默漏算 / 歧义物料算错类
- 发生场景：规范需求表 B 区结构说明、备注、成本要求；物料名含「外带反射」等歧义词
- 错误表现：网袋/隔层/侧袋等自动生成推理待核 BOM 并计价；或结构说明有结构词但无提示；外带反射被静默按主面料面积算
- 根因：结构说明与 C 区显式字段未分流；缺项无覆盖检查；歧义物料无归类说明
- 正确做法：C 区外料/里料/拉链/工艺等直接进 BOM；结构说明只进 `structure_gap_hints`（`participates_in_cost=False`）；用户确认后 `confirmation_source=structure_confirmed` 才入 BOM；歧义物料输出 `ambiguous_material_classification`
- 禁止做法：结构说明关键词直接生成正式 BOM；歧义物料低置信度静默计价；改动 PDF/审批主流程
- 必测项：`pytest tests/test_structure_gap_hints.py tests/test_demand_template_structure_inference.py`
- 相关文件/模块：structure_gap_hints.py、bag_quote_pipeline.py、server.py、quote_validation_gate.py、static/app.js

### 错误模式：推理待核结构件/工艺件默认用量 1套/1组
- 发生场景：结构推理生成 BOM、结构确认表、物料明细「规格/用量」列
- 错误表现：侧袋/背垫/提手/隔层/工艺费等显示 `推理待核 / 1套`，并按 1 套参与小计
- 根因：`kimi_client._default_market_usage_for_row` 对结构候选一律 fallback `1套`；展示层未替换推理项用量
- 正确做法：`pending_inference_usage_label` 按名称关键词给待确认单位（几片/几条/几米/几个/几道工序/待填数量）；名称含明确数量则保留；无明确数量 `amount=0`、`exclude_from_cost=True`；仅明确成套组件才用「套」
- 禁止做法：推理待核项默认 `1套/1组`；待填数量参与正式计价
- 必测项：`pytest tests/test_pending_inference_usage.py tests/test_structure_confirmation_merge.py tests/test_material_detail_display.py tests/test_bag_quote_pipeline.py`；BOM 中背垫→几片、提手→几条、工艺费→几道工序
- 相关文件/模块：material_inference.py、kimi_client.py、material_detail_display.py

### 错误模式：需求表结构说明误生成推理待核 BOM（网袋/隔层）
- 发生场景：规范需求表（A–G 区块）上传后结构确认弹窗
- 错误表现：结构说明/参考图/成本要求中的「隔层」「网袋」等被当成真实结构件，自动生成「推理待核」BOM 行
- 根因：`apply_bag_quote_preparse` 对完整 `structure_text`（含 B 区结构说明 + xlsx 附录）做结构清单/推理补漏，未区分字段来源
- 正确做法：`demand_field_sources` 标记字段类型；`demand_template=True` 时 `structure_inference_text=""`；仅 `explicit_material_field`/`explicit_accessory_field`/`process_field` 生成 BOM；备注命中只进 `structure_inference_hints` 风险提示
- 禁止做法：从「结构说明」「参考图片/链接」「成本要控制」自动生成网袋/隔层/侧袋等待核行
- 必测项：`pytest tests/test_demand_template_structure_inference.py`；模板表上传后结构确认表无网袋/隔层推理行；C 区拉链/外料仍正常
- 相关文件/模块：demand_field_sources.py、demand_parser.py、bag_quote_pipeline.py、material_inference.py、server.py

### 错误模式：结构缺项缺用量/单价阻断正式报价
- 发生场景：结构/明细预览中丝印、车缝等结构缺项勾选「加入正式 BOM」
- 错误表现：显示「待补用量/单价」，提示必须手填后才能报价，业务员无法继续
- 根因：缺项行 `exclude_from_cost=True`；校验默认阻断；`merge_structure_confirmation_user_items` 合并补丁时清掉 AI 标记
- 正确做法：规则估算用量/单价；徽章「AI估算待复核」；允许继续报价并在结果中提示待复核；管理员改价保存视为确认
- 禁止做法：AI 估算伪装知识库命中；客户 PDF 出现「AI估算」
- 必测项：`pytest tests/test_structure_gap_ai_estimate.py`
- 相关文件/模块：kimi_client.py、material_row_validity.py、server.py、static/app.js、static/admin/admin.js

### 错误模式：展示层漏格式化（2 位及以上小数 / 整数带 .0）
- 发生场景：前台计算过程拆解表、物料合计、管理员 BOM/板房用量表、报价单 PDF/预填接口
- 错误表现：`12.5579元/㎡`、`20.50元`、`2.3901元` 等长小数或固定两位小数直接输出
- 根因：部分渲染函数仍 `String(...)` / `.toFixed(2)`；预填接口 text 字段原样透传 tier 长小数
- 正确做法：展示层统一 `formatNumbersInDisplayText` / `formatDisplayNumber` / `formatBomDisplayNumberText` / `formatMoney`；预填用 `format_numbers_in_display_text` 格式化客户可见 price text；计算仍用原始数值字段
- 禁止做法：为展示提前 round 后端 tier/amount 数值；`.toFixed(2)` 固定两位展示
- 必测项：`pytest tests/test_display_number_format.py tests/test_display_format_layers.py`；前台/后台/PDF 不出现 2 位及以上小数；整数不显示 `.0`
- 相关文件/模块：static/app.js、static/admin/admin.js、static/quote_sheet.js、quote_sheet_prefill.py、display_number_format.py

### 错误模式：需求表 C/F/G 区只读首行值行导致物料/数量/包装漏解析
- 发生场景：标准需求表(填写区)如 B260178；C 区表头下有多行值；无 F. 标题仅有数量1/2/3；G. 包装与装箱
- 错误表现：materials 仅 6 条；quantities 空；quote_params.G 无礼盒/纸箱；第 2 行 EPE/黑色拉链/拉头/拉片丢失
- 根因：`_zip_headers_to_values` 只配对首条值行；`SECTION_TITLE_PATTERN` 不含 G；数量区无 F 标题时不入 sections.F；表头/值行误判（如「编码」被 `\码` 正则命中）
- 正确做法：表头+多值行 column merge（`;` 合并）；`detect_section_marker` 支持 A-G；无 F 标题时从数量1 表头+下一行提取；G 区 param label 含包装/外箱/装箱；值行与表头用 `_looks_like_demand_data_value` 区分
- 禁止做法：把结构说明自动当正式 BOM；空值覆盖已有列；改动报价公式/价格库
- 必测项：`pytest tests/test_demand_parser_multrow_sections.py tests/test_demand_strict_table_materials.py tests/test_sheet_parser.py`；B260178 materials≥10、quantities=(500,1000,1500)、sections.G 含礼盒/纸箱
- 相关文件/模块：demand_parser.py、sheet_parser.py

### 错误模式：拉头/拉链单价离谱（总价误填为单价）
- 发生场景：需求表 C 区拉头/金属拉链；报价同步入库；KB 命中
- 错误表现：明细出现「黑色拉头*1：60元/个」「金色金属拉链：120元/条」，小计异常
- 根因：历史 `quote_auto_learn` 将「金色拉头 60元/个」写入正式库；`sync_quote_detail_rows_to_price_kb` 对 `kb_hit=True` 走 `AUTO_QUOTE_SYNC` 未拦截异常单价
- 正确做法：`judge_kb_insert_candidate` 名称含拉头且单价≥10、含拉链且单价≥20 → `pending_review`/`AUTO_PENDING_PRICE`；KB 命中与 `parse_items` 同步拒绝异常单价；正式库脏数据用 `scripts/audit_suspicious_zipper_slider_prices.py` 审计后后台人工删改
- 禁止做法：仅改前端显示；无确认脚本删正式库；正常 0.3元/个拉头、0.3元/条拉链误拦
- 必测项：`pytest tests/test_kb_auto_learn_rules.py -k suspicious_slider or suspicious_metal_zipper`；`pytest tests/test_kb_data_quality.py tests/test_price_learn_loop.py -q`
- 相关文件/模块：kb_data_quality.py、price_admin_store.py、price_kb.py、quote_engine.py、server.py

### 错误模式：知识库价覆盖业务表单价 / 价格来源优先级混乱
- 发生场景：需求表 C 区已填单价；KB 命中；报价同步入库
- 错误表现：业务填 0.35元/个 被 KB 0.3 覆盖；或冲突价被 AUTO_QUOTE_SYNC 当可信价
- 根因：`attach_demand_items` KB 命中无条件写 `unit_price`；缺 `price_source` 字段；`kb_hit=True` 被当作单价权威
- 正确做法：优先级 业务表/手工 > 正式 KB（仅缺价补价）> AI 估算；冲突保留业务价并 `price_conflict_required`；业务价/冲突/AI 价只进待审核不写正式库；异常 KB 拉头/拉链价拒绝参与报价
- 禁止做法：KB 覆盖已有业务单价；待审核候选参与 lookup；冲突价 AUTO_QUOTE_SYNC 直写正式库
- 必测项：`pytest tests/test_price_source_priority.py tests/test_kb_auto_learn_rules.py tests/test_price_learn_loop.py tests/test_kb_data_quality.py -q`
- 相关文件/模块：price_source_resolver.py、price_kb.py、server.py、quote_engine.py、price_admin_store.py、kimi_client.py、sheet_parser.py

## 快速验收命令（自报项目目录）

```powershell
$env:PYTHONPATH='.'
pytest tests/test_material_spec_usage_enricher.py tests/test_material_detail_display.py tests/test_quote_sheet_prefill.py tests/test_quote_validation_gate.py tests/test_quote_anomaly_learning.py tests/test_fabric_lining_usage_parity.py -q
```
