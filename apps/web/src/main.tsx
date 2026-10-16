import "@fontsource-variable/unbounded/index.css";
import "@fontsource-variable/geist/index.css";
import "@fontsource-variable/geist-mono/index.css";
import "./index.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import { wireCrossTabAuth } from "./app/auth";
import { queryClient } from "./app/queryClient";
import { createRouter } from "./app/router";
import { initTheme } from "./app/theme";
import { env } from "./lib/env";

async function boot() {
  initTheme();
  wireCrossTabAuth();
  // VITE_API_MOCKS=true serves /v1 from the in-browser mock API built from the contracts.
  if (env.mocks) {
    const { startMocks } = await import("./mocks/browser");
    await startMocks();
  }
  const router = createRouter();
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App router={router} queryClient={queryClient} />
    </StrictMode>,
  );
}

void boot();
