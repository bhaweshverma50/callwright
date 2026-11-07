import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BookPlus } from "lucide-react";
import { useEffect, useState } from "react";
import { api, unwrap } from "../../api/client";
import { isApiError } from "../../api/errors";
import type { KnowledgeBase } from "../../api/knowledge";
import { problemMessage } from "../../api/problems";
import { Button, Dialog, Field, Input, Textarea } from "../../components";
import { kbKeys } from "../../api/knowledge";

/** Create (or rename) a knowledge base. The description helps the agent decide when to search it. */
export function CreateKbDialog({
  open,
  onOpenChange,
  onCreated,
  existing,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (kb: KnowledgeBase) => void;
  existing?: KnowledgeBase;
}) {
  const qc = useQueryClient();
  const [name, setName] = useState(existing?.name ?? "");
  const [description, setDescription] = useState(existing?.description ?? "");
  const [nameError, setNameError] = useState<string | null>(null);
  useEffect(() => {
    if (open) {
      setName(existing?.name ?? "");
      setDescription(existing?.description ?? "");
      setNameError(null);
    }
  }, [open, existing]);

  const save = useMutation({
    mutationFn: async () => {
      const body = { name: name.trim(), description: description.trim() };
      return (await unwrap(
        existing ? api.PATCH("/knowledge-bases/{kb_id}", { params: { path: { kb_id: existing.id } }, body }) : api.POST("/knowledge-bases", { body }),
      )) as KnowledgeBase;
    },
    onSuccess: (kb) => {
      void qc.invalidateQueries({ queryKey: kbKeys.all });
      onCreated(kb);
      onOpenChange(false);
    },
    onError: (e) =>
      setNameError(isApiError(e) && e.status === 409 ? "A knowledge base with this name already exists." : problemMessage(e, "knowledge base")),
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !save.isPending && onOpenChange(o)}
      icon={<BookPlus />}
      title={existing ? "Rename knowledge base" : "New knowledge base"}
      description={existing ? undefined : "A named set of documents. Agents you attach it to can search it during calls."}
      footer={
        <>
          <Button onClick={() => onOpenChange(false)} disabled={save.isPending}>
            Cancel
          </Button>
          <Button variant="primary" pending={save.isPending} disabled={!name.trim()} onClick={() => save.mutate()}>
            {existing ? "Save" : "Create"}
          </Button>
        </>
      }
    >
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) save.mutate();
        }}
      >
        <Field label="Name" error={nameError}>
          {({ id, describedBy, invalid }) => (
            <Input
              id={id}
              autoFocus
              maxLength={120}
              placeholder="Clinic policies"
              aria-describedby={describedBy}
              aria-invalid={invalid}
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setNameError(null);
              }}
            />
          )}
        </Field>
        <Field label="What is in it" hint="Optional. The agent reads this to decide when to search, so name the topics.">
          {({ id, describedBy }) => (
            <Textarea
              id={id}
              maxLength={500}
              className="min-h-20"
              placeholder="Refunds, cancellations, opening hours and prices"
              aria-describedby={describedBy}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          )}
        </Field>
        <button type="submit" hidden />
      </form>
    </Dialog>
  );
}
