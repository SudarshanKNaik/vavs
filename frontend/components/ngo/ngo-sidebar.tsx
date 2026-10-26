"use client";

import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import { LogOut } from "lucide-react";
import { cn } from "@/lib/utils";
import { useLocalAuth } from "@/lib/local-auth";

const navItems = [
  { href: "/ngo/dashboard", label: "Dashboard", exact: true },
  { href: "/ngo/patients", label: "Patients", exact: true },
  { href: "/ngo/patients/new", label: "Add Patient", exact: true },
  { href: "/ngo/patients/import", label: "Import CSV", exact: false },
];

export function NgoSidebar() {
  const pathname = usePathname();
  const { user, logout } = useLocalAuth();

  return (
    <aside className="fixed left-0 top-0 z-40 flex h-screen w-64 flex-col border-r border-sidebar-border bg-sidebar">
      <div className="flex h-16 items-center px-6">
        <Link href="/" className="flex items-center gap-2 font-serif text-2xl tracking-tight text-sidebar-foreground">
          <Image src="/assets/Clarus.png" alt="" width={32} height={32} />
          CareSync AI
        </Link>
      </div>

      <div className="mx-3 rounded-lg border border-sidebar-border px-3 py-2">
        <p className="text-[10px] uppercase tracking-wider text-muted-foreground">NGO Portal</p>
        <p className="truncate text-sm font-medium text-sidebar-foreground">{user?.ngo_name || "NGO"}</p>
      </div>

      <nav className="flex-1 space-y-1 px-3 py-4" aria-label="NGO navigation">
        {navItems.map((item) => {
          const isActive = item.exact
            ? pathname === item.href || (item.href === "/ngo/patients" && /^\/ngo\/patients\/(?!new|import)[^/]+$/.test(pathname))
            : pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={isActive ? "page" : undefined}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors",
                isActive
                  ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium border-l-2 border-sage"
                  : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
              )}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-sidebar-border px-3 py-4">
        <p className="truncate px-3 pb-2 text-xs text-muted-foreground">{user?.email}</p>
        <button
          onClick={() => logout({ logoutParams: { returnTo: "/ngo-signIn" } })}
          className="flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-sm text-destructive transition-colors hover:bg-destructive/10"
        >
          <LogOut className="size-4" />
          Sign Out
        </button>
      </div>
    </aside>
  );
}
