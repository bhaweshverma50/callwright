import { setupWorker } from "msw/browser";
import { handlers } from "./handlers";
import { agentHandlers } from "./agents/handlers";
import { callHandlers, seedMockCalls, seedMockLiveCalls } from "./calls/handlers";
import { flowHandlers } from "./flows";
import { toolHandlers } from "./tools";
import { channelHandlers } from "./channels/handlers";
import { qualityHandlers } from "./quality/handlers";
import { simHandlers } from "./sim/handlers";
import { issueHandlers } from "./issues/handlers";
import { callbackHandlers } from "./callbacks/handlers";
import { callerLanguageHandlers } from "./callerLanguage/handlers";
import { enablePersistence } from "./db";

/** Starts the in-browser mock API. Imported dynamically only when VITE_API_MOCKS=true. */
export async function startMocks() {
  enablePersistence();
  // `?seed` fills the call list, for demos and the home page tour recording (scripts/record-tour.mjs).
  const params = new URLSearchParams(location.search);
  if (params.has("seed")) seedMockCalls();
  // `?live=3` puts calls on air (ringing, then live, transcripts growing); `?live=0` or none: quiet.
  const live = params.get("live");
  if (live !== null) seedMockLiveCalls(live === "" ? 3 : Number(live));
  const worker = setupWorker(
    ...handlers,
    ...agentHandlers,
    ...callHandlers,
    ...toolHandlers,
    ...channelHandlers,
    ...flowHandlers,
    ...qualityHandlers,
    ...simHandlers,
    ...issueHandlers,
    ...callbackHandlers,
    ...callerLanguageHandlers,
  );
  await worker.start({
    onUnhandledRequest: "bypass",
    quiet: true,
    serviceWorker: { url: "/mockServiceWorker.js" },
  });
}
