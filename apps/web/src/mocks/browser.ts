import { setupWorker } from "msw/browser";
import { seedMockCalls, seedMockLiveCalls } from "./calls/handlers";
import { enablePersistence } from "./db";
import { allHandlers } from "./registry";

/** Starts the in-browser mock API. Imported dynamically only when VITE_API_MOCKS=true. */
export async function startMocks() {
  enablePersistence();
  // `?seed` fills the call list, for demos and the home page tour recording (scripts/record-tour.mjs).
  const params = new URLSearchParams(location.search);
  if (params.has("seed")) seedMockCalls();
  // `?live=3` puts calls on air (ringing, then live, transcripts growing); `?live=0` or none: quiet.
  const live = params.get("live");
  if (live !== null) seedMockLiveCalls(live === "" ? 3 : Number(live));
  const worker = setupWorker(...allHandlers);
  await worker.start({
    onUnhandledRequest: "bypass",
    quiet: true,
    serviceWorker: { url: "/mockServiceWorker.js" },
  });
}
