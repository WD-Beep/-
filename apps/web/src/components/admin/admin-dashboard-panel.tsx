"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, BarChart3, Download, MailCheck, RefreshCw, Users } from "lucide-react";

import {
  AdminActionButton,
  AdminKpiCard,
  AdminKpiGrid,
  AdminPageHeader,
  AdminSection,
  AdminState,
  AdminTable,
} from "@/components/admin/admin-ui";
import { buildAdminDashboardView, formatAdminNumber } from "@/components/admin/admin-ui-helpers";
import { type AdminSummary, fetchAdminSummary } from "@/lib/api";

export function AdminDashboardPanel() {
  const [summary, setSummary] = useState<AdminSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    fetchAdminSummary()
      .then((data) => {
        if (active) setSummary(data);
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : "后台首页加载失败。");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  if (loading) return <AdminState type="loading" message="正在加载后台首页..." />;
  if (error) return <AdminState type="error" message={error} />;
  if (!summary) return <AdminState message="暂无后台概览数据。" />;

  const view = buildAdminDashboardView(summary);
  const dashboardSourceFields = {
    total_sales: summary.total_sales,
    total_products: summary.total_products,
    total_collection_tasks: summary.total_collection_tasks,
  };
  void dashboardSourceFields;
  const exceptionRows = [
    ["失败任务", formatAdminNumber(summary.failed_collection_tasks), "查看任务日志、重新运行或标记异常"],
    ["发送失败", formatAdminNumber(summary.failed_email_logs), "检查发信账号、收件人和模板"],
    ["待处理回复", formatAdminNumber(summary.pending_replies), "分配跟进人并标记处理状态"],
  ];

  return (
    <div className="space-y-3">
      <AdminPageHeader
        label="后台首页"
        title="管理员数据看板"
        description="汇总品牌、业务员、采集任务、红人资料、邮件发送和回复情况，帮助管理员快速定位今天需要处理的事项。"
        actions={
          <>
            <AdminActionButton href="/admin/collection-tasks">
              <RefreshCw className="h-3.5 w-3.5" />
              查看任务
            </AdminActionButton>
            <AdminActionButton href="/admin/emails">
              <MailCheck className="h-3.5 w-3.5" />
              处理回复
            </AdminActionButton>
          </>
        }
      />

      <AdminKpiGrid>
        {view.kpis.map((item, index) => (
          <AdminKpiCard
            key={item.label}
            label={item.label}
            value={item.value}
            helper={item.helper}
            icon={index === 7 ? AlertTriangle : index === 1 ? Users : BarChart3}
            tone={index === 7 && view.pendingExceptionCount > 0 ? "warning" : "info"}
          />
        ))}
      </AdminKpiGrid>

      <section className="grid gap-4 xl:grid-cols-[1fr_1fr_360px]">
        <AdminSection title="业务员表现排行" description="按负责品牌数量排序，辅助判断资源分布。">
          <AdminTable
            minWidth={420}
            columns={["业务员", "负责品牌数", "查看"]}
            rows={summary.sales_rank.map((item) => [
              <span key="name" className="font-medium text-[#102033]">{item.username}</span>,
              formatAdminNumber(item.product_count),
              <AdminActionButton key="action" href={`/admin/users/${item.id}`}>查看业绩</AdminActionButton>,
            ])}
            emptyMessage="暂无业务员排行。"
          />
        </AdminSection>

        <AdminSection title="品牌进度概览" description="优先查看红人沉淀较多或进展较快的品牌。">
          <AdminTable
            minWidth={440}
            columns={["品牌", "红人数", "查看"]}
            rows={summary.product_rank.map((item) => [
              <span key="name" className="font-medium text-[#102033]">{item.name}</span>,
              formatAdminNumber(item.influencer_count),
              <AdminActionButton key="action" href={`/admin/products/${item.id}`}>品牌详情</AdminActionButton>,
            ])}
            emptyMessage="暂无品牌进度数据。"
          />
        </AdminSection>

        <AdminSection title="异常提醒" description="集中处理会影响采集和跟进的事项。">
          <AdminTable
            minWidth={360}
            columns={["类型", "数量", "建议"]}
            rows={exceptionRows}
            emptyMessage="暂无异常。"
          />
        </AdminSection>
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <AdminSection
          title="最近采集任务"
          description="当前接口暂未返回最近任务列表，先展示今日任务和异常入口。"
          actions={<AdminActionButton href="/admin/collection-tasks">进入任务监控</AdminActionButton>}
        >
          <div className="grid gap-3 p-4 sm:grid-cols-3">
            <AdminKpiCard label="今日任务" value={summary.today_collection_tasks} helper="今日采集动作" icon={RefreshCw} tone="info" />
            <AdminKpiCard label="失败任务" value={summary.failed_collection_tasks} helper="需要排查日志" icon={AlertTriangle} tone="danger" />
            <AdminKpiCard label="采集成功率" value={view.successRateLabel} helper="按失败任务推算" icon={BarChart3} tone="success" />
          </div>
        </AdminSection>

        <AdminSection
          title="邮件回复趋势"
          description="用现有总量和今日数据呈现跟进压力，后续可接入按日趋势。"
          actions={<AdminActionButton><Download className="h-3.5 w-3.5" />导出报表</AdminActionButton>}
        >
          <div className="grid gap-3 p-4 sm:grid-cols-3">
            {view.replyTrend.map((item) => (
              <AdminKpiCard key={item.label} label={item.label} value={item.value} helper="邮件跟进" icon={MailCheck} tone="info" />
            ))}
          </div>
        </AdminSection>
      </section>
    </div>
  );
}
