// 文件说明：前端 API 代理路由，负责转发浏览器请求到后端；当前文件：route
import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.INTERNAL_API_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";
const PROXY_TIMEOUT_MS = 30_000;

const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "content-length",
  "host",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

type RouteContext = {
  params: Promise<{ path?: string[] }>;
};

async function proxyCollectionTaskRequest(request: NextRequest, context: RouteContext) {
  const { path = [] } = await context.params;
  const target = new URL(`${BACKEND_URL}/api/collection-tasks/${path.map(encodeURIComponent).join("/")}`);
  target.search = request.nextUrl.search;

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!HOP_BY_HOP_HEADERS.has(key.toLowerCase())) {
      headers.set(key, value);
    }
  });

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  const response = await fetch(target, {
    method: request.method,
    headers,
    body: hasBody ? await request.arrayBuffer() : undefined,
    signal: AbortSignal.timeout(PROXY_TIMEOUT_MS),
  });

  const responseHeaders = new Headers();
  response.headers.forEach((value, key) => {
    if (!HOP_BY_HOP_HEADERS.has(key.toLowerCase())) {
      responseHeaders.set(key, value);
    }
  });

  return new NextResponse(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: responseHeaders,
  });
}

export async function GET(request: NextRequest, context: RouteContext) {
  return proxyCollectionTaskRequest(request, context);
}

export async function POST(request: NextRequest, context: RouteContext) {
  return proxyCollectionTaskRequest(request, context);
}

export async function PUT(request: NextRequest, context: RouteContext) {
  return proxyCollectionTaskRequest(request, context);
}

export async function PATCH(request: NextRequest, context: RouteContext) {
  return proxyCollectionTaskRequest(request, context);
}

export async function DELETE(request: NextRequest, context: RouteContext) {
  return proxyCollectionTaskRequest(request, context);
}
