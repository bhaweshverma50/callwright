import { lazy, Suspense } from "react";
import { Navigate, createBrowserRouter, type RouteObject } from "react-router";
import { FullPageLoader } from "../components";
import { BILLING_ITEM } from "./nav";
import { AuthGuard } from "./AuthGuard";
import { RouteError } from "./RouteError";
import { Shell } from "./Shell";
import { DashboardPlaceholder } from "../routes/dashboard/DashboardPlaceholder";
import { NotFound } from "../routes/NotFound";
import { AreaPlaceholder, RecordPlaceholder } from "../routes/placeholders/AreaPlaceholder";
import { Enterprise } from "../routes/public/Enterprise";
import { ForgotPassword } from "../routes/public/ForgotPassword";
import { Home } from "../routes/public/Home";
import { Privacy, Terms } from "../routes/public/Legal";
import { Login } from "../routes/public/Login";
import { PublicLayout } from "../routes/public/PublicLayout";
import { Register } from "../routes/public/Register";
import { ResetPassword } from "../routes/public/ResetPassword";
import { VerifyEmail } from "../routes/public/VerifyEmail";
import { SettingsPage } from "../routes/settings/SettingsPage";

/*
  The largest pages load on demand. Inside the shell and the public layout their Suspense boundary
  shows the logo loader in the page area (Shell.tsx, PublicLayout.tsx); the gallery has no layout,
  so it gets a full-page one here.
*/
const BillingPage = lazy(() => import("../routes/billing/BillingPage").then((m) => ({ default: m.BillingPage })));
const Pricing = lazy(() => import("../routes/public/Pricing").then((m) => ({ default: m.Pricing })));
const ComponentsGallery = lazy(() => import("../routes/dev/ComponentsGallery").then((m) => ({ default: m.ComponentsGallery })));

/** Areas whose specs have not shipped: list route, plus record routes where the spec has one. */
const placeholderRoutes: RouteObject[] = [
  { path: "agents", element: <AreaPlaceholder to="/agents" /> },
  { path: "agents/new", element: <AreaPlaceholder to="/agents" /> },
  { path: "agents/templates", element: <AreaPlaceholder to="/agents" /> },
  { path: "agents/:id/*", element: <RecordPlaceholder to="/agents" prefix="agt" kind="agent" /> },
  { path: "calls", element: <AreaPlaceholder to="/calls" /> },
  { path: "phone-numbers", element: <AreaPlaceholder to="/phone-numbers" /> },
  { path: "knowledge-base", element: <AreaPlaceholder to="/knowledge-base" /> },
  { path: "datasets", element: <AreaPlaceholder to="/datasets" /> },
  { path: "simulations", element: <AreaPlaceholder to="/simulations" /> },
  { path: "simulations/runs/:id", element: <RecordPlaceholder to="/simulations" prefix="srun" kind="simulation run" /> },
  { path: "review", element: <AreaPlaceholder to="/review" /> },
  { path: "calibration", element: <AreaPlaceholder to="/calibration" /> },
  { path: "issues", element: <AreaPlaceholder to="/issues" /> },
  { path: "issues/:id", element: <RecordPlaceholder to="/issues" prefix="iss" kind="issue" /> },
];

/** Public and protected route groups (T026). Unknown signed-in addresses get NotFound (T095). */
export const routes: RouteObject[] = [
  {
    errorElement: <RouteError />,
    children: [
      {
        element: <PublicLayout />,
        children: [
          { index: true, element: <Home /> },
          { path: "pricing", element: <Pricing /> },
          { path: "enterprise", element: <Enterprise /> },
          { path: "privacy", element: <Privacy /> },
          { path: "terms", element: <Terms /> },
        ],
      },
      { path: "login", element: <Login /> },
      { path: "register", element: <Register /> },
      { path: "verify-email", element: <VerifyEmail /> },
      { path: "forgot-password", element: <ForgotPassword /> },
      { path: "reset-password", element: <ResetPassword /> },
      {
        path: "dev/components",
        element: (
          <Suspense fallback={<FullPageLoader label="Loading components" />}>
            <ComponentsGallery />
          </Suspense>
        ),
      },
      {
        element: <AuthGuard />,
        children: [
          {
            element: <Shell />,
            children: [
              {
                errorElement: <RouteError inShell />,
                children: [
                  { path: "app", element: <Navigate to="/dashboard" replace /> },
                  { path: "dashboard", element: <DashboardPlaceholder /> },
                  { path: BILLING_ITEM.to.slice(1), element: <BillingPage /> },
                  { path: "settings", element: <SettingsPage /> },
                  ...placeholderRoutes,
                  { path: "*", element: <NotFound /> },
                ],
              },
            ],
          },
        ],
      },
    ],
  },
];

export function createRouter() {
  return createBrowserRouter(routes);
}
