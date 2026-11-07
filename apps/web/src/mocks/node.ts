import { setupServer } from "msw/node";
import { allHandlers } from "./registry";

export const server = setupServer(...allHandlers);
