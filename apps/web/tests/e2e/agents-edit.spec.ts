import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./helpers";

async function openFrontDesk(page: Page) {
  await signIn(page, "/agents");
  await page.getByRole("link", { name: "Front desk agent" }).click();
  await expect(page).toHaveURL(/\/edit$/);
  await expect(page.getByLabel("Agent name")).toHaveValue("Front desk agent");
}

// T092 (US1.9 to US1.14): inline errors on blur, Save sends nothing while errors remain.
test("inline validation blocks the save without a request", async ({ page }) => {
  await openFrontDesk(page);
  const saves: string[] = [];
  page.on("request", (r) => r.method() === "PUT" && r.url().includes("/draft") && saves.push(r.url()));

  await page.getByRole("tab", { name: "Advanced" }).click();
  await page.getByLabel("Webhook address", { exact: true }).fill("notaurl");
  await page.getByLabel("Webhook address", { exact: true }).blur();
  await expect(page.getByText(/Enter a full address that starts with https/)).toBeVisible();
  await page.getByLabel("Webhook timeout", { exact: true }).fill("0.05");
  await page.getByLabel("Webhook timeout", { exact: true }).blur();
  await expect(page.getByText("Webhook timeout must be between 1 and 30 seconds.")).toBeVisible();

  await page.getByRole("tab", { name: "Call behaviour" }).click();
  const max = page.getByLabel("Maximum call duration", { exact: true });
  await max.fill("0.2");
  await max.blur();
  await expect(page.getByText("Maximum call duration must be between 30 seconds and 60 minutes.")).toBeVisible();
  await max.fill("61");
  await max.blur();
  await expect(page.getByText("Maximum call duration must be between 30 seconds and 60 minutes.")).toBeVisible();
  await page.getByLabel("Ring time", { exact: true }).fill("-1");
  await page.getByLabel("Ring time", { exact: true }).blur();
  await expect(page.getByText("Ring time must be between 0 and 30 seconds.")).toBeVisible();
  // Exact readings for valid values.
  await page.getByLabel("Ring time", { exact: true }).fill("1.5");
  await expect(page.getByText("Rings for 1.5 s before the agent answers.")).toBeVisible();

  await page.getByRole("button", { name: "Save", exact: true }).click();
  const summary = page.getByRole("dialog", { name: "Fix these before saving" });
  await expect(summary.getByText("Webhook address", { exact: true })).toBeVisible();
  await expect(summary.getByText("Maximum call duration", { exact: true })).toBeVisible();
  await expect(summary.getByText("Webhook timeout", { exact: true })).toBeVisible();
  expect(saves).toEqual([]);
});

test("variables, greeting, provider switch and a saved version", async ({ page }) => {
  await openFrontDesk(page);
  // A hand-typed name must follow the rule.
  await page.getByLabel("New variable name").fill("bad name!");
  await page.getByRole("button", { name: "Add variable" }).click();
  await expect(page.getByText(/Use letters, digits and underscores/)).toBeVisible();

  // Caller first: the greeting is kept but not used.
  await page.getByRole("radio", { name: "Caller" }).click();
  await expect(page.getByLabel("Greeting", { exact: true })).toBeDisabled();
  await expect(page.getByLabel("Greeting", { exact: true })).toHaveValue("Thanks for calling Halcyon Dental. How can I help you today?");
  await expect(page.getByText(/Not spoken while the caller speaks first/)).toBeVisible();
  await page.getByRole("radio", { name: "Agent" }).click();

  // Switching voice provider picks that provider's default voice for the language.
  await page.getByRole("tab", { name: "Voice and speech" }).click();
  await page.getByLabel("Voice provider", { exact: true }).click();
  await page.getByRole("option", { name: "Cartesia" }).click();
  await expect(page.getByText("Voice set to Skylar, Cartesia's default for English (US).")).toBeVisible();

  await page.getByLabel("Note for this version").fill("Try Cartesia");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Saved as version 4").first()).toBeVisible();
  await expect(page.getByText("All changes saved in version 4")).toBeVisible();
});
