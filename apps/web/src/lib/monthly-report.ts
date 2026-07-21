// 文件说明：前端公共工具和业务辅助函数；当前文件：monthly report
import type { DashboardMonthlyReport } from "@/lib/api";

export type MonthlyReportTone = "primary" | "success" | "warning" | "danger" | "neutral";

export type MonthlyReportCard = {
  label: string;
  value: string;
  helper: string;
  href: string;
  tone: MonthlyReportTone;
};

export type MonthlyReportFunnelStep = {
  label: string;
  value: number;
  href: string;
};

export type MonthlyReportSkipReason = {
  label: string;
  value: number;
  helper: string;
  href: string;
  tone: MonthlyReportTone;
};

export type MonthlyReportTodo = {
  title: string;
  description: string;
  href: string;
  actionLabel: string;
  tone: MonthlyReportTone;
};

export type MonthlyReportSections = {
  overview: { title: string; cards: MonthlyReportCard[] };
  outreachRecap: { title: string; funnel: MonthlyReportFunnelStep[] };
  draftQuality: { title: string; cards: MonthlyReportCard[] };
  queuePerformance: { title: string; cards: MonthlyReportCard[] };
  skipReasons: { title: string; items: MonthlyReportSkipReason[] };
  replyProgress: { title: string; cards: MonthlyReportCard[] };
  todos: MonthlyReportTodo[];
};

export const monthlyReportReviewNotice =
  "月报是复盘视角，只展示结果和待办入口；发送仍然必须在草稿审核页完成。";

function normalizeTone(tone: string | null | undefined): MonthlyReportTone {
  if (tone === "primary" || tone === "success" || tone === "warning" || tone === "danger" || tone === "neutral") {
    return tone;
  }
  return "neutral";
}

function cardFromApi(card: DashboardMonthlyReport["overview"]["cards"][number]): MonthlyReportCard {
  return { ...card, tone: normalizeTone(card.tone) };
}

function skipReasonFromApi(item: DashboardMonthlyReport["skip_reasons"]["items"][number]): MonthlyReportSkipReason {
  return { ...item, tone: normalizeTone(item.tone) };
}

function todoFromApi(todo: DashboardMonthlyReport["todos"][number]): MonthlyReportTodo {
  return {
    title: todo.title,
    description: todo.description,
    href: todo.href,
    actionLabel: todo.action_label,
    tone: normalizeTone(todo.tone),
  };
}

export function monthlyReportSectionsFromApi(report: DashboardMonthlyReport): MonthlyReportSections {
  return {
    overview: { title: report.overview.title, cards: report.overview.cards.map(cardFromApi) },
    outreachRecap: { title: report.outreach_recap.title, funnel: report.outreach_recap.funnel },
    draftQuality: { title: report.draft_quality.title, cards: report.draft_quality.cards.map(cardFromApi) },
    queuePerformance: { title: report.queue_performance.title, cards: report.queue_performance.cards.map(cardFromApi) },
    skipReasons: { title: report.skip_reasons.title, items: report.skip_reasons.items.map(skipReasonFromApi) },
    replyProgress: { title: report.reply_progress.title, cards: report.reply_progress.cards.map(cardFromApi) },
    todos: report.todos.map(todoFromApi),
  };
}

function csvCell(value: string | number): string {
  return `"${String(value).replaceAll('"', '""')}"`;
}

export function buildMonthlyReportExportCsv(
  month: string,
  updatedAt: string,
  sections = buildMonthlyReportSections(),
): string {
  const rows: Array<Array<string | number>> = [
    ["月份", month],
    ["本月更新时间", updatedAt],
    ["说明", monthlyReportReviewNotice],
    [],
    ["模块", "指标", "数值", "说明"],
  ];

  sections.overview.cards.forEach((card) => rows.push([sections.overview.title, card.label, card.value, card.helper]));
  sections.outreachRecap.funnel.forEach((step) => rows.push([sections.outreachRecap.title, step.label, step.value, "漏斗阶段"]));
  sections.draftQuality.cards.forEach((card) => rows.push([sections.draftQuality.title, card.label, card.value, card.helper]));
  sections.queuePerformance.cards.forEach((card) => rows.push([sections.queuePerformance.title, card.label, card.value, card.helper]));
  sections.skipReasons.items.forEach((item) => rows.push([sections.skipReasons.title, item.label, item.value, item.helper]));
  sections.replyProgress.cards.forEach((card) => rows.push([sections.replyProgress.title, card.label, card.value, card.helper]));
  sections.todos.forEach((todo) => rows.push(["本月待办", todo.title, todo.actionLabel, todo.description]));

  return `\uFEFF${rows.map((row) => row.map(csvCell).join(",")).join("\r\n")}`;
}

export function buildMonthlyReportSections(report?: DashboardMonthlyReport): MonthlyReportSections {
  if (report) {
    return monthlyReportSectionsFromApi(report);
  }

  return {
    overview: {
      title: "运营总览",
      cards: [
        { label: "Instagram 达人数", value: "12,486", helper: "总库 18,920 人", href: "/influencers?platform=instagram", tone: "primary" },
        { label: "邮箱覆盖率", value: "68.4%", helper: "较上月 +5.2%", href: "/influencers?has_email=true", tone: "success" },
        { label: "高匹配达人", value: "842", helper: "优先复盘", href: "/influencers?high_value=true", tone: "warning" },
        { label: "ROI 预估均值", value: "3.7x", helper: "样本 516 人", href: "/influencers?sort=roi", tone: "primary" },
        { label: "采集任务数", value: "38", helper: "完成 31 个", href: "/collection-tasks", tone: "neutral" },
        { label: "邮件记录数", value: "1,286", helper: "含回复 96 封", href: "/outreach-records", tone: "primary" },
      ] satisfies MonthlyReportCard[],
    },
    outreachRecap: {
      title: "外联运营复盘",
      funnel: [
        { label: "AI 生成草稿", value: 980, href: "/outreach-campaigns" },
        { label: "已审核", value: 812, href: "/outreach-campaigns" },
        { label: "已批准", value: 684, href: "/outreach-campaigns" },
        { label: "已入队", value: 612, href: "/outreach-send-queue?status=queued" },
        { label: "已发送", value: 546, href: "/outreach-records?view=sent" },
        { label: "已回复", value: 96, href: "/email-replies" },
        { label: "有合作意向", value: 41, href: "/email-replies?intent_status=interested" },
      ] satisfies MonthlyReportFunnelStep[],
    },
    draftQuality: {
      title: "草稿审核质量",
      cards: [
        { label: "待审核草稿", value: "168", helper: "进入审核页", href: "/outreach-campaigns", tone: "warning" },
        { label: "已修改草稿", value: "74", helper: "人工优化", href: "/outreach-campaigns", tone: "primary" },
        { label: "高价值待确认", value: "32", helper: "需打开确认", href: "/outreach-campaigns", tone: "warning" },
        { label: "已跳过草稿", value: "118", helper: "查看原因", href: "/outreach-campaigns", tone: "neutral" },
        { label: "草稿批准率", value: "69.8%", helper: "普通草稿", href: "/outreach-campaigns", tone: "success" },
        { label: "高价值确认率", value: "51.6%", helper: "偏低关注", href: "/outreach-campaigns", tone: "warning" },
      ] satisfies MonthlyReportCard[],
    },
    queuePerformance: {
      title: "发送队列表现",
      cards: [
        { label: "本月入队", value: "612", helper: "已批准邮件", href: "/outreach-send-queue?status=queued", tone: "primary" },
        { label: "本月发送", value: "546", helper: "成功 532", href: "/outreach-records?view=sent", tone: "primary" },
        { label: "发送成功率", value: "97.4%", helper: "稳定", href: "/outreach-records?view=sent", tone: "success" },
        { label: "发送失败数", value: "14", helper: "需处理", href: "/outreach-send-queue?status=failed", tone: "danger" },
        { label: "今日剩余额度", value: "84", helper: "限额 200", href: "/outreach-send-queue?quota=today", tone: "neutral" },
        { label: "平均发送间隔", value: "8m", helper: "保守发送", href: "/outreach-send-queue?metric=interval", tone: "neutral" },
      ] satisfies MonthlyReportCard[],
    },
    skipReasons: {
      title: "跳过原因分析",
      items: [
        { label: "缺邮箱", value: 96, helper: "补充联系方式", href: "/influencers?missing_contact=true", tone: "primary" },
        { label: "无效邮箱", value: 42, helper: "修正或移除", href: "/influencers", tone: "danger" },
        { label: "黑名单", value: 18, helper: "不可发送", href: "/influencers", tone: "danger" },
        { label: "已发送", value: 76, helper: "避免重复", href: "/outreach-records?view=sent", tone: "neutral" },
        { label: "已回复", value: 25, helper: "转跟进", href: "/email-replies", tone: "success" },
        { label: "高价值未确认", value: 32, helper: "进入草稿详情", href: "/outreach-campaigns", tone: "warning" },
        { label: "草稿未批准", value: 64, helper: "审核后入队", href: "/outreach-campaigns", tone: "primary" },
      ] satisfies MonthlyReportSkipReason[],
    },
    replyProgress: {
      title: "回复与合作进展",
      cards: [
        { label: "已回复", value: "96", helper: "本月新增", href: "/email-replies", tone: "success" },
        { label: "感兴趣", value: "41", helper: "优先跟进", href: "/email-replies?intent_status=interested", tone: "success" },
        { label: "待报价", value: "18", helper: "报价单", href: "/email-replies", tone: "primary" },
        { label: "待寄样", value: "12", helper: "样品流程", href: "/email-replies", tone: "primary" },
        { label: "UGC 合作", value: "9", helper: "内容合作", href: "/email-replies?deal=ugc", tone: "neutral" },
        { label: "付费合作", value: "7", helper: "预算确认", href: "/email-replies?deal=paid", tone: "warning" },
        { label: "联盟佣金合作", value: "15", helper: "佣金方案", href: "/email-replies?deal=affiliate", tone: "primary" },
      ] satisfies MonthlyReportCard[],
    },
    todos: [
      { title: "32 个高价值草稿未确认", description: "打开草稿详情逐条确认，批准后才能入队。", href: "/outreach-campaigns", actionLabel: "去确认", tone: "warning" },
      { title: "14 封发送失败需要处理", description: "查看失败原因，修正邮箱或重新入队。", href: "/outreach-send-queue?status=failed", actionLabel: "处理失败", tone: "danger" },
      { title: "96 位已回复红人待跟进", description: "按感兴趣、报价、寄样状态分派销售动作。", href: "/email-replies", actionLabel: "跟进回复", tone: "success" },
      { title: "96 位缺邮箱红人需要补充联系方式", description: "进入达人列表补齐邮箱后再参与外联。", href: "/influencers?missing_contact=true", actionLabel: "补联系方式", tone: "primary" },
    ] satisfies MonthlyReportTodo[],
  };
}
