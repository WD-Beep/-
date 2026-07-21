// 文件说明：前端页面路由入口；当前文件：page
import { Suspense } from "react";

import { OutreachCampaignDetailPanel } from "@/components/outreach-campaigns/outreach-campaign-detail-panel";
import { LoadingState } from "@/components/shared/page-states";

export default async function OutreachCampaignDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <Suspense fallback={<LoadingState label="加载批次明细..." />}>
      <OutreachCampaignDetailPanel campaignId={Number(id)} />
    </Suspense>
  );
}
