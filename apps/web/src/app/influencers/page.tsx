// 文件说明：前端页面路由入口；当前文件：page
import { Suspense } from "react";

import { InfluencersPanel } from "@/components/influencers/influencers-panel";
import { LoadingState } from "@/components/shared/page-states";

export default function InfluencersPage() {
  return (
    <Suspense fallback={<LoadingState label="加载红人库..." />}>
      <InfluencersPanel />
    </Suspense>
  );
}
