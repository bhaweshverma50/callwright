import { Navigate, createBrowserRouter, type RouteObject } from "react-router";
import { BILLING_ITEM } from "./nav";
import { AuthGuard } from "./AuthGuard";
import { RouteError } from "./RouteError";
import { Shell } from "./Shell";
import { BillingPage } from "../routes/billing/BillingPage";
import { DashboardPlaceholder } from "../routes/dashboard/DashboardPlaceholder";
import { ComponentsGallery } from "../routes/dev/ComponentsGallery";
import { NotFound } from "../routes/NotFound";
import { AreaPlaceholder, RecordPlaceholder } from "../routes/placeholders/AreaPlaceholder";
import { Enterprise } from "../routes/public/Enterprise";
import { ForgotPassword } from "../routes/public/ForgotPassword";
import { Home } from "../routes/public/Home";
import { Privacy, Terms } from "../routes/public/Legal";
import { Login } from "../routes/public/Login";
import { Pricing } from "../routes/public/Pricing";
import { PublicLayout } from "../routes/public/PublicLayout";
import { Register } from "../routes/public/Register";
import { ResetPassword } from "../routes/public/ResetPassword";
import { VerifyEmail } from "../routes/public/VerifyEmail";
import { SettingsPage } from "../routes/settings/SettingsPage";

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
      { path: "dev/components", element: <ComponentsGallery /> },
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
