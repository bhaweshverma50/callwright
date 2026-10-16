import { setupWorker } from "msw/browser";
import { handlers } from "./handlers";
import { enablePersistence } from "./db";

/** Starts the in-browser mock API. Imported dynamically only when VITE_API_MOCKS=true. */
export async function startMocks() {
  enablePersistence();
  const worker = setupWorker(...handlers);
  await worker.start({
    onUnhandledRequest: "bypass",
    quiet: true,
    serviceWorker: { url: "/mockServiceWorker.js" },
  });
}
