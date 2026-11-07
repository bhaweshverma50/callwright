import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { MotionConfig } from "motion/react";
import { useEffect } from "react";
import { bindSessionCache } from "./api/session";
import { RouterProvider, type createBrowserRouter } from "react-router";
import { Toaster, TooltipProvider } from "./components";
import { WakeOverlay } from "./app/WakeOverlay";

/**
 * Providers around the router: query cache, motion (follows the reduced-motion setting), tooltips
 * with one shared delay (components/Tooltip.tsx), toasts.
 */
export function App({ router, queryClient }: { router: ReturnType<typeof createBrowserRouter>; queryClient: QueryClient }) {
  // Sign-in and sign-out clear this cache (api/session.ts), so tests' own clients are respected.
  useEffect(() => bindSessionCache(queryClient), [queryClient]);
  return (
    <QueryClientProvider client={queryClient}>
      <MotionConfig reducedMotion="user">
        <TooltipProvider>
          <RouterProvider router={router} />
          <Toaster />
          <WakeOverlay />
        </TooltipProvider>
      </MotionConfig>
    </QueryClientProvider>
  );
}
