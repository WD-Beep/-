// 文件说明：前端页面路由入口；当前文件：page
import { Suspense } from "react";

import { OutreachRecordsPageClient } from "@/components/email-logs/outreach-records-page-client";
import { LoadingState } from "@/components/shared/page-states";

export default function OutreachRecordsPage() {
  return (
    <Suspense fallback={<LoadingState label="加载外联记录..." />}>
      <OutreachRecordsPageClient />
    </Suspense>
  );
}
