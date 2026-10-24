"use client";

import { LocalAuthProvider } from "@/lib/local-auth";

export default function LocalAuthProviderWrapper({
  children,
}: {
  children: React.ReactNode;
}) {
  return <LocalAuthProvider>{children}</LocalAuthProvider>;
}
