import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { createMemoryRouter, MemoryRouter } from "react-router";
import { signIn } from "../api/auth";
import { App } from "../App";
import { createQueryClient } from "../api/queryClient";
import { routes } from "../router";
import { session } from "../api/session";
import { Toaster, TooltipProvider } from "../components";
import { DEMO_EMAIL, DEMO_PASSWORD } from "../mocks/demoAccount";

/** Signs the demo account in against the mock API (MSW node server). */
export async function signInDemo() {
  session.set(await signIn(DEMO_EMAIL, DEMO_PASSWORD));
}

/** Renders the whole app (real routes, providers, mock API) at `path`. */
export function renderApp(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const queryClient = createQueryClient();
  const utils = render(<App router={router} queryClient={queryClient} />);
  return { ...utils, router, queryClient };
}

export interface ProviderOptions {
  /** A memory router around the component; a string is the initial path. */
  router?: boolean | string;
  /** Render the toast viewport next to the component. */
  toaster?: boolean;
  /** The query client to use (a fresh one by default). */
  queryClient?: QueryClient;
}

/**
 * Renders one component with what every page gets from the app shell: a fresh query client and
 * tooltips, plus a memory router and the toast viewport when asked for.
 */
export function renderWithProviders(ui: ReactNode, { router, toaster, queryClient = createQueryClient() }: ProviderOptions = {}) {
  const wrap = (node: ReactNode) => {
    const inner = (
      <>
        {node}
        {toaster && <Toaster />}
      </>
    );
    return (
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          {router ? <MemoryRouter initialEntries={[typeof router === "string" ? router : "/"]}>{inner}</MemoryRouter> : inner}
        </TooltipProvider>
      </QueryClientProvider>
    );
  };
  const utils = render(wrap(ui));
  return { ...utils, queryClient, rerender: (next: ReactNode) => utils.rerender(wrap(next)) };
}
