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
