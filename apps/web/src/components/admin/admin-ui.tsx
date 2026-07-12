"use client";

import type React from "react";
import type { LucideIcon } from "lucide-react";
import { AlertTriangle, ChevronLeft, ChevronRight, Loader2, MoreHorizontal } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { AdminTone, StatusMeta } from "./admin-ui-helpers";
import { formatAdminNumber } from "./admin-ui-helpers";

export function AdminPageHeader({
  label,
  title,
  description,
  actions,
}: {
  label: string;
  title: string;
  description: string;
  actions?: React.ReactNode;
}) {
  return (
    <section className="flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <p className="text-xs font-semibold tracking-[0.14em] text-[#4F6B8A]">{label}</p>
        <h1 className="mt-2 text-2xl font-semibold tracking-normal text-[#102033]">{title}</h1>
        <p className="mt-1 max-w-[760px] text-sm leading-6 text-[#667085]">{description}</p>
      </div>
      {actions ? <div className="flex flex-wrap items-center justify-end gap-2">{actions}</div> : null}
    </section>
  );
}

export function AdminKpiGrid({ children }: { children: React.ReactNode }) {
  return <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-8">{children}</section>;
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
    <div className="min-w-0 rounded-lg border border-[#DDE6F0] bg-white p-4 shadow-[0_6px_18px_rgba(16,32,51,0.06)] transition hover:-translate-y-0.5 hover:shadow-[0_10px_24px_rgba(16,32,51,0.09)]">
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs font-medium text-[#667085]">{label}</p>
        {Icon ? (
          <span className={cn("inline-flex h-9 w-9 items-center justify-center rounded-full", toneClasses[tone].soft)}>
            <Icon className="h-4 w-4" />
          </span>
        ) : null}
      </div>
      <p className="mt-2 truncate text-3xl font-bold tabular-nums text-[#102033]">
        {typeof value === "number" ? formatAdminNumber(value) : value ?? "暂无"}
      </p>
      {helper ? <p className="mt-1 truncate text-xs text-[#7A8796]">{helper}</p> : null}
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
    <section className="overflow-hidden rounded-lg border border-[#DDE6F0] bg-white shadow-[0_6px_18px_rgba(16,32,51,0.05)]">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#E5ECF4] bg-[#F7F9FC] px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold text-[#102033]">{title}</h2>
          {description ? <p className="mt-0.5 text-xs text-[#667085]">{description}</p> : null}
        </div>
        {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}

export function AdminFilterBar({ children }: { children: React.ReactNode }) {
  return (
    <section className="flex flex-wrap items-end gap-3 rounded-lg border border-[#DDE6F0] bg-white p-3 shadow-[0_6px_18px_rgba(16,32,51,0.05)]">
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
    <label className={cn("grid min-w-[150px] gap-1.5 text-xs font-medium text-[#667085]", className)}>
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
        "h-9 rounded-md border border-[#D8E2EE] bg-[#FBFCFE] px-3 text-sm text-[#102033] outline-none transition placeholder:text-[#98A2B3] focus:border-[#2563EB] focus:ring-2 focus:ring-[#DBEAFE]",
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
        "h-9 rounded-md border border-[#D8E2EE] bg-[#FBFCFE] px-3 text-sm text-[#102033] outline-none transition focus:border-[#2563EB] focus:ring-2 focus:ring-[#DBEAFE]",
        props.className,
      )}
    />
  );
}

export function AdminStatusBadge({ meta }: { meta: StatusMeta }) {
  return (
    <span className={cn("inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold", toneClasses[meta.tone].badge)}>
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
                    "h-10 whitespace-nowrap border-b border-[#DDE6F0] px-3 py-0",
                    columnIndex === columns.length - 1 && column === "操作" && "w-[132px] min-w-[132px]",
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
                {row.map((cell, cellIndex) => (
                  <td
                    key={cellIndex}
                    className={cn(
                      "h-12 max-w-[280px] px-3 py-2 align-middle leading-5",
                      cellIndex === row.length - 1 && columns[cellIndex] === "操作" && "w-[132px] min-w-[132px] max-w-[132px]",
                    )}
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {showPagination ? (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#E5ECF4] bg-white px-4 py-3 text-sm text-[#667085]">
          <div>
            共 <span className="font-semibold text-[#102033]">{formatAdminNumber(rows.length)}</span> 条，
            当前 {formatAdminNumber(startIndex + 1)}-
            {formatAdminNumber(Math.min(startIndex + currentPageSize, rows.length))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={currentPageSize}
              onChange={(event) => {
                setCurrentPageSize(Number(event.target.value));
                setCurrentPage(1);
              }}
              className="h-8 rounded-md border border-[#D8E2EE] bg-white px-2 text-sm text-[#344054] outline-none focus:border-[#2563EB] focus:ring-2 focus:ring-[#DBEAFE]"
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
              className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-[#D8E2EE] bg-white text-[#344054] transition hover:bg-[#F3F6FA] disabled:cursor-not-allowed disabled:opacity-45"
              aria-label="上一页"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="min-w-16 text-center text-sm font-medium text-[#344054]">
              {safePage} / {totalPages}
            </span>
            <button
              type="button"
              disabled={safePage >= totalPages}
              onClick={() => setCurrentPage((value) => Math.min(totalPages, value + 1))}
              className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-[#D8E2EE] bg-white text-[#344054] transition hover:bg-[#F3F6FA] disabled:cursor-not-allowed disabled:opacity-45"
              aria-label="下一页"
            >
              <ChevronRight className="h-4 w-4" />
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
}: {
  message: string;
  type?: "empty" | "loading" | "error";
}) {
  const Icon = type === "loading" ? Loader2 : AlertTriangle;
  return (
    <div className="flex min-h-[160px] items-center justify-center rounded-md border border-[#DDE6F0] bg-white p-6 text-sm text-[#667085]">
      <div className="flex items-center gap-2">
        {type === "empty" ? null : <Icon className={cn("h-4 w-4", type === "loading" && "animate-spin", type === "error" && "text-[#B42318]")} />}
        <span className={type === "error" ? "text-[#B42318]" : undefined}>{message}</span>
      </div>
    </div>
  );
}

export function AdminActionGroup({ children }: { children: React.ReactNode }) {
  return <div className="grid w-full grid-cols-2 gap-2 [&_a]:w-full [&_button]:w-full">{children}</div>;
}

export function AdminCompactActions({
  primaryHref,
  primaryLabel = "详情",
  items,
}: {
  primaryHref?: string;
  primaryLabel?: string;
  items: Array<{ label: string; href?: string; danger?: boolean; disabled?: boolean; onClick?: () => void }>;
}) {
  return (
    <div className="flex w-full items-center gap-2">
      <AdminActionButton href={primaryHref}>{primaryLabel}</AdminActionButton>
      <AdminMoreMenu items={items} />
    </div>
  );
}

export function AdminMoreMenu({
  items,
}: {
  items: Array<{ label: string; href?: string; danger?: boolean; disabled?: boolean; onClick?: () => void }>;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handlePointerDown(event: MouseEvent) {
      if (!ref.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-label="更多操作"
        onClick={() => setOpen((value) => !value)}
        className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-[#D8E2EE] bg-white text-[#344054] transition hover:bg-[#F3F6FA]"
      >
        <MoreHorizontal className="h-4 w-4" />
      </button>
      {open ? (
        <div className="absolute right-0 z-30 mt-1 w-36 rounded-md border border-[#D8E2EE] bg-white p-1 shadow-[0_12px_28px_rgba(16,32,51,0.16)]">
          {items.map((item) =>
            item.href && !item.disabled ? (
              <a
                key={item.label}
                href={item.href}
                className={cn(
                  "block rounded px-2.5 py-1.5 text-sm transition hover:bg-[#F4F7FB]",
                  item.danger ? "text-[#B42318]" : "text-[#344054]",
                )}
              >
                {item.label}
              </a>
            ) : (
              <button
                key={item.label}
                type="button"
                disabled={item.disabled}
                onClick={() => {
                  item.onClick?.();
                  setOpen(false);
                }}
                className={cn(
                  "block w-full rounded px-2.5 py-1.5 text-left text-sm transition hover:bg-[#F4F7FB] disabled:cursor-not-allowed disabled:text-[#98A2B3]",
                  item.danger ? "text-[#B42318]" : "text-[#344054]",
                )}
              >
                {item.label}
              </button>
            ),
          )}
        </div>
      ) : null}
    </div>
  );
}

export function AdminAvatarLabel({
  name,
  subtitle,
}: {
  name: string;
  subtitle?: string;
}) {
  const palettes = [
    "bg-[#DBEAFE] text-[#1D4ED8]",
    "bg-[#DCFCE7] text-[#047857]",
    "bg-[#FEF3C7] text-[#B54708]",
    "bg-[#FCE7F3] text-[#BE185D]",
    "bg-[#EDE9FE] text-[#6D28D9]",
  ];
  const index = Math.abs(name.charCodeAt(0) || 0) % palettes.length;

  return (
    <div className="flex min-w-0 items-center gap-3">
      <span className={cn("inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-sm font-bold", palettes[index])}>
        {name.slice(0, 1).toUpperCase()}
      </span>
      <span className="min-w-0">
        <span className="block truncate font-semibold text-[#102033]">{name}</span>
        {subtitle ? <span className="block truncate text-xs text-[#667085]">{subtitle}</span> : null}
      </span>
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
  if (href) {
    return (
      <Button asChild variant="outline" size="sm">
        <a href={href}>{children}</a>
      </Button>
    );
  }
  return (
    <Button type="button" variant="outline" size="sm" onClick={onClick} disabled={disabled ?? !onClick}>
      {children}
    </Button>
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
