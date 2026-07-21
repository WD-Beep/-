// 文件说明：前端页面路由入口；当前文件：route
import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.INTERNAL_API_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";
const LONG_RUNNING_TIMEOUT_MS = 15 * 60 * 1000;
const LONG_PROXY_TIMEOUT = "LONG_PROXY_TIMEOUT";
const LONG_PROXY_UNAVAILABLE = "LONG_PROXY_UNAVAILABLE";

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

async function proxyLongRunningRequest(request: NextRequest, context: RouteContext) {
  const { path = [] } = await context.params;
  const target = new URL(`${BACKEND_URL}/${path.map(encodeURIComponent).join("/")}`);
  target.search = request.nextUrl.search;

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!HOP_BY_HOP_HEADERS.has(key.toLowerCase())) {
      headers.set(key, value);
    }
  });

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  let response: Response;
  try {
    response = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
      signal: AbortSignal.timeout(LONG_RUNNING_TIMEOUT_MS),
    });
  } catch (error) {
    const errorName = error instanceof Error ? error.name : "UnknownError";
    const isTimeout = errorName === "TimeoutError" || errorName === "AbortError";
    console.error("Long-running API proxy failed", {
      path: target.pathname,
      error_name: errorName,
      timeout: isTimeout,
    });
    if (isTimeout) {
      return NextResponse.json(
        {
          detail: "后端长任务请求超时，请稍后重试。",
          code: LONG_PROXY_TIMEOUT,
          retryable: true,
          stage: "proxy",
        },
        { status: 504 },
      );
    }
    return NextResponse.json(
      {
        detail: "无法连接后端长任务服务，请稍后重试。",
        code: LONG_PROXY_UNAVAILABLE,
        retryable: true,
        stage: "proxy",
      },
      { status: 502 },
    );
  }

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
  return proxyLongRunningRequest(request, context);
}

export async function POST(request: NextRequest, context: RouteContext) {
  return proxyLongRunningRequest(request, context);
}

export async function PUT(request: NextRequest, context: RouteContext) {
  return proxyLongRunningRequest(request, context);
}

export async function PATCH(request: NextRequest, context: RouteContext) {
  return proxyLongRunningRequest(request, context);
}

export async function DELETE(request: NextRequest, context: RouteContext) {
  return proxyLongRunningRequest(request, context);
}
