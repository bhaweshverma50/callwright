/**
 * Every mock API handler and every mock store, listed once. The browser worker (browser.ts) and
 * the test server (node.ts) serve `allHandlers`; tests put every store back with `resetAll()`
 * after each case (src/test/setup.ts). A new mock module adds its handlers and its reset here.
 */
import { agentHandlers } from "./agents/handlers";
import { callbackHandlers, resetMockCallbacks } from "./callbacks/handlers";
import { callerLanguageHandlers, resetMockCallerLanguages } from "./callerLanguage/handlers";
import { callHandlers, resetMockCalls } from "./calls/handlers";
import { channelHandlers, resetMockChannels } from "./channels/handlers";
import { connectorHandlers } from "./connectors/handlers";
import { resetConnectorStore } from "./connectors/store";
import { resetMockDb } from "./db";
import { flowHandlers, resetMockFlows } from "./flows";
import { handlers } from "./handlers";
import { issueHandlers } from "./issues/handlers";
import { resetIssueMocks } from "./issues/store";
import { qualityHandlers, resetQualityMocks } from "./quality/handlers";
import { simHandlers } from "./sim/handlers";
import { resetSimMocks } from "./sim/store";
import { resetToolStore, toolHandlers } from "./tools";

export const allHandlers = [
  ...handlers,
  ...agentHandlers,
  ...callHandlers,
  ...toolHandlers,
  ...connectorHandlers,
  ...channelHandlers,
  ...flowHandlers,
  ...qualityHandlers,
  ...simHandlers,
  ...issueHandlers,
  ...callbackHandlers,
  ...callerLanguageHandlers,
];

/** The workspace, agents, ledger and sessions live in the db state, so resetMockDb covers them. */
export function resetAll() {
  resetMockDb();
  resetMockCalls();
  resetMockCallbacks();
  resetMockCallerLanguages();
  resetMockChannels();
  resetMockFlows();
  resetToolStore();
  resetConnectorStore();
  resetQualityMocks();
  resetSimMocks();
  resetIssueMocks();
}
