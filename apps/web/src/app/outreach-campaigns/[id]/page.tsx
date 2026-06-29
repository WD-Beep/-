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
