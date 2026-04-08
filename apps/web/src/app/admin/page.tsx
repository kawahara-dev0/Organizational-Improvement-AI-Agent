"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

export default function AdminRootPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/admin/proposals");
  }, [router]);
  return null;
}
