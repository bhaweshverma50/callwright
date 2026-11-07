import "@fontsource-variable/unbounded/index.css";
import "@fontsource-variable/geist/index.css";
import "@fontsource-variable/geist-mono/index.css";
import "./index.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { queryClient } from "./api/queryClient";
import { wireCrossTabAuth } from "./api/session";
import { createRouter } from "./router";
import { initTheme } from "./app/theme";
import { FullPageLoader } from "./components";
import { installDemoHints } from "./lib/demoHints";
import { env } from "./lib/env";

async function boot() {
  initTheme();
  wireCrossTabAuth();
  const root = createRoot(document.getElementById("root")!);
  // The logo loader holds the screen while boot work runs (the mock API worker in mock mode).
  root.render(<FullPageLoader />);
  // VITE_API_MOCKS=true serves /v1 from the in-browser mock API built from the contracts.
  if (env.mocks) {
    const [{ startMocks }, demo] = await Promise.all([import("./mocks/browser"), import("./mocks/demoAccount")]);
    await startMocks();
    installDemoHints({ email: demo.DEMO_EMAIL, password: demo.DEMO_PASSWORD, verifyToken: demo.mockVerifyToken, resetToken: demo.mockResetToken });
  }
  const router = createRouter();
  root.render(
    <StrictMode>
      <App router={router} queryClient={queryClient} />
    </StrictMode>,
  );
}

void boot();
