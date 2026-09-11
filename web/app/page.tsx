"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { homePathForRole, useSession } from "@/lib/session";
import { PulseLoader } from "@/components/PulseLoader";

/** Sends each role to the landing page that belongs to it. */
export default function RootPage() {
  const { session, loading } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    router.replace(session ? homePathForRole(session.user.role) : "/login");
  }, [session, loading, router]);

  return <PulseLoader />;
}
