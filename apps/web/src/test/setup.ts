import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { MotionGlobalConfig } from "motion";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "../mocks/node";
import { resetAll } from "../mocks/registry";
import { resetWakeForTests } from "../api/wakeGate";

// Full parallel runs load every worker; route pages behind the app shell can take over the 1 s
// default to appear, which made findBy* queries flake (IssueDetailPage, IssuesPage).
configure({ asyncUtilTimeout: 4000 });

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
  resetAll();
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
