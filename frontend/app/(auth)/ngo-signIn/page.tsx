"use client";

import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useLocalAuth } from "@/lib/local-auth";
import { ngoLogin } from "@/services/ngo-api";
import { Button } from "@/components/ui/button";

export default function NgoSignIn() {
  const { startSession, isLoading } = useLocalAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      startSession(await ngoLogin(email, password));
      router.push("/ngo/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setSubmitting(false);
    }
  };

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Loading...</p>;
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">NGO Login</h1>
        <p className="text-sm text-muted-foreground">Sign in to your NGO portal account.</p>
      </div>

      <label className="block">
        <span className="mb-1 block text-xs font-medium text-muted-foreground">Email</span>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="username"
          required
          className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
        />
      </label>
      <label className="block">
        <span className="mb-1 block text-xs font-medium text-muted-foreground">Password</span>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          required
          className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
        />
      </label>

      {error && <p role="alert" className="text-xs text-destructive">{error}</p>}

      <Button type="submit" disabled={submitting}>
        {submitting ? "Logging in..." : "Login"}
      </Button>

      <p className="text-xs text-muted-foreground">
        New NGO? <Link href="/ngo-signUp" className="underline">Register your NGO</Link>
      </p>
    </form>
  );
}
