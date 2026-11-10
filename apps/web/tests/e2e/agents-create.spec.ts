import { expect, test } from "@playwright/test";
import { signIn } from "./helpers";

// T031 (US1) and T051 (US2) against the mock API.
test("create a single-prompt agent: chooser, error summary, fixed temperature, variables, leave guard, save, reload", async ({ page }) => {
  await signIn(page, "/agents");
  await page.getByRole("link", { name: "New agent" }).click();
  await expect(page.getByText("The type cannot be changed later.")).toBeVisible();
  await expect(page.getByRole("radio", { name: /^Single prompt/ })).toHaveAttribute("aria-checked", "true");
  await page.getByRole("button", { name: "Continue with single prompt" }).click();
  await expect(page).toHaveURL(/\/agents\/templates$/);
  await page.getByRole("link", { name: /Start from scratch/ }).click();
  await expect(page).toHaveURL(/\/agents\/new\/single$/);

  // Every problem at once, nothing created.
  await page.getByRole("button", { name: "Create agent" }).click();
  const summary = page.getByRole("dialog", { name: "Fix these before creating the agent" });
  await expect(summary).toBeVisible();
  await expect(summary.getByText("Agent name", { exact: true })).toBeVisible();
  await expect(summary.getByText("System prompt", { exact: true })).toBeVisible();
  await summary.getByRole("button", { name: /System prompt/ }).click();
  await expect(page.getByLabel("System prompt")).toBeFocused();

  // Fixed temperature is locked with the reason.
  await expect(page.locator("#f-llm-temperature")).toHaveAttribute("data-disabled", "");
  await expect(page.getByText("This model only supports temperature 1.0.")).toBeVisible();

  await page.getByLabel("Agent name").fill("Clinic desk");
  await page.getByLabel("System prompt").fill("Hello {{customer_name}}, about order {{ order_id }}.");
  await expect(page.getByText("{{customer_name}}", { exact: true })).toBeVisible();
  await expect(page.getByText("{{order_id}}", { exact: true })).toBeVisible();

  // A never-saved form is guarded too.
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Billing" }).click();
  const guard = page.getByRole("alertdialog", { name: "Leave without saving?" });
  await expect(guard).toBeVisible();
  await guard.getByRole("button", { name: "Stay" }).click();
  await expect(page).toHaveURL(/\/agents\/new\/single$/);

  await page.getByRole("button", { name: "Create agent" }).click();
  await expect(page.getByText("Agent created", { exact: true }).first()).toBeVisible();
  await expect(page).toHaveURL(/\/agents\/agt_[0-9A-Z]{26}\/edit$/);
  await expect(page.getByText("Version 1", { exact: true })).toBeVisible();

  await page.reload();
  await expect(page.getByLabel("Agent name")).toHaveValue("Clinic desk");
  await expect(page.getByLabel("System prompt")).toHaveValue("Hello {{customer_name}}, about order {{ order_id }}.");
  await expect(page.getByRole("textbox", { name: "Default for order_id" })).toBeVisible();
});

test("use a template: preview creates nothing until Use template", async ({ page }) => {
  await signIn(page, "/agents/templates");
  await page
    .getByRole("group", { name: "Industry" })
    .getByRole("button", { name: /Healthcare/ })
    .click();
  await expect(page.getByRole("button", { name: /Loan payment reminder/ })).toHaveCount(0);
  await page.getByRole("button", { name: /Pre-visit patient check-in/ }).click();
  const dialog = page.getByRole("dialog", { name: "Pre-visit patient check-in" });
  await expect(dialog.getByText("{{patient_name}}").first()).toBeVisible();
  await dialog.getByRole("button", { name: "Use template" }).dblclick();
  await expect(page).toHaveURL(/\/agents\/agt_[0-9A-Z]{26}\/edit$/);
  await expect(page.getByLabel("Agent name")).toHaveValue("Pre-visit patient check-in");
  await expect(page.getByRole("textbox", { name: "Default for patient_name" })).toHaveValue("Maria Gomez");
  await page.getByRole("link", { name: "Agents" }).first().click();
  await expect(page.getByRole("link", { name: "Pre-visit patient check-in" })).toHaveCount(1);
});

test("find, duplicate and delete agents", async ({ page }) => {
  await signIn(page, "/agents");
  const all = (n: number) => page.getByRole("tab", { name: new RegExp(`^All\\s*${n}$`) });
  await expect(all(4)).toBeVisible();
  await page.getByLabel("Search agents by name or agent ID").fill("desk");
  await expect(page.getByRole("link", { name: "Front desk agent" })).toBeVisible();
  await expect(all(1)).toBeVisible();
  await page.getByLabel("Search agents by name or agent ID").fill("zzz");
  await expect(page.getByRole("heading", { name: 'No agents match "zzz"' })).toBeVisible();
  await page.getByRole("button", { name: "Show all agents" }).click();
  await expect(all(4)).toBeVisible();

  await page.getByRole("button", { name: "Actions for Front desk agent" }).click();
  await page.getByRole("menuitem", { name: "Duplicate…" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Duplicate and open" }).dblclick();
  await expect(page.getByText("Agent duplicated", { exact: true }).first()).toBeVisible();
  await expect(page).toHaveURL(/\/agents\/agt_[0-9A-Z]{26}\/edit$/);
  await page.getByRole("link", { name: "Agents" }).first().click();
  await expect(page.getByRole("link", { name: "Front desk agent (copy)" })).toHaveCount(1);
  await expect(all(5)).toBeVisible();

  await page.getByRole("button", { name: "Actions for Front desk agent (copy)" }).click();
  await page.getByRole("menuitem", { name: "Delete" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Delete agent" }).click();
  await expect(page.getByText("Agent deleted", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("link", { name: "Front desk agent (copy)" })).toHaveCount(0);

  // Still attached to a phone number: refused with the attachment.
  await page.getByRole("button", { name: "Actions for Billing line" }).click();
  await page.getByRole("menuitem", { name: "Delete" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Delete agent" }).click();
  await expect(page.getByRole("dialog", { name: "Billing line is still taking calls" })).toBeVisible();
  await expect(page.getByText("+1 (415) 555-0142")).toBeVisible();
});
