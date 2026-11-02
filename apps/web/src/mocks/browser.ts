import { setupWorker } from "msw/browser";
import { handlers } from "./handlers";
import { agentHandlers } from "./agents/handlers";
import { callHandlers, seedMockCalls } from "./calls/handlers";
import { flowHandlers } from "./flows";
import { toolHandlers } from "./tools";
import { channelHandlers } from "./channels/handlers";
import { qualityHandlers } from "./quality/handlers";
import { simHandlers } from "./sim/handlers";
import { enablePersistence } from "./db";

/** Starts the in-browser mock API. Imported dynamically only when VITE_API_MOCKS=true. */
export async function startMocks() {
  enablePersistence();
  // `?seed` fills the call list, for demos and the home page tour recording (scripts/record-tour.mjs).
  if (new URLSearchParams(location.search).has("seed")) seedMockCalls();
  const worker = setupWorker(
    ...handlers,
    ...agentHandlers,
    ...callHandlers,
    ...toolHandlers,
    ...channelHandlers,
    ...flowHandlers,
    ...qualityHandlers,
    ...simHandlers,
  );
  await worker.start({
    onUnhandledRequest: "bypass",
    quiet: true,
    serviceWorker: { url: "/mockServiceWorker.js" },
  });
}
