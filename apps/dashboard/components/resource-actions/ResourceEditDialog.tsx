"use client";

import { useState } from "react";
import {
  Sheet,
  SheetContent,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { MarkdownDocument } from "@/components/MarkdownDocument";

/**
 * Reusable content-edit panel. A title `Input` + a markdown `Textarea` for the
 * body, with a live preview rendered through the Phase 1 `MarkdownDocument`
 * viewer so what the user edits matches how it renders. Calls `onSave` with the
 * edited fields. A side panel, not a centered modal, so the list/page you
 * opened it from stays visible for reference while editing.
 */
export function ResourceEditDialog({
  open,
  onOpenChange,
  initial,
  onSave,
  pending = false,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initial: { title: string; content_md: string };
  onSave: (fields: { title: string; content_md: string }) => void;
  pending?: boolean;
}) {
  const [title, setTitle] = useState(initial.title);
  const [contentMd, setContentMd] = useState(initial.content_md);
  const [showPreview, setShowPreview] = useState(false);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Edit content</SheetTitle>
        </SheetHeader>

        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="resource-edit-title">Title</Label>
            <Input
              id="resource-edit-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>

          <div className="flex min-h-0 flex-1 flex-col gap-1.5">
            <div className="flex items-center justify-between">
              <Label htmlFor="resource-edit-body">Content (Markdown)</Label>
              <button
                type="button"
                className="text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
                onClick={() => setShowPreview((v) => !v)}
              >
                {showPreview ? "Edit" : "Preview"}
              </button>
            </div>
            {showPreview ? (
              <div className="flex-1 overflow-auto rounded-md border p-3">
                <MarkdownDocument text={contentMd} />
              </div>
            ) : (
              <Textarea
                id="resource-edit-body"
                value={contentMd}
                onChange={(e) => setContentMd(e.target.value)}
                className="flex-1 resize-none font-mono text-xs"
              />
            )}
          </div>
        </div>

        <SheetFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={pending}
          >
            Cancel
          </Button>
          <Button
            onClick={() => onSave({ title, content_md: contentMd })}
            disabled={pending}
          >
            Save
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
