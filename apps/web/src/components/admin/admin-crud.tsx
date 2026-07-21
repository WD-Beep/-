// 文件说明：前端管理员后台组件；当前文件：admin crud
"use client";

import { useRouter } from "next/navigation";
import { ArrowLeft, Pencil, Trash2 } from "lucide-react";

import { AdminActionButton } from "@/components/admin/admin-ui";
import { cn } from "@/lib/utils";

export function AdminBackButton({
  fallbackHref,
  className,
  label = "返回上一页",
}: {
  fallbackHref: string;
  className?: string;
  label?: string;
}) {
  const router = useRouter();

  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={() => {
        if (typeof window !== "undefined" && window.history.length > 1) {
          router.back();
          return;
        }
        router.push(fallbackHref);
      }}
      className={cn(
        "inline-flex h-8 w-8 items-center justify-center rounded-md border border-[#DDE6F0] bg-white text-[#344054] transition hover:border-[#2563EB] hover:bg-[#F4F7FF] hover:text-[#2563EB]",
        className,
      )}
    >
      <ArrowLeft className="h-3.5 w-3.5" />
    </button>
  );
}

export function AdminDetailToolbar({
  fallbackHref,
  onEdit,
  onDelete,
  editLabel = "编辑",
  deleteLabel = "删除",
  extra,
}: {
  fallbackHref: string;
  onEdit?: () => void;
  onDelete?: () => void;
  editLabel?: string;
  deleteLabel?: string;
  extra?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      {extra}
      {onEdit ? (
        <AdminActionButton onClick={onEdit}>
          <Pencil className="h-3.5 w-3.5" />
          {editLabel}
        </AdminActionButton>
      ) : null}
      {onDelete ? (
        <button
          type="button"
          onClick={onDelete}
          className="inline-flex h-9 items-center gap-1.5 rounded-md border border-[#FECDCA] bg-[#FEF3F2] px-3 text-sm font-medium text-[#B42318] transition hover:bg-[#FEE4E2]"
        >
          <Trash2 className="h-3.5 w-3.5" />
          {deleteLabel}
        </button>
      ) : null}
      <AdminBackButton fallbackHref={fallbackHref} />
    </div>
  );
}

export function AdminFeedbackBanner({
  message,
  tone = "success",
}: {
  message: string | null;
  tone?: "success" | "error";
}) {
  if (!message) return null;
  if (tone === "error") {
    return (
      <div className="rounded-md border border-[#FECDCA] bg-[#FEF3F2] px-3 py-2 text-xs text-[#B42318]">{message}</div>
    );
  }
  return (
    <div className="rounded-md border border-[#BAE6D1] bg-[#ECFDF3] px-3 py-2 text-xs text-[#047857]">{message}</div>
  );
}
