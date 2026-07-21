// 文件说明：前端管理员后台组件；当前文件：admin monthly report panel
"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { BarChart3, CheckCircle2, Download, Mail, RefreshCw } from "lucide-react";

import {
  AdminInput,
  AdminKpiCard,
  AdminKpiGrid,
  AdminPageHeader,
  AdminSection,
  AdminState,
  AdminStatusBadge,
} from "@/components/admin/admin-ui";
import type { AdminTone } from "@/components/admin/admin-ui-helpers";
import { fetchDashboardMonthlyReport, type DashboardMonthlyReport } from "@/lib/api";
import {
  buildMonthlyReportExportCsv,
  buildMonthlyReportSections,
  monthlyReportReviewNotice,
  type MonthlyReportTone,
} from "@/lib/monthly-report";

const currentMonth = new Date().toISOString().slice(0, 7);

function toneToAdminTone(tone: MonthlyReportTone): AdminTone {
  if (tone === "primary") return "info";
  if (tone === "success" || tone === "warning" || tone === "danger" || tone === "neutral") return tone;
  return "neutral";
}

function adminHref(href: string): string {
  const map: Array<[string, string]> = [
    ["/influencers", "/admin/influencers"],
    ["/collection-tasks", "/admin/collection-tasks"],
    ["/email-replies", "/admin/emails"],
    ["/outreach-records", "/admin/emails"],
    ["/outreach-send-queue", "/admin/emails"],
    ["/outreach-campaigns", "/admin/emails"],
  ];
  const match = map.find(([source]) => href.startsWith(source));
  return match ? href.replace(match[0], match[1]) : href;
}

function formatUpdatedAt(value: string | null | undefined, month: string) {
  if (!value) return `${month} 月报`;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return `${month} 月报`;
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

export function AdminMonthlyReportPanel() {
  const [month, setMonth] = useState(currentMonth);
  const [report, setReport] = useState<DashboardMonthlyReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exportMessage, setExportMessage] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const sections = useMemo(() => buildMonthlyReportSections(report ?? undefined), [report]);
  const updatedAt = formatUpdatedAt(report?.updated_at, month);
  const reviewNotice = report?.review_notice ?? monthlyReportReviewNotice;

  useEffect(() => {
    let active = true;
    fetchDashboardMonthlyReport(month)
      .then((nextReport) => {
        if (active) {
          setReport(nextReport);
          setError(null);
        }
      })
      .catch((err) => {
        if (active) {
          setReport(null);
          setError(err instanceof Error ? err.message : "月报数据加载失败，当前展示兜底数据。");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [month, refreshKey]);

  function handleMonthChange(value: string) {
    setMonth(value);
    setLoading(true);
    setError(null);
  }

  function handleExport() {
    const csv = buildMonthlyReportExportCsv(month, updatedAt, sections);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `admin-monthly-report-${month}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
    setExportMessage(`已导出 ${month} 月度总结`);
    window.setTimeout(() => setExportMessage(null), 2200);
  }

  return (
    <div className="space-y-3">
      <AdminPageHeader
        label="月度总结"
        title="月度运营可视化"
        description="按月份复盘采集、红人、邮件触达、回复进展和待处理事项，帮助管理员看清每个月具体情况。"
        actions={
          <>
            <label className="grid gap-1 text-xs font-medium text-[#667085]">
              选择月份
              <AdminInput type="month" value={month} onChange={(event) => handleMonthChange(event.target.value)} />
            </label>
            <button
              type="button"
              onClick={() => {
                setLoading(true);
                setRefreshKey((value) => value + 1);
              }}
              className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-[#D8E2EE] bg-white px-4 text-sm font-medium text-[#344054] transition hover:bg-[#F3F6FA]"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              刷新
            </button>
            <button
              type="button"
              onClick={handleExport}
              className="inline-flex h-9 items-center justify-center gap-2 rounded-md bg-[#2563EB] px-4 text-sm font-medium text-white transition hover:bg-[#1D4ED8]"
            >
              <Download className="h-4 w-4" />
              导出月报
            </button>
          </>
        }
      />

      <div className="flex flex-wrap items-center gap-2 text-xs text-[#667085]">
        <AdminStatusBadge meta={{ label: month, tone: "info" }} />
        <span>更新时间：{updatedAt}</span>
        {loading ? <AdminStatusBadge meta={{ label: "正在加载", tone: "info" }} /> : null}
        {error ? <AdminStatusBadge meta={{ label: "接口不可用，展示兜底数据", tone: "warning" }} /> : null}
        {exportMessage ? <AdminStatusBadge meta={{ label: exportMessage, tone: "success" }} /> : null}
      </div>

      <AdminKpiGrid>
        {sections.overview.cards.map((card, index) => (
          <Link key={card.label} href={adminHref(card.href)} className="block">
            <AdminKpiCard
              label={card.label}
              value={card.value}
              helper={card.helper}
              icon={index % 3 === 0 ? BarChart3 : index % 3 === 1 ? CheckCircle2 : Mail}
              tone={toneToAdminTone(card.tone)}
            />
          </Link>
        ))}
      </AdminKpiGrid>

      <AdminSection
        title={sections.outreachRecap.title}
        description={reviewNotice}
        actions={<AdminStatusBadge meta={{ label: "复盘视角", tone: "warning" }} />}
      >
        <div className="grid gap-3 p-4 lg:grid-cols-7">
          {sections.outreachRecap.funnel.map((step, index) => {
            const max = Math.max(...sections.outreachRecap.funnel.map((item) => item.value), 1);
            const percent = Math.max(8, Math.round((step.value / max) * 100));
            return (
              <Link
                key={step.label}
                href={adminHref(step.href)}
                className="rounded-lg border border-[#DDE6F0] bg-[#FBFCFE] p-3 transition hover:-translate-y-0.5 hover:shadow-[0_10px_22px_rgba(16,32,51,0.08)]"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-medium text-[#667085]">{step.label}</span>
                  <span className="text-xs text-[#98A2B3]">#{index + 1}</span>
                </div>
                <div className="mt-3 text-2xl font-bold tabular-nums text-[#102033]">{step.value}</div>
                <div className="mt-3 h-2 rounded-full bg-[#E8EEF6]">
                  <div className="h-2 rounded-full bg-[#2563EB]" style={{ width: `${percent}%` }} />
                </div>
              </Link>
            );
          })}
        </div>
      </AdminSection>

      <section className="grid gap-4 xl:grid-cols-2">
        <ReportCards title={sections.draftQuality.title} cards={sections.draftQuality.cards} />
        <ReportCards title={sections.queuePerformance.title} cards={sections.queuePerformance.cards} />
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1.3fr)_minmax(360px,0.9fr)]">
        <AdminSection title={sections.skipReasons.title} description="看清楚没发出或没推进的主要原因。">
          <div className="grid gap-2 p-4 sm:grid-cols-2">
            {sections.skipReasons.items.map((item) => (
              <Link key={item.label} href={adminHref(item.href)} className="rounded-lg border border-[#DDE6F0] bg-white p-3 transition hover:bg-[#F8FAFD]">
                <div className="flex items-center justify-between gap-3">
                  <span className="font-medium text-[#102033]">{item.label}</span>
                  <AdminStatusBadge meta={{ label: String(item.value), tone: toneToAdminTone(item.tone) }} />
                </div>
                <p className="mt-1 text-xs text-[#667085]">{item.helper}</p>
              </Link>
            ))}
          </div>
        </AdminSection>
        <ReportCards title={sections.replyProgress.title} cards={sections.replyProgress.cards} />
      </section>

      <AdminSection title="本月待办" description="从月度复盘回到可执行事项。">
        <div className="grid gap-3 p-4 xl:grid-cols-2">
          {sections.todos.map((todo) => (
            <Link key={todo.title} href={adminHref(todo.href)} className="rounded-lg border border-[#DDE6F0] bg-white p-4 transition hover:-translate-y-0.5 hover:shadow-[0_10px_22px_rgba(16,32,51,0.08)]">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="font-semibold text-[#102033]">{todo.title}</h3>
                  <p className="mt-1 text-sm leading-6 text-[#667085]">{todo.description}</p>
                </div>
                <AdminStatusBadge meta={{ label: todo.actionLabel, tone: toneToAdminTone(todo.tone) }} />
              </div>
            </Link>
          ))}
        </div>
      </AdminSection>

      {loading ? <AdminState type="loading" message="正在刷新月度数据..." /> : null}
    </div>
  );
}

function ReportCards({
  title,
  cards,
}: {
  title: string;
  cards: ReturnType<typeof buildMonthlyReportSections>["overview"]["cards"];
}) {
  return (
    <AdminSection title={title}>
      <div className="grid gap-3 p-4 sm:grid-cols-2 2xl:grid-cols-3">
        {cards.map((card) => (
          <Link key={card.label} href={adminHref(card.href)} className="rounded-lg border border-[#DDE6F0] bg-white p-3 transition hover:bg-[#F8FAFD]">
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm font-medium text-[#667085]">{card.label}</span>
              <AdminStatusBadge meta={{ label: card.value, tone: toneToAdminTone(card.tone) }} />
            </div>
            <p className="mt-2 text-xs leading-5 text-[#667085]">{card.helper}</p>
          </Link>
        ))}
      </div>
    </AdminSection>
  );
}
