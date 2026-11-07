import { lazy, Suspense } from "react";
import { Navigate, createBrowserRouter, type RouteObject } from "react-router";
import { AuthGuard } from "./app/AuthGuard";
import { RouteError } from "./app/RouteError";
import { Shell } from "./app/Shell";
import { FullPageLoader } from "./components";
import {
  agentEditPath,
  agentFlowPath,
  agentHomePath,
  AGENTS_PATH,
  agentTestingPath,
  AUTH_PAGES,
  BILLING_PATH,
  CALIBRATION_PATH,
  CALLBACKS_PATH,
  callComparePath,
  CALLS_PATH,
  DASHBOARD_PATH,
  datasetPath,
  DATASETS_PATH,
  experimentPath,
  issuePath,
  ISSUES_PATH,
  NEW_AGENT_PATH,
  NEW_FLOW_AGENT_PATH,
  NEW_SINGLE_AGENT_PATH,
  PHONE_NUMBERS_PATH,
  REVIEW_PATH,
  SETTINGS_PATH,
  SIMULATIONS_PATH,
  simulationRunPath,
  TEMPLATES_PATH,
} from "./lib/paths";
import { AgentRedirect } from "./routes/agents/agentRedirect";
import { NotFound } from "./routes/NotFound";
import { Enterprise } from "./routes/public/Enterprise";
import { ForgotPassword } from "./routes/public/ForgotPassword";
import { Home } from "./routes/public/Home";
import { Privacy, Terms } from "./routes/public/Legal";
import { Login } from "./routes/public/Login";
import { PublicLayout } from "./routes/public/PublicLayout";
import { TestCheckout } from "./routes/checkout/TestCheckout";
import { Register } from "./routes/public/Register";
import { ResetPassword } from "./routes/public/ResetPassword";
import { VerifyEmail } from "./routes/public/VerifyEmail";
import { SettingsPage } from "./routes/settings/SettingsPage";
import { knowledgeRoutes } from "./routes/knowledge";

/*
  The largest pages load on demand. Inside the shell and the public layout their Suspense boundary
  shows the logo loader in the page area (Shell.tsx, PublicLayout.tsx); the gallery has no layout,
  so it gets a full-page one here.
*/
const BillingPage = lazy(() => import("./routes/billing/BillingPage").then((m) => ({ default: m.BillingPage })));
const Pricing = lazy(() => import("./routes/public/Pricing").then((m) => ({ default: m.Pricing })));
const ComponentsGallery = lazy(() => import("./routes/dev/ComponentsGallery").then((m) => ({ default: m.ComponentsGallery })));
const AgentsListPage = lazy(() => import("./routes/agents/AgentsListPage").then((m) => ({ default: m.AgentsListPage })));
const NewAgentTypePage = lazy(() => import("./routes/agents/NewAgentTypePage").then((m) => ({ default: m.NewAgentTypePage })));
const TemplatesPage = lazy(() => import("./routes/agents/TemplatesPage").then((m) => ({ default: m.TemplatesPage })));
const AgentEditorPage = lazy(() => import("./routes/agents/editor/AgentEditorPage").then((m) => ({ default: m.AgentEditorPage })));
const CallHistoryPage = lazy(() => import("./routes/calls/CallHistoryPage").then((m) => ({ default: m.CallHistoryPage })));
const CallbacksPage = lazy(() => import("./routes/calls/callbacks/CallbacksPage").then((m) => ({ default: m.CallbacksPage })));
const ComparePage = lazy(() => import("./routes/calls/ComparePage").then((m) => ({ default: m.ComparePage })));
const DashboardPage = lazy(() => import("./routes/dashboard/DashboardPage").then((m) => ({ default: m.DashboardPage })));
const PhoneNumbersPage = lazy(() => import("./routes/channels/PhoneNumbersPage").then((m) => ({ default: m.PhoneNumbersPage })));
const NewFlowAgentPage = lazy(() => import("./routes/flows/NewFlowAgentPage").then((m) => ({ default: m.NewFlowAgentPage })));
const FlowBuilderPage = lazy(() => import("./routes/flows/FlowBuilderPage").then((m) => ({ default: m.FlowBuilderPage })));
const ReviewPage = lazy(() => import("./routes/review/ReviewPage").then((m) => ({ default: m.ReviewPage })));
const CalibrationPage = lazy(() => import("./routes/calibration/CalibrationPage").then((m) => ({ default: m.CalibrationPage })));
const AgentTestingPage = lazy(() => import("./routes/agents/AgentTestingPage").then((m) => ({ default: m.AgentTestingPage })));
const SimulationsPage = lazy(() => import("./routes/simulations/SimulationsPage").then((m) => ({ default: m.SimulationsPage })));
const ExperimentPage = lazy(() => import("./routes/simulations/ExperimentPage").then((m) => ({ default: m.ExperimentPage })));
const RunComparePage = lazy(() => import("./routes/simulations/RunComparePage").then((m) => ({ default: m.RunComparePage })));
const DatasetsPage = lazy(() => import("./routes/datasets/DatasetsPage").then((m) => ({ default: m.DatasetsPage })));
const DatasetPage = lazy(() => import("./routes/datasets/DatasetPage").then((m) => ({ default: m.DatasetPage })));
const IssuesPage = lazy(() => import("./routes/issues/IssuesPage").then((m) => ({ default: m.IssuesPage })));
const IssueDetailPage = lazy(() => import("./routes/issues/IssueDetailPage").then((m) => ({ default: m.IssueDetailPage })));

/** Agent builder (spec 002, T024), browser test calls (003) and the flow builder (004). */
const agentRoutes: RouteObject[] = [
  { path: AGENTS_PATH, element: <AgentsListPage /> },
  { path: NEW_AGENT_PATH, element: <NewAgentTypePage /> },
  { path: TEMPLATES_PATH, element: <TemplatesPage /> },
  { path: NEW_SINGLE_AGENT_PATH, element: <AgentEditorPage /> },
  { path: NEW_FLOW_AGENT_PATH, element: <NewFlowAgentPage /> },
  { path: agentHomePath(":id"), element: <AgentRedirect /> },
  { path: agentEditPath(":id"), element: <AgentEditorPage /> },
  { path: agentFlowPath(":id"), element: <FlowBuilderPage /> },
  { path: agentTestingPath(":id"), element: <AgentTestingPage /> },
];

/** Testing and simulation (spec 008): batches, individual runs, comparisons and datasets. */
const simulationRoutes: RouteObject[] = [
  { path: SIMULATIONS_PATH, element: <SimulationsPage /> },
  { path: simulationRunPath(":runId"), element: <RunComparePage /> },
  { path: experimentPath(":experimentId"), element: <ExperimentPage /> },
  { path: DATASETS_PATH, element: <DatasetsPage /> },
  { path: datasetPath(":datasetId"), element: <DatasetPage /> },
];

/** Issues and auto-fix (spec 009): the issue list with detection, and one issue with its fix loop. */
const issueRoutes: RouteObject[] = [
  { path: ISSUES_PATH, element: <IssuesPage /> },
  { path: issuePath(":id"), element: <IssueDetailPage /> },
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
      { path: AUTH_PAGES.login, element: <Login /> },
      { path: AUTH_PAGES.register, element: <Register /> },
      { path: AUTH_PAGES.verifyEmail, element: <VerifyEmail /> },
      { path: AUTH_PAGES.forgotPassword, element: <ForgotPassword /> },
      { path: AUTH_PAGES.resetPassword, element: <ResetPassword /> },
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
                  { path: "app", element: <Navigate to={DASHBOARD_PATH} replace /> },
                  { path: DASHBOARD_PATH, element: <DashboardPage /> },
                  { path: CALLS_PATH, element: <CallHistoryPage /> },
                  { path: CALLBACKS_PATH, element: <CallbacksPage /> },
                  { path: callComparePath(":callId"), element: <ComparePage /> },
                  { path: BILLING_PATH, element: <BillingPage /> },
                  { path: SETTINGS_PATH, element: <SettingsPage /> },
                  { path: PHONE_NUMBERS_PATH, element: <PhoneNumbersPage /> },
                  { path: REVIEW_PATH, element: <ReviewPage /> },
                  { path: CALIBRATION_PATH, element: <CalibrationPage /> },
                  ...agentRoutes,
                  ...knowledgeRoutes,
                  ...simulationRoutes,
                  ...issueRoutes,
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
