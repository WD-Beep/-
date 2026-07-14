"use client";

import { useCallback, useMemo, useState } from "react";
import { BellRing } from "lucide-react";

import { AdminFeedbackBanner } from "@/components/admin/admin-crud";
import { EmailEditDrawer, ReplyHandleDrawer } from "@/components/admin/admin-entity-management";
import {
  AdminActionButton,
  AdminCompactActions,
  AdminFilterBar,
  AdminFilterField,
  AdminInput,
  AdminSection,
  AdminSelect,
  AdminStatusBadge,
  AdminTable,
} from "@/components/admin/admin-ui";
import {
  formatAdminDate,
  formatAdminNumber,
  formatSalespersonDisplay,
  getAdminWorkStatusMeta,
  getReplyProcessingStatusMeta,
  getReplyStateLabel,
} from "@/components/admin/admin-ui-helpers";
import {
  addInfluencerFollowup,
  type AdminEmail,
  type AdminReply,
  type AdminUser,
  updateEmailReply,
} from "@/lib/api";
import {
  getAdminWorkQueueEntry,
  resolveAdminWorkStatus,
  type AdminWorkStatus,
  upsertAdminWorkQueueEntry,
} from "@/lib/admin-work-queue";

export type AdminFollowUpItem =
  | { kind: "reply"; item: AdminReply }
  | { kind: "email"; item: AdminEmail };

type FollowTab = "all" | "email" | "reply" | "reminded" | "handled" | "no_action";

const tabs: Array<{ key: FollowTab; label: string }> = [
  { key: "all", label: "全部待跟进" },
  { key: "email", label: "邮件待跟进" },
  { key: "reply", label: "回复待处理" },
  { key: "reminded", label: "已提醒" },
  { key: "handled", label: "已处理" },
  { key: "no_action", label: "无需处理" },
];

function Truncate({ text, className }: { text: string; className?: string }) {
  return (
    <span className={className ?? "block max-w-[220px] truncate font-medium text-[#102033]"} title={text}>
      {text}
    </span>
  );
}

function buildItems(emails: AdminEmail[], replies: AdminReply[]): AdminFollowUpItem[] {
  return [
    ...replies.map((item) => ({ kind: "reply" as const, item })),
    ...emails.map((item) => ({ kind: "email" as const, item })),
  ];
}

function workStatusOf(entry: AdminFollowUpItem): AdminWorkStatus {
  if (entry.kind === "reply") {
    return resolveAdminWorkStatus("reply", entry.item.id, entry.item.processing_status);
  }
  return resolveAdminWorkStatus("email", entry.item.id, entry.item.has_replied ? "processed" : "unprocessed");
}

function matchesTab(entry: AdminFollowUpItem, tab: FollowTab): boolean {
  const status = workStatusOf(entry);
  if (tab === "handled") return status === "handled";
  if (tab === "no_action") return status === "no_action";
  if (tab === "reminded") return status === "reminded";
  if (tab === "email") {
    return entry.kind === "email" && status !== "handled" && status !== "no_action" && !entry.item.has_replied;
  }
  if (tab === "reply") {
    return (
      entry.kind === "reply" &&
      status !== "handled" &&
      status !== "no_action" &&
      (entry.item.processing_status === "unprocessed" ||
        getReplyProcessingStatusMeta(entry.item.processing_status).tone === "warning" ||
        status === "pending" ||
        status === "reminded" ||
        status === "in_progress")
    );
  }
  // all pending follow-ups
  if (status === "handled" || status === "no_action") return false;
  if (entry.kind === "email") return !entry.item.has_replied || status === "pending" || status === "reminded";
  return (
    entry.item.processing_status !== "processed" &&
    entry.item.processing_status !== "handled"
  );
}

type AdminFollowUpWorkbenchProps = {
  emails: AdminEmail[];
  replies: AdminReply[];
  users: AdminUser[];
  onReload: () => Promise<void>;
};

export function AdminFollowUpWorkbench({ emails, replies, users, onReload }: AdminFollowUpWorkbenchProps) {
  const [tab, setTab] = useState<FollowTab>("all");
  const [salesFilter, setSalesFilter] = useState("");
  const [brandFilter, setBrandFilter] = useState("");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editReply, setEditReply] = useState<AdminReply | null>(null);
  const [editEmail, setEditEmail] = useState<AdminEmail | null>(null);

  const allItems = useMemo(() => buildItems(emails, replies), [emails, replies]);

  const tabCounts = useMemo(() => {
    const counts: Record<FollowTab, number> = {
      all: 0,
      email: 0,
      reply: 0,
      reminded: 0,
      handled: 0,
      no_action: 0,
    };
    for (const entry of allItems) {
      for (const t of tabs) {
        if (matchesTab(entry, t.key)) counts[t.key] += 1;
      }
    }
    return counts;
  }, [allItems]);

  const filteredItems = useMemo(() => {
    return allItems.filter((entry) => {
      if (!matchesTab(entry, tab)) return false;
      const username = entry.item.username ?? "";
      const brand = entry.item.product_name ?? "";
      const subject =
        entry.kind === "reply"
          ? `${entry.item.subject ?? ""} ${entry.item.from_address ?? ""}`
          : `${entry.item.subject ?? ""} ${(entry.item.recipients ?? []).join(" ")} ${entry.item.influencer_username ?? ""}`;
      if (salesFilter && username !== salesFilter) return false;
      if (brandFilter && brand !== brandFilter) return false;
      if (search && !`${username} ${brand} ${subject}`.toLowerCase().includes(search.trim().toLowerCase())) return false;
      return true;
    });
  }, [allItems, brandFilter, salesFilter, search, tab]);

  const salesOptions = useMemo(() => {
    const names = new Set<string>();
    for (const entry of allItems) {
      if (entry.item.username) names.add(entry.item.username);
    }
    return Array.from(names).sort();
  }, [allItems]);

  const brandOptions = useMemo(() => {
    const names = new Set<string>();
    for (const entry of allItems) {
      if (entry.item.product_name) names.add(entry.item.product_name);
    }
    return Array.from(names).sort((a, b) => a.localeCompare(b, "zh-Hans-CN"));
  }, [allItems]);

  const remindOne = useCallback(
    async (entry: AdminFollowUpItem) => {
      const key = `${entry.kind}:${entry.item.id}`;
      setBusyKey(key);
      setError(null);
      try {
        const assignee = users.find((user) => user.username === entry.item.username);
        upsertAdminWorkQueueEntry({
          type: entry.kind,
          id: entry.item.id,
          assigneeUserId: assignee?.id ?? entry.item.user_id ?? null,
          status: "reminded",
          note: "管理员已提醒跟进",
        });
        if (entry.kind === "reply") {
          await updateEmailReply(entry.item.id, {
            manual_note: `[管理员提醒跟进] ${new Date().toLocaleString("zh-CN")} 请尽快处理。`,
          });
          if (entry.item.product_influencer_id) {
            await addInfluencerFollowup(entry.item.product_influencer_id, {
              action_type: "admin_reminder",
              content: `管理员提醒跟进回复：${entry.item.subject || entry.item.from_address}`,
              operator_name: "admin",
            });
          }
        } else if (entry.item.product_influencer_id) {
          await addInfluencerFollowup(entry.item.product_influencer_id, {
            action_type: "admin_reminder",
            content: `管理员提醒跟进邮件：${entry.item.subject || "无主题"}`,
            operator_name: "admin",
          });
        }
        setFeedback("已发送跟进提醒。");
        await onReload();
      } catch (err) {
        setError(err instanceof Error ? err.message : "提醒失败。");
      } finally {
        setBusyKey(null);
      }
    },
    [onReload, users],
  );

  async function remindSelected() {
    const targets = filteredItems.filter((entry) => selected.has(`${entry.kind}:${entry.item.id}`));
    for (const entry of targets) {
      await remindOne(entry);
    }
    setSelected(new Set());
  }

  async function markStatus(entry: AdminFollowUpItem, status: "handled" | "no_action") {
    const key = `${entry.kind}:${entry.item.id}`;
    setBusyKey(key);
    setError(null);
    try {
      if (entry.kind === "reply" && status === "handled") {
        await updateEmailReply(entry.item.id, { processing_status: "processed" });
      }
      upsertAdminWorkQueueEntry({
        type: entry.kind,
        id: entry.item.id,
        status,
        handledBy: "admin",
      });
      setFeedback(status === "handled" ? "已标记为已处理。" : "已标记为无需处理。");
      await onReload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败。");
    } finally {
      setBusyKey(null);
    }
  }

  return (
    <div className="space-y-3">
      <AdminFeedbackBanner message={feedback} />
      <AdminFeedbackBanner message={error} tone="error" />

      <AdminSection
        title="待跟进中心"
        description="统一查看子账号未回复、待处理与已提醒数据，支持提醒、编辑和状态流转。"
        actions={
          <AdminActionButton onClick={() => void remindSelected()} disabled={!selected.size}>
            <BellRing className="h-3.5 w-3.5" />
            批量提醒 ({selected.size})
          </AdminActionButton>
        }
      >
        <div className="flex gap-1 overflow-x-auto border-b border-[#E5ECF4] bg-[#F7F9FC] px-2 pt-2">
          {tabs.map((item) => (
            <button
              key={item.key}
              type="button"
              onClick={() => {
                setTab(item.key);
                setSelected(new Set());
              }}
              className={[
                "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-t-md border border-b-0 px-2.5 text-xs font-medium transition",
                tab === item.key
                  ? "border-[#DDE6F0] bg-white text-[#102033]"
                  : "border-transparent text-[#667085] hover:bg-white/70 hover:text-[#102033]",
              ].join(" ")}
            >
              {item.label}
              <span className="rounded-full bg-[#EEF2F7] px-1.5 py-0.5 text-[10px] tabular-nums text-[#667085]">
                {formatAdminNumber(tabCounts[item.key])}
              </span>
            </button>
          ))}
        </div>

        <div className="p-2.5">
          <AdminFilterBar>
            <AdminFilterField label="搜索" className="min-w-[180px] flex-1">
              <AdminInput value={search} placeholder="主题 / 业务员 / 品牌" onChange={(e) => setSearch(e.target.value)} />
            </AdminFilterField>
            <AdminFilterField label="业务员">
              <AdminSelect value={salesFilter} onChange={(e) => setSalesFilter(e.target.value)}>
                <option value="">全部</option>
                {salesOptions.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </AdminSelect>
            </AdminFilterField>
            <AdminFilterField label="品牌">
              <AdminSelect value={brandFilter} onChange={(e) => setBrandFilter(e.target.value)}>
                <option value="">全部</option>
                {brandOptions.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </AdminSelect>
            </AdminFilterField>
          </AdminFilterBar>
        </div>

        <AdminTable
          minWidth={1100}
          pageSize={15}
          columns={["", "类型", "业务员", "品牌", "主题", "状态", "跟进", "时间", "提醒", "操作"]}
          rows={filteredItems.map((entry) => {
            const key = `${entry.kind}:${entry.item.id}`;
            const status = workStatusOf(entry);
            const queue = getAdminWorkQueueEntry(entry.kind, entry.item.id);
            const salesUser = users.find((user) => user.username === entry.item.username);
            const subject =
              entry.kind === "reply"
                ? entry.item.subject || entry.item.from_address
                : entry.item.subject || entry.item.influencer_username || "暂无主题";
            const time = entry.kind === "reply" ? entry.item.received_at : entry.item.sent_at;
            return [
              <input
                key="select"
                type="checkbox"
                checked={selected.has(key)}
                onChange={(event) => {
                  setSelected((prev) => {
                    const next = new Set(prev);
                    if (event.target.checked) next.add(key);
                    else next.delete(key);
                    return next;
                  });
                }}
              />,
              entry.kind === "reply" ? "回复" : "邮件",
              salesUser ? formatSalespersonDisplay(salesUser) : entry.item.username ?? "暂无",
              entry.item.product_name ?? "暂无",
              <Truncate key="subject" text={subject} />,
              entry.kind === "reply" ? (
                <AdminStatusBadge key="reply" meta={getReplyProcessingStatusMeta(entry.item.processing_status)} />
              ) : (
                <AdminStatusBadge key="reply" meta={getReplyStateLabel(entry.item.has_replied)} />
              ),
              <AdminStatusBadge key="work" meta={getAdminWorkStatusMeta(status)} />,
              formatAdminDate(time),
              queue?.remindCount ? `${queue.remindCount}次` : "0",
              <AdminCompactActions
                key="actions"
                primaryLabel={busyKey === key ? "..." : "提醒"}
                primaryOnClick={() => void remindOne(entry)}
                secondaryLabel="编辑"
                secondaryOnClick={() => {
                  if (entry.kind === "reply") setEditReply(entry.item);
                  else setEditEmail(entry.item);
                }}
                items={[
                  { label: "标记已处理", onClick: () => void markStatus(entry, "handled") },
                  { label: "无需处理", onClick: () => void markStatus(entry, "no_action") },
                  {
                    label: "查看红人",
                    href: entry.item.product_influencer_id ? `/admin/influencers/${entry.item.product_influencer_id}` : undefined,
                    disabled: !entry.item.product_influencer_id,
                  },
                ]}
              />,
            ];
          })}
          emptyMessage="当前分类暂无记录。"
        />
      </AdminSection>

      <ReplyHandleDrawer
        open={Boolean(editReply)}
        reply={editReply}
        onClose={() => setEditReply(null)}
        onSaved={() => {
          setFeedback("回复已更新。");
          void onReload();
        }}
      />
      <EmailEditDrawer
        open={Boolean(editEmail)}
        email={editEmail}
        onClose={() => setEditEmail(null)}
        onSaved={() => {
          setFeedback("邮件跟进状态已更新。");
          void onReload();
        }}
      />
    </div>
  );
}

export function AdminSalesReminderBanner({ users }: { users: AdminUser[] }) {
  const pendingCount = users.reduce((sum, user) => sum + (user.pending_reply_count ?? 0), 0);
  if (!pendingCount) return null;
  return (
    <div className="flex items-center gap-2 rounded-md border border-[#FDE68A] bg-[#FFFBEB] px-3 py-2 text-xs text-[#92400E]">
      <BellRing className="h-3.5 w-3.5 shrink-0" />
      <span>
        全站待处理回复 <strong>{pendingCount}</strong> 条，可在待跟进中心按业务员筛选并批量提醒。
      </span>
    </div>
  );
}
