/**
 * Mock API for spec 012 (caller language), shaped by specs/012-caller-language/contracts. The
 * store is filled by `seedMockCallerLanguages(calls)`, which `seedMockCalls()` runs: mock call 1
 * (a phone call) switched to Hindi at 0:42 and saved it for the caller, mock call 4 started in the
 * caller's saved Spanish, and mock call 3 (a browser call) switched to Spanish without saving it.
 * Every other call stayed in the agent's language. `deleted` records each forget request so
 * tests can check what reached the server.
 */
import { http, HttpResponse, type JsonBodyType } from "msw";
import type { CallLanguage, CallerPreference, LanguageRef } from "../../api/callerLanguage";
import type { CallListItem } from "../../api/calls";
import { env } from "../../lib/env";

const url = (path: string) => `${env.apiBaseUrl}${path}`;
const json = <T>(body: T, status = 200) => HttpResponse.json(body as unknown as JsonBodyType, { status });
const problem = (status: number, code: string, detail: string) =>
  HttpResponse.json({ type: `https://callwright.dev/problems/${code.replace(/_/g, "-")}`, title: "Error", status, code, detail } as JsonBodyType, {
    status,
    headers: { "content-type": "application/problem+json" },
  });

const ENGLISH: LanguageRef = { code: "en-US", label: "English (US)" };
const HINDI: LanguageRef = { code: "hi", label: "Hindi" };
const SPANISH: LanguageRef = { code: "es", label: "Spanish" };

interface Row {
  call: CallListItem;
  started: LanguageRef;
  startedFrom: CallLanguage["started_from"];
  switches: CallLanguage["switches"];
}

interface Store {
  calls: Map<string, Row>;
  preferences: CallerPreference[];
  deleted: string[];
}
let store: Store = { calls: new Map(), preferences: [], deleted: [] };

export const mockCallerLanguages = () => store;

export function resetMockCallerLanguages() {
  store = { calls: new Map(), preferences: [], deleted: [] };
}

export const mockPreferenceId = (n: number) => `cpf_01JCPREF${String(n).padStart(18, "0")}`;

/** The number whose language is saved: the caller on inbound calls, the dialled number on outbound. */
function callerNumber(c: CallListItem): string | null {
  if (c.channel === "web") return null;
  return c.channel === "sip_outbound" ? (c.to_number ?? null) : (c.from_number ?? null);
}

const at = (iso: string, ms: number) => new Date(Date.parse(iso) + ms).toISOString();

export function seedMockCallerLanguages(calls: CallListItem[]) {
  resetMockCallerLanguages();
  for (const call of calls) store.calls.set(call.call_id, { call, started: ENGLISH, startedFrom: "agent", switches: [] });
  const row = (i: number) => (calls[i] ? store.calls.get(calls[i].call_id) : undefined);

  // Mock call 1: a phone caller switched to Hindi 42 seconds in; it was saved for their number.
  const switched = row(1);
  if (switched) {
    switched.switches = [{ offset_ms: 42_000, from: ENGLISH, to: HINDI }];
    const number = callerNumber(switched.call);
    if (number)
      store.preferences.push({
        id: mockPreferenceId(1),
        phone_number: number,
        language: HINDI,
        updated_at: at(switched.call.started_at, 42_000),
        last_call_id: switched.call.call_id,
      });
  }
  // Mock call 3: a browser test call switched to Spanish; browser calls never save a language.
  const web = row(3);
  if (web) web.switches = [{ offset_ms: 25_000, from: ENGLISH, to: SPANISH }];
  // Mock call 4: the caller's saved Spanish (from an older call) started this one.
  const saved = row(4);
  const number = saved && callerNumber(saved.call);
  if (saved && number) {
    saved.started = SPANISH;
    saved.startedFrom = "saved_preference";
    store.preferences.push({
      id: mockPreferenceId(4),
      phone_number: number,
      language: SPANISH,
      updated_at: at(saved.call.started_at, -6 * 86_400_000),
      last_call_id: null,
    });
  }
}

const preferenceFor = (number: string | null) => (number ? (store.preferences.find((p) => p.phone_number === number) ?? null) : null);

export const callerLanguageHandlers = [
  http.get(url("/calls/:id/language"), ({ params }) => {
    const row = store.calls.get(String(params.id));
    if (!row) return problem(404, "not_found", "No call with that id exists in this workspace.");
    const number = callerNumber(row.call);
    const body: CallLanguage = {
      call_id: row.call.call_id,
      agent_language: ENGLISH,
      started_language: row.started,
      started_from: row.startedFrom,
      switches: row.switches,
      caller_number: number,
      preference: preferenceFor(number),
    };
    return json(body);
  }),
  http.get(url("/caller-preferences"), ({ request }) => {
    const q = new URL(request.url).searchParams;
    const phone = q.get("phone_number");
    const rows = store.preferences
      .filter((p) => !phone || p.phone_number === phone)
      .sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at));
    const page = Number(q.get("page") ?? 1);
    const size = Number(q.get("page_size") ?? 50);
    return json({
      items: rows.slice((page - 1) * size, page * size),
      total: rows.length,
      page,
      page_size: size,
      total_pages: Math.ceil(rows.length / size),
    });
  }),
  http.delete(url("/caller-preferences/:id"), ({ params }) => {
    const id = String(params.id);
    store.deleted.push(id);
    if (!store.preferences.some((p) => p.id === id)) return problem(404, "not_found", "No saved language with that id exists in this workspace.");
    store.preferences = store.preferences.filter((p) => p.id !== id);
    return new HttpResponse(null, { status: 204 });
  }),
];
