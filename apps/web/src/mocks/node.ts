import { setupServer } from "msw/node";
import { handlers } from "./handlers";
import { agentHandlers } from "./agents/handlers";
import { callHandlers } from "./calls/handlers";
import { toolHandlers } from "./tools";

export const server = setupServer(...handlers, ...agentHandlers, ...callHandlers, ...toolHandlers);
