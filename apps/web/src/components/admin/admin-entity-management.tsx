"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";

import { AdminDeleteConfirmDialog } from "@/components/admin/admin-products-management";
import {
  AdminDrawer,
  AdminFilterField,
  AdminInput,
  AdminSelect,
} from "@/components/admin/admin-ui";
import { Button } from "@/components/ui/button";
import {
  addInfluencerFollowup,
  deleteInfluencers,
  fetchInfluencer,
  type AdminEmail,
  type AdminInfluencer,
  type AdminProduct,
  type AdminReply,
  type AdminUser,
  type Influencer,
  updateEmailReply,
  updateInfluencer,
  updateInfluencerLead,
} from "@/lib/api";
import { upsertAdminWorkQueueEntry } from "@/lib/admin-work-queue";

const followStatusOptions = [
  { value: "new", label: "未联系" },
  { value: "to_contact", label: "待联系" },
  { value: "contacted", label: "已联系" },
  { value: "replied", label: "已回复" },
  { value: "interested", label: "有意向" },
  { value: "invalid", label: "无效邮箱" },
  { value: "blacklisted", label: "黑名单" },
];

export function hasInfluencerBusinessData(influencer: AdminInfluencer | Influencer): boolean {
  const status = influencer.follow_status;
  return status === "contacted" || status === "replied" || status === "interested" || Boolean(influencer.email);
}

type InfluencerEditDrawerProps = {
  open: boolean;
  influencerId: number | null;
  products: AdminProduct[];
  users: AdminUser[];
  onClose: () => void;
  onSaved: (influencer: Influencer) => void;
};

export function InfluencerEditDrawer({
  open,
  influencerId,
  products,
  users,
  onClose,
  onSaved,
}: InfluencerEditDrawerProps) {
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [username, setUsername] = useState("");
  const [platform, setPlatform] = useState("instagram");
  const [profileUrl, setProfileUrl] = useState("");
  const [email, setEmail] = useState("");
  const [country, setCountry] = useState("");
  const [language, setLanguage] = useState("");
  const [category, setCategory] = useState("");
  const [niche, setNiche] = useState("");
  const [followersCount, setFollowersCount] = useState("");
  const [engagementRate, setEngagementRate] = useState("");
  const [followStatus, setFollowStatus] = useState("new");
  const [ownerName, setOwnerName] = useState("");
  const [note, setNote] = useState("");

  useEffect(() => {
    if (!open || !influencerId) return;
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      setLoading(true);
      setError(null);
      fetchInfluencer(influencerId)
        .then((item) => {
          if (!active) return;
          setDisplayName(item.display_name ?? "");
          setUsername(item.username ?? "");
          setPlatform(item.platform ?? "instagram");
          setProfileUrl(item.profile_url ?? "");
          setEmail(item.final_email || item.email || "");
          setCountry(item.country ?? "");
          setLanguage(item.language ?? "");
          setCategory(item.category ?? "");
          setNiche(item.niche ?? "");
          setFollowersCount(item.followers_count != null ? String(item.followers_count) : "");
          setEngagementRate(item.engagement_rate != null ? String(item.engagement_rate) : "");
          setFollowStatus(item.follow_status ?? "new");
          setOwnerName(item.owner_name ?? item.owner ?? "");
          setNote(item.note ?? item.lead_note ?? "");
        })
        .catch((err) => {
          if (active) setError(err instanceof Error ? err.message : "加载红人失败。");
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    });
    return () => {
      active = false;
    };
  }, [influencerId, open]);

  const salesUsers = useMemo(() => users.filter((user) => user.role === "sales"), [users]);

  if (!open) return null;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!influencerId) return;
    setSubmitting(true);
    setError(null);
    try {
      const updated = await updateInfluencer(influencerId, {
        display_name: displayName.trim() || null,
        username: username.trim() || undefined,
        platform,
        profile_url: profileUrl.trim() || undefined,
        email: email.trim() || null,
        country: country.trim() || null,
        language: language.trim() || null,
        category: category.trim() || null,
        niche: niche.trim() || null,
        followers_count: followersCount ? Number(followersCount) : null,
        engagement_rate: engagementRate ? Number(engagementRate) : null,
        follow_status: followStatus,
        owner: ownerName.trim() || null,
        note: note.trim() || null,
      });
      await updateInfluencerLead(influencerId, {
        owner_name: ownerName.trim() || null,
        lead_note: note.trim() || null,
        operator_name: "admin",
      });
      onSaved(updated);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存红人失败。");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AdminDrawer open={open} title="编辑红人" description="修改红人资料、联系状态和负责人。" onClose={onClose}>
      {loading ? (
        <p className="text-sm text-[#667085]">正在加载红人资料...</p>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          {error ? <div className="rounded-md border border-[#FECDCA] bg-[#FEF3F2] px-4 py-3 text-sm text-[#B42318]">{error}</div> : null}
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="grid gap-1.5 text-sm font-medium text-[#344054]">
              红人名称
              <AdminInput value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
            </label>
            <label className="grid gap-1.5 text-sm font-medium text-[#344054]">
              用户名
              <AdminInput value={username} onChange={(e) => setUsername(e.target.value)} />
            </label>
            <label className="grid gap-1.5 text-sm font-medium text-[#344054]">
              平台
              <AdminSelect value={platform} onChange={(e) => setPlatform(e.target.value)}>
                <option value="instagram">Instagram</option>
                <option value="youtube">YouTube</option>
                <option value="tiktok">TikTok</option>
                <option value="facebook">Facebook</option>
              </AdminSelect>
            </label>
            <label className="grid gap-1.5 text-sm font-medium text-[#344054] sm:col-span-2">
              主页链接
              <AdminInput value={profileUrl} onChange={(e) => setProfileUrl(e.target.value)} />
            </label>
            <label className="grid gap-1.5 text-sm font-medium text-[#344054]">
              邮箱
              <AdminInput value={email} onChange={(e) => setEmail(e.target.value)} />
            </label>
            <label className="grid gap-1.5 text-sm font-medium text-[#344054]">
              联系状态
              <AdminSelect value={followStatus} onChange={(e) => setFollowStatus(e.target.value)}>
                {followStatusOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </AdminSelect>
            </label>
            <label className="grid gap-1.5 text-sm font-medium text-[#344054]">
              国家
              <AdminInput value={country} onChange={(e) => setCountry(e.target.value)} />
            </label>
            <label className="grid gap-1.5 text-sm font-medium text-[#344054]">
              语言
              <AdminInput value={language} onChange={(e) => setLanguage(e.target.value)} />
            </label>
            <label className="grid gap-1.5 text-sm font-medium text-[#344054]">
              类目
              <AdminInput value={category} onChange={(e) => setCategory(e.target.value)} />
            </label>
            <label className="grid gap-1.5 text-sm font-medium text-[#344054]">
              领域
              <AdminInput value={niche} onChange={(e) => setNiche(e.target.value)} />
            </label>
            <label className="grid gap-1.5 text-sm font-medium text-[#344054]">
              粉丝数
              <AdminInput type="number" value={followersCount} onChange={(e) => setFollowersCount(e.target.value)} />
            </label>
            <label className="grid gap-1.5 text-sm font-medium text-[#344054]">
              互动率 (%)
              <AdminInput type="number" step="0.1" value={engagementRate} onChange={(e) => setEngagementRate(e.target.value)} />
            </label>
            <AdminFilterField label="负责人 / 业务员" className="sm:col-span-2">
              <AdminSelect value={ownerName} onChange={(e) => setOwnerName(e.target.value)}>
                <option value="">未分配</option>
                {salesUsers.map((user) => (
                  <option key={user.id} value={user.username}>
                    {user.display_name ? `${user.display_name} / ${user.username}` : user.username}
                  </option>
                ))}
              </AdminSelect>
            </AdminFilterField>
            <label className="grid gap-1.5 text-sm font-medium text-[#344054] sm:col-span-2">
              备注
              <AdminInput value={note} onChange={(e) => setNote(e.target.value)} />
            </label>
          </div>
          <p className="text-xs text-[#667085]">
            所属品牌：{products.find((product) => product.influencers?.some((row) => row.id === influencerId))?.name ?? "请在品牌详情中调整"}
          </p>
          <div className="flex justify-end gap-2 border-t border-[#E5ECF4] pt-4">
            <Button type="button" variant="outline" onClick={onClose} disabled={submitting}>
              取消
            </Button>
            <Button type="submit" disabled={submitting} className="bg-[#2563EB] text-white hover:bg-[#1D4ED8]">
              {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              保存
            </Button>
          </div>
        </form>
      )}
    </AdminDrawer>
  );
}

export async function applyInfluencerQuickAction(
  influencerId: number,
  action: string,
): Promise<Influencer> {
  if (action === "mark_contacted") {
    return updateInfluencerLead(influencerId, { lead_status: "contacted", operator_name: "admin" });
  }
  if (action === "mark_replied") {
    return updateInfluencerLead(influencerId, { lead_status: "replied", operator_name: "admin" });
  }
  if (action === "mark_invalid") {
    return updateInfluencerLead(influencerId, { lead_status: "invalid", invalid_reason: "管理员标记无效邮箱", operator_name: "admin" });
  }
  if (action === "add_follow_up") {
    await addInfluencerFollowup(influencerId, {
      action_type: "admin_follow_up",
      content: "管理员加入待跟进列表",
      operator_name: "admin",
    });
    return updateInfluencer(influencerId, { follow_status: "to_contact" });
  }
  throw new Error("未知操作。");
}

export async function deleteInfluencerSafely(influencer: AdminInfluencer) {
  if (hasInfluencerBusinessData(influencer)) {
    await updateInfluencerLead(influencer.id, {
      lead_status: "invalid",
      invalid_reason: "管理员归档：存在邮件或跟进记录，未物理删除。",
      operator_name: "admin",
    });
    return { mode: "archived" as const };
  }
  await deleteInfluencers([influencer.id]);
  return { mode: "deleted" as const };
}

type ReplyHandleDrawerProps = {
  open: boolean;
  reply: AdminReply | null;
  onClose: () => void;
  onSaved: () => void;
};

function ReplyHandleForm({
  reply,
  onClose,
  onSaved,
}: {
  reply: AdminReply;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [processingStatus, setProcessingStatus] = useState(reply.processing_status ?? "unprocessed");
  const [intentStatus, setIntentStatus] = useState(reply.intent_status ?? "unprocessed");
  const [note, setNote] = useState("");
  const [joinFollowUp, setJoinFollowUp] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await updateEmailReply(reply!.id, {
        processing_status: processingStatus === "processed" ? "processed" : "unprocessed",
        intent_status: intentStatus,
        manual_note: note.trim() || null,
      });
      if (processingStatus === "processed") {
        upsertAdminWorkQueueEntry({ type: "reply", id: reply!.id, status: "handled", handledBy: "admin" });
      } else if (joinFollowUp) {
        upsertAdminWorkQueueEntry({ type: "reply", id: reply!.id, status: "pending", note: note.trim() || null });
      }
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存回复处理状态失败。");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      {error ? <div className="rounded-md border border-[#FECDCA] bg-[#FEF3F2] px-3 py-2 text-sm text-[#B42318]">{error}</div> : null}
      <div className="grid gap-2 rounded-md border border-[#E5ECF4] bg-[#F8FAFD] p-3 text-xs text-[#667085] sm:grid-cols-2">
        <p>品牌：{reply.product_name || "暂无"}</p>
        <p>业务员：{reply.username || "暂无"}</p>
        <p>发件人：{reply.from_address || "暂无"}</p>
        <p>收到时间：{reply.received_at ? new Date(reply.received_at).toLocaleString("zh-CN") : "暂无"}</p>
      </div>
      <label className="grid gap-1 text-sm font-medium text-[#344054]">
        邮件主题
        <AdminInput value={reply.subject || ""} disabled />
      </label>
      <AdminFilterField label="处理状态">
        <AdminSelect value={processingStatus} onChange={(e) => setProcessingStatus(e.target.value)}>
          <option value="unprocessed">待处理</option>
          <option value="processed">已处理</option>
        </AdminSelect>
      </AdminFilterField>
      <AdminFilterField label="意向状态">
        <AdminSelect value={intentStatus} onChange={(e) => setIntentStatus(e.target.value)}>
          <option value="unprocessed">待判断</option>
          <option value="interested">有意向</option>
          <option value="follow_up">待跟进</option>
          <option value="not_interested">无意向</option>
          <option value="unmatched">未匹配</option>
        </AdminSelect>
      </AdminFilterField>
      <label className="flex items-center gap-2 text-sm text-[#344054]">
        <input type="checkbox" checked={joinFollowUp} onChange={(e) => setJoinFollowUp(e.target.checked)} />
        加入待跟进中心
      </label>
      <label className="grid gap-1 text-sm font-medium text-[#344054]">
        备注
        <AdminInput value={note} onChange={(e) => setNote(e.target.value)} placeholder="记录处理说明" />
      </label>
      <div className="flex justify-end gap-2 border-t border-[#E5ECF4] pt-3">
        <Button type="button" variant="outline" size="sm" onClick={onClose} disabled={submitting}>
          取消
        </Button>
        <Button type="submit" size="sm" disabled={submitting} className="bg-[#2563EB] text-white hover:bg-[#1D4ED8]">
          {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          保存
        </Button>
      </div>
    </form>
  );
}

export function ReplyHandleDrawer({ open, reply, onClose, onSaved }: ReplyHandleDrawerProps) {
  if (!open || !reply) return null;

  return (
    <AdminDrawer open={open} title="编辑回复" description={reply.subject || "回复记录"} onClose={onClose}>
      <ReplyHandleForm key={reply.id} reply={reply} onClose={onClose} onSaved={onSaved} />
    </AdminDrawer>
  );
}

type EmailEditDrawerProps = {
  open: boolean;
  email: AdminEmail | null;
  onClose: () => void;
  onSaved: () => void;
};

function EmailEditForm({
  email,
  onClose,
  onSaved,
}: {
  email: AdminEmail;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [followStatus, setFollowStatus] = useState<"pending" | "reminded" | "handled" | "no_action">(
    email.has_replied ? "handled" : "pending",
  );
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      upsertAdminWorkQueueEntry({
        type: "email",
        id: email!.id,
        assigneeUserId: email!.user_id,
        status: followStatus,
        note: note.trim() || null,
        handledBy: followStatus === "handled" || followStatus === "no_action" ? "admin" : null,
      });
      if (email!.product_influencer_id && followStatus === "reminded") {
        await addInfluencerFollowup(email!.product_influencer_id, {
          action_type: "admin_reminder",
          content: note.trim() || `管理员更新邮件跟进：${email!.subject || "无主题"}`,
          operator_name: "admin",
        });
      }
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存邮件跟进失败。");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      {error ? <div className="rounded-md border border-[#FECDCA] bg-[#FEF3F2] px-3 py-2 text-sm text-[#B42318]">{error}</div> : null}
      <div className="grid gap-2 rounded-md border border-[#E5ECF4] bg-[#F8FAFD] p-3 text-xs text-[#667085] sm:grid-cols-2">
        <p>品牌：{email.product_name || "暂无"}</p>
        <p>业务员：{email.username || "暂无"}</p>
        <p>收件人：{(email.recipients ?? []).join("、") || "暂无"}</p>
        <p>发送状态：{email.status || "暂无"}</p>
        <p>是否回复：{email.has_replied ? "已回复" : "未回复"}</p>
        <p>发送时间：{email.sent_at ? new Date(email.sent_at).toLocaleString("zh-CN") : "暂无"}</p>
      </div>
      <label className="grid gap-1 text-sm font-medium text-[#344054]">
        邮件主题
        <AdminInput value={email.subject || ""} disabled />
      </label>
      <AdminFilterField label="跟进状态">
        <AdminSelect value={followStatus} onChange={(e) => setFollowStatus(e.target.value as typeof followStatus)}>
          <option value="pending">待跟进</option>
          <option value="reminded">已提醒</option>
          <option value="handled">已处理</option>
          <option value="no_action">无需处理</option>
        </AdminSelect>
      </AdminFilterField>
      <label className="grid gap-1 text-sm font-medium text-[#344054]">
        备注
        <AdminInput value={note} onChange={(e) => setNote(e.target.value)} placeholder="跟进说明" />
      </label>
      <p className="text-[11px] text-[#667085]">主题、收件人等发送字段由系统记录，管理员可调整跟进状态与备注。</p>
      <div className="flex justify-end gap-2 border-t border-[#E5ECF4] pt-3">
        <Button type="button" variant="outline" size="sm" onClick={onClose} disabled={submitting}>
          取消
        </Button>
        <Button type="submit" size="sm" disabled={submitting} className="bg-[#2563EB] text-white hover:bg-[#1D4ED8]">
          {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          保存
        </Button>
      </div>
    </form>
  );
}

export function EmailEditDrawer({ open, email, onClose, onSaved }: EmailEditDrawerProps) {
  if (!open || !email) return null;

  return (
    <AdminDrawer open={open} title="编辑邮件跟进" description={email.subject || "邮件记录"} onClose={onClose}>
      <EmailEditForm key={email.id} email={email} onClose={onClose} onSaved={onSaved} />
    </AdminDrawer>
  );
}

export function InfluencerDeleteConfirmDialog({
  open,
  influencer,
  loading,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  influencer: AdminInfluencer | null;
  loading?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const hasData = influencer ? hasInfluencerBusinessData(influencer) : false;
  return (
    <AdminDeleteConfirmDialog
      open={open}
      title={hasData ? "确认归档红人？" : "确认删除红人？"}
      description={
        hasData
          ? "该红人已有联系、回复或邮件记录，物理删除可能影响统计。系统将改为归档（标记无效）。"
          : "删除后不可恢复，请确认该红人不再需要。"
      }
      confirmDisabled={false}
      loading={loading}
      onCancel={onCancel}
      onConfirm={onConfirm}
    />
  );
}
