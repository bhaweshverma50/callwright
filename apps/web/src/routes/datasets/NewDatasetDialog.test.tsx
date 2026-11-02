import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { sim } from "../../mocks/sim/store";
import { renderApp, signInDemo } from "../../test/render";

const creates = () => sim().bodies.filter((b) => b.path === "/datasets");

async function openForm() {
  await signInDemo();
  const user = userEvent.setup();
  const app = renderApp("/datasets");
  await screen.findByRole("link", { name: /Hard cases/ }, { timeout: 5000 });
  await user.click(screen.getByRole("button", { name: "New dataset" }));
  const dialog = await screen.findByRole("dialog", { name: "New dataset" });
  return { user, dialog, ...app };
}

describe("New dataset form (T095, FR-036)", () => {
  it("shows a message under each missing field and sends nothing", async () => {
    const { user, dialog } = await openForm();
    await user.click(within(dialog).getByRole("button", { name: "Create" }));
    expect(within(dialog).getByRole("textbox", { name: "Name" })).toHaveAttribute("aria-invalid", "true");
    expect(
      within(dialog)
        .getAllByRole("alert")
        .map((a) => a.textContent),
    ).toEqual(["Enter a name", "Choose an agent"]);
    expect(within(dialog).getByRole("combobox", { name: "Agent" })).toHaveAttribute("aria-invalid", "true");
    expect(creates()).toHaveLength(0);

    await user.type(within(dialog).getByRole("textbox", { name: "Name" }), "Reschedules");
    await user.click(within(dialog).getByRole("button", { name: "Create" }));
    expect(
      within(dialog)
        .getAllByRole("alert")
        .map((a) => a.textContent),
    ).toEqual(["Choose an agent"]);
    expect(creates()).toHaveLength(0);
  });

  it("shows a name already in use (any case) under the name", async () => {
    const { user, dialog } = await openForm();
    const name = within(dialog).getByRole("textbox", { name: "Name" });
    await user.type(name, "hard cases");
    await user.click(within(dialog).getByRole("combobox", { name: "Agent" }));
    await user.click(await screen.findByRole("option", { name: "Front desk agent" }));
    await user.click(within(dialog).getByRole("button", { name: "Create" }));
    await waitFor(() => expect(name).toHaveAttribute("aria-invalid", "true"));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("already in use");
    expect(name.getAttribute("aria-describedby")).toBe(within(dialog).getByRole("alert").id);
    expect(creates()).toHaveLength(1);
  });

  it("creates a dataset and opens it", async () => {
    const { user, dialog, router } = await openForm();
    await user.type(within(dialog).getByRole("textbox", { name: "Name" }), "Insurance calls");
    await user.click(within(dialog).getByRole("combobox", { name: "Agent" }));
    await user.click(await screen.findByRole("option", { name: "Billing line" }));
    await user.click(within(dialog).getByRole("button", { name: "Create" }));
    await waitFor(() => expect(router.state.location.pathname).toMatch(/^\/datasets\/ds_/));
    expect(await screen.findByRole("heading", { name: "Insurance calls" })).toBeInTheDocument();
  });
});

describe("Dataset items (T095)", () => {
  it("loads items page by page with the total and marks unavailable calls", async () => {
    await signInDemo();
    const user = userEvent.setup();
    renderApp("/datasets");
    await user.click(await screen.findByRole("link", { name: /October regression suite/ }, { timeout: 5000 }));
    const nav = await screen.findByRole("navigation", { name: "Pagination" }, { timeout: 5000 });
    expect(nav).toHaveTextContent("1 to 50 of 240 calls");
    expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(51);
    expect(within(screen.getByRole("table")).getAllByText("Unavailable")).toHaveLength(2);
    await user.click(within(nav).getByRole("button", { name: "Next" }));
    await waitFor(() => expect(screen.getByRole("navigation", { name: "Pagination" })).toHaveTextContent("51 to 100 of 240 calls"));
    expect(sim().requests.some((r) => /GET \/datasets\/ds_\w+\/items\?page=2&page_size=50/.test(r))).toBe(true);
  });
});
