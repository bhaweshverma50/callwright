import { render } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { api, unwrap } from "../api/client";
import { App } from "../App";
import { createQueryClient } from "../api/queryClient";
import { routes } from "../router";
import { session } from "../api/session";
import { DEMO_EMAIL, DEMO_PASSWORD } from "../mocks/db";

/** Signs the demo account in against the mock API (MSW node server). */
export async function signInDemo() {
  const s = await unwrap(api.POST("/auth/sign-in", { body: { email: DEMO_EMAIL, password: DEMO_PASSWORD } }));
  session.set(s);
}

/** Renders the whole app (real routes, providers, mock API) at `path`. */
export function renderApp(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const queryClient = createQueryClient();
  const utils = render(<App router={router} queryClient={queryClient} />);
  return { ...utils, router, queryClient };
}
