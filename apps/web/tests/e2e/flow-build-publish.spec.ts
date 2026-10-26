import { expect, test } from "@playwright/test";
import { signUp } from "./real";

// 004 T094 (US1, US2): create a flow agent, add a step, see and fix the validation error it
// causes, then publish. Real API only.
test("create a flow agent, fix a validation error and publish", async ({ page, request }) => {
  await signUp(page, request);
  await page.goto("/agents/new/flow");
  await page.getByLabel("Agent name").fill("Clinic intake");
  await page.getByRole("button", { name: "Create and open the canvas" }).click();
  await page.waitForURL(/\/agents\/agt_[0-9A-Z]+\/flow$/);
  await expect(page.locator(".react-flow__node")).toHaveCount(3);

  // A Say step with no message and no connection is an error.
  await page.getByRole("button", { name: "Add step", exact: true }).click();
  await page.getByRole("button", { name: "Add Say" }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(4);
  await page.getByRole("button", { name: "Close settings" }).click();
  await page.getByRole("tab", { name: /Problems/ }).click();
  await expect(page.getByText("Write the message this node says.")).toBeVisible();

  // Fix it by deleting the step (Delete key, with an Undo notice).
  await page.locator(".react-flow__node", { hasText: "Say" }).click();
  await page.getByRole("button", { name: "Close settings" }).click();
  await page.locator(".react-flow__node", { hasText: "Say" }).click();
  await page.keyboard.press("Delete");
  await expect(page.getByText("Deleted 1 step").first()).toBeVisible();
  await expect(page.locator(".react-flow__node")).toHaveCount(3);
  await page.getByRole("tab", { name: /Problems/ }).click();
  await expect(page.getByText("No problems. Ready to publish.")).toBeVisible();

  // Back to what was saved, so nothing is left to save.
  await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Publish", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Publish", exact: true }).click();
  await expect(page.getByText(/Published version \d+/).first()).toBeVisible();
  await expect(page.getByText(/Live on version \d+/)).toBeVisible();
});
