import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { describe, expect, it } from "vitest";
import type { KbDocument } from "../../../api/knowledge";
import { connectorStore, seedConnection, seedSource } from "../../../mocks/connectors/store";
import { json, url } from "../../../mocks/http";
import { server } from "../../../mocks/node";
import { seedKb, toolStore } from "../../../mocks/tools";
import { renderApp, signInDemo } from "../../../test/render";

function syncedDoc(kbId: string, sourceId: string, over: Partial<KbDocument> = {}): KbDocument {
  const doc: KbDocument = {
    id: `doc_01J${String(toolStore.docs.length + 100).padStart(23, "0")}`,
    kb_id: kbId,
    file_name: "Clinic hours.docx",
    display_name: "Clinic hours",
    file_type: "docx",
    file_size: 20_000,
    sha256: "a".repeat(64),
    status: "ready",
    error_code: null,
    error_message: null,
    page_count: null,
    chunk_count: 3,
    replaces_doc_id: null,
    created_at: new Date().toISOString(),
    processed_at: new Date().toISOString(),
    archived_at: null,
    managed: true,
    source: { source_id: sourceId, root_name: "Clinic policies", path: "2026", web_view_link: "https://docs.google.com/document/d/x/edit" },
    ...over,
  };
  toolStore.docs.unshift(doc);
  return doc;
}

describe("Google Drive sources on a knowledge base (022 US2 to US5)", () => {
  it("adds a Drive folder through the folder browser", async () => {
    await signInDemo();
    seedConnection();
    const kb = seedKb("Clinic policies");
    const user = userEvent.setup();
    renderApp(`/knowledge-base/${kb.id}`);
    await user.click((await screen.findAllByRole("button", { name: "Add Google Drive source" }))[0]!);
    const dialog = await screen.findByRole("dialog", { name: "Add a Google Drive source" });
    expect(within(dialog).getByText("Team drive")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: /Clinic policies/ }));
    expect(within(dialog).getByRole("button", { name: /2026/ })).toBeInTheDocument();
    expect(within(dialog).getByRole("switch")).toBeChecked();
    await user.click(within(dialog).getByRole("button", { name: "Sync Clinic policies" }));
    expect(await screen.findByText("Drive source added")).toBeInTheDocument();
    expect(connectorStore.sources).toHaveLength(1);
    expect(connectorStore.sources[0]!.root_id).toBe("fld_clinic");
  });

  it("asks to connect Google first when there is no connection", async () => {
    await signInDemo();
    const kb = seedKb("Clinic policies");
    const user = userEvent.setup();
    renderApp(`/knowledge-base/${kb.id}`);
    await user.click((await screen.findAllByRole("button", { name: "Add Google Drive source" }))[0]!);
    expect(await screen.findByText("Connect Google first")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to Connections" })).toHaveAttribute("href", "/settings/connections");
  });

  it("shows synced documents with their Drive origin and no Delete", async () => {
    await signInDemo();
    const kb = seedKb("Clinic policies");
    const src = seedSource(kb.id, { document_count: 1 });
    syncedDoc(kb.id, src.id);
    renderApp(`/knowledge-base/${kb.id}`);
    expect((await screen.findAllByText("Google Drive")).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: /Open in Drive/ })[0]).toHaveAttribute("href", "https://docs.google.com/document/d/x/edit");
    expect(screen.queryByRole("button", { name: "Delete Clinic hours" })).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Source Clinic policies" })).toBeInTheDocument();
  });

  it("starts a sync and changes the schedule", async () => {
    await signInDemo();
    const kb = seedKb("Clinic policies");
    const src = seedSource(kb.id);
    const user = userEvent.setup();
    renderApp(`/knowledge-base/${kb.id}`);
    const card = await screen.findByRole("region", { name: "Source Clinic policies" });
    await user.click(within(card).getByRole("button", { name: "Sync now" }));
    expect(await screen.findByText("Sync started")).toBeInTheDocument();
    expect(connectorStore.runs.filter((r) => r.source_id === src.id)).toHaveLength(2);
    await user.click(within(card).getByRole("combobox", { name: "Sync schedule" }));
    await user.click(await screen.findByRole("option", { name: "Every hour" }));
    await waitFor(() => expect(connectorStore.sources[0]!.interval_minutes).toBe(60));
  });

  it("holds mass archiving for a decision", async () => {
    await signInDemo();
    const kb = seedKb("Clinic policies");
    seedSource(kb.id, {
      state: "needs_attention",
      attention_reason: "mass_archive",
      attention_message: "This sync would archive 25 of 100 documents",
      held_archive: { would_archive: 25, of: 100 },
    });
    const user = userEvent.setup();
    renderApp(`/knowledge-base/${kb.id}`);
    expect(await screen.findByText("This sync would archive 25 of 100 documents.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Keep them" }));
    expect(await screen.findByText("Archiving cancelled")).toBeInTheDocument();
    expect(connectorStore.sources[0]!.held_archive).toBeNull();
  });

  it("links to Connections when access is lost", async () => {
    await signInDemo();
    const kb = seedKb("Clinic policies");
    seedSource(kb.id, {
      state: "needs_attention",
      attention_reason: "access_lost",
      attention_message: "Access to this folder was lost. Reconnect the Google account or share the folder again",
    });
    renderApp(`/knowledge-base/${kb.id}`);
    expect(await screen.findByRole("link", { name: "Reconnect in Connections" })).toHaveAttribute("href", "/settings/connections");
  });

  it("removes a source and keeps its documents", async () => {
    await signInDemo();
    const kb = seedKb("Clinic policies");
    seedSource(kb.id);
    const user = userEvent.setup();
    renderApp(`/knowledge-base/${kb.id}`);
    await user.click(await screen.findByRole("button", { name: "Remove source Clinic policies" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Remove Clinic policies?" });
    await user.click(within(dialog).getByRole("button", { name: "Remove source" }));
    expect(await screen.findByText("Source removed")).toBeInTheDocument();
    expect(connectorStore.sources).toHaveLength(0);
  });

  it("shows sync history with run details", async () => {
    await signInDemo();
    const kb = seedKb("Clinic policies");
    const src = seedSource(kb.id, { document_count: 10 });
    connectorStore.runs[0]!.errors = [
      {
        drive_file_id: "x",
        name: "Slots",
        path: "",
        web_view_link: null,
        state: "skipped",
        reason: "unsupported_type",
        duplicate_of_doc_id: null,
        message: null,
      },
    ];
    connectorStore.runs[0]!.counts.skipped = 1;
    const user = userEvent.setup();
    renderApp(`/knowledge-base/${kb.id}`);
    const card = await screen.findByRole("region", { name: `Source ${src.root_name}` });
    await user.click(within(card).getByRole("button", { name: "History" }));
    const runs = await screen.findByRole("list", { name: "Sync runs" });
    expect(within(runs).getByText(/First sync/)).toBeInTheDocument();
    expect(within(runs).getByText("10 added, 1 skipped")).toBeInTheDocument();
    await user.click(within(runs).getByRole("button"));
    expect(await screen.findByText("Not a Google Doc, PDF or Word file")).toBeInTheDocument();
  });

  it("restores an archived document from the Archived tab", async () => {
    await signInDemo();
    const kb = seedKb("Clinic policies");
    const src = seedSource(kb.id);
    syncedDoc(kb.id, src.id, { status: "archived", archived_at: new Date(Date.now() - 5 * 86_400_000).toISOString() });
    const user = userEvent.setup();
    renderApp(`/knowledge-base/${kb.id}`);
    await user.click(await screen.findByRole("tab", { name: /Archived/ }));
    expect(await screen.findByText("25 days")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Restore" }));
    expect(await screen.findByText("Document restored")).toBeInTheDocument();
    expect(toolStore.docs[0]!.status).toBe("ready");
  });
});

describe("Kept documents (022 T066)", () => {
  it("shows a file-missing badge and archives a kept document", async () => {
    await signInDemo();
    const kb = seedKb("Clinic policies");
    const src = seedSource(kb.id);
    syncedDoc(kb.id, src.id, {
      source: { source_id: src.id, root_name: "Clinic policies", path: "", web_view_link: null, file_missing: true },
    });
    let archived = "";
    server.use(
      http.post(url("/knowledge-bases/:kbId/documents/:docId/archive"), ({ params }) => {
        archived = String(params.docId);
        const doc = toolStore.docs.find((d) => d.id === params.docId)!;
        Object.assign(doc, { status: "archived", archived_at: new Date().toISOString() });
        return json(doc);
      }),
    );
    const user = userEvent.setup();
    renderApp(`/knowledge-base/${kb.id}`);
    expect((await screen.findAllByText("File missing in Drive")).length).toBeGreaterThan(0);
    await user.click(screen.getAllByRole("button", { name: "Archive" })[0]!);
    expect(await screen.findByText("Document archived")).toBeInTheDocument();
    expect(archived).toBe(toolStore.docs[0]!.id);
  });
});
