// 文件说明：前端 API 代理路由，负责转发浏览器请求到后端；当前文件：route
import { NextResponse } from "next/server";

const BACKEND_URL =
  process.env.INTERNAL_API_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";
const LONG_TIMEOUT_MS = 120_000;

function forwardTenantHeaders(request: Request): HeadersInit {
  const headers: Record<string, string> = {};
  for (const key of ["X-User-Id", "X-Product-Id"]) {
    const value = request.headers.get(key);
    if (value) {
      headers[key] = value;
    }
  }
  return headers;
}

export async function POST(
  request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const { id } = await context.params;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), LONG_TIMEOUT_MS);

  try {
    const response = await fetch(`${BACKEND_URL}/api/influencers/${id}/refresh-contact`, {
      method: "POST",
      headers: forwardTenantHeaders(request),
      signal: controller.signal,
      cache: "no-store",
    });
    const body = await response.text();
    return new NextResponse(body, {
      status: response.status,
      headers: {
        "Content-Type": response.headers.get("content-type") ?? "application/json",
      },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "proxy failed";
    return NextResponse.json(
      { detail: `联系方式深挖请求超时或后端不可用：${message}` },
      { status: 504 },
    );
  } finally {
    clearTimeout(timer);
  }
}
