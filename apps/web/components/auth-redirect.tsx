"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { UNAUTHENTICATED_EVENT } from "@/lib/api";

/** Sends the user to /login when any API call reports 401 (session missing or expired). */
export function AuthRedirect() {
  const router = useRouter();
  const path = usePathname();
  useEffect(() => {
    const onUnauthenticated = () => {
      if (!path.startsWith("/login")) router.replace(`/login?next=${encodeURIComponent(path)}`);
    };
    window.addEventListener(UNAUTHENTICATED_EVENT, onUnauthenticated);
    return () => window.removeEventListener(UNAUTHENTICATED_EVENT, onUnauthenticated);
  }, [router, path]);
  return null;
}
