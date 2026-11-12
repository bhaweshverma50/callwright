import { useMutation } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useState } from "react";
import { deleteSource, type KnowledgeSource } from "../../../api/knowledge";
import { problemMessage } from "../../../api/problems";
import { Button, ChoiceGroup, Dialog, toast } from "../../../components";

/** Remove a Drive source, keeping its documents as ordinary uploads or archiving them (FR-018). */
export function RemoveSourceDialog({
  open,
  onOpenChange,
  kbId,
  source,
  onRemoved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  kbId: string;
  source: KnowledgeSource;
  onRemoved: () => void;
}) {
  const [documents, setDocuments] = useState<"keep" | "archive">("keep");
  const remove = useMutation({
    mutationFn: () => deleteSource(kbId, source.id, documents),
    onSuccess: () => {
      onOpenChange(false);
      onRemoved();
      toast({
        tone: "success",
        title: "Source removed",
        description: documents === "keep" ? "Its documents are now ordinary uploads." : "Its documents were archived for 30 days.",
      });
    },
  });
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !remove.isPending && onOpenChange(o)}
      role="alertdialog"
      size="sm"
      icon={<Trash2 />}
      title={`Remove ${source.root_name}?`}
      description="Callwright stops syncing this folder. Choose what happens to its documents."
      footer={
        <>
          <Button autoFocus onClick={() => onOpenChange(false)} disabled={remove.isPending}>
            Cancel
          </Button>
          <Button variant="danger" pending={remove.isPending} onClick={() => remove.mutate()}>
            Remove source
          </Button>
        </>
      }
    >
      <ChoiceGroup<"keep" | "archive">
        aria-label="Documents from this source"
        columns={1}
        size="sm"
        value={documents}
        onValueChange={setDocuments}
        options={[
          { value: "keep", title: "Keep the documents", description: "They stay searchable as uploads you can replace or delete." },
          { value: "archive", title: "Archive the documents", description: "They leave search and can be restored for 30 days." },
        ]}
      />
      {remove.error && (
        <p role="alert" className="mt-3 text-[13px] text-danger-text">
          {problemMessage(remove.error, "source")}
        </p>
      )}
    </Dialog>
  );
}
