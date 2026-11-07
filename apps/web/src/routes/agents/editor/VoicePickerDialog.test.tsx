import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { createQueryClient } from "../../../api/queryClient";
import { TooltipProvider } from "../../../components";
import { voiceCatalog } from "../../../mocks/agents/catalog";
import { signInDemo } from "../../../test/render";
import { VoicePickerDialog } from "./VoicePickerDialog";

// 002 T085: the voice list is a radio group whose preview buttons sit beside each radio, not
// inside it, and arrow keys move the selection.
describe("VoicePickerDialog keyboard and roles", () => {
  it("keeps preview buttons out of the radios and selects with the arrow keys", async () => {
    await signInDemo();
    const provider = voiceCatalog.tts.find((p) => p.provider === "elevenlabs")!;
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={createQueryClient()}>
        <TooltipProvider>
          <VoicePickerDialog
            open
            onOpenChange={() => {}}
            provider={provider}
            model={provider.default_model}
            language="en-US"
            catalog={voiceCatalog}
            value=""
            onChoose={() => {}}
          />
        </TooltipProvider>
      </QueryClientProvider>,
    );
    const group = await screen.findByRole("radiogroup", { name: "Voices" });
    const radios = await within(group).findAllByRole("radio");
    expect(radios.length).toBeGreaterThan(1);
    for (const radio of radios) expect(within(radio).queryByRole("button")).toBeNull();
    expect(within(group).getAllByRole("button", { name: /preview$/ }).length).toBeGreaterThan(0);

    radios[0]!.focus();
    await user.keyboard("{ArrowDown}");
    await waitFor(() => expect(within(group).getAllByRole("radio")[1]).toHaveAttribute("aria-checked", "true"));
    expect(within(group).getAllByRole("radio")[1]).toHaveFocus();
    await user.keyboard("{Home}");
    await waitFor(() => expect(within(group).getAllByRole("radio")[0]).toHaveAttribute("aria-checked", "true"));
  });
});
