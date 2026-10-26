import { setupWorker } from "msw/browser";
import { handlers } from "./handlers";
import { agentHandlers } from "./agents/handlers";
import { toolHandlers } from "./tools";
import { enablePersistence } from "./db";

/** Starts the in-browser mock API. Imported dynamically only when VITE_API_MOCKS=true. */
export async function startMocks() {
  enablePersistence();
  const worker = setupWorker(...handlers, ...agentHandlers, ...toolHandlers);
  await worker.start({
    onUnhandledRequest: "bypass",
    quiet: true,
    serviceWorker: { url: "/mockServiceWorker.js" },
  });
}
