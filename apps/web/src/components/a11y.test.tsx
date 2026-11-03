import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { Button } from "./Button";
import { Dialog } from "./Dialog";
import { Input } from "./Field";
import { Menu, MenuContent, MenuItem, MenuTrigger } from "./Menu";
import { FieldRow } from "./Panel";
import { Select } from "./Select";
import { Slider } from "./Slider";
import { SwitchControl } from "./Switch";
import { TooltipProvider } from "./Tooltip";

// 002 T085: keyboard and screen-reader fixes in the shared primitives the agent editor is built on.

describe("FieldRow names and describes its control", () => {
  it("names a slider thumb from the row label and reads the row help as its description", () => {
    render(
      <FieldRow label="Speed" htmlFor="f-speed" description="How fast the agent talks.">
        <Slider id="f-speed" value={1} min={0.5} max={2} step={0.1} onValueChange={() => {}} />
      </FieldRow>,
    );
    const slider = screen.getByRole("slider", { name: "Speed" });
    expect(slider).toHaveAccessibleDescription("How fast the agent talks.");
  });

  it("keeps the control's own description (an error) after the row help", () => {
    render(
      <FieldRow label="Timeout" htmlFor="f-timeout" description="Seconds before giving up.">
        <Input id="f-timeout" aria-describedby="f-timeout-err" defaultValue="0" />
        <p id="f-timeout-err">Must be at least 1.</p>
      </FieldRow>,
    );
    expect(screen.getByRole("textbox", { name: "Timeout" })).toHaveAccessibleDescription("Seconds before giving up. Must be at least 1.");
  });

  it("describes switches and selects too, but not other controls in the row", () => {
    render(
      <TooltipProvider>
        <FieldRow label="Record calls" htmlFor="f-rec" description="Store audio for review." inline>
          <SwitchControl id="f-rec" checked onCheckedChange={() => {}} />
        </FieldRow>
        <FieldRow label="Provider" htmlFor="f-prov" description="Who runs the model.">
          <Select id="f-prov" value="a" onValueChange={() => {}} options={[{ value: "a", label: "Acme" }]} />
          <button type="button">About providers</button>
        </FieldRow>
      </TooltipProvider>,
    );
    expect(screen.getByRole("switch", { name: "Record calls" })).toHaveAccessibleDescription("Store audio for review.");
    expect(screen.getByRole("combobox", { name: "Provider" })).toHaveAccessibleDescription("Who runs the model.");
    expect(screen.getByRole("button", { name: "About providers" })).not.toHaveAccessibleDescription();
  });

  it("an explicit aria-label still wins over the row label", () => {
    render(
      <FieldRow label="Volume" htmlFor="f-vol">
        <Slider id="f-vol" aria-label="Agent volume" value={1} min={0} max={2} onValueChange={() => {}} />
      </FieldRow>,
    );
    expect(screen.getByRole("slider", { name: "Agent volume" })).toBeInTheDocument();
  });
});

function DialogHarness() {
  const [open, setOpen] = useState(false);
  return (
    <TooltipProvider>
      <Button onClick={() => setOpen(true)}>Rename</Button>
      <Dialog open={open} onOpenChange={setOpen} title="Rename agent" footer={<Button onClick={() => setOpen(false)}>Done</Button>}>
        <Input aria-label="New name" />
      </Dialog>
    </TooltipProvider>
  );
}

describe("Dialog focus", () => {
  it("starts on the first control in the body, not the close button, and returns to the opener on Escape", async () => {
    const user = userEvent.setup();
    render(<DialogHarness />);
    const opener = screen.getByRole("button", { name: "Rename" });
    await user.click(opener);
    const dialog = await screen.findByRole("dialog", { name: "Rename agent" });
    await waitFor(() => expect(screen.getByRole("textbox", { name: "New name" })).toHaveFocus());
    await user.keyboard("{Escape}");
    await waitFor(() => expect(dialog).not.toBeInTheDocument());
    await waitFor(() => expect(opener).toHaveFocus());
  });

  it("returns focus to the menu's trigger when a menu item opened it", async () => {
    function MenuHarness() {
      const [open, setOpen] = useState(false);
      return (
        <TooltipProvider>
          <Menu>
            <MenuTrigger asChild>
              <Button>More</Button>
            </MenuTrigger>
            <MenuContent>
              <MenuItem onSelect={() => setOpen(true)}>Import</MenuItem>
            </MenuContent>
          </Menu>
          <Dialog open={open} onOpenChange={setOpen} title="Import cases">
            <Input aria-label="File name" />
          </Dialog>
        </TooltipProvider>
      );
    }
    const user = userEvent.setup();
    render(<MenuHarness />);
    const trigger = screen.getByRole("button", { name: "More" });
    trigger.focus();
    await user.keyboard("{Enter}");
    await user.click(await screen.findByRole("menuitem", { name: "Import" }));
    const dialog = await screen.findByRole("dialog", { name: "Import cases" });
    await user.keyboard("{Escape}");
    await waitFor(() => expect(dialog).not.toBeInTheDocument());
    await waitFor(() => expect(trigger).toHaveFocus());
  });
});

describe("Button pending", () => {
  it("stays focused and announced as unavailable, and ignores clicks", async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(<Button onClick={onClick}>Save</Button>);
    const button = screen.getByRole("button", { name: "Save" });
    button.focus();
    rerender(
      <Button onClick={onClick} pending>
        Save
      </Button>,
    );
    expect(button).toHaveFocus();
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(button).not.toBeDisabled();
    await user.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("an explicitly disabled button is still disabled", () => {
    render(
      <Button pending disabled>
        Save
      </Button>,
    );
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });
});
