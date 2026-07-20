"use client";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { Download, Eye, MoreHorizontal, Pencil, Trash2 } from "lucide-react";

export interface ResourceAction {
  view?: () => void;
  edit?: () => void;
  /** Opens a ConfirmDialog owned by the caller. */
  delete?: () => void;
  /** Download hrefs per format (anchors to the download proxy with ?fmt=). */
  download?: { docx?: string; pdf?: string };
}

/**
 * Consistent row-actions affordance for any resource: a `MoreHorizontal`
 * trigger opening a dropdown whose items are the enabled subset of
 * view / edit / delete / download. A missing handler => that item is not
 * rendered, so future resources get CRUD-for-free by passing props.
 */
export function ResourceRowActions({
  actions,
  label = "item",
}: {
  actions: ResourceAction;
  label?: string;
}) {
  const hasDownload =
    !!actions.download && (!!actions.download.docx || !!actions.download.pdf);
  const hasAny =
    !!actions.view || !!actions.edit || !!actions.delete || hasDownload;

  if (!hasAny) return null;

  const hasDestructiveSeparator =
    !!actions.delete && (!!actions.view || !!actions.edit || hasDownload);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label={`${label} actions`}>
          <MoreHorizontal />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        {actions.view ? (
          <DropdownMenuItem onSelect={() => actions.view?.()}>
            <Eye />
            View
          </DropdownMenuItem>
        ) : null}
        {actions.edit ? (
          <DropdownMenuItem onSelect={() => actions.edit?.()}>
            <Pencil />
            Edit
          </DropdownMenuItem>
        ) : null}
        {actions.download?.docx ? (
          <DropdownMenuItem asChild>
            <a href={actions.download.docx} download>
              <Download />
              Download .docx
            </a>
          </DropdownMenuItem>
        ) : null}
        {actions.download?.pdf ? (
          <DropdownMenuItem asChild>
            <a href={actions.download.pdf} download>
              <Download />
              Download .pdf
            </a>
          </DropdownMenuItem>
        ) : null}
        {hasDestructiveSeparator ? <DropdownMenuSeparator /> : null}
        {actions.delete ? (
          <DropdownMenuItem
            variant="destructive"
            onSelect={() => actions.delete?.()}
          >
            <Trash2 />
            Delete
          </DropdownMenuItem>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
