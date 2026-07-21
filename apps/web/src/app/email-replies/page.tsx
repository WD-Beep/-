// 文件说明：前端页面路由入口；当前文件：page
import { Suspense } from "react";

import { EmailRepliesPanel } from "@/components/email-replies/email-replies-panel";

export default function EmailRepliesPage() {
  return (
    <Suspense fallback={null}>
      <EmailRepliesPanel />
    </Suspense>
  );
}
