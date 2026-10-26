"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useLocalAuth } from "@/lib/local-auth";
import { ngoAccessDecision } from "@/lib/ngo-validation";
import { NgoSidebar } from "@/components/ngo/ngo-sidebar";

export default function NgoLayout({ children }: { children: React.ReactNode }) {
  const { isLoading, user, token } = useLocalAuth();
  const router = useRouter();
  const access = ngoAccessDecision(isLoading, user?.role, !!token);

  useEffect(() => {
    if (access === "signin") router.replace("/ngo-signIn");
    // Doctors/patients are sent back to their own portals.
    if (access === "forbidden") router.replace(user?.role === "patient" ? "/patient" : "/dashboard");
  }, [access, router, user?.role]);

  if (access !== "allow") {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-sm text-muted-foreground">Loading…</div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen">
      <NgoSidebar />
      <div className="flex flex-1 flex-col pl-64">
        <main className="flex-1 p-6">{children}</main>
      </div>
    </div>
  );
}
