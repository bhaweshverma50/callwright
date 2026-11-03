import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { mockCallbackId, mockCallbacks } from "../../mocks/callbacks/handlers";
import { mockCallerLanguages, mockPreferenceId } from "../../mocks/callerLanguage/handlers";
import { mockCallId, seedMockCalls } from "../../mocks/calls/handlers";
import { renderApp, signInDemo } from "../../test/render";
import { transcriptText } from "./Transcript";

describe("CallDetailDrawer (006 US2)", () => {
  it("renders the transcript with a failed tool, an interruption and n/a latency parts", async () => {
    seedMockCalls(10);
    await signInDemo();
    renderApp(`/calls?call=${mockCallId(0)}`);
    const drawer = await screen.findByRole("dialog", undefined, { timeout: 5000 });
    expect(await within(drawer).findByText("Where is my order?", undefined, { timeout: 5000 })).toBeInTheDocument();
    expect(within(drawer).getByText("Error")).toBeInTheDocument();
    expect(within(drawer).getByText("3,004 ms")).toBeInTheDocument();
    expect(within(drawer).getByText("Interrupted")).toBeInTheDocument();
    expect(within(drawer).getByRole("img", { name: /voice first audio n\/a/ })).toBeInTheDocument();
    expect(within(drawer).getByText("v3")).toBeInTheDocument();
  });

  it("hides the flow path when the call has no transitions", async () => {
    seedMockCalls(10);
    await signInDemo();
    renderApp(`/calls?call=${mockCallId(0)}`);
    const drawer = await screen.findByRole("dialog", undefined, { timeout: 5000 });
    await within(drawer).findByText("Where is my order?", undefined, { timeout: 5000 });
    expect(within(drawer).queryByRole("tab", { name: /Flow path/ })).not.toBeInTheDocument();
  });

  it("shows the retention message for a deleted recording, transcript still there", async () => {
    seedMockCalls(10);
    await signInDemo();
    const user = userEvent.setup();
    renderApp(`/calls?call=${mockCallId(4)}`);
    const drawer = await screen.findByRole("dialog", undefined, { timeout: 5000 });
    await user.click(await within(drawer).findByRole("button", { name: "Play recording" }));
    expect(await within(drawer).findByText("Recording deleted under your retention policy", undefined, { timeout: 5000 })).toBeInTheDocument();
    expect(within(drawer).getByText("Where is my order?")).toBeInTheDocument();
  });

  it("marks analysis as processing while post-call steps run", async () => {
    seedMockCalls(10);
    await signInDemo();
    const user = userEvent.setup();
    renderApp(`/calls?call=${mockCallId(3)}`);
    const drawer = await screen.findByRole("dialog", undefined, { timeout: 5000 });
    await user.click(await within(drawer).findByRole("tab", { name: "Analysis" }));
    expect(within(drawer).getAllByText("Processing").length).toBeGreaterThanOrEqual(3);
  });

  it("shows the receipt with the 1.13x model surcharge", async () => {
    seedMockCalls(10);
    await signInDemo();
    const user = userEvent.setup();
    renderApp(`/calls?call=${mockCallId(0)}&tab=cost`);
    const drawer = await screen.findByRole("dialog", undefined, { timeout: 5000 });
    await user.click(await within(drawer).findByRole("tab", { name: "Cost" }));
    expect(await within(drawer).findByText("1.13x", undefined, { timeout: 5000 })).toBeInTheDocument();
    expect(within(drawer).getAllByText("$0.477").length).toBeGreaterThan(0);
  });

  it("shows the callback booked on the call and cancels it (011)", async () => {
    seedMockCalls(10);
    await signInDemo();
    const user = userEvent.setup();
    renderApp(`/calls?call=${mockCallId(1)}`);
    const drawer = await screen.findByRole("dialog", undefined, { timeout: 5000 });
    const card = await within(drawer).findByRole("region", { name: "Callbacks" }, { timeout: 5000 });
    expect(card).toHaveTextContent("Callback scheduled for Sat 17 Oct, 5:00 pm");
    expect(card).toHaveTextContent("EDT");
    expect(card).toHaveTextContent("Caller was heading into a meeting; continue rescheduling the cleaning appointment.");
    expect(card).toHaveTextContent("+1 555 123 4567");
    expect(within(card).getByText("Scheduled")).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Cancel callback" }));
    const confirm = await screen.findByRole("alertdialog", { name: "Cancel this callback?" });
    await user.click(within(confirm).getByRole("button", { name: "Cancel callback" }));
    await waitFor(() => expect(mockCallbacks().cancelled).toEqual([mockCallbackId(0)]));
    expect(await within(card).findByText("Cancelled", undefined, { timeout: 5000 })).toBeInTheDocument();
    expect(card).toHaveTextContent("was cancelled");
    expect(within(card).queryByRole("button", { name: "Cancel callback" })).not.toBeInTheDocument();
  });

  it("renders no callback card when the call booked none", async () => {
    seedMockCalls(10);
    await signInDemo();
    renderApp(`/calls?call=${mockCallId(0)}`);
    const drawer = await screen.findByRole("dialog", undefined, { timeout: 5000 });
    await within(drawer).findByText("Where is my order?", undefined, { timeout: 5000 });
    expect(within(drawer).queryByRole("region", { name: "Callbacks" })).not.toBeInTheDocument();
  });

  it("shows the language switch and forgets the caller's saved language (012)", async () => {
    seedMockCalls(10);
    await signInDemo();
    const user = userEvent.setup();
    renderApp(`/calls?call=${mockCallId(1)}`);
    const drawer = await screen.findByRole("dialog", undefined, { timeout: 5000 });
    const card = await within(drawer).findByRole("region", { name: "Language" }, { timeout: 5000 });
    expect(card).toHaveTextContent("Started in English (US)");
    expect(within(card).getByRole("list", { name: "Language switches" })).toHaveTextContent("Switched to Hindi at 0:42");
    expect(card).toHaveTextContent("Saved for +1 555 123 4567: Hindi, updated");
    await user.click(within(card).getByRole("button", { name: /Forget the saved language/ }));
    await waitFor(() => expect(mockCallerLanguages().deleted).toEqual([mockPreferenceId(1)]));
    await waitFor(() => expect(card).not.toHaveTextContent("Saved for"));
    expect(card).toHaveTextContent("Switched to Hindi at 0:42");
  });

  it("says when a call started in the caller's saved language (012)", async () => {
    seedMockCalls(10);
    await signInDemo();
    renderApp(`/calls?call=${mockCallId(4)}`);
    const drawer = await screen.findByRole("dialog", undefined, { timeout: 5000 });
    const card = await within(drawer).findByRole("region", { name: "Language" }, { timeout: 5000 });
    expect(card).toHaveTextContent("Started in Spanish (saved for this caller)");
    expect(card).toHaveTextContent("Saved for +1 415 555 0004: Spanish");
  });

  it("never mentions saving on a browser call (012)", async () => {
    seedMockCalls(10);
    await signInDemo();
    renderApp(`/calls?call=${mockCallId(3)}`);
    const drawer = await screen.findByRole("dialog", undefined, { timeout: 5000 });
    const card = await within(drawer).findByRole("region", { name: "Language" }, { timeout: 5000 });
    expect(card).toHaveTextContent("Switched to Spanish at 0:25");
    expect(card).not.toHaveTextContent(/saved/i);
    expect(within(card).queryByRole("button")).not.toBeInTheDocument();
  });

  it("copies plain text with bracketed tool lines", () => {
    expect(
      transcriptText([
        { id: "a", type: "message", role: "user", text: "Hi", interrupted: false, offset_ms: 0 },
        { id: "b", type: "tool_call", tool_name: "lookup", arguments: { id: "A1", n: 2 }, offset_ms: 0 },
        { id: "c", type: "tool_result", tool_call_id: "b", tool_name: "lookup", output: "late", is_error: true, offset_ms: 0 },
      ]),
    ).toBe('Caller: Hi\n[Tool call: lookup({"id": "A1", "n": 2})]\n[Tool error: lookup -> late]');
  });
});
