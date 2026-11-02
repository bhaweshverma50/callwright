import { lazy, Suspense } from "react";
import { Navigate, createBrowserRouter, type RouteObject } from "react-router";
import { FullPageLoader } from "../components";
import { BILLING_ITEM } from "./nav";
import { AuthGuard } from "./AuthGuard";
import { RouteError } from "./RouteError";
import { Shell } from "./Shell";
import { AgentRedirect } from "../routes/agents/agentRedirect";
import { NotFound } from "../routes/NotFound";
import { AreaPlaceholder, RecordPlaceholder } from "../routes/placeholders/AreaPlaceholder";
import { Enterprise } from "../routes/public/Enterprise";
import { ForgotPassword } from "../routes/public/ForgotPassword";
import { Home } from "../routes/public/Home";
import { Privacy, Terms } from "../routes/public/Legal";
import { Login } from "../routes/public/Login";
import { PublicLayout } from "../routes/public/PublicLayout";
import { TestCheckout } from "../routes/checkout/TestCheckout";
import { Register } from "../routes/public/Register";
import { ResetPassword } from "../routes/public/ResetPassword";
import { VerifyEmail } from "../routes/public/VerifyEmail";
import { SettingsPage } from "../routes/settings/SettingsPage";
import "../routes/agents/tools";
import "../routes/agents/quality";
import { knowledgeRoutes } from "../routes/knowledge";

/*
  The largest pages load on demand. Inside the shell and the public layout their Suspense boundary
  shows the logo loader in the page area (Shell.tsx, PublicLayout.tsx); the gallery has no layout,
  so it gets a full-page one here.
*/
const BillingPage = lazy(() => import("../routes/billing/BillingPage").then((m) => ({ default: m.BillingPage })));
const Pricing = lazy(() => import("../routes/public/Pricing").then((m) => ({ default: m.Pricing })));
const ComponentsGallery = lazy(() => import("../routes/dev/ComponentsGallery").then((m) => ({ default: m.ComponentsGallery })));
const AgentsListPage = lazy(() => import("../routes/agents/AgentsListPage").then((m) => ({ default: m.AgentsListPage })));
const NewAgentTypePage = lazy(() => import("../routes/agents/NewAgentTypePage").then((m) => ({ default: m.NewAgentTypePage })));
const TemplatesPage = lazy(() => import("../routes/agents/TemplatesPage").then((m) => ({ default: m.TemplatesPage })));
const AgentEditorPage = lazy(() => import("../routes/agents/editor/AgentEditorPage").then((m) => ({ default: m.AgentEditorPage })));
const CallHistoryPage = lazy(() => import("../routes/calls/CallHistoryPage").then((m) => ({ default: m.CallHistoryPage })));
const ComparePage = lazy(() => import("../routes/calls/ComparePage").then((m) => ({ default: m.ComparePage })));
const DashboardPage = lazy(() => import("../routes/dashboard/DashboardPage").then((m) => ({ default: m.DashboardPage })));
const PhoneNumbersPage = lazy(() => import("../routes/channels/PhoneNumbersPage").then((m) => ({ default: m.PhoneNumbersPage })));
const NewFlowAgentPage = lazy(() => import("../routes/flows/NewFlowAgentPage").then((m) => ({ default: m.NewFlowAgentPage })));
const FlowBuilderPage = lazy(() => import("../routes/flows/FlowBuilderPage").then((m) => ({ default: m.FlowBuilderPage })));
const ReviewPage = lazy(() => import("../routes/review/ReviewPage").then((m) => ({ default: m.ReviewPage })));
const CalibrationPage = lazy(() => import("../routes/calibration/CalibrationPage").then((m) => ({ default: m.CalibrationPage })));
const AgentTestingPage = lazy(() => import("../routes/agents/AgentTestingPage").then((m) => ({ default: m.AgentTestingPage })));
const SimulationsPage = lazy(() => import("../routes/simulations/SimulationsPage").then((m) => ({ default: m.SimulationsPage })));
const ExperimentPage = lazy(() => import("../routes/simulations/ExperimentPage").then((m) => ({ default: m.ExperimentPage })));
const RunComparePage = lazy(() => import("../routes/simulations/RunComparePage").then((m) => ({ default: m.RunComparePage })));
const DatasetsPage = lazy(() => import("../routes/datasets/DatasetsPage").then((m) => ({ default: m.DatasetsPage })));
const DatasetPage = lazy(() => import("../routes/datasets/DatasetPage").then((m) => ({ default: m.DatasetPage })));

/** Agent builder (spec 002, T024), browser test calls (003) and the flow builder (004). */
const agentRoutes: RouteObject[] = [
  { path: "agents", element: <AgentsListPage /> },
  { path: "agents/new", element: <NewAgentTypePage /> },
  { path: "agents/templates", element: <TemplatesPage /> },
  { path: "agents/new/single", element: <AgentEditorPage /> },
  { path: "agents/new/flow", element: <NewFlowAgentPage /> },
  { path: "agents/:id", element: <AgentRedirect /> },
  { path: "agents/:id/edit", element: <AgentEditorPage /> },
  { path: "agents/:id/flow", element: <FlowBuilderPage /> },
  { path: "agents/:id/testing", element: <AgentTestingPage /> },
];

/** Testing and simulation (spec 008): batches, individual runs, comparisons and datasets. */
const simulationRoutes: RouteObject[] = [
  { path: "simulations", element: <SimulationsPage /> },
  { path: "simulations/runs/:runId", element: <RunComparePage /> },
  { path: "simulations/:experimentId", element: <ExperimentPage /> },
  { path: "datasets", element: <DatasetsPage /> },
  { path: "datasets/:datasetId", element: <DatasetPage /> },
];

/** Areas whose specs have not shipped: list route, plus record routes where the spec has one. */
const placeholderRoutes: RouteObject[] = [
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
      // Where "Add funds" lands in STRIPE_MODE=fake (test cards decide the outcome).
      { path: "checkout/:sessionId", element: <TestCheckout /> },
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
                  { path: "dashboard", element: <DashboardPage /> },
                  { path: "calls", element: <CallHistoryPage /> },
                  { path: "calls/:callId/compare", element: <ComparePage /> },
                  { path: BILLING_ITEM.to.slice(1), element: <BillingPage /> },
                  { path: "settings", element: <SettingsPage /> },
                  { path: "phone-numbers", element: <PhoneNumbersPage /> },
                  { path: "review", element: <ReviewPage /> },
                  { path: "calibration", element: <CalibrationPage /> },
                  ...agentRoutes,
                  ...knowledgeRoutes,
                  ...simulationRoutes,
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
