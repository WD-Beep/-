import type { CollectionMode, CollectionTaskStatus, EmailLogStatus } from "@/lib/api";

/** 侧边栏导航 */
export const NAV_ITEMS = [
  { href: "/", label: "数据概览" },
  { href: "/influencers", label: "红人库" },
  { href: "/collection-tasks", label: "采集任务" },
  { href: "/link-import", label: "链接导入" },
  { href: "/message-templates", label: "话术库" },
  { href: "/email-logs", label: "邮件日志" },
  { href: "/settings", label: "系统设置" },
] as const;

export const PLATFORM_LABELS: Record<string, string> = {
  instagram: "Instagram",
  tiktok: "TikTok",
  youtube: "YouTube",
  facebook: "Facebook",
  general: "通用",
  pinterest: "Pinterest",
  ltk: "LTK",
  shopmy: "ShopMy",
  multi: "多平台",
};

export const PLATFORM_CAPABILITY_STATUS_LABELS: Record<string, string> = {
  supported: "API Direct 已支持",
  not_configured: "API Direct 未配置",
  not_available: "API Direct 未接入",
  url_only: "仅 URL 导入",
};

export const COLLECTION_MODE_LABELS: Record<CollectionMode, string> = {
  discovery: "自动发现",
  keyword: "关键词采集",
  category_discovery: "类目采集",
  clustering: "相似账号",
  urls: "链接采集",
  mixed: "混合采集",
  comment_authors: "链接采集",
  competitor_product: "竞品商品发现",
};

export const SOURCE_DISCOVERY_LABELS: Record<string, string> = {
  comment_author: "评论区",
  post_author: "帖子作者",
  url_profile: "链接主页",
  competitor_product: "竞品商品发现",
};

export const CANDIDATE_SOURCE_TYPE_LABELS: Record<string, string> = {
  keyword_post_author: "关键词帖子作者",
  hashtag_post_author: "Hashtag 帖子作者",
  comment_author: "评论区用户",
  input_profile: "输入主页",
  input_post: "输入帖子",
  input_reel: "输入 Reel",
  related_profile: "相似账号",
  competitor_product_post_author: "竞品商品帖子作者",
  keyword_video_author: "关键词视频作者",
  keyword_channel: "关键词频道",
  keyword_video_channel: "关键词视频频道",
  input_url: "URL 导入",
  unknown: "未知来源",
};

export const CANDIDATE_STATUS_LABELS: Record<
  string,
  { label: string; variant: "default" | "secondary" | "success" | "warning" | "destructive" }
> = {
  discovered: { label: "已发现", variant: "secondary" },
  pending_profile: { label: "待补采", variant: "warning" },
  profile_fetched: { label: "已补采", variant: "default" },
  profile_failed: { label: "补采失败", variant: "destructive" },
  filtered_out: { label: "已过滤", variant: "warning" },
  inserted: { label: "已入库", variant: "success" },
  duplicate: { label: "重复账号", variant: "secondary" },
};

export const CANDIDATE_FAILURE_LABELS: Record<string, string> = {
  below_min_followers: "粉丝未达标",
  excluded_keyword: "命中排除词",
  profile_fetch_failed: "主页补采失败",
  private_account: "私密账号",
  disabled_or_deleted: "账号不存在",
  invalid_username: "无效用户名",
  missing_profile_detail: "主页数据缺失",
  duplicate: "重复",
  api_failed: "API 失败",
  unknown: "未知原因",
};

/** 主模式选项（评论区发现已并入统一流水线开关） */
export const COLLECTION_MODE_OPTIONS: {
  value: CollectionMode;
  label: string;
  hint: string;
}[] = [
  {
    value: "keyword",
    label: "关键词采集",
    hint: "手动输入关键词 → 扩展 hashtag / 平台搜索 → 发现帖子作者与链接",
  },
  {
    value: "category_discovery",
    label: "类目采集",
    hint: "填写类目后系统自动扩展平台关键词与链接种子，可补充偏好关键词",
  },
  {
    value: "discovery",
    label: "自动发现（Hashtag）",
    hint: "与关键词采集相同，适合直接输入 hashtag 或关键词",
  },
  {
    value: "urls",
    label: "链接导入",
    hint: "主页 / 帖子 / Reel 链接或用户名：自动识别并抓取评论区用户",
  },
  {
    value: "mixed",
    label: "混合采集",
    hint: "关键词与链接合并去重，统一走评论区增强与主页补采",
  },
  {
    value: "clustering",
    label: "相似账号（可选）",
    hint: "从种子主页扩展相似账号，并可对种子近期帖子抓评论",
  },
  {
    value: "competitor_product",
    label: "竞品商品发现",
    hint: "输入 Amazon 链接/ASIN/关键词，搜索 Instagram 上疑似推广该商品或竞品的红人",
  },
];

export const TASK_STATUS_LABELS: Record<
  CollectionTaskStatus,
  { label: string; variant: "default" | "secondary" | "success" | "warning" | "destructive" }
> = {
  pending: { label: "待运行", variant: "warning" },
  running: { label: "运行中", variant: "default" },
  completed: { label: "成功", variant: "success" },
  completed_with_results: { label: "有结果", variant: "success" },
  completed_no_results: { label: "无结果", variant: "warning" },
  partial_failed: { label: "部分成功", variant: "warning" },
  failed: { label: "失败", variant: "destructive" },
  paused: { label: "已暂停", variant: "secondary" },
  draft: { label: "草稿", variant: "secondary" },
};

export const EMAIL_LOG_STATUS_LABELS: Record<
  EmailLogStatus,
  { label: string; variant: "default" | "secondary" | "success" | "warning" | "destructive" }
> = {
  pending: { label: "待发送", variant: "warning" },
  sent: { label: "已发送", variant: "success" },
  failed: { label: "失败", variant: "destructive" },
};

export const OUTREACH_PROVIDER_LABELS: Record<string, string> = {
  smtp: "SMTP",
  mailchimp: "Mailchimp",
};

export const PROFILE_FAILURE_REASON_LABELS: Record<string, string> = {
  profile_not_found: "主页不存在",
  private_account: "私密账号",
  missing_profile_detail: "主页详情缺失",
  scraper_blocked: "采集被拦截",
  invalid_username: "无效用户名",
  excluded_keyword: "命中排除词",
  below_min_followers: "粉丝未达 3 万",
  invalid_profile: "无效主页",
};

export function platformLabel(platform: string): string {
  return PLATFORM_LABELS[platform] ?? platform;
}

/** 粉丝/订阅者展示文案：YouTube 用订阅者，其余平台保持粉丝。 */
export function followersAudienceLabel(platform: string): string {
  return platform === "youtube" ? "订阅者" : "粉丝";
}

export function taskPlatforms(task: { platform: string; platforms?: string[] }): string[] {
  if (task.platforms?.length) return task.platforms;
  if (task.platform === "multi") return [];
  return [task.platform || "instagram"];
}

export function outreachLabel(provider: string): string {
  return OUTREACH_PROVIDER_LABELS[provider] ?? provider;
}

export function aiModeLabel(mode: string): string {
  if (mode === "kimi") return "Kimi AI";
  if (mode === "heuristic") return "规则评分（未配置 Kimi）";
  if (mode === "heuristic_fallback") return "规则评分（Kimi 失败降级）";
  return mode;
}

const ERROR_TRANSLATIONS: [RegExp, string][] = [
  [/邮件服务未配置/i, "邮件服务未配置，请在 .env 中填写 SMTP_HOST / SMTP_USER / SMTP_PASSWORD / SMTP_FROM 后重启后端"],
  [/SMTP 认证失败/i, "SMTP 认证失败：请在腾讯企业邮箱后台生成「客户端专用密码」，更新 .env 的 SMTP_PASSWORD 后重启后端"],
  [/535.*authentication failed/i, "SMTP 认证失败：请使用企业邮箱「客户端专用密码」，不要用网页登录密码"],
  [/API_DIRECT_API_KEY/i, "未配置 API Direct 密钥（API_DIRECT_API_KEY）"],
  [/Apify 采集失败/i, "Instagram 采集 API 失败"],
  [/APIFY_TOKEN/i, "未配置 Apify Token（APIFY_TOKEN）"],
  [/APIFY_INSTAGRAM/i, "未配置 Instagram Apify Actor"],
  [/评论发现/i, "评论区 API 步骤失败"],
  [/Hashtag #/i, "Hashtag 采集失败"],
  [/not configured/i, "服务未配置"],
  [/Discovery mode requires hashtags or keywords/i, "自动发现模式需填写关键词"],
];

export function translateErrorMessage(message: string | null | undefined): string {
  if (!message) return "";
  for (const [pattern, replacement] of ERROR_TRANSLATIONS) {
    if (pattern.test(message)) return replacement;
  }
  return message;
}

export function translateBackendMessage(message: string | null | undefined): string {
  if (!message) return "";
  return translateErrorMessage(message);
}

export function healthStatusLabel(status: string): string {
  if (status === "ok") return "正常";
  return status;
}

export function collectorModeLabel(mode: string): string {
  if (mode === "apify") return "Apify 真实采集";
  if (mode === "mock") return "Mock（已禁用）";
  return mode;
}

export const LEAD_STATUS_LABELS: Record<
  string,
  { label: string; variant: "default" | "secondary" | "success" | "warning" | "destructive" }
> = {
  new: { label: "新线索", variant: "secondary" },
  to_contact: { label: "待联系", variant: "warning" },
  contacted: { label: "已联系", variant: "default" },
  replied: { label: "已回复", variant: "default" },
  interested: { label: "有意向", variant: "success" },
  quoted: { label: "已报价", variant: "success" },
  cooperating: { label: "合作中", variant: "success" },
  cooperated: { label: "已合作", variant: "success" },
  invalid: { label: "无效", variant: "destructive" },
  blacklisted: { label: "黑名单", variant: "destructive" },
  negotiating: { label: "洽谈中", variant: "default" },
  collaborated: { label: "已合作", variant: "success" },
  rejected: { label: "已拒绝", variant: "destructive" },
};

export const FOLLOWUP_ACTION_LABELS: Record<string, string> = {
  note: "备注",
  email_sent: "发送邮件",
  dm_sent: "发送 DM",
  replied: "收到回复",
  status_changed: "状态变更",
  quote_sent: "发送报价",
  cooperation_started: "开始合作",
  cooperation_done: "合作完成",
  invalid_marked: "标记无效",
  blacklisted: "加入黑名单",
};

export const CONTACT_CHANNEL_LABELS: Record<string, string> = {
  email: "邮件",
  instagram_dm: "Instagram DM",
  whatsapp: "WhatsApp",
  website_form: "官网表单",
  other: "其他",
};

export function leadStatusLabel(status: string | null | undefined): string {
  if (!status) return "新线索";
  return LEAD_STATUS_LABELS[status]?.label ?? status;
}

export function leadStatusVariant(
  status: string | null | undefined,
): "default" | "secondary" | "success" | "warning" | "destructive" {
  if (!status) return "secondary";
  return LEAD_STATUS_LABELS[status]?.variant ?? "secondary";
}

export const EMAIL_SOURCE_LABELS: Record<string, string> = {
  bio: "Instagram 简介",
  instagram_bio: "Instagram 简介",
  business_email: "商务邮箱",
  business_profile: "商务主页",
  public_email: "公开邮箱",
  website_contact: "官网联系页",
  linktree: "Linktree",
  beacons: "Beacons",
  stan_store: "Stan Store",
  carrd: "Carrd",
  website: "官网",
  other_page: "外链页面",
  public_profile: "公开主页",
  manual: "人工录入",
};

export const CONTACT_CREDIBILITY_LABELS: Record<string, string> = {
  high: "高",
  medium: "中",
  low: "低",
  unknown: "未知",
};

export const CONTACT_FETCH_STATUS_LABELS: Record<string, string> = {
  not_started: "未开始",
  success: "成功",
  partial_failed: "部分失败",
  failed: "失败",
};

export function emailSourceLabel(source: string | null | undefined): string {
  if (!source) return "-";
  return EMAIL_SOURCE_LABELS[source] ?? source;
}

export function contactCredibilityLabel(level: string | null | undefined): string {
  if (!level) return "未知";
  return CONTACT_CREDIBILITY_LABELS[level] ?? level;
}

export const MESSAGE_TEMPLATE_SCENARIO_OPTIONS = [
  { value: "first_contact", label: "首次联系" },
  { value: "quote", label: "报价沟通" },
  { value: "follow_up_replied", label: "已回复跟进" },
  { value: "follow_up_no_reply", label: "未回复二次跟进" },
  { value: "sample_shipping", label: "样品寄送" },
  { value: "collaboration_confirm", label: "合作确认" },
  { value: "reject", label: "拒绝/暂不合作" },
  { value: "after_sales", label: "售后维护" },
  { value: "custom", label: "自定义场景" },
] as const;

export const MESSAGE_TEMPLATE_SCENARIO_LABELS: Record<string, string> = Object.fromEntries(
  MESSAGE_TEMPLATE_SCENARIO_OPTIONS.map((item) => [item.value, item.label]),
);

export const MESSAGE_TEMPLATE_LANGUAGE_OPTIONS = [
  { value: "zh", label: "中文" },
  { value: "en", label: "英文" },
  { value: "other", label: "其他" },
] as const;

export const MESSAGE_TEMPLATE_LANGUAGE_LABELS: Record<string, string> = Object.fromEntries(
  MESSAGE_TEMPLATE_LANGUAGE_OPTIONS.map((item) => [item.value, item.label]),
);

export const MESSAGE_TEMPLATE_PLATFORM_OPTIONS = [
  { value: "", label: "不限" },
  { value: "instagram", label: "Instagram" },
  { value: "tiktok", label: "TikTok" },
  { value: "youtube", label: "YouTube" },
  { value: "facebook", label: "Facebook" },
  { value: "general", label: "通用" },
] as const;

export function messageTemplateScenarioLabel(value: string | null | undefined): string {
  if (!value) return "-";
  return MESSAGE_TEMPLATE_SCENARIO_LABELS[value] ?? value;
}

export function messageTemplateLanguageLabel(value: string | null | undefined): string {
  if (!value) return "-";
  return MESSAGE_TEMPLATE_LANGUAGE_LABELS[value] ?? value;
}
