export type AdminWorkItemType = "reply" | "email";

export type AdminWorkStatus = "pending" | "reminded" | "in_progress" | "handled" | "no_action";

export type AdminWorkQueueEntry = {
  key: string;
  type: AdminWorkItemType;
  id: number;
  assigneeUserId: number | null;
  status: AdminWorkStatus;
  remindedAt: string | null;
  handledAt: string | null;
  handledBy: string | null;
  remindCount: number;
  note: string | null;
  updatedAt: string;
};

const STORAGE_KEY = "admin-work-queue-v2";

export function getWorkQueueKey(type: AdminWorkItemType, id: number): string {
  return `${type}:${id}`;
}

function readStore(): Record<string, AdminWorkQueueEntry> {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, AdminWorkQueueEntry>;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function writeStore(store: Record<string, AdminWorkQueueEntry>) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
}

export function readAdminWorkQueue(): Record<string, AdminWorkQueueEntry> {
  return readStore();
}

export function getAdminWorkQueueEntry(type: AdminWorkItemType, id: number): AdminWorkQueueEntry | null {
  return readStore()[getWorkQueueKey(type, id)] ?? null;
}

export function upsertAdminWorkQueueEntry(input: {
  type: AdminWorkItemType;
  id: number;
  assigneeUserId?: number | null;
  status?: AdminWorkStatus;
  note?: string | null;
  handledBy?: string | null;
}): AdminWorkQueueEntry {
  const key = getWorkQueueKey(input.type, input.id);
  const store = readStore();
  const existing = store[key];
  const now = new Date().toISOString();
  const status = input.status ?? existing?.status ?? "pending";
  const next: AdminWorkQueueEntry = {
    key,
    type: input.type,
    id: input.id,
    assigneeUserId: input.assigneeUserId ?? existing?.assigneeUserId ?? null,
    status,
    remindedAt: status === "reminded" ? now : existing?.remindedAt ?? null,
    handledAt: status === "handled" || status === "no_action" ? now : existing?.handledAt ?? null,
    handledBy: input.handledBy ?? existing?.handledBy ?? null,
    remindCount: status === "reminded" ? (existing?.remindCount ?? 0) + 1 : existing?.remindCount ?? 0,
    note: input.note ?? existing?.note ?? null,
    updatedAt: now,
  };
  store[key] = next;
  writeStore(store);
  return next;
}

export function resolveAdminWorkStatus(
  type: AdminWorkItemType,
  id: number,
  apiProcessingStatus?: string | null,
): AdminWorkStatus {
  if (apiProcessingStatus === "processed" || apiProcessingStatus === "handled") {
    return "handled";
  }
  const entry = getAdminWorkQueueEntry(type, id);
  if (entry?.status === "no_action") return "no_action";
  if (entry?.status === "handled") return "handled";
  if (entry?.status === "reminded") return "reminded";
  if (entry?.status === "in_progress") return "in_progress";
  if (apiProcessingStatus === "unprocessed" || !apiProcessingStatus) return "pending";
  return "pending";
}

export function isPendingAdminWork(
  type: AdminWorkItemType,
  id: number,
  apiProcessingStatus?: string | null,
  extraPending = false,
): boolean {
  const status = resolveAdminWorkStatus(type, id, apiProcessingStatus);
  if (status === "handled" || status === "no_action") return false;
  if (extraPending) return true;
  return status === "pending" || status === "reminded" || status === "in_progress";
}
