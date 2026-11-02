import { setupServer } from "msw/node";
import { handlers } from "./handlers";
import { agentHandlers } from "./agents/handlers";
import { callHandlers } from "./calls/handlers";
import { flowHandlers } from "./flows";
import { toolHandlers } from "./tools";
import { channelHandlers } from "./channels/handlers";
import { qualityHandlers } from "./quality/handlers";
import { simHandlers } from "./sim/handlers";

export const server = setupServer(
  ...handlers,
  ...agentHandlers,
  ...callHandlers,
  ...toolHandlers,
  ...channelHandlers,
  ...flowHandlers,
  ...qualityHandlers,
  ...simHandlers,
);
