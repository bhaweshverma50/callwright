/**
 * The real driver for `WebCallPanel`: microphone precheck, `POST /v1/sessions/web-call`, then a
 * LiveKit room (research R17). `livekit-client` loads on first use so pages that only show the
 * panel never pay for it.
 */
import { api, unwrap } from "../api/client";
import type { Latency } from "./signal";
import { LATENCY_TOPIC, type AgentActivity, type MicCheck, type WebCallDriver } from "./webCall";

/** Confirms microphone access without creating anything server side (FR-047). */
export async function checkMicrophone(): Promise<MicCheck> {
  const md = typeof navigator === "undefined" ? undefined : navigator.mediaDevices;
  if (!md?.getUserMedia) return "unavailable";
  try {
    const status = await navigator.permissions?.query({ name: "microphone" as PermissionName });
    if (status?.state === "denied") return "denied";
  } catch {
    /* Permissions API without microphone support: fall through to the prompt. */
  }
  try {
    const stream = await md.getUserMedia({ audio: true });
    // LiveKit opens its own track after joining; the grant is remembered, so it does not prompt again.
    stream.getTracks().forEach((t) => t.stop());
    return "granted";
  } catch (e) {
    const name = e instanceof DOMException ? e.name : "";
    return name === "NotAllowedError" || name === "SecurityError" ? "denied" : "unavailable";
  }
}

const ACTIVITY: Record<string, AgentActivity> = {
  initializing: "joining",
  listening: "listening",
  idle: "listening",
  thinking: "thinking",
  speaking: "speaking",
};

export function createLiveDriver(): WebCallDriver {
  return {
    simulated: false,
    checkMicrophone,
    async createSession(req, idempotencyKey) {
      const body = { ...req, version: req.version ?? "draft" };
      return unwrap(api.POST("/sessions/web-call", { params: { header: { "Idempotency-Key": idempotencyKey } }, body }));
    },
    async connect(session, listener) {
      const lk = await import("livekit-client");
      const room = new lk.Room({ adaptiveStream: true, dynacast: true });
      const audioEls: HTMLMediaElement[] = [];
      const segments = new Map<string, string>();
      let hungUp = false;
      const timer: { level?: ReturnType<typeof setInterval> } = {};

      const finish = (reason: "user_hangup" | "agent_hangup" | "connection_lost") => {
        if (hungUp) return;
        hungUp = true;
        if (timer.level) clearInterval(timer.level);
        audioEls.forEach((el) => el.remove());
        room.unregisterTextStreamHandler("lk.transcription");
        listener.ended(reason);
      };

      const agent = () => [...room.remoteParticipants.values()].find((p) => p.isAgent);

      room.registerTextStreamHandler("lk.transcription", (reader, from) => {
        const attrs = reader.info.attributes ?? {};
        const id = attrs["lk.segment_id"] ?? reader.info.id;
        const micSid = room.localParticipant.getTrackPublication(lk.Track.Source.Microphone)?.trackSid;
        const fromCaller = from.identity === room.localParticipant.identity || (micSid !== undefined && attrs["lk.transcribed_track_id"] === micSid);
        const who = fromCaller ? "caller" : "agent";
        void (async () => {
          // Each stream carries one segment: interim caller updates arrive as new streams with the
          // same segment id, agent speech as deltas within one stream.
          let text = "";
          for await (const chunk of reader) {
            text += chunk;
            segments.set(id, text);
            listener.turn({ id, who, text, final: false });
          }
          listener.turn({ id, who, text: segments.get(id) ?? text, final: who === "agent" || attrs["lk.transcription_final"] === "true" });
        })().catch(() => {});
      });

      room.on(lk.RoomEvent.TrackSubscribed, (track) => {
        if (track.kind !== lk.Track.Kind.Audio) return;
        const el = track.attach();
        el.hidden = true;
        document.body.appendChild(el);
        audioEls.push(el);
      });
      room.on(lk.RoomEvent.ParticipantAttributesChanged, (changed, p) => {
        const state = changed["lk.agent.state"];
        if (p.isAgent && state) listener.activity(ACTIVITY[state] ?? "listening");
      });
      room.on(lk.RoomEvent.DataReceived, (payload, _p, _kind, topic) => {
        if (topic !== LATENCY_TOPIC) return;
        try {
          const m = JSON.parse(new TextDecoder().decode(payload)) as { segment_id?: string; stt_ms: number; llm_ms: number; tts_ms: number };
          const l: Latency = { stt: Math.round(m.stt_ms), llm: Math.round(m.llm_ms), tts: Math.round(m.tts_ms) };
          listener.latency(m.segment_id ?? null, l);
        } catch {
          /* ignore malformed metrics */
        }
      });
      room.on(lk.RoomEvent.ParticipantDisconnected, (p) => {
        if (!p.isAgent) return;
        finish("agent_hangup");
        void room.disconnect();
      });
      room.on(lk.RoomEvent.Disconnected, (reason) => {
        finish(reason === lk.DisconnectReason.CLIENT_INITIATED ? "user_hangup" : "connection_lost");
      });

      await room.connect(session.server_url, session.participant_token);
      await room.localParticipant.setMicrophoneEnabled(true);
      await room.startAudio().catch(() => {});
      const initial = agent()?.attributes["lk.agent.state"];
      listener.activity(initial ? (ACTIVITY[initial] ?? "listening") : "joining");

      timer.level = setInterval(() => {
        listener.levels({ caller: room.localParticipant.audioLevel, agent: agent()?.audioLevel ?? 0 });
      }, 100);

      return {
        async setMuted(m) {
          await room.localParticipant.setMicrophoneEnabled(!m);
        },
        async hangUp() {
          await room.disconnect();
          finish("user_hangup");
        },
      };
    },
  };
}
