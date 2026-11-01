import { StrictMode } from "react";
import { act, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useSingleFlightPolling } from "./useSingleFlightPolling";

function PollingHarness({ poll }: { poll: (signal: AbortSignal) => Promise<void> }) {
  useSingleFlightPolling({ enabled: true, identity: "paper-1", intervalMs: 1000, poll });
  return null;
}

describe("useSingleFlightPolling", () => {
  afterEach(() => vi.useRealTimers());

  it("waits for a slow request before scheduling the next poll in StrictMode", async () => {
    vi.useFakeTimers();
    const requests: Array<{ resolve: () => void; signal: AbortSignal }> = [];
    const poll = vi.fn((signal: AbortSignal) => new Promise<void>((resolve) => requests.push({ resolve, signal })));

    render(
      <StrictMode>
        <PollingHarness poll={poll} />
      </StrictMode>,
    );

    await act(async () => vi.advanceTimersByTime(1000));
    expect(poll).toHaveBeenCalledTimes(1);

    await act(async () => vi.advanceTimersByTime(5000));
    expect(poll).toHaveBeenCalledTimes(1);

    await act(async () => requests[0].resolve());
    await act(async () => vi.advanceTimersByTime(999));
    expect(poll).toHaveBeenCalledTimes(1);
    await act(async () => vi.advanceTimersByTime(1));
    expect(poll).toHaveBeenCalledTimes(2);
  });

  it("aborts the active request when the component unmounts", async () => {
    vi.useFakeTimers();
    let activeSignal: AbortSignal | undefined;
    const poll = vi.fn((signal: AbortSignal) => {
      activeSignal = signal;
      return new Promise<void>(() => undefined);
    });
    const view = render(<PollingHarness poll={poll} />);

    await act(async () => vi.advanceTimersByTime(1000));
    expect(activeSignal?.aborted).toBe(false);

    view.unmount();
    expect(activeSignal?.aborted).toBe(true);
  });
});
