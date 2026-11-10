/**
 * The real driver for `WebCallPanel`: microphone precheck, `POST /v1/sessions/web-call`, then a
 * LiveKit room (research R17). `livekit-client` loads on first use so pages that only show the
 * panel never pay for it.
 */
import { startDemoCall, startWebCall } from "../api/calls";
import { publishRoomData, ROOM_TOPICS } from "./roomData";
import { DTMF_CODES, type AgentActivity, type MicCheck, type WebCallDriver } from "./webCall";
import { type Latency } from "../components";

const AGENT_JOIN_TIMEOUT_MS = 20_000;

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

/**
 * One latency message from the voice worker (worker/metrics.py `latency_payload`):
 * `{turn_index, stt_ms, llm_ms, tts_ms, e2e_ms?}`. It names no transcript segment, so the chip goes
 * on the latest agent turn. Null for anything malformed.
 */
export function parseLatencyMessage(payload: Uint8Array): Latency | null {
  try {
    const m = JSON.parse(new TextDecoder().decode(payload)) as Record<string, unknown>;
    const ms = (v: unknown) => (typeof v === "number" && Number.isFinite(v) && v >= 0 ? Math.round(v) : null);
    const stt = ms(m.stt_ms);
    const llm = ms(m.llm_ms);
    const tts = ms(m.tts_ms);
    if (stt === null || llm === null || tts === null || stt + llm + tts === 0) return null;
    return { stt, llm, tts };
  } catch {
    return null;
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
  return liveDriver((req, key) => startWebCall({ ...req, version: req.version ?? "draft" }, key));
}

/** The home page playground: no account, the demo agent of one scenario (`POST /v1/public/demo-calls`). */
export function createDemoDriver(scenario: string): WebCallDriver {
  return liveDriver(() => startDemoCall(scenario));
}

function liveDriver(createSession: WebCallDriver["createSession"]): WebCallDriver {
  return {
    simulated: false,
    checkMicrophone,
    createSession,
    async connect(session, listener) {
      const lk = await import("livekit-client");
      const room = new lk.Room({ adaptiveStream: true, dynacast: true });
      const audioEls: HTMLMediaElement[] = [];
      const segments = new Map<string, string>();
      let hungUp = false;
      const timer: { level?: ReturnType<typeof setInterval>; agentJoin?: ReturnType<typeof setTimeout> } = {};

      const finish = (reason: "user_hangup" | "agent_hangup" | "connection_lost") => {
        if (hungUp) return;
        hungUp = true;
        if (timer.level) clearInterval(timer.level);
        if (timer.agentJoin) clearTimeout(timer.agentJoin);
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
        })().catch((e: unknown) => console.warn("A transcript stream ended early.", e));
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
        if (topic === ROOM_TOPICS.latency) {
          const latency = parseLatencyMessage(payload);
          if (latency) listener.latency(null, latency);
        }
        // Every topic also reaches onRoomData listeners (the flow builder's node highlight).
        publishRoomData(topic, payload);
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
      // The call is live once the room is joined. Publishing the microphone negotiates with the
      // server and can take seconds, so it runs alongside; a failure ends the call.
      room.localParticipant.setMicrophoneEnabled(true).catch(() => {
        finish("connection_lost");
        void room.disconnect();
      });
      // Autoplay may be blocked until the next click; the call still runs and audio starts then.
      void room.startAudio().catch((e: unknown) => console.warn("Call audio is waiting for a click to start.", e));
      const initial = agent()?.attributes["lk.agent.state"];
      listener.activity(initial ? (ACTIVITY[initial] ?? "listening") : "joining");

      // The agent normally joins before the caller. A call the worker refused or failed leaves an
      // empty room, so give up instead of waiting for an agent that never comes.
      if (!agent()) {
        timer.agentJoin = setTimeout(() => {
          if (agent()) return;
          finish("connection_lost");
          void room.disconnect();
        }, AGENT_JOIN_TIMEOUT_MS);
      }

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
        async sendDigit(d) {
          const code = DTMF_CODES[d];
          if (code !== undefined) await room.localParticipant.publishDtmf(code, d);
        },
      };
    },
  };
}
