# Knowledge Base (`/knowledge-base`)

Live walkthrough, 2026-10-16 (no documents). Screens: `screens/kb-*`, and the flow-level attach dialog `screens/gs-kb-attach-source.png`.

## Page

- Eyebrow "KNOWLEDGE", title "Give agents memory.", subtitle "Upload PDFs and docs - agents retrieve passages live during calls with RAG."
- Button **Upload document**. Empty state "No documents yet / Upload PDF or DOCX files to give your agents RAG-based knowledge." with a second button "Upload your first document" (opens the same dialog).
- GET `/knowledge-bases` returns `[]`.

## Upload Document dialog

| Control | Type | Details |
|---|---|---|
| Document Name | text | free text, no placeholder |
| Drop zone | click or drag | "Drag & drop or click to select (PDF, DOCX - max 20 MB)". Click opens a file chooser (`accept=".pdf,.docx"`, single file). |
| Cancel | button | |
| Upload | button | disabled until a file is selected (a name alone keeps it disabled) |

Not tested (would require choosing a file): size/type error messages, duplicate-name check, progress bar. The bundle-derived messages are in the functional spec section 4.

## Attaching to a flow agent

Flow Global Settings, Knowledge Base, "+ Attach source" opens "Select Knowledge Bases": search box + checklist of existing documents ("No knowledge bases found"), Cancel / Confirm. Confirm is enabled with nothing selected and sends POST `/knowledge-bases/agents/{agent_id}` `{kb_ids:[]}`. There is no upload, Markdown or URL source option anywhere in the UI, even though the flow empty state says "Upload PDFs, Markdown files, or paste a URL".

No chunking, embedding model, top-k, re-index or per-document enable controls exist.
