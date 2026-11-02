import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { MotionGlobalConfig } from "motion";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "../mocks/node";
import { resetMockDb } from "../mocks/db";
import { resetMockCalls } from "../mocks/calls/handlers";
import { resetQualityMocks } from "../mocks/quality/handlers";
import { resetWakeForTests } from "../api/wakeGate";

// Animations finish instantly in tests, so tickers and transitions show their final state.
MotionGlobalConfig.skipAnimations = true;

// jsdom gaps used by Radix primitives.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver;
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.releasePointerCapture = () => {};
  Element.prototype.setPointerCapture = () => {};
}
if (!Element.prototype.scrollIntoView) Element.prototype.scrollIntoView = () => {};
window.matchMedia ??= ((query: string) => ({
  matches: false,
  media: query,
  onchange: null,
  addListener: () => {},
  removeListener: () => {},
  addEventListener: () => {},
  removeEventListener: () => {},
  dispatchEvent: () => false,
})) as typeof window.matchMedia;

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
  resetMockDb();
  resetMockCalls();
  resetQualityMocks();
  resetWakeForTests();
  localStorage.clear();
});
afterAll(() => server.close());

// jsdom has no IntersectionObserver; motion's useInView (home page sections) needs one. Nothing is ever in view.
if (!("IntersectionObserver" in globalThis)) {
  globalThis.IntersectionObserver = class {
    readonly root = null;
    readonly rootMargin = "";
    readonly thresholds = [];
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() {
      return [];
    }
  } as unknown as typeof IntersectionObserver;
}
