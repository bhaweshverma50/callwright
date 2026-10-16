import { setupServer } from "msw/node";
import { handlers } from "./handlers";
import { agentHandlers } from "./agents/handlers";

export const server = setupServer(...handlers, ...agentHandlers);
