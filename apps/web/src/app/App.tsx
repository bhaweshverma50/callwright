import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { RouterProvider, type createBrowserRouter } from "react-router";
import { Toaster, TooltipProvider } from "../components";

/** Providers around the router: query cache, tooltips (short delay), toasts. */
export function App({ router, queryClient }: { router: ReturnType<typeof createBrowserRouter>; queryClient: QueryClient }) {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={250} skipDelayDuration={150}>
        <RouterProvider router={router} />
        <Toaster />
      </TooltipProvider>
    </QueryClientProvider>
  );
}
