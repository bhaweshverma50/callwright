/**
 * Browser-direct streaming transcription with Deepgram (006 T081, research R7). The API mints a
 * listen-only token valid for at most 60 s; the socket authenticates with it as a WebSocket
 * subprotocol. Final segments are joined; `finish()` closes the stream and resolves with the text.
 */
import type { StreamCredential } from "../../../api/assistants";

export interface LiveTranscriber {
  send: (chunk: Blob) => void;
  finish: () => Promise<string>;
  close: () => void;
}

export function openDeepgramStream(credential: StreamCredential, onPartial?: (text: string) => void): Promise<LiveTranscriber> {
  return new Promise((resolve, reject) => {
    const protocols = credential.auth_scheme === "websocket_subprotocol_token" ? ["bearer", credential.token] : undefined;
    const ws = new WebSocket(credential.stream_url, protocols);
    const finals: string[] = [];
    let settle: ((text: string) => void) | null = null;
    const timer = window.setTimeout(() => reject(new Error("stream did not open")), 4000);
    ws.onopen = () => {
      window.clearTimeout(timer);
      resolve({
        send: (chunk) => ws.readyState === WebSocket.OPEN && ws.send(chunk),
        finish: () =>
          new Promise<string>((done) => {
            settle = done;
            if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "CloseStream" }));
            window.setTimeout(() => done(finals.join(" ").trim()), 2500);
          }),
        close: () => ws.close(),
      });
    };
    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(String(e.data)) as { channel?: { alternatives?: { transcript?: string }[] }; is_final?: boolean };
        const text = msg.channel?.alternatives?.[0]?.transcript ?? "";
        if (!text) return;
        if (msg.is_final) finals.push(text);
        onPartial?.([...finals, msg.is_final ? "" : text].join(" ").trim());
      } catch {
        /* metadata frames */
      }
    };
    ws.onerror = () => reject(new Error("stream failed"));
    ws.onclose = () => settle?.(finals.join(" ").trim());
  });
}
