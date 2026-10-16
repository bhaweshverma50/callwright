/**
 * Mock audio for voice and ambient previews: a short, soft two-note phrase rendered as an 8 kHz
 * mono WAV data URI. Each seed gets its own pitch so previews are distinguishable. Real previews
 * come from the vendor (voices) or signed storage URLs (uploads).
 */
const cache = new Map<number, string>();

export function chimeDataUri(seed: number): string {
  const hit = cache.get(seed);
  if (hit) return hit;
  const rate = 8000;
  const seconds = 0.9;
  const n = Math.round(rate * seconds);
  const base = 220 * Math.pow(2, (seed % 7) / 12);
  const bytes = new Uint8Array(44 + n);
  const view = new DataView(bytes.buffer);
  const text = (o: number, s: string) => [...s].forEach((c, i) => view.setUint8(o + i, c.charCodeAt(0)));
  text(0, "RIFF");
  view.setUint32(4, 36 + n, true);
  text(8, "WAVE");
  text(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, rate, true);
  view.setUint32(28, rate, true);
  view.setUint16(32, 1, true);
  view.setUint16(34, 8, true);
  text(36, "data");
  view.setUint32(40, n, true);
  for (let i = 0; i < n; i++) {
    const t = i / rate;
    const f = t < seconds / 2 ? base : base * 1.25;
    const local = t < seconds / 2 ? t : t - seconds / 2;
    const env = Math.min(1, local * 40) * Math.exp(-local * 6);
    const v = Math.sin(2 * Math.PI * f * t) * 0.6 + Math.sin(4 * Math.PI * f * t) * 0.15;
    bytes[44 + i] = Math.round(128 + 70 * env * v);
  }
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]!);
  const uri = `data:audio/wav;base64,${btoa(bin)}`;
  cache.set(seed, uri);
  return uri;
}
