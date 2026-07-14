import { notFound } from "next/navigation";

import { AdminInfluencerDetailPanel } from "@/components/admin/admin-influencer-detail-panel";
import { fetchInfluencerServer } from "@/lib/api";

type PageProps = {
  params: Promise<{ id: string }>;
};

export default async function AdminInfluencerDetailPage({ params }: PageProps) {
  const { id } = await params;
  const influencerId = Number(id);
  if (!Number.isInteger(influencerId) || influencerId <= 0) notFound();

  try {
    await fetchInfluencerServer(influencerId);
  } catch (error) {
    const err = error as Error & { status?: number };
    if (err.status === 404) notFound();
    throw error;
  }

  return <AdminInfluencerDetailPanel influencerId={influencerId} />;
}
