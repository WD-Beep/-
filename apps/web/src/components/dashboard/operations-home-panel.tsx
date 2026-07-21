// 文件说明：前端页面组件；当前文件：operations home panel
import Link from "next/link";
import {
  BookOpen,
  Clock,
  Inbox,
  Link2,
  Mail,
  Megaphone,
  Search,
  Send,
  Users,
} from "lucide-react";

import { AdminShell } from "@/components/layout/admin-shell";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const primaryFlows = [
  {
    href: "/influencers",
    title: "红人库",
    description: "筛选、补充联系方式、标记跟进状态。",
    icon: Users,
  },
  {
    href: "/collection-tasks",
    title: "采集任务",
    description: "创建关键词采集或查看链接导入进度。",
    icon: Search,
  },
  {
    href: "/link-knowledge-bases",
    title: "链接库",
    description: "沉淀品牌链接知识，生成外联话术。",
    icon: Link2,
  },
  {
    href: "/outreach-campaigns",
    title: "AI 批量发邮件",
    description: "选择红人、生成内容、确认并发送。",
    icon: Megaphone,
  },
];

const workQueues = [
  { href: "/outreach-send-queue", label: "发送队列", icon: Clock },
  { href: "/email-logs", label: "邮件日志", icon: Mail },
  { href: "/email-replies", label: "回复跟进", icon: Inbox },
  { href: "/outreach-records", label: "发送记录", icon: Send },
  { href: "/knowledge-bases", label: "知识库", icon: BookOpen },
];

export function OperationsHomePanel() {
  return (
    <AdminShell
      title="数据概览"
      description="业务员常用入口集中在这里，继续处理采集、红人筛选、AI 外联、邮件日志和回复跟进。"
    >
      <div className="h-full min-h-0 overflow-auto bg-[hsl(214_38%_95%)] p-4 lg:p-5">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <Badge variant="outline" className="border-blue-200 bg-white text-blue-700">
            工作台
          </Badge>
          <span className="text-xs text-slate-500">按日常处理顺序打开对应模块。</span>
        </div>

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.3fr)_360px]">
          <section className="grid gap-3 md:grid-cols-2">
            {primaryFlows.map((item) => {
              const Icon = item.icon;
              return (
                <Link key={item.href} href={item.href} className="group block">
                  <Card className="h-full rounded-xl border-slate-200 bg-white transition group-hover:border-blue-200 group-hover:shadow-sm">
                    <CardHeader className="flex-row items-start gap-3 space-y-0 p-5">
                      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600 ring-1 ring-blue-100">
                        <Icon className="h-5 w-5" />
                      </span>
                      <div className="min-w-0">
                        <CardTitle className="text-base">{item.title}</CardTitle>
                        <CardDescription className="mt-1 leading-5">{item.description}</CardDescription>
                      </div>
                    </CardHeader>
                  </Card>
                </Link>
              );
            })}
          </section>

          <Card className="rounded-xl border-slate-200 bg-white">
            <CardHeader className="p-5 pb-3">
              <CardTitle className="text-base">待处理队列</CardTitle>
              <CardDescription>从发送、邮件和回复模块继续推进外联结果。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2 p-5 pt-0">
              {workQueues.map((item) => {
                const Icon = item.icon;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className="flex min-h-10 items-center justify-between rounded-lg px-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 hover:text-blue-700"
                  >
                    <span className="inline-flex items-center gap-2">
                      <Icon className="h-4 w-4 text-slate-400" />
                      {item.label}
                    </span>
                    <span className="text-slate-300">›</span>
                  </Link>
                );
              })}
            </CardContent>
          </Card>
        </div>
      </div>
    </AdminShell>
  );
}

