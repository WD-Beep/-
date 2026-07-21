// 文件说明：前端页面路由入口；当前文件：page
import { notFound } from "next/navigation";

import { LinkScriptJobDetailPanel } from "@/components/link-knowledge-bases/link-knowledge-panels";

type PageProps = {
  params: Promise<{ id: string }>;
};

export default async function LinkScriptJobPage({ params }: PageProps) {
  const { id } = await params;
  const jobId = Number(id);
  if (!Number.isInteger(jobId) || jobId <= 0) {
    notFound();
  }
  return <LinkScriptJobDetailPanel jobId={jobId} />;
}
