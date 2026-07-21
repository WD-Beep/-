// 文件说明：前端页面路由入口；当前文件：page
import { notFound } from "next/navigation";

import { EditLinkKnowledgeBasePanel } from "@/components/link-knowledge-bases/link-knowledge-panels";

type PageProps = {
  params: Promise<{ id: string }>;
};

export default async function EditLinkKnowledgeBasePage({ params }: PageProps) {
  const { id } = await params;
  const baseId = Number(id);
  if (!Number.isInteger(baseId) || baseId <= 0) {
    notFound();
  }
  return <EditLinkKnowledgeBasePanel baseId={baseId} />;
}
