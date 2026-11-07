/** Knowledge routes (spec 005, T005): /knowledge-base and /knowledge-base/:id. Pages load on demand. */
import { lazy } from "react";
import type { RouteObject } from "react-router";
import { KNOWLEDGE_PATH, knowledgeBasePath } from "../../lib/paths";

const KnowledgeListPage = lazy(() => import("./KnowledgeListPage").then((m) => ({ default: m.KnowledgeListPage })));
const KnowledgeBasePage = lazy(() => import("./KnowledgeBasePage").then((m) => ({ default: m.KnowledgeBasePage })));

export const knowledgeRoutes: RouteObject[] = [
  { path: KNOWLEDGE_PATH, element: <KnowledgeListPage /> },
  { path: knowledgeBasePath(":id"), element: <KnowledgeBasePage /> },
];
