// 文件说明：前端页面路由入口；当前文件：page
"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function LinkImportRedirectPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/collection-tasks?create=link_import");
  }, [router]);

  return null;
}
