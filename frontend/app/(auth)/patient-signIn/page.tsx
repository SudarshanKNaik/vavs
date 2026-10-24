"use client";

import Link from "next/link";
import { useLocalAuth } from "@/lib/local-auth";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";

export default function PatientSignInPage() {
  const { loginWithPassword, isLoading } = useLocalAuth();
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
      await loginWithPassword({ role: "patient", email, password });
      router.push("/patient");
    } catch (err) {
      const text = err instanceof Error ? err.message : "Login failed";
      setError(text.replace(/^\{"detail":"|"\}$/g, ""));
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
        <h1 className="text-xl font-semibold">Patient Login</h1>
        <p className="text-sm text-muted-foreground">Use your email and password.</p>
      </div>

      <input
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="Email"
        required
        className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
      />
      <input
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        placeholder="Password"
        required
        className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
      />

      {error && <p className="text-xs text-destructive">{error}</p>}

      <Button type="submit" disabled={submitting}>
        {submitting ? "Logging in..." : "Login"}
      </Button>

      <p className="text-xs text-muted-foreground">
        No account? <Link href="/patient-signUp" className="underline">Create patient account</Link>
      </p>
    </form>
  );
}
