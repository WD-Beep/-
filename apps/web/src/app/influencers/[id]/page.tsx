import { notFound } from "next/navigation";

import { InfluencerDetail } from "@/components/influencers/influencer-detail";
import { fetchInfluencerServer } from "@/lib/api";

type PageProps = {
  params: Promise<{ id: string }>;
};

export default async function InfluencerDetailPage({ params }: PageProps) {
  const { id } = await params;
  const influencerId = Number(id);

  if (!Number.isInteger(influencerId) || influencerId <= 0) {
    notFound();
  }

  const influencerPromise = fetchInfluencerServer(influencerId).catch((error: Error & { status?: number }) => {
    if (error.status === 404) {
      notFound();
    }
    throw error;
  });

  const influencer = await influencerPromise;
  if (!influencer) {
    notFound();
  }

  return <InfluencerDetail initial={influencer} />;
}
