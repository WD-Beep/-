"use client";

import type React from "react";
import type { LucideIcon } from "lucide-react";
import { AlertTriangle, ChevronLeft, ChevronRight, Loader2, MoreHorizontal, ShoppingBag, UserRound, X } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { AdminTone, StatusMeta } from "./admin-ui-helpers";
import { formatAdminNumber } from "./admin-ui-helpers";

import { AdminBackButton } from "@/components/admin/admin-crud";

export function AdminPageHeader({
  label,
  title,
  description,
  actions,
  backFallback = "/admin/dashboard",
}: {
  label: string;
  title: string;
  description: string;
  actions?: React.ReactNode;
  /** 无历史记录时回退；默认回仪表盘，列表页也统一显示返回 */
  backFallback?: string;
}) {
  return (
    <section className="flex flex-wrap items-start justify-between gap-2">
      <div className="flex min-w-0 items-start gap-2.5">
        <AdminBackButton fallbackHref={backFallback} className="mt-0.5 h-8 w-8 shrink-0" />
        <div className="min-w-0">
          <p className="text-[11px] font-semibold tracking-[0.12em] text-[#4F6B8A]">{label}</p>
          <h1 className="mt-0.5 text-xl font-semibold tracking-normal text-[#102033]">{title}</h1>
          <p className="mt-0.5 max-w-[760px] text-xs leading-5 text-[#667085]">{description}</p>
        </div>
      </div>
      {actions ? <div className="flex flex-wrap items-center justify-end gap-1.5">{actions}</div> : null}
    </section>
  );
}

export function AdminKpiGrid({ children }: { children: React.ReactNode }) {
  return <section className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-8">{children}</section>;
}

export function AdminKpiCard({
  label,
  value,
  helper,
  icon: Icon,
  tone = "neutral",
}: {
  label: string;
  value: number | string | null | undefined;
  helper?: string;
  icon?: LucideIcon;
  tone?: AdminTone;
}) {
  return (
    <div className="min-w-0 rounded-md border border-[#DDE6F0] bg-white px-3 py-2.5 shadow-[0_2px_8px_rgba(16,32,51,0.04)]">
      <div className="flex items-start justify-between gap-2">
        <p className="text-[11px] font-medium text-[#667085]">{label}</p>
        {Icon ? (
          <span className={cn("inline-flex h-7 w-7 items-center justify-center rounded-full", toneClasses[tone].soft)}>
            <Icon className="h-3.5 w-3.5" />
          </span>
        ) : null}
      </div>
      <p className="mt-1 truncate text-xl font-bold tabular-nums text-[#102033]">
        {typeof value === "number" ? formatAdminNumber(value) : value ?? "暂无"}
      </p>
      {helper ? <p className="mt-0.5 truncate text-[11px] text-[#7A8796]">{helper}</p> : null}
    </div>
  );
}

export function AdminSection({
  title,
  description,
  children,
  actions,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <section className="overflow-hidden rounded-md border border-[#DDE6F0] bg-white shadow-[0_2px_8px_rgba(16,32,51,0.04)]">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#E5ECF4] bg-[#F7F9FC] px-3 py-2">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-[#102033]">{title}</h2>
          {description ? <p className="mt-0.5 text-[11px] text-[#667085]">{description}</p> : null}
        </div>
        {actions ? <div className="flex items-center gap-1.5">{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}

export function AdminFilterBar({ children }: { children: React.ReactNode }) {
  return (
    <section className="flex flex-wrap items-end gap-2 rounded-md border border-[#DDE6F0] bg-white p-2.5 shadow-[0_2px_8px_rgba(16,32,51,0.04)]">
      {children}
    </section>
  );
}

export function AdminFilterField({
  label,
  children,
  className,
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <label className={cn("grid min-w-[130px] gap-1 text-[11px] font-medium text-[#667085]", className)}>
      {label}
      {children}
    </label>
  );
}

export function AdminInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={cn(
        "h-8 rounded-md border border-[#D8E2EE] bg-[#FBFCFE] px-2.5 text-sm text-[#102033] outline-none transition placeholder:text-[#98A2B3] focus:border-[#2563EB] focus:ring-1 focus:ring-[#DBEAFE]",
        props.className,
      )}
    />
  );
}

export function AdminSelect(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={cn(
        "h-8 rounded-md border border-[#D8E2EE] bg-[#FBFCFE] px-2.5 text-sm text-[#102033] outline-none transition focus:border-[#2563EB] focus:ring-1 focus:ring-[#DBEAFE]",
        props.className,
      )}
    />
  );
}

export function AdminStatusBadge({ meta }: { meta: StatusMeta }) {
  return (
    <span className={cn("inline-flex items-center rounded-full border px-1.5 py-0 text-[11px] font-semibold leading-5", toneClasses[meta.tone].badge)}>
      {meta.label}
    </span>
  );
}

export function AdminTable({
  columns,
  rows,
  minWidth = 1100,
  emptyMessage = "暂无记录。",
  pageSize = 10,
  pageSizeOptions = [10, 20, 50],
}: {
  columns: string[];
  rows: React.ReactNode[][];
  minWidth?: number;
  emptyMessage?: string;
  pageSize?: number;
  pageSizeOptions?: number[];
}) {
  const [currentPage, setCurrentPage] = useState(1);
  const [currentPageSize, setCurrentPageSize] = useState(pageSize);

  if (!rows.length) return <AdminState message={emptyMessage} />;

  const totalPages = Math.max(1, Math.ceil(rows.length / currentPageSize));
  const safePage = Math.min(currentPage, totalPages);
  const startIndex = (safePage - 1) * currentPageSize;
  const visibleRows = rows.slice(startIndex, startIndex + currentPageSize);
  const showPagination = rows.length > currentPageSize || pageSizeOptions.some((option) => option < rows.length);

  return (
    <div>
      <div className="overflow-auto">
        <table className="w-full border-collapse text-left text-sm" style={{ minWidth }}>
          <thead className="bg-[#F4F7FB] text-xs font-semibold text-[#667085]">
            <tr>
              {columns.map((column, columnIndex) => (
                <th
                  key={column}
                  className={cn(
                    "h-8 whitespace-nowrap border-b border-[#DDE6F0] px-2.5 py-0",
                    columnIndex === columns.length - 1 && column === "操作" && "w-[148px] min-w-[148px]",
                  )}
                >
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[#E5ECF4]">
            {visibleRows.map((row, rowIndex) => (
              <tr key={startIndex + rowIndex} className="bg-white text-[#344054] transition hover:bg-[#F8FAFD]">
                {row.map((cell, cellIndex) => {
                  const isActions = cellIndex === row.length - 1 && columns[cellIndex] === "操作";
                  return (
                  <td
                    key={cellIndex}
                    className={cn(
                      "h-9 max-w-[220px] px-2.5 py-1 align-middle text-sm leading-4",
                      isActions ? "w-[148px] min-w-[148px] max-w-[220px] overflow-visible" : "truncate",
                    )}
                    title={typeof cell === "string" || typeof cell === "number" ? String(cell) : undefined}
                  >
                    {cell}
                  </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {showPagination ? (
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[#E5ECF4] bg-white px-3 py-2 text-xs text-[#667085]">
          <div>
            共 <span className="font-semibold text-[#102033]">{formatAdminNumber(rows.length)}</span> 条，
            当前 {formatAdminNumber(startIndex + 1)}-
            {formatAdminNumber(Math.min(startIndex + currentPageSize, rows.length))}
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <select
              value={currentPageSize}
              onChange={(event) => {
                setCurrentPageSize(Number(event.target.value));
                setCurrentPage(1);
              }}
              className="h-7 rounded-md border border-[#D8E2EE] bg-white px-2 text-xs text-[#344054] outline-none focus:border-[#2563EB]"
            >
              {pageSizeOptions.map((option) => (
                <option key={option} value={option}>
                  {option} 条 / 页
                </option>
              ))}
            </select>
            <button
              type="button"
              disabled={safePage <= 1}
              onClick={() => setCurrentPage((value) => Math.max(1, value - 1))}
              className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-[#D8E2EE] bg-white text-[#344054] transition hover:bg-[#F3F6FA] disabled:cursor-not-allowed disabled:opacity-45"
              aria-label="上一页"
            >
              <ChevronLeft className="h-3.5 w-3.5" />
            </button>
            <span className="min-w-12 text-center text-xs font-medium text-[#344054]">
              {safePage} / {totalPages}
            </span>
            <button
              type="button"
              disabled={safePage >= totalPages}
              onClick={() => setCurrentPage((value) => Math.min(totalPages, value + 1))}
              className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-[#D8E2EE] bg-white text-[#344054] transition hover:bg-[#F3F6FA] disabled:cursor-not-allowed disabled:opacity-45"
              aria-label="下一页"
            >
              <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function AdminState({
  message,
  type = "empty",
  action,
}: {
  message: string;
  type?: "empty" | "loading" | "error";
  action?: React.ReactNode;
}) {
  const Icon = type === "loading" ? Loader2 : AlertTriangle;
  return (
    <div className="flex min-h-[100px] items-center justify-center rounded-md border border-[#DDE6F0] bg-white p-4 text-sm text-[#667085]">
      <div className="flex max-w-md flex-col items-center gap-3 text-center">
        <div className="flex items-center gap-2">
          {type === "empty" ? null : <Icon className={cn("h-4 w-4", type === "loading" && "animate-spin", type === "error" && "text-[#B42318]")} />}
          <span className={type === "error" ? "text-[#B42318]" : undefined}>{message}</span>
        </div>
        {action ? <div className="flex items-center justify-center gap-2">{action}</div> : null}
      </div>
    </div>
  );
}

export function AdminActionGroup({ children }: { children: React.ReactNode }) {
  return <div className="grid w-full grid-cols-2 gap-2 [&_a]:w-full [&_button]:w-full">{children}</div>;
}

export function AdminCompactActions({
  primaryHref,
  primaryOnClick,
  primaryLabel = "详情",
  secondaryLabel,
  secondaryOnClick,
  items,
}: {
  primaryHref?: string;
  primaryOnClick?: () => void;
  primaryLabel?: string;
  secondaryLabel?: string;
  secondaryOnClick?: () => void;
  items: Array<{ label: string; href?: string; danger?: boolean; disabled?: boolean; onClick?: () => void }>;
}) {
  return (
    <div className="flex w-full items-center gap-1.5 overflow-visible">
      <AdminActionButton href={primaryHref} onClick={primaryOnClick}>
        {primaryLabel}
      </AdminActionButton>
      {secondaryLabel ? (
        <AdminActionButton onClick={secondaryOnClick}>{secondaryLabel}</AdminActionButton>
      ) : null}
      {items.length ? <AdminMoreMenu items={items} /> : null}
    </div>
  );
}

export function AdminMoreMenu({
  items,
}: {
  items: Array<{ label: string; href?: string; danger?: boolean; disabled?: boolean; onClick?: () => void }>;
}) {
  const [open, setOpen] = useState(false);
  const [coords, setCoords] = useState<{ top: number; left: number } | null>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  function updatePosition() {
    const button = buttonRef.current;
    if (!button) return;
    const rect = button.getBoundingClientRect();
    const menuWidth = 160;
    const menuHeight = Math.min(items.length * 28 + 12, 280);
    const left = Math.min(Math.max(8, rect.right - menuWidth), window.innerWidth - menuWidth - 8);
    const openUp = rect.bottom + menuHeight + 8 > window.innerHeight && rect.top > menuHeight;
    const top = openUp ? rect.top - menuHeight - 4 : rect.bottom + 4;
    setCoords({ top, left });
  }

  useLayoutEffect(() => {
    if (!open) return;
    updatePosition();
  }, [open, items.length]);

  useEffect(() => {
    if (!open) return;
    function handlePointerDown(event: MouseEvent) {
      const target = event.target as Node;
      if (buttonRef.current?.contains(target) || menuRef.current?.contains(target)) return;
      setOpen(false);
    }
    function handleReposition() {
      updatePosition();
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    window.addEventListener("resize", handleReposition);
    window.addEventListener("scroll", handleReposition, true);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("resize", handleReposition);
      window.removeEventListener("scroll", handleReposition, true);
    };
  }, [open, items.length]);

  const menu =
    open && coords && typeof document !== "undefined"
      ? createPortal(
          <div
            ref={menuRef}
            role="menu"
            className="fixed z-[80] w-40 rounded-md border border-[#D8E2EE] bg-white p-1 shadow-[0_12px_28px_rgba(16,32,51,0.18)]"
            style={{ top: coords.top, left: coords.left }}
          >
            {items.map((item) =>
              item.href && !item.disabled ? (
                <a
                  key={item.label}
                  href={item.href}
                  role="menuitem"
                  onClick={() => setOpen(false)}
                  className={cn(
                    "block rounded px-2 py-1.5 text-xs transition hover:bg-[#F4F7FB]",
                    item.danger ? "text-[#B42318]" : "text-[#344054]",
                  )}
                >
                  {item.label}
                </a>
              ) : (
                <button
                  key={item.label}
                  type="button"
                  role="menuitem"
                  disabled={item.disabled}
                  onClick={() => {
                    item.onClick?.();
                    setOpen(false);
                  }}
                  className={cn(
                    "block w-full rounded px-2 py-1.5 text-left text-xs transition hover:bg-[#F4F7FB] disabled:cursor-not-allowed disabled:text-[#98A2B3]",
                    item.danger ? "text-[#B42318]" : "text-[#344054]",
                  )}
                >
                  {item.label}
                </button>
              ),
            )}
          </div>,
          document.body,
        )
      : null;

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        aria-label="更多操作"
        aria-expanded={open}
        onClick={(event) => {
          event.stopPropagation();
          setOpen((value) => !value);
        }}
        className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-[#D8E2EE] bg-white text-[#344054] transition hover:bg-[#F3F6FA]"
      >
        <MoreHorizontal className="h-3.5 w-3.5" />
      </button>
      {menu}
    </>
  );
}

export function AdminAvatarLabel({
  name,
  subtitle,
}: {
  name: string;
  subtitle?: string;
}) {
  return <AdminBrandLabel name={name} subtitle={subtitle} />;
}

export function AdminSalespersonLabel({
  name,
  subtitle,
  avatarUrl,
  compact = false,
}: {
  name: string;
  subtitle?: string;
  avatarUrl?: string | null;
  compact?: boolean;
}) {
  const size = compact ? "h-8 w-8" : "h-9 w-9";
  const iconSize = compact ? "h-4 w-4" : "h-4 w-4";

  return (
    <div className="flex min-w-0 items-center gap-2.5">
      {avatarUrl ? (
        <img src={avatarUrl} alt="" className={cn("shrink-0 rounded-full border border-[#D8E2EE] object-cover", size)} />
      ) : (
        <span className={cn("inline-flex shrink-0 items-center justify-center rounded-full border border-[#D8E2EE] bg-[#F4F7FB] text-[#5F6B7A]", size)}>
          <UserRound className={iconSize} />
        </span>
      )}
      <span className="min-w-0">
        <span className={cn("block truncate text-[#102033]", compact ? "text-sm font-medium" : "font-medium")}>{name}</span>
        {subtitle ? <span className="block truncate text-xs text-[#667085]">{subtitle}</span> : null}
      </span>
    </div>
  );
}

export function AdminBrandLabel({
  name,
  subtitle,
  logoUrl,
  compact = false,
}: {
  name: string;
  subtitle?: string;
  logoUrl?: string | null;
  compact?: boolean;
}) {
  const size = compact ? "h-8 w-8" : "h-9 w-9";
  const iconSize = compact ? "h-3.5 w-3.5" : "h-4 w-4";

  return (
    <div className="flex min-w-0 items-center gap-2.5">
      {logoUrl ? (
        <img src={logoUrl} alt="" className={cn("shrink-0 rounded-md border border-[#D8E2EE] object-cover", size)} />
      ) : (
        <span className={cn("inline-flex shrink-0 items-center justify-center rounded-md border border-[#E5ECF4] bg-[#FAFBFC] text-[#667085]", size)}>
          <ShoppingBag className={iconSize} />
        </span>
      )}
      <span className="min-w-0">
        <span className={cn("block truncate text-[#344054]", compact ? "text-sm" : "text-sm font-medium")}>{name}</span>
        {subtitle ? <span className="block truncate font-mono text-[11px] text-[#98A2B3]">{subtitle}</span> : null}
      </span>
    </div>
  );
}

export function AdminConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "确认",
  cancelLabel = "取消",
  danger = false,
  loading = false,
  confirmDisabled = false,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  description: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  loading?: boolean;
  confirmDisabled?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-[#102033]/50 p-4 backdrop-blur-[1px]">
      <div className="w-full max-w-md rounded-xl border border-[#D8E2EE] bg-white p-5 shadow-[0_24px_64px_rgba(16,32,51,0.18)]">
        <h3 className="text-base font-semibold text-[#102033]">{title}</h3>
        <p className="mt-2 text-sm leading-6 text-[#667085]">{description}</p>
        <div className="mt-5 flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onCancel} disabled={loading}>
            {cancelLabel}
          </Button>
          <Button
            type="button"
            onClick={onConfirm}
            disabled={loading || confirmDisabled}
            className={danger ? "bg-[#B42318] text-white hover:bg-[#912018]" : "bg-[#2563EB] text-white hover:bg-[#1D4ED8]"}
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}

export function AdminDrawer({
  open,
  title,
  description,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  description?: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button type="button" aria-label="关闭抽屉" onClick={onClose} className="absolute inset-0 bg-[#102033]/45 backdrop-blur-[1px]" />
      <aside className="relative flex h-full w-full max-w-[920px] flex-col border-l border-[#D8E2EE] bg-white shadow-[-24px_0_64px_rgba(16,32,51,0.18)]">
        <div className="flex items-start justify-between gap-4 border-b border-[#E5ECF4] bg-[#F7F9FC] px-5 py-4">
          <div className="min-w-0">
            <h2 className="truncate text-lg font-semibold text-[#102033]">{title}</h2>
            {description ? <p className="mt-1 text-sm text-[#667085]">{description}</p> : null}
          </div>
          <button
            type="button"
            aria-label="关闭"
            onClick={onClose}
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-[#D8E2EE] bg-white text-[#667085] transition hover:bg-[#F3F6FA]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-auto p-5">{children}</div>
      </aside>
    </div>
  );
}

export function AdminActionButton({
  children,
  href,
  onClick,
  disabled,
}: {
  children: React.ReactNode;
  href?: string;
  onClick?: () => void;
  disabled?: boolean;
}) {
  const className =
    "inline-flex h-7 items-center gap-1 rounded-md border border-[#D8E2EE] bg-white px-2 text-xs font-medium text-[#344054] transition hover:border-[#2563EB] hover:bg-[#F4F7FF] hover:text-[#2563EB] disabled:cursor-not-allowed disabled:opacity-50";
  if (href) {
    return (
      <a href={href} className={className}>
        {children}
      </a>
    );
  }
  return (
    <button type="button" className={className} onClick={onClick} disabled={disabled ?? !onClick}>
      {children}
    </button>
  );
}

const toneClasses: Record<AdminTone, { badge: string; soft: string }> = {
  success: {
    badge: "border-[#BAE6D1] bg-[#ECFDF3] text-[#047857]",
    soft: "bg-[#ECFDF3] text-[#047857]",
  },
  warning: {
    badge: "border-[#FEDF89] bg-[#FFFAEB] text-[#B54708]",
    soft: "bg-[#FFFAEB] text-[#B54708]",
  },
  danger: {
    badge: "border-[#FECDCA] bg-[#FEF3F2] text-[#B42318]",
    soft: "bg-[#FEF3F2] text-[#B42318]",
  },
  info: {
    badge: "border-[#BFDBFE] bg-[#EFF6FF] text-[#1D4ED8]",
    soft: "bg-[#EFF6FF] text-[#1D4ED8]",
  },
  muted: {
    badge: "border-[#D8E2EE] bg-[#F4F7FB] text-[#5F6B7A]",
    soft: "bg-[#F4F7FB] text-[#5F6B7A]",
  },
  neutral: {
    badge: "border-[#D8E2EE] bg-white text-[#344054]",
    soft: "bg-[#F4F7FB] text-[#344054]",
  },
};
