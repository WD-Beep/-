"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Bot,
  Database,
  Download,
  Filter,
  Layers,
  Loader2,
  Mail,
  Play,
  RefreshCw,
  Search,
  Send,
  Server,
  Sparkles,
  Target,
  Users,
} from "lucide-react";

import { AdminShell } from "@/components/layout/admin-shell";
import { useActiveProductId } from "@/components/providers/product-provider";
import { HealthStatus } from "@/components/dashboard/health-status";
import { ErrorAlert, LoadingState } from "@/components/shared/page-states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { downloadInfluencerExport, fetchDashboardSummary, type DashboardSummary } from "@/lib/api";

type IconType = typeof Target;

function formatMetric(value: number | string | null | undefined, fallback = "-"): string {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "number") return value.toLocaleString("zh-CN");
  return value;
}

function StatCard({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: IconType;
  label: string;
  value: number | string | null | undefined;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border bg-muted/25 p-4">
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs text-muted-foreground">{label}</p>
        <Icon className="h-4 w-4 text-primary" />
      </div>
      <p className="mt-2 text-2xl font-semibold tracking-normal">{formatMetric(value)}</p>
      {hint ? <p className="mt-1 text-xs leading-5 text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function PipelineStep({
  index,
  title,
  icon: Icon,
  items,
  tone,
}: {
  index: number;
  title: string;
  icon: IconType;
  items: string[];
  tone: "blue" | "teal" | "violet" | "slate" | "orange" | "green";
}) {
  const toneClass = {
    blue: "border-blue-200 bg-blue-50/60 text-blue-700",
    teal: "border-teal-200 bg-teal-50/60 text-teal-700",
    violet: "border-violet-200 bg-violet-50/60 text-violet-700",
    slate: "border-slate-200 bg-slate-50/70 text-slate-700",
    orange: "border-orange-200 bg-orange-50/70 text-orange-700",
    green: "border-emerald-200 bg-emerald-50/70 text-emerald-700",
  }[tone];

  return (
    <div className="rounded-lg border bg-background p-4">
      <div className="flex items-center gap-3">
        <div className={`flex h-9 w-9 items-center justify-center rounded-md border ${toneClass}`}>
          <Icon className="h-4 w-4" />
        </div>
        <div className="min-w-0">
          <p className="text-xs font-medium text-muted-foreground">{index}. 模块</p>
          <h3 className="truncate text-sm font-semibold">{title}</h3>
        </div>
      </div>
      <ul className="mt-4 space-y-2 text-xs leading-5 text-muted-foreground">
        {items.map((item) => (
          <li key={item} className="flex gap-2">
            <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-primary/70" />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ActionCard({
  icon: Icon,
  title,
  description,
  href,
  label,
}: {
  icon: IconType;
  title: string;
  description: string;
  href: string;
  label: string;
}) {
  return (
    <div className="flex flex-col justify-between gap-4 rounded-lg border bg-background p-4">
      <div className="flex gap-3">
        <Icon className="mt-0.5 h-4 w-4 text-primary" />
        <div>
          <p className="text-sm font-medium">{title}</p>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">{description}</p>
        </div>
      </div>
      <Button variant="secondary" size="sm" asChild>
        <Link href={href}>{label}</Link>
      </Button>
    </div>
  );
}

function RecentTaskRow({ task }: { task: DashboardSummary["recent_tasks"][number] }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b py-3 last:border-0">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium">{task.name}</p>
        <p className="mt-1 text-xs text-muted-foreground">
          Instagram · {task.collection_mode} · {task.result_count} 条结果
        </p>
      </div>
      <Badge
        variant={
          task.status === "completed" || task.status === "completed_with_results"
            ? "success"
            : task.status === "partial_failed" || task.status === "completed_no_results"
              ? "warning"
              : task.status === "failed"
                ? "destructive"
                : "secondary"
        }
      >
        {task.status}
      </Badge>
    </div>
  );
}

export function DashboardPanel() {
  const productId = useActiveProductId();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchDashboardSummary();
      setSummary(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "数据概览加载失败，请确认后端服务已启动。");
      setSummary(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (productId === null) {
      setLoading(false);
      return;
    }
    queueMicrotask(() => {
      void load();
    });
  }, [load, productId]);

  const taskSuccessRate = useMemo(() => {
    if (!summary || summary.total_tasks === 0) return "0%";
    return `${Math.round((summary.completed_tasks / summary.total_tasks) * 100)}%`;
  }, [summary]);

  return (
    <AdminShell title="Instagram 红人智能采集平台" description="采集、清洗、AI 画像、合作评估与外联沉淀">
      <div className="mb-4 flex flex-wrap gap-2">
        <Button variant="default" size="sm" asChild>
          <Link href="/collection-tasks">
            <Play className="h-4 w-4" />
            创建采集任务
          </Link>
        </Button>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          刷新数据
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            void downloadInfluencerExport({ platform: "instagram" }).catch((err) =>
              setError(err instanceof Error ? err.message : "导出失败"),
            );
          }}
        >
          <Download className="h-4 w-4" />
          导出 Instagram 数据
        </Button>
      </div>

      {error ? <ErrorAlert message={error} className="mb-4" /> : null}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-1">
          <HealthStatus />
        </div>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>核心数据指标</CardTitle>
            <CardDescription>优先看采集规模、触达能力、合作匹配和 ROI 预估</CardDescription>
          </CardHeader>
          <CardContent>
            {loading && !summary ? (
              <LoadingState label="正在加载数据..." />
            ) : summary ? (
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                <StatCard icon={Users} label="Instagram 达人" value={summary.instagram_influencers} hint={`总库 ${summary.total_influencers} 人`} />
                <StatCard icon={Mail} label="邮箱覆盖率" value={`${summary.email_coverage_rate}%`} hint={`${summary.contactable_count} 人可触达`} />
                <StatCard icon={Target} label="高匹配达人" value={summary.high_match_count} hint={`平均匹配 ${summary.average_product_fit ?? "-"} 分`} />
                <StatCard icon={Sparkles} label="ROI 预估均值" value={summary.average_roi_forecast ? `${summary.average_roi_forecast}x` : "-"} hint={`综合评分 ${summary.average_score ?? "-"} 分`} />
                <StatCard icon={Layers} label="采集任务" value={summary.total_tasks} hint={`${summary.active_tasks} 个进行中`} />
                <StatCard icon={Bot} label="任务完成率" value={taskSuccessRate} hint={`${summary.failed_tasks} 个失败`} />
                <StatCard icon={Send} label="邮件记录" value={summary.total_email_logs} hint={`${summary.sent_emails} 封已发送`} />
                <StatCard icon={Database} label="平台覆盖" value={summary.platforms.length} hint="当前聚焦 Instagram" />
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">暂无统计数据</p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="mt-6">
        <CardHeader>
          <CardTitle>系统数据流（Instagram 专用）</CardTitle>
          <CardDescription>
            入口层 → 采集清洗 → AI 画像 → 数据中心 → 应用服务 → 输出行动
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="mb-4 hidden items-center gap-1 text-xs text-muted-foreground xl:flex">
            {["入口层", "采集清洗", "AI 画像", "数据中心", "应用服务", "输出行动"].map((label, i, arr) => (
              <span key={label} className="flex items-center gap-1">
                <span className="font-medium text-foreground">{label}</span>
                {i < arr.length - 1 ? <span className="px-1 text-primary">→</span> : null}
              </span>
            ))}
          </div>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
            <PipelineStep
              index={1}
              title="入口层"
              icon={Search}
              tone="blue"
              items={["主页 URL / 用户名批量", "Hashtag 自动发现", "粘贴链接导入批次", "任务调度入口"]}
            />
            <PipelineStep
              index={2}
              title="采集清洗层"
              icon={Filter}
              tone="teal"
              items={["Apify Instagram 采集", "去重与互动率过滤", "邮箱/外链提取", "异常任务标记"]}
            />
            <PipelineStep
              index={3}
              title="AI 画像层"
              icon={Bot}
              tone="orange"
              items={["Kimi 画像（失败降级 Mock）", "综合评分与 Product Fit", "Travel Fit / 购买力 / 带货", "ROI 预估与合作建议"]}
            />
            <PipelineStep
              index={4}
              title="数据中心"
              icon={Database}
              tone="violet"
              items={["PostgreSQL 持久化", "红人库多维筛选", "评分理由与标签", "采集任务运行记录"]}
            />
            <PipelineStep
              index={5}
              title="应用服务层"
              icon={Server}
              tone="slate"
              items={["FastAPI 业务接口", "定时采集调度", "SMTP / Mailchimp 外联", "健康检查与配置状态"]}
            />
            <PipelineStep
              index={6}
              title="输出行动层"
              icon={Send}
              tone="green"
              items={["红人详情跟进", "Excel 名单导出", "邮件日志追踪", "高匹配达人优先触达"]}
            />
          </div>
        </CardContent>
      </Card>

      <div className="mt-6 grid gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>运营入口</CardTitle>
            <CardDescription>从采集到跟进的常用路径</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-2">
            <ActionCard
              icon={Play}
              title="创建 Instagram 采集"
              description="粘贴主页 URL 或输入 hashtag，采集后自动清洗并调用 Kimi 生成画像。"
              href="/collection-tasks"
              label="去创建"
            />
            <ActionCard
              icon={Users}
              title="筛选高匹配达人"
              description="按有邮箱、可联系、高匹配快速筛选，再进入详情查看合作建议。"
              href="/influencers"
              label="看红人库"
            />
            <ActionCard
              icon={Database}
              title="批量链接导入"
              description="适合已有一批 Instagram 链接时快速建批次并运行导入。"
              href="/link-import"
              label="去导入"
            />
            <ActionCard
              icon={Mail}
              title="查看外联记录"
              description="跟踪邮件发送状态、附件导出和失败原因。"
              href="/email-logs"
              label="看记录"
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>最近任务</CardTitle>
            <CardDescription>最近更新的采集任务</CardDescription>
          </CardHeader>
          <CardContent>
            {summary?.recent_tasks?.length ? (
              summary.recent_tasks.map((task) => <RecentTaskRow key={task.id} task={task} />)
            ) : (
              <p className="text-sm text-muted-foreground">暂无任务，先创建一个 Instagram 采集任务。</p>
            )}
          </CardContent>
        </Card>
      </div>
    </AdminShell>
  );
}
