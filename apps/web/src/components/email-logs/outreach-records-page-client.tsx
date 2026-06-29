"use client";

import { useSearchParams } from "next/navigation";

import { EmailLogsPanel } from "@/components/email-logs/email-logs-panel";

export function OutreachRecordsPageClient() {
  const searchParams = useSearchParams();

  return (
    <EmailLogsPanel recordsOnly initialView={searchParams.get("view")} />
  );
}
