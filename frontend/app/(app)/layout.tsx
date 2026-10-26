"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useLocalAuth } from "@/lib/local-auth";
import { Sidebar } from "@/components/app/sidebar";
import { Topbar } from "@/components/app/topbar";

export default function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { isLoading, isAuthenticated, user } = useLocalAuth();
  const router = useRouter();
  const isNgoUser = user?.role === "ngo";

  // NGO accounts have their own portal and no doctor privileges.
  useEffect(() => {
    if (isNgoUser) router.replace("/ngo/dashboard");
  }, [isNgoUser, router]);

  if (isLoading || isNgoUser) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-sm text-muted-foreground">Loading…</div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <div className="flex flex-1 flex-col pl-64">
        <Topbar />
        <main className="flex-1 p-6">{children}</main>
      </div>
    </div>
  );
}
