// 文件说明：前端页面路由入口；当前文件：page
import { Suspense } from "react";

import { OutreachCampaignsPanel } from "@/components/outreach-campaigns/outreach-campaigns-panel";
import { LoadingState } from "@/components/shared/page-states";

export default function OutreachCampaignsPage() {
  return (
    <Suspense fallback={<LoadingState label="加载外联活动..." />}>
      <OutreachCampaignsPanel />
    </Suspense>
  );
}
