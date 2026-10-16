import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { MotionConfig } from "motion/react";
import { RouterProvider, type createBrowserRouter } from "react-router";
import { Toaster, TooltipProvider } from "../components";

/**
 * Providers around the router: query cache, motion (follows the reduced-motion setting), tooltips
 * with a short delay, toasts.
 */
export function App({ router, queryClient }: { router: ReturnType<typeof createBrowserRouter>; queryClient: QueryClient }) {
  return (
    <QueryClientProvider client={queryClient}>
      <MotionConfig reducedMotion="user">
        <TooltipProvider delayDuration={250} skipDelayDuration={150}>
          <RouterProvider router={router} />
          <Toaster />
        </TooltipProvider>
      </MotionConfig>
    </QueryClientProvider>
  );
}
