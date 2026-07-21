// 文件说明：项目源码文件；当前文件：middleware
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { AUTH_COOKIE } from "@/lib/auth-constants";

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const isAuthenticated = request.cookies.get(AUTH_COOKIE)?.value === "1";
  const isLoginPage = pathname === "/login";
  const isAdminLoginPage = pathname === "/admin/login";

  if (isAdminLoginPage) {
    const forceRelogin = request.nextUrl.searchParams.get("relogin") === "1";
    if (forceRelogin) {
      const response = NextResponse.next();
      response.cookies.set(AUTH_COOKIE, "", { path: "/", maxAge: 0 });
      return response;
    }
    return NextResponse.next();
  }

  if (isLoginPage) {
    const forceRelogin = request.nextUrl.searchParams.get("relogin") === "1";
    if (forceRelogin) {
      const response = NextResponse.next();
      response.cookies.set(AUTH_COOKIE, "", { path: "/", maxAge: 0 });
      return response;
    }
    return NextResponse.next();
  }

  if (!isAuthenticated) {
    const loginUrl = new URL(pathname.startsWith("/admin") ? "/admin/login" : "/login", request.url);
    if (pathname !== "/") {
      loginUrl.searchParams.set("from", pathname);
    }
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|api-proxy|api-long|api/collection-tasks).*)"],
};
