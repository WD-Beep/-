// 文件说明：前端页面路由入口；当前文件：route
import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.INTERNAL_API_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";
const PROXY_TIMEOUT_MS = 30_000;
const PROXY_TIMEOUT = "PROXY_TIMEOUT";
const PROXY_UNAVAILABLE = "PROXY_UNAVAILABLE";

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

async function proxyApiRequest(request: NextRequest, context: RouteContext) {
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
      signal: AbortSignal.timeout(PROXY_TIMEOUT_MS),
    });
  } catch (error) {
    const errorName = error instanceof Error ? error.name : "UnknownError";
    const isTimeout = errorName === "TimeoutError" || errorName === "AbortError";
    console.error("API proxy failed", {
      path: target.pathname,
      error_name: errorName,
      timeout: isTimeout,
    });
    if (isTimeout) {
      return NextResponse.json(
        {
          detail: "后端接口请求超时，请稍后重试；如果刚部署过，请刷新页面后再试。",
          code: PROXY_TIMEOUT,
          retryable: true,
          stage: "proxy",
        },
        { status: 504 },
      );
    }
    return NextResponse.json(
      {
        detail: "后端接口连接中断，请刷新页面重试；如果频繁出现，说明 Web 代理或服务器内存不稳定。",
        code: PROXY_UNAVAILABLE,
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
  return proxyApiRequest(request, context);
}

export async function POST(request: NextRequest, context: RouteContext) {
  return proxyApiRequest(request, context);
}

export async function PUT(request: NextRequest, context: RouteContext) {
  return proxyApiRequest(request, context);
}

export async function PATCH(request: NextRequest, context: RouteContext) {
  return proxyApiRequest(request, context);
}

export async function DELETE(request: NextRequest, context: RouteContext) {
  return proxyApiRequest(request, context);
}
