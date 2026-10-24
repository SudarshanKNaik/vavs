"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocalAuth } from "@/lib/local-auth";
import {
  createConsultationMessage,
  getOrCreateConsultationRoom,
  listConsultationMessages,
  type ConsultationMessage,
  type ConsultationRoom,
} from "@/services/api";
import { Button } from "@/components/ui/button";
import { Loader2, MessageCircleMore } from "lucide-react";

function formatDateTime(value: string) {
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return value;
  return dt.toLocaleString();
}

export default function ConsultationChatPage() {
  const params = useParams<{ appointmentId: string }>();
  const appointmentId = params?.appointmentId || "";

  const { user, isLoading, isAuthenticated } = useLocalAuth();

  const actorRole = useMemo(() => {
    if (user?.role === "doctor") return "doctor" as const;
    return "patient" as const;
  }, [user?.role]);
  const actorId = user?.sub || "";

  const [room, setRoom] = useState<ConsultationRoom | null>(null);
  const [messages, setMessages] = useState<ConsultationMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [statusText, setStatusText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadMessages = useCallback(async () => {
    if (!appointmentId || !actorId) return;
    const rows = await listConsultationMessages(appointmentId, actorRole, actorId);
    setMessages(Array.isArray(rows) ? rows : []);
  }, [actorId, actorRole, appointmentId]);

  useEffect(() => {
    if (!isAuthenticated || !appointmentId || !actorId) {
      setLoading(false);
      return;
    }

    let active = true;

    (async () => {
      setLoading(true);
      setError(null);
      try {
        const roomRow = await getOrCreateConsultationRoom(appointmentId, {
          actor_role: actorRole,
          actor_id: actorId,
          provider: "daily",
        });
        if (!active) return;
        setRoom(roomRow);

        const initialMessages = await listConsultationMessages(appointmentId, actorRole, actorId);
        if (!active) return;
        setMessages(Array.isArray(initialMessages) ? initialMessages : []);
      } catch (err) {
        if (!active) return;
        const text = err instanceof Error ? err.message : "Failed to load consultation chat.";
        setError(text);
      } finally {
        if (active) setLoading(false);
      }
    })();

    return () => {
      active = false;
    };
  }, [actorId, actorRole, appointmentId, isAuthenticated]);

  useEffect(() => {
    if (!isAuthenticated || !appointmentId || !actorId) return;

    const timer = setInterval(() => {
      loadMessages().catch(() => {
        // Keep polling resilient; visible errors are shown on explicit actions.
      });
    }, 3000);

    return () => clearInterval(timer);
  }, [actorId, appointmentId, isAuthenticated, loadMessages]);

  const handleSend = useCallback(async () => {
    const text = draft.trim();
    if (!text || !appointmentId || !actorId) return;

    setSending(true);
    setError(null);
    setStatusText(null);
    try {
      const created = await createConsultationMessage(appointmentId, {
        actor_role: actorRole,
        actor_id: actorId,
        message: text,
      });
      setMessages((prev) => [...prev, created]);
      setDraft("");
      setStatusText("Message sent.");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to send message.";
      setError(msg);
    } finally {
      setSending(false);
    }
  }, [actorId, actorRole, appointmentId, draft]);

  if (isLoading || loading) {
    return (
      <div className="mx-auto flex min-h-screen max-w-5xl items-center justify-center px-6">
        <div className="inline-flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          Preparing consultation chat...
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className="mx-auto flex min-h-screen max-w-4xl items-center justify-center px-6">
        <div className="rounded-xl border border-border bg-card p-8 text-center">
          <h1 className="text-xl font-semibold">Consultation Chat</h1>
          <p className="mt-2 text-sm text-muted-foreground">Please sign in to access this consultation room.</p>
          <div className="mt-4">
            <Link href="/patient-signIn"><Button>Go to Login</Button></Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto min-h-screen max-w-5xl px-6 py-8">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Consultation</p>
          <h1 className="mt-1 text-2xl font-semibold">
            {room?.room_url ? "Appointment Video Call" : "Appointment Chat Room"}
          </h1>
          <p className="mt-1 text-xs text-muted-foreground">
            Appointment: {appointmentId} {room ? `· Room: ${room.room_name}` : ""}
          </p>
        </div>
        <Link href={actorRole === "doctor" ? "/appointments" : "/patient"}>
          <Button variant="outline">Back</Button>
        </Link>
      </div>

      <section className="rounded-2xl border border-border bg-card shadow-sm">
        {room?.room_url && (
          <div className="border-b border-border p-4">
            <div className="mb-2 flex items-center justify-between gap-2">
              <p className="text-sm font-medium">Video Consultation</p>
              <a
                href={room.room_url}
                target="_blank"
                rel="noreferrer"
                className="text-xs text-primary hover:underline"
              >
                Open in new tab
              </a>
            </div>
            <div className="overflow-hidden rounded-xl border border-border bg-muted/20">
              <iframe
                src={room.room_url}
                title="Consultation video call"
                allow="camera; microphone; display-capture; fullscreen"
                className="h-[380px] w-full"
              />
            </div>
          </div>
        )}

        <div className="flex items-center gap-2 border-b border-border px-4 py-3">
          <MessageCircleMore className="size-4 text-primary" />
          <p className="text-sm font-medium">Live Chat</p>
          <span className="ml-auto rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
            {messages.length} message{messages.length === 1 ? "" : "s"}
          </span>
        </div>

        <div className="max-h-[52vh] min-h-[42vh] space-y-3 overflow-y-auto bg-gradient-to-b from-background to-muted/20 p-4">
          {messages.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
              No messages yet. Start the consultation by sending the first message.
            </div>
          ) : (
            messages.map((msg) => {
              const mine = msg.sender_type === actorRole;
              return (
                <div key={msg.id} className={`flex ${mine ? "justify-end" : "justify-start"}`}>
                  <div
                    className={`max-w-[82%] rounded-2xl px-3 py-2 text-sm shadow-sm ${
                      mine
                        ? "bg-primary text-primary-foreground"
                        : "border border-border bg-background text-foreground"
                    }`}
                  >
                    <p className="text-[11px] opacity-80">
                      {msg.sender_type === "doctor" ? "Doctor" : msg.sender_type === "patient" ? "Patient" : "System"}
                    </p>
                    <p className="mt-1 whitespace-pre-wrap">{msg.message}</p>
                    <p className="mt-1 text-[10px] opacity-70">{formatDateTime(msg.created_at)}</p>
                  </div>
                </div>
              );
            })
          )}
        </div>

        <div className="border-t border-border bg-background/70 p-4">
          <div className="flex gap-2">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Type your message..."
              rows={2}
              className="w-full resize-none rounded-xl border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
            />
            <Button disabled={sending || !draft.trim()} onClick={() => void handleSend()}>
              {sending ? "Sending..." : "Send"}
            </Button>
          </div>
          {statusText && <p className="mt-2 text-xs text-emerald-600">{statusText}</p>}
          {error && <p className="mt-2 text-xs text-destructive">{error}</p>}
        </div>
      </section>
    </div>
  );
}
