import type { PlatformCapabilitiesResponse, PlatformCapability } from "./api";

export function formatCollectionSourceSummary(
  meta: Pick<
    PlatformCapabilitiesResponse,
    | "instagram_data_provider"
    | "youtube_data_provider"
    | "tiktok_data_provider"
    | "facebook_data_provider"
    | "apify_configured"
    | "api_direct_configured"
  >,
): string {
  const ig = meta.instagram_data_provider;
  const yt = meta.youtube_data_provider;
  const tt = meta.tiktok_data_provider ?? "apify";
  const fb = meta.facebook_data_provider ?? "apify";
  const apifyNote = meta.apify_configured ? "" : "（Apify 未配置密钥）";
  return (
    `Instagram 默认 ${ig}；YouTube 默认 ${yt}；TikTok 默认 ${tt}；` +
    `Facebook 默认 ${fb}${apifyNote}`
  );
}

export function formatPlatformCapabilityHint(cap: PlatformCapability | undefined, fallback = ""): string {
  if (!cap) return fallback;
  return cap.message || fallback;
}
