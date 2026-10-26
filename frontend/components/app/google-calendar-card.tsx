"use client";

import { useCallback, useEffect, useState } from "react";
import { CalendarCheck, CalendarDays, Loader2, Unplug } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  disconnectGoogleCalendar,
  getGoogleCalendarStatus,
  startGoogleCalendarConnect,
  type GoogleCalendarStatus,
} from "@/services/api";

/** Settings card: connect the doctor's Google Calendar with OAuth. */
export function GoogleCalendarCard({ doctorId }: { doctorId?: string }) {
  const [status, setStatus] = useState<GoogleCalendarStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const load = useCallback(async () => {
    if (!doctorId) return;
    try {
      setStatus(await getGoogleCalendarStatus(doctorId));
    } catch (err) {
      setMessage({ type: "error", text: err instanceof Error ? err.message : "Could not load status." });
    }
  }, [doctorId]);

  useEffect(() => {
    load();
    // Result of the Google redirect (?google=connected|error&message=...).
    const params = new URLSearchParams(window.location.search);
    const result = params.get("google");
    if (result === "connected") {
      setMessage({ type: "success", text: "Google Calendar connected. Upcoming appointments are being added to it." });
    } else if (result === "error") {
      setMessage({ type: "error", text: params.get("message") || "Google Calendar connection failed." });
    }
    if (result) window.history.replaceState(null, "", "/settings");
  }, [load]);

  const connect = async () => {
    if (!doctorId) return;
    setBusy(true);
    setMessage(null);
    try {
      const { auth_url } = await startGoogleCalendarConnect(doctorId);
      window.location.href = auth_url;
    } catch (err) {
      setMessage({ type: "error", text: err instanceof Error ? err.message : "Could not start Google sign-in." });
      setBusy(false);
    }
  };

  const disconnect = async () => {
    if (!doctorId || !window.confirm("Disconnect Google Calendar? Existing events stay in your calendar; new bookings won't be added.")) return;
    setBusy(true);
    setMessage(null);
    try {
      await disconnectGoogleCalendar(doctorId);
      setMessage({ type: "success", text: "Google Calendar disconnected." });
      await load();
    } catch (err) {
      setMessage({ type: "error", text: err instanceof Error ? err.message : "Could not disconnect." });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-xl border border-border bg-card">
      <div className="border-b border-border px-5 py-4">
        <h3 className="text-sm font-semibold">Google Calendar</h3>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Bookings, reschedules and cancellations appear in your calendar, and times you&apos;re busy there
          aren&apos;t offered to patients or the call agent.
        </p>
      </div>
      <div className="space-y-3 p-5">
        {!status ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />Checking connection…
          </div>
        ) : status.connected ? (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <CalendarCheck className="size-5 text-success" />
              <div>
                <p className="text-sm font-medium">Connected{status.google_email ? ` as ${status.google_email}` : ""}</p>
                {status.last_error ? (
                  <p className="text-xs text-destructive">Last sync problem: {status.last_error}</p>
                ) : (
                  <p className="text-xs text-muted-foreground">Syncing to your primary calendar.</p>
                )}
              </div>
            </div>
            <Button variant="outline" onClick={disconnect} disabled={busy}>
              {busy ? <Loader2 className="size-4 animate-spin" /> : <Unplug className="size-4" />}
              Disconnect
            </Button>
          </div>
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-muted-foreground">
              {status.oauth_configured
                ? "Not connected."
                : "Google sign-in isn't configured on the server yet (GOOGLE_OAUTH_CLIENT_SECRET is missing)."}
            </p>
            <Button onClick={connect} disabled={busy || !status.oauth_configured || !doctorId}>
              {busy ? <Loader2 className="size-4 animate-spin" /> : <CalendarDays className="size-4" />}
              Connect Google Calendar
            </Button>
          </div>
        )}
        {message && (
          <p className={`text-xs ${message.type === "success" ? "text-success" : "text-destructive"}`}>{message.text}</p>
        )}
      </div>
    </div>
  );
}
