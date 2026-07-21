// 文件说明：前端采集任务组件；当前文件：task delete confirm dialog
"use client";

import { Loader2, X } from "lucide-react";

import { Button } from "@/components/ui/button";

type TaskDeleteConfirmDialogProps = {
  open: boolean;
  title: string;
  body: string;
  confirmLabel?: string;
  loading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

export function TaskDeleteConfirmDialog({
  open,
  title,
  body,
  confirmLabel = "删除",
  loading = false,
  onConfirm,
  onCancel,
}: TaskDeleteConfirmDialogProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-3 sm:p-4">
      <div
        className="w-full max-w-md rounded-lg border bg-background p-5 shadow-lg"
        role="dialog"
        aria-modal="true"
        aria-labelledby="task-delete-title"
      >
        <div className="flex items-start justify-between gap-3">
          <h2 id="task-delete-title" className="text-base font-semibold">
            {title}
          </h2>
          <button
            type="button"
            className="rounded p-1 text-muted-foreground hover:bg-muted"
            aria-label="关闭"
            onClick={onCancel}
            disabled={loading}
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className="mt-3 whitespace-pre-line text-sm text-muted-foreground">{body}</p>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="outline" onClick={onCancel} disabled={loading}>
            取消
          </Button>
          <Button variant="destructive" onClick={onConfirm} disabled={loading}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
