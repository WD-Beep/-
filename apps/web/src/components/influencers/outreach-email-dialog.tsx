"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, Mail, RefreshCw, Send, Clock } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorAlert, SuccessAlert } from "@/components/shared/page-states";
import {
  previewInfluencerOutreachEmail,
  sendInfluencerOutreachEmail,
  enqueueInfluencerOutreachEmail,
  type Influencer,
  type SingleOutreachEmailPreview,
} from "@/lib/api";
import {
  canSendOutreachEmail,
  outreachRecipientIssue,
  outreachSendConfirmMessage,
} from "@/lib/outreach-email-helpers";
import { EmailAddressCell } from "@/lib/email-address-cell";
import { translateErrorMessage } from "@/lib/labels";

type OutreachEmailDialogProps = {
  influencer: Influencer;
  open: boolean;
  onClose: () => void;
  onSent?: () => void;
};

export function OutreachEmailDialog({
  influencer,
  open,
  onClose,
  onSent,
}: OutreachEmailDialogProps) {
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [preview, setPreview] = useState<SingleOutreachEmailPreview | null>(null);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [confirmSend, setConfirmSend] = useState(false);
  const [queuing, setQueuing] = useState(false);
  const [confirmQueue, setConfirmQueue] = useState(false);

  const loadPreview = useCallback(async () => {
    setLoading(true);
    setError(null);
    setSuccess(null);
    setConfirmSend(false);
    setConfirmQueue(false);
    try {
      const data = await previewInfluencerOutreachEmail(influencer.id);
      setPreview(data);
      setSubject(data.subject);
      setBody(data.body);
    } catch (err) {
      setPreview(null);
      setSubject("");
      setBody("");
      setError(err instanceof Error ? err.message : "生成失败");
    } finally {
      setLoading(false);
    }
  }, [influencer.id]);

  useEffect(() => {
    if (!open) return;
    queueMicrotask(() => {
      void loadPreview();
    });
  }, [open, loadPreview]);

  async function handleEnqueue() {
    if (!preview) return;
    if (!confirmQueue) {
      setConfirmQueue(true);
      return;
    }
    setQueuing(true);
    setError(null);
    setSuccess(null);
    try {
      await enqueueInfluencerOutreachEmail(influencer.id, {
        subject: subject.trim(),
        body: body.trim(),
        matched_knowledge: preview.matched_knowledge,
        ai_reason: preview.reason,
        template_title: preview.template_title,
      });
      setSuccess("已加入发送队列。可在邮件日志页手动「发送今日队列」。");
      setConfirmQueue(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加入队列失败");
      setConfirmQueue(false);
    } finally {
      setQueuing(false);
    }
  }

  async function handleSend() {
    if (!preview) return;
    if (!confirmSend) {
      setConfirmSend(true);
      return;
    }
    setSending(true);
    setError(null);
    setSuccess(null);
    try {
      const result = await sendInfluencerOutreachEmail(influencer.id, {
        subject: subject.trim(),
        body: body.trim(),
      });
      if (result.success) {
        setSuccess(result.message || "邮件发送成功");
        setConfirmSend(false);
        onSent?.();
      } else {
        setError(translateErrorMessage(result.message || "发送失败"));
        setConfirmSend(false);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "发送失败");
      setConfirmSend(false);
    } finally {
      setSending(false);
    }
  }

  const sendable = canSendOutreachEmail({
    recipient: preview?.recipient ?? "",
    subject,
    body,
    senderEmail: preview?.sender_email,
  });
  const recipientIssue = outreachRecipientIssue(preview?.recipient, preview?.sender_email);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <Card className="max-h-[92vh] w-full max-w-2xl overflow-y-auto">
        <CardHeader className="border-b sticky top-0 bg-card z-10">
          <div className="flex items-start justify-between gap-4">
            <div>
              <CardTitle className="flex items-center gap-2 text-lg">
                <Mail className="h-5 w-5 text-primary" />
                AI 定制邮件
              </CardTitle>
              <CardDescription className="mt-1">
                {influencer.display_name || influencer.username} · @{influencer.username}
              </CardDescription>
            </div>
            <Button variant="ghost" size="sm" onClick={onClose}>
              关闭
            </Button>
          </div>
        </CardHeader>

        <CardContent className="space-y-4 pt-4">
          {error ? <ErrorAlert message={translateErrorMessage(error)} /> : null}
          {success ? <SuccessAlert message={success} /> : null}

          {loading ? (
            <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              正在生成定制邮件…
            </div>
          ) : preview ? (
            <>
              <div className="grid gap-2 text-sm">
                <p className="flex items-center gap-2">
                  <span className="text-muted-foreground shrink-0">收件人：</span>
                  <EmailAddressCell email={preview.recipient || null} />
                </p>
                <p className="flex items-center gap-2">
                  <span className="text-muted-foreground shrink-0">发件人：</span>
                  <span
                    className="block max-w-[420px] truncate text-sm"
                    title={preview.sender_display || preview.sender_email || "-"}
                  >
                    {preview.sender_display || preview.sender_email || "-"}
                  </span>
                </p>
                <p>
                  <span className="text-muted-foreground">参考话术：</span>
                  {preview.template_title || "系统默认话术"}
                </p>
              </div>

              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">邮件标题</label>
                <input
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                />
              </div>

              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">邮件正文</label>
                <textarea
                  className="min-h-[220px] w-full rounded-md border bg-background px-3 py-2 text-sm"
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                />
              </div>

              {preview.reason ? (
                <p className="text-xs text-muted-foreground">推荐理由：{preview.reason}</p>
              ) : null}

              {preview.matched_knowledge.length > 0 ? (
                <div className="rounded-md border p-3 text-xs text-muted-foreground space-y-1">
                  <p className="font-medium text-foreground">知识库引用</p>
                  {preview.matched_knowledge.map((item, idx) => (
                    <p key={`${item.document}-${idx}`}>
                      {item.document}
                      {item.section ? ` · ${item.section}` : ""} — {item.summary}
                    </p>
                  ))}
                </div>
              ) : null}

              {recipientIssue ? (
                <p className="text-sm text-amber-700">{recipientIssue}</p>
              ) : null}
              {confirmQueue ? (
                <p className="text-sm text-amber-700">
                  确认将当前预览邮件加入发送队列？不会立即发送，需在邮件日志页手动触发「发送今日队列」。
                </p>
              ) : null}
              {confirmSend ? (
                <p className="text-sm text-amber-700">
                  {outreachSendConfirmMessage(preview.recipient)}
                </p>
              ) : null}
            </>
          ) : null}

          <div className="flex flex-wrap gap-2 border-t pt-3">
            <Button variant="outline" disabled={loading || sending || queuing} onClick={() => void loadPreview()}>
              <RefreshCw className="h-4 w-4" />
              重新生成
            </Button>
            <Button
              variant="outline"
              disabled={loading || sending || queuing || !sendable || !preview}
              onClick={() => void handleEnqueue()}
            >
              {queuing ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Clock className="h-4 w-4" />
              )}
              {confirmQueue ? "确认加入队列" : "加入发送队列"}
            </Button>
            {confirmQueue ? (
              <Button variant="ghost" size="sm" onClick={() => setConfirmQueue(false)}>
                取消
              </Button>
            ) : null}
            <Button
              variant={confirmSend ? "destructive" : "default"}
              disabled={loading || sending || queuing || !sendable || !preview}
              onClick={() => void handleSend()}
            >
              {sending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
              {confirmSend ? "确认发送" : "发送邮件"}
            </Button>
            {confirmSend ? (
              <Button variant="ghost" size="sm" onClick={() => setConfirmSend(false)}>
                取消
              </Button>
            ) : null}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
