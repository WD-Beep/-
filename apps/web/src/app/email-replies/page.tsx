import { Suspense } from "react";

import { EmailRepliesPanel } from "@/components/email-replies/email-replies-panel";

export default function EmailRepliesPage() {
  return (
    <Suspense fallback={null}>
      <EmailRepliesPanel />
    </Suspense>
  );
}
