"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Mic, MicOff, PhoneOff, Video, VideoOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { consultationSignalUrl, getConsultationIceServers } from "@/services/api";

type Role = "doctor" | "patient";
type Status = "idle" | "starting" | "waiting" | "connecting" | "connected" | "ended" | "error";

type Signal =
  | { type: "joined"; role: Role; peer_present: boolean }
  | { type: "peer-joined"; role: Role }
  | { type: "peer-left"; role: Role }
  | { type: "replaced" }
  | { type: "offer" | "answer"; sdp: RTCSessionDescriptionInit }
  | { type: "ice"; candidate: RTCIceCandidateInit }
  | { type: "hangup" }
  | { type: "media-state"; audio: boolean; video: boolean };

/**
 * 1:1 video call between the doctor and the patient, browser to browser
 * (WebRTC). Our backend only relays the connection setup, so there's no
 * third-party sign-in and audio/video never pass through our servers.
 */
export function VideoCall({ appointmentId, role, actorId }: { appointmentId: string; role: Role; actorId: string }) {
  const otherLabel = role === "doctor" ? "patient" : "doctor";
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [micOn, setMicOn] = useState(true);
  const [camOn, setCamOn] = useState(true);
  const [remoteMedia, setRemoteMedia] = useState({ audio: true, video: true });

  const localVideoRef = useRef<HTMLVideoElement>(null);
  const remoteVideoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const iceServersRef = useRef<RTCIceServer[]>([]);
  const pendingIceRef = useRef<RTCIceCandidateInit[]>([]);
  const leavingRef = useRef(false);

  const send = useCallback((message: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(JSON.stringify(message));
  }, []);

  const closePeer = useCallback(() => {
    pcRef.current?.close();
    pcRef.current = null;
    pendingIceRef.current = [];
    if (remoteVideoRef.current) remoteVideoRef.current.srcObject = null;
  }, []);

  const createPeer = useCallback(() => {
    closePeer();
    const pc = new RTCPeerConnection({ iceServers: iceServersRef.current });
    streamRef.current?.getTracks().forEach((track) => pc.addTrack(track, streamRef.current as MediaStream));
    pc.ontrack = (event) => {
      if (remoteVideoRef.current && event.streams[0]) remoteVideoRef.current.srcObject = event.streams[0];
    };
    pc.onicecandidate = (event) => {
      if (event.candidate) send({ type: "ice", candidate: event.candidate.toJSON() });
    };
    pc.onconnectionstatechange = () => {
      if (pc !== pcRef.current) return;
      if (pc.connectionState === "connected") {
        setStatus("connected");
        setError(null);
      } else if (pc.connectionState === "failed") {
        setStatus("error");
        setError(
          "Couldn't connect directly to the other person. Their network or yours may block video calls; try another network (e.g. mobile data).",
        );
      }
    };
    pcRef.current = pc;
    return pc;
  }, [closePeer, send]);

  const flushPendingIce = useCallback(async () => {
    const pc = pcRef.current;
    if (!pc) return;
    for (const candidate of pendingIceRef.current.splice(0)) {
      await pc.addIceCandidate(candidate).catch(() => undefined);
    }
  }, []);

  const handleSignal = useCallback(
    async (msg: Signal) => {
      switch (msg.type) {
        case "joined":
          // If the other person is already here, they send us an offer.
          setStatus(msg.peer_present ? "connecting" : "waiting");
          break;
        case "peer-joined": {
          // We were waiting: start the connection.
          setStatus("connecting");
          const pc = createPeer();
          const offer = await pc.createOffer();
          await pc.setLocalDescription(offer);
          send({ type: "offer", sdp: pc.localDescription });
          break;
        }
        case "offer": {
          setStatus("connecting");
          const pc = createPeer();
          await pc.setRemoteDescription(msg.sdp);
          await flushPendingIce();
          const answer = await pc.createAnswer();
          await pc.setLocalDescription(answer);
          send({ type: "answer", sdp: pc.localDescription });
          break;
        }
        case "answer":
          if (pcRef.current) {
            await pcRef.current.setRemoteDescription(msg.sdp);
            await flushPendingIce();
          }
          break;
        case "ice":
          if (pcRef.current?.remoteDescription) {
            await pcRef.current.addIceCandidate(msg.candidate).catch(() => undefined);
          } else {
            pendingIceRef.current.push(msg.candidate);
          }
          break;
        case "media-state":
          setRemoteMedia({ audio: msg.audio, video: msg.video });
          break;
        case "peer-left":
        case "hangup":
          closePeer();
          setRemoteMedia({ audio: true, video: true });
          setStatus("waiting");
          break;
        case "replaced":
          leavingRef.current = true;
          setStatus("ended");
          setError("This call was opened in another tab or window.");
          break;
      }
    },
    [closePeer, createPeer, flushPendingIce, send],
  );

  const stopEverything = useCallback(() => {
    closePeer();
    wsRef.current?.close();
    wsRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (localVideoRef.current) localVideoRef.current.srcObject = null;
  }, [closePeer]);

  const join = useCallback(async () => {
    setError(null);
    setStatus("starting");
    leavingRef.current = false;
    let stream: MediaStream;
    try {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
      } catch {
        // No camera (or camera blocked): join with audio only.
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        setCamOn(false);
      }
    } catch (err) {
      console.error("Video call: camera/microphone unavailable", err);
      setStatus("error");
      setError("Camera and microphone access is needed for the video call. Allow it in your browser and try again.");
      return;
    }

    try {
      streamRef.current = stream;
      if (localVideoRef.current) localVideoRef.current.srcObject = stream;
      iceServersRef.current = await getConsultationIceServers();

      const ws = new WebSocket(consultationSignalUrl(appointmentId, role, actorId));
      wsRef.current = ws;
      ws.onmessage = (event) => {
        try {
          void handleSignal(JSON.parse(event.data) as Signal);
        } catch {
          // ignore malformed messages
        }
      };
      ws.onclose = (event) => {
        if (leavingRef.current || wsRef.current !== ws) return;
        stopEverything();
        setStatus("error");
        setError(
          event.code === 4403
            ? event.reason || "You don't have access to this consultation."
            : "Lost connection to the server. Rejoin to continue.",
        );
      };
    } catch (err) {
      console.error("Video call: could not start", err);
      stopEverything();
      setStatus("error");
      setError("Couldn't start the video call. Check your connection and try again.");
    }
  }, [actorId, appointmentId, handleSignal, role, stopEverything]);

  const leave = useCallback(() => {
    leavingRef.current = true;
    send({ type: "hangup" });
    stopEverything();
    setStatus("ended");
  }, [send, stopEverything]);

  const toggleMic = () => {
    const next = !micOn;
    streamRef.current?.getAudioTracks().forEach((t) => (t.enabled = next));
    setMicOn(next);
    send({ type: "media-state", audio: next, video: camOn });
  };

  const toggleCam = () => {
    const tracks = streamRef.current?.getVideoTracks() || [];
    if (tracks.length === 0) return;
    const next = !camOn;
    tracks.forEach((t) => (t.enabled = next));
    setCamOn(next);
    send({ type: "media-state", audio: micOn, video: next });
  };

  // Hang up cleanly when the page is closed or left.
  useEffect(() => {
    const onUnload = () => send({ type: "hangup" });
    window.addEventListener("beforeunload", onUnload);
    return () => {
      window.removeEventListener("beforeunload", onUnload);
      leavingRef.current = true;
      stopEverything();
    };
  }, [send, stopEverything]);

  const inCall = status === "waiting" || status === "connecting" || status === "connected";
  const statusText: Record<Status, string> = {
    idle: "",
    starting: "Starting your camera…",
    waiting: `Waiting for the ${otherLabel} to join…`,
    connecting: `Connecting to the ${otherLabel}…`,
    connected: "Connected",
    ended: "You left the call.",
    error: "",
  };

  return (
    <div className="space-y-3">
      <div className="relative overflow-hidden rounded-xl border border-border bg-neutral-900">
        <video ref={remoteVideoRef} autoPlay playsInline className={`aspect-video w-full object-cover ${status === "connected" ? "" : "invisible"}`} />
        {status !== "connected" && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center text-sm text-neutral-200">
            {status === "idle" || status === "ended" || status === "error" ? (
              <>
                {error ? <p className="max-w-md text-red-300">{error}</p> : status === "ended" ? <p>{statusText.ended}</p> : (
                  <p>Your camera and microphone are only turned on when you join.</p>
                )}
                <Button onClick={() => void join()}>
                  <Video className="size-4" />
                  {status === "idle" ? "Join video call" : "Rejoin"}
                </Button>
              </>
            ) : (
              <p className="inline-flex items-center gap-2">
                <Loader2 className="size-4 animate-spin" />
                {statusText[status]}
              </p>
            )}
          </div>
        )}
        {status === "connected" && !remoteMedia.video && (
          <div className="absolute inset-0 flex items-center justify-center bg-neutral-900 text-sm text-neutral-300">
            The {otherLabel} turned their camera off
          </div>
        )}
        {status === "connected" && !remoteMedia.audio && (
          <span className="absolute left-3 top-3 inline-flex items-center gap-1 rounded-full bg-black/60 px-2 py-1 text-[11px] text-white">
            <MicOff className="size-3" /> {otherLabel} muted
          </span>
        )}
        <video
          ref={localVideoRef}
          autoPlay
          playsInline
          muted
          className={`absolute bottom-3 right-3 aspect-video w-32 rounded-lg border border-white/30 bg-neutral-800 object-cover shadow-lg sm:w-44 ${
            inCall && camOn ? "" : "hidden"
          }`}
        />
      </div>

      {inCall && (
        <div className="flex items-center justify-center gap-2">
          <Button variant="outline" size="sm" onClick={toggleMic} aria-pressed={!micOn} title={micOn ? "Mute" : "Unmute"}>
            {micOn ? <Mic className="size-4" /> : <MicOff className="size-4 text-destructive" />}
            {micOn ? "Mute" : "Unmute"}
          </Button>
          <Button variant="outline" size="sm" onClick={toggleCam} aria-pressed={!camOn} title={camOn ? "Turn camera off" : "Turn camera on"}>
            {camOn ? <Video className="size-4" /> : <VideoOff className="size-4 text-destructive" />}
            {camOn ? "Camera off" : "Camera on"}
          </Button>
          <Button size="sm" onClick={leave} className="bg-destructive text-white hover:bg-destructive/90">
            <PhoneOff className="size-4" />
            Leave
          </Button>
        </div>
      )}
    </div>
  );
}
