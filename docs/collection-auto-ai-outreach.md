# 采集后自动 AI 发邮箱说明

## 功能定位

“采集后自动 AI 发邮箱”和“AI 批量发邮箱”的核心逻辑类似，都是根据业务员填写的模板要求、产品卖点、合作方式和红人资料，为每个红人生成一封定制邮件。

区别在于触发方式：

| 功能 | 触发方式 | 适用场景 |
| --- | --- | --- |
| AI 批量发邮箱 | 业务员先手动选择红人，再进入批量发信页面生成并发送 | 已经有红人名单，需要人工挑选后批量发 |
| 采集后自动 AI 发邮箱 | 创建采集任务时提前填写模板，采集完成后系统自动筛选红人、生成邮件并进入发送队列 | 业务员只想创建采集任务，后面自动采集、自动生成、自动发 |

简单理解：

```text
AI 批量发邮箱 = 手动选择红人后批量生成并发送
采集后自动 AI 发邮箱 = 采集完成后自动选择红人并批量生成发送
```

## 自动流程

开启“采集完成后自动 AI 发邮件”后，系统会按下面流程处理：

1. 采集任务运行完成。
2. 系统筛选本次采集到的红人。
3. 自动跳过无邮箱、无效邮箱、已发过、重复红人、测试邮箱等不可发送对象。
4. AI 读取任务里填写的邮件主题模板、正文模板/话术要求、产品卖点、合作方式和备注。
5. AI 结合每个红人的昵称、平台、粉丝量、互动率、简介、内容方向、采集关键词等信息生成定制邮件。
6. 生成后的邮件进入发送队列。
7. 系统按发送限制分批发送，发送结果进入发信记录和回复中心。

## 模板怎么生效

创建任务里的模板不是直接原封不动发出去，而是作为 AI 的“规则和素材”。

例如业务员填写：

```text
不要像群发广告，语气简短真诚。
合作方式是寄样品 + Amazon Affiliate / commission。
产品适合 travel essentials、packing tips、suitcase organization。
```

AI 会根据这些要求，再结合每个红人的真实信息，单独生成不同的话术。

## 字段填写建议

### 邮件主题模板

推荐：

```text
Quick Collaboration Idea for Your Travel Content
```

也可以使用：

```text
Collaboration Opportunity with Travel Laundry Bags
```

建议主题不要太广告化，避免使用过强营销词。

### 产品名称

```text
EPEDAL24 Travel Laundry Bags
```

如果不想突出品牌，也可以写：

```text
Travel Laundry Bags
```

### 邮件正文模板 / 话术要求

```text
请根据红人的昵称、平台、内容风格、粉丝量、互动率、简介和采集关键词，生成一封自然的英文合作邀请邮件。

先友好打招呼，说明我们看到对方的旅行、收纳、居家或生活方式内容，觉得很适合我们的 Travel Laundry Bags。

邮件需要表达：
1. 我们希望寄样品给红人体验；
2. 红人可以拍摄旅行收纳、行李箱整理、脏衣分装、家庭收纳等内容；
3. 如果内容合适，可以进一步合作 Amazon Affiliate / commission；
4. 语气要真诚、简短、像真人业务员发出的邮件，不要像群发广告；
5. 不要夸大产品效果，不要承诺没有写明的收益；
6. 邮件结尾请询问对方是否愿意了解更多合作细节。
```

### 产品卖点

英文版：

```text
Lightweight and portable travel laundry bags.
Helps separate dirty clothes from clean clothes in luggage.
Suitable for travel, family trips, gym, dorms, and home organization.
Easy to fold, store, and carry.
Useful for packing videos, travel essentials content, suitcase organization, and home storage content.
```

中文版：

```text
便携、轻量、可折叠；可以把脏衣服和干净衣服分开；适合旅行、家庭出游、健身、宿舍、家庭收纳和行李箱整理；适合拍摄 travel essentials、packing tips、suitcase organization、home organization 等内容。
```

### 合作方式 / 合作诉求

```text
We can provide a free product sample for content creation.
The creator can share the product in travel packing, luggage organization, laundry separation, or home organization content.
If the content performs well, we can discuss Amazon Affiliate or commission-based cooperation.
Commission range can be 10%-30% depending on the collaboration.
```

### 备注

```text
We can provide product samples, product links, discount codes, and brand information if the creator is interested.
Please keep the email concise and personalized.
Do not mention exact payment unless the creator asks.
Do not overpromise results.
The email should sound friendly and professional.
```

## 推荐填写整合版

如果业务员不想分开整理，可以直接按下面内容填写：

```text
邮件主题：Quick Collaboration Idea for Your Travel Content

产品名称：EPEDAL24 Travel Laundry Bags

邮件正文模板/话术要求：
请根据红人的昵称、平台、内容风格、粉丝量、互动率、简介和采集关键词，生成一封自然的英文合作邀请邮件。先友好打招呼，说明我们看到对方的旅行、收纳、居家或生活方式内容，觉得很适合我们的旅行脏衣袋产品。邮件需要简短、真诚、像真人业务员发出的邀请，不要像群发广告。表达我们可以寄样品给红人体验，可以用于旅行收纳、行李箱整理、脏衣分装、家庭收纳等内容。如果内容合适，可以进一步沟通 Amazon Affiliate 或佣金合作。结尾询问对方是否愿意了解更多合作细节。

产品卖点：
便携、轻量、可折叠；可以把脏衣服和干净衣服分开；适合旅行、家庭出游、健身、宿舍、家庭收纳和行李箱整理；适合拍摄 travel essentials、packing tips、suitcase organization、home organization 等内容。

合作方式/合作诉求：
可寄样品给红人体验并拍摄内容。内容方向可以是旅行打包、行李箱整理、脏衣分类、家庭收纳等。如果内容表现合适，可以进一步沟通 Amazon Affiliate 或 10%-30% 佣金合作。

备注：
可补充产品链接、优惠码、样品政策和品牌介绍。邮件不要太长，不要夸大效果，不要直接承诺固定收益。语气要友好、专业、自然。
```

## 注意事项

- 自动发信不是一次性全部发完，而是进入发送队列分批发送。
- 建议控制每天发送量和每小时发送量，降低 Gmail 或 SMTP 风控风险。
- 模板越清楚，AI 生成的话术越稳定。
- 不要在模板里承诺固定收益、固定佣金或未确认的合作条件。
- 如果 DeepSeek/API Key 配置错误、余额不足或模型调用失败，AI 生成会失败，系统应记录失败原因。
