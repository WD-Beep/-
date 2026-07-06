"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BarChart3,
  CalendarDays,
  CheckCircle2,
  ChevronRight,
  Clock,
  Download,
  Mail,
  MessageCircleReply,
  Send,
  Sparkles,
  Target,
  Users,
} from "lucide-react";

import { AdminShell } from "@/components/layout/admin-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { fetchDashboardMonthlyReport, type DashboardMonthlyReport } from "@/lib/api";
import {
  buildMonthlyReportExportCsv,
  buildMonthlyReportSections,
  monthlyReportReviewNotice,
  type MonthlyReportCard,
  type MonthlyReportFunnelStep,
  type MonthlyReportSkipReason,
  type MonthlyReportTodo,
  type MonthlyReportTone,
} from "@/lib/monthly-report";
import { cn } from "@/lib/utils";

type IconType = typeof Target;

const toneClasses: Record<
  MonthlyReportTone,
  {
    card: string;
    icon: string;
    text: string;
    soft: string;
    bar: string;
    dot: string;
  }
> = {
  primary: {
    card: "border-blue-100 bg-blue-50/35 hover:border-blue-200",
    icon: "bg-blue-50 text-blue-600 ring-blue-100",
    text: "text-blue-700",
    soft: "bg-blue-50 text-blue-700 ring-blue-100",
    bar: "bg-blue-600",
    dot: "bg-blue-500",
  },
  success: {
    card: "border-emerald-100 bg-emerald-50/35 hover:border-emerald-200",
    icon: "bg-emerald-50 text-emerald-700 ring-emerald-100",
    text: "text-emerald-700",
    soft: "bg-emerald-50 text-emerald-700 ring-emerald-100",
    bar: "bg-emerald-600",
    dot: "bg-emerald-500",
  },
  warning: {
    card: "border-amber-100 bg-amber-50/55 hover:border-amber-200",
    icon: "bg-amber-50 text-amber-700 ring-amber-100",
    text: "text-amber-700",
    soft: "bg-amber-50 text-amber-800 ring-amber-100",
    bar: "bg-amber-500",
    dot: "bg-amber-500",
  },
  danger: {
    card: "border-rose-100 bg-rose-50/45 hover:border-rose-200",
    icon: "bg-rose-50 text-rose-700 ring-rose-100",
    text: "text-rose-700",
    soft: "bg-rose-50 text-rose-700 ring-rose-100",
    bar: "bg-rose-500",
    dot: "bg-rose-500",
  },
  neutral: {
    card: "border-slate-200 bg-slate-50/70 hover:border-slate-300",
    icon: "bg-slate-100 text-slate-600 ring-slate-200",
    text: "text-slate-600",
    soft: "bg-slate-100 text-slate-600 ring-slate-200",
    bar: "bg-slate-500",
    dot: "bg-slate-400",
  },
};

const overviewIcons: IconType[] = [Users, Mail, Target, BarChart3, Sparkles, Send];

function currentMonthValue() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function formatReportUpdatedAt(value: string | null | undefined, month: string) {
  if (!value) return `${month}-03 09:00`;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function MetricCard({
  card,
  icon: Icon,
}: {
  card: MonthlyReportCard;
  icon?: IconType;
}) {
  const tone = toneClasses[card.tone];
  const CardIcon = Icon ?? BarChart3;

  return (
    <Link
      href={card.href}
      className={cn(
        "group block min-h-[112px] rounded-2xl border p-4 transition hover:-translate-y-0.5 hover:shadow-sm",
        tone.card,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-xs font-medium text-slate-500">{card.label}</p>
          <p className="mt-2 text-[26px] font-semibold tracking-normal text-slate-950">{card.value}</p>
        </div>
        <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ring-1", tone.icon)}>
          <CardIcon className="h-4 w-4" />
        </span>
      </div>
      <div className="mt-2 flex items-center justify-between gap-2 text-xs">
        <span className={cn("truncate font-medium", tone.text)}>{card.helper}</span>
        <span className="inline-flex items-center text-slate-400 transition group-hover:text-blue-600">
          明细
          <ChevronRight className="h-3.5 w-3.5" />
        </span>
      </div>
    </Link>
  );
}

function ReportSection({
  title,
  description,
  children,
  action,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <Card className="rounded-[22px] border-slate-200/80 bg-[hsl(210_35%_99%)] shadow-[0_14px_38px_rgba(30,58,95,0.06)]">
      <CardHeader className="flex-row items-start justify-between gap-3 space-y-0 p-5 pb-3">
        <div>
          <CardTitle>{title}</CardTitle>
          {description ? <CardDescription className="mt-1">{description}</CardDescription> : null}
        </div>
        {action}
      </CardHeader>
      <CardContent className="p-5 pt-2">{children}</CardContent>
    </Card>
  );
}

function MonthSelector({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="inline-flex h-10 items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-700 shadow-sm">
      <CalendarDays className="h-4 w-4 text-slate-400" />
      <input
        type="month"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-8 bg-transparent text-sm font-medium outline-none"
        aria-label="选择月份"
      />
    </label>
  );
}

function FunnelChart({ steps }: { steps: MonthlyReportFunnelStep[] }) {
  const max = Math.max(...steps.map((step) => step.value), 1);

  return (
    <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_180px]">
      <div className="space-y-3">
        {steps.map((step, index) => {
          const width = Math.max(7, Math.round((step.value / max) * 100));
          const isReplyStage = step.label.includes("回复") || step.label.includes("合作");

          return (
            <Link
              key={step.label}
              href={step.href}
              className="group grid gap-2 rounded-xl px-2 py-1.5 transition hover:bg-slate-50 sm:grid-cols-[124px_minmax(0,1fr)_82px]"
            >
              <div className="flex items-center gap-2 text-sm font-medium text-slate-700">
                <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-slate-100 text-[11px] text-slate-500">
                  {index + 1}
                </span>
                {step.label}
              </div>
              <div className="flex min-w-0 items-center">
                <div className="h-3 w-full overflow-hidden rounded-full bg-slate-100">
                  <div
                    className={cn("h-full rounded-full", isReplyStage ? "bg-emerald-500" : "bg-blue-600")}
                    style={{ width: `${width}%` }}
                  />
                </div>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="font-semibold text-slate-950">{step.value.toLocaleString("zh-CN")}</span>
                <ChevronRight className="h-4 w-4 text-slate-300 transition group-hover:text-blue-600" />
              </div>
            </Link>
          );
        })}
      </div>

      <div className="rounded-2xl border border-slate-200 bg-slate-50/80 p-4">
        <p className="text-xs font-medium text-slate-500">发送到回复转化</p>
        <p className="mt-3 text-3xl font-semibold tracking-normal text-slate-950">7.6%</p>
        <p className="mt-3 text-xs leading-5 text-slate-500">从已发送到已回复的本月漏斗表现，合作意向进入跟进流程。</p>
        <Badge variant="outline" className="mt-4 border-amber-200 bg-amber-50 text-amber-700">
          高价值需人工确认
        </Badge>
      </div>
    </div>
  );
}

function SkipReasonList({ items }: { items: MonthlyReportSkipReason[] }) {
  const max = Math.max(...items.map((item) => item.value), 1);

  return (
    <div className="space-y-3">
      {items.map((item) => {
        const tone = toneClasses[item.tone];
        return (
          <Link
            key={item.label}
            href={item.href}
            className="group grid gap-2 rounded-xl px-2 py-1.5 transition hover:bg-slate-50 sm:grid-cols-[120px_minmax(0,1fr)_148px]"
          >
            <div className="text-sm font-medium text-slate-700">{item.label}</div>
            <div className="flex items-center gap-3">
              <div className="h-3 flex-1 overflow-hidden rounded-full bg-slate-100">
                <div className={cn("h-full rounded-full", tone.bar)} style={{ width: `${(item.value / max) * 100}%` }} />
              </div>
              <span className="w-12 text-right text-sm font-semibold text-slate-950">{item.value} 人</span>
            </div>
            <div className={cn("flex items-center justify-between text-xs font-medium", tone.text)}>
              {item.helper}
              <ChevronRight className="h-4 w-4 text-slate-300 transition group-hover:text-blue-600" />
            </div>
          </Link>
        );
      })}
    </div>
  );
}

function TodoItem({ todo }: { todo: MonthlyReportTodo }) {
  const tone = toneClasses[todo.tone];

  return (
    <Link
      href={todo.href}
      className={cn(
        "group grid gap-3 rounded-2xl border p-4 transition hover:-translate-y-0.5 hover:shadow-sm md:grid-cols-[1fr_auto] md:items-center",
        todo.tone === "warning" ? "border-amber-200 bg-amber-50/60" : "border-slate-200 bg-slate-50/70",
      )}
    >
      <div className="flex gap-3">
        <span className={cn("mt-1 h-2.5 w-2.5 shrink-0 rounded-full", tone.dot)} />
        <div>
          <p className="text-sm font-semibold text-slate-950">{todo.title}</p>
          <p className="mt-1 text-xs leading-5 text-slate-500">{todo.description}</p>
        </div>
      </div>
      <span className={cn("inline-flex items-center text-sm font-medium", tone.text)}>
        {todo.actionLabel}
        <ChevronRight className="h-4 w-4 transition group-hover:translate-x-0.5" />
      </span>
    </Link>
  );
}

export function DashboardPanel() {
  const [month, setMonth] = useState(currentMonthValue);
  const [report, setReport] = useState<DashboardMonthlyReport | null>(null);
  const [isLoadingReport, setIsLoadingReport] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [exportMessage, setExportMessage] = useState<string | null>(null);
  const sections = useMemo(() => buildMonthlyReportSections(report ?? undefined), [report]);
  const updatedAt = formatReportUpdatedAt(report?.updated_at, month);
  const reviewNotice = report?.review_notice ?? monthlyReportReviewNotice;

  useEffect(() => {
    let ignore = false;
    queueMicrotask(() => {
      if (!ignore) {
        setIsLoadingReport(true);
        setLoadError(null);
      }
    });
    fetchDashboardMonthlyReport(month)
      .then((nextReport) => {
        if (!ignore) setReport(nextReport);
      })
      .catch((error: unknown) => {
        if (!ignore) {
          setReport(null);
          setLoadError(error instanceof Error ? error.message : "月报数据加载失败，当前展示兜底数据。");
        }
      })
      .finally(() => {
        if (!ignore) setIsLoadingReport(false);
      });
    return () => {
      ignore = true;
    };
  }, [month]);

  function handleExportReport() {
    const csv = buildMonthlyReportExportCsv(month, updatedAt, sections);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `monthly-operation-report-${month}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
    setExportMessage(`已导出 ${month} 月报`);
    window.setTimeout(() => setExportMessage(null), 2400);
  }

  return (
    <AdminShell
      title="月度运营报告"
      description="按月份复盘达人采集、草稿审核、发送队列、回复与合作进展"
      actions={
        <>
          <MonthSelector value={month} onChange={setMonth} />
          <Button type="button" className="h-10 rounded-xl bg-blue-600 hover:bg-blue-700" onClick={handleExportReport}>
            <Download className="h-4 w-4" />
            导出月报
          </Button>
        </>
      }
    >
      <div className="h-full min-h-0 overflow-auto rounded-[28px] bg-[hsl(214_38%_95%)] p-4 lg:p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <Badge variant="outline" className="border-blue-200 bg-white text-blue-700">
              {month}
            </Badge>
            <span>本月更新时间 {updatedAt}</span>
            {isLoadingReport ? <span className="rounded-full bg-blue-50 px-2 py-1 text-blue-700">正在加载月报数据</span> : null}
            {loadError ? <span className="rounded-full bg-amber-50 px-2 py-1 text-amber-700">接口暂不可用，已显示兜底数据</span> : null}
            {exportMessage ? <span className="rounded-full bg-emerald-50 px-2 py-1 text-emerald-700">{exportMessage}</span> : null}
          </div>
          <div className="rounded-full bg-white px-3 py-1.5 text-xs text-slate-500 ring-1 ring-slate-200">
            所有模块已按当前月份筛选
          </div>
        </div>

        <div className="space-y-4">
          <ReportSection title={sections.overview.title} description="关键运营指标，点击数据卡进入对应明细列表">
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
              {sections.overview.cards.map((card, index) => (
                <MetricCard key={card.label} card={card} icon={overviewIcons[index]} />
              ))}
            </div>
          </ReportSection>

          <ReportSection
            title={sections.outreachRecap.title}
            description={reviewNotice}
            action={
              <Badge variant="outline" className="border-amber-200 bg-amber-50 text-amber-700">
                不在月报直接发送
              </Badge>
            }
          >
            <FunnelChart steps={sections.outreachRecap.funnel} />
          </ReportSection>

          <div className="grid gap-4 xl:grid-cols-2">
            <ReportSection title={sections.draftQuality.title} description="关注草稿是否可批准，高价值红人需打开草稿详情确认">
              <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">
                {sections.draftQuality.cards.map((card) => (
                  <MetricCard key={card.label} card={card} icon={card.tone === "warning" ? AlertTriangle : CheckCircle2} />
                ))}
              </div>
            </ReportSection>

            <ReportSection title={sections.queuePerformance.title} description="展示入队、发送和失败结果，实际发送仍在发送队列执行">
              <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">
                {sections.queuePerformance.cards.map((card) => (
                  <MetricCard key={card.label} card={card} icon={card.tone === "danger" ? AlertTriangle : Clock} />
                ))}
              </div>
            </ReportSection>
          </div>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.55fr)_minmax(360px,1fr)]">
            <ReportSection title={sections.skipReasons.title} description="清楚说明没发出的原因，避免业务员误判">
              <SkipReasonList items={sections.skipReasons.items} />
            </ReportSection>

            <ReportSection title={sections.replyProgress.title} description="从回复进入报价、寄样与合作推进">
              <div className="grid gap-3 sm:grid-cols-2">
                {sections.replyProgress.cards.map((card) => (
                  <MetricCard key={card.label} card={card} icon={card.label === "已回复" ? MessageCircleReply : Mail} />
                ))}
              </div>
            </ReportSection>
          </div>

          <ReportSection title="本月待办" description="复盘后的入口，帮助团队回到对应明细处理">
            <div className="grid gap-3 xl:grid-cols-2">
              {sections.todos.map((todo) => (
                <TodoItem key={todo.title} todo={todo} />
              ))}
            </div>
          </ReportSection>
        </div>
      </div>
    </AdminShell>
  );
}
