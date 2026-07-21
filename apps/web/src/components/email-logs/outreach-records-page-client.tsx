// 文件说明：前端邮件记录和发送队列组件；当前文件：outreach records page client
"use client";

import { useSearchParams } from "next/navigation";

import { EmailLogsPanel } from "@/components/email-logs/email-logs-panel";

export function OutreachRecordsPageClient() {
  const searchParams = useSearchParams();

  return (
    <EmailLogsPanel recordsOnly initialView={searchParams.get("view")} />
  );
}
