import { Suspense } from "react";

import { CollectionTasksPanel } from "@/components/collection-tasks/collection-tasks-panel";
import { LoadingState } from "@/components/shared/page-states";

export default function CollectionTasksPage() {
  return (
    <Suspense fallback={<LoadingState label="加载采集任务..." />}>
      <CollectionTasksPanel />
    </Suspense>
  );
}
