import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => cleanup());

// Test-only: React Router's data router builds a fetch Request with jsdom's AbortSignal, which Node's
// Request rejects ("Expected signal to be an instance of AbortSignal"), so link clicks silently fail to
// navigate under jsdom. Drop the signal so navigation can be tested; real browsers are unaffected.
const NodeRequest = globalThis.Request;
globalThis.Request = class extends NodeRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    if (init?.signal) {
      const { signal: _signal, ...rest } = init;
      super(input, rest);
    } else {
      super(input, init);
    }
  }
} as typeof Request;
