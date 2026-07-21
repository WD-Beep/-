// 文件说明：前端红人列表和详情组件；当前文件：batch outreach dialog
"use client";

import { useCallback, useEffect, useState } from "react";
import { Copy, Loader2, Mail, Send, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorAlert, SuccessAlert } from "@/components/shared/page-states";
import {
  previewOutreachBatch,
  sendOutreachBatch,
  type Influencer,
  type OutreachBatchPreviewResponse,
  type OutreachPreviewItem,
} from "@/lib/api";
import { translateErrorMessage } from "@/lib/labels";
import {
  buildDryRunSuccessMessage,
  buildRealSendSuccessMessage,
  countSendablePreviewItems,
  realSendButtonLabel,
  shouldProceedRealSend,
} from "@/lib/batch-outreach-helpers";

type BatchOutreachDialogProps = {
  influencers: Influencer[];
  open: boolean;
  onClose: () => void;
  onComplete?: () => void;
};

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function PreviewCard({ item }: { item: OutreachPreviewItem }) {
  const [copied, setCopied] = useState(false);

  return (
    <div className="rounded-lg border p-4 space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="font-medium">
            {item.display_name || item.username} · @{item.username}
          </p>
          <p className="text-xs text-muted-foreground">
            收件人：{item.recipient || "无邮箱"} · {item.can_send ? "可发送" : "不可发送"}
          </p>
        </div>
        {item.generated_by_ai ? (
          <span className="text-xs rounded bg-primary/10 px-2 py-0.5 text-primary">AI 生成</span>
        ) : (
          <span className="text-xs rounded bg-muted px-2 py-0.5 text-muted-foreground">模板降级</span>
        )}
      </div>
      <div>
        <p className="text-xs font-medium text-muted-foreground">标题</p>
        <p className="text-sm break-all">{item.subject || "-"}</p>
      </div>
      <div>
        <p className="text-xs font-medium text-muted-foreground">正文</p>
        <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap rounded bg-muted/40 p-2 text-xs">
          {item.body || "-"}
        </pre>
      </div>
      {item.reason ? (
        <p className="text-xs text-muted-foreground">推荐理由：{item.reason}</p>
      ) : null}
      {item.matched_knowledge.length > 0 ? (
        <div className="text-xs text-muted-foreground">
          知识库引用：
          {item.matched_knowledge.map((k) => k.document).join(" · ")}
        </div>
      ) : null}
      {item.risk_notes.length > 0 ? (
        <div className="text-xs text-amber-700">{item.risk_notes.join(" · ")}</div>
      ) : null}
      {item.error_message ? (
        <p className="text-xs text-destructive">{translateErrorMessage(item.error_message)}</p>
      ) : null}
      {item.body ? (
        <Button
          size="sm"
          variant="outline"
          onClick={() => {
            void copyText(`Subject: ${item.subject}\n\n${item.body}`).then((ok) => {
              if (ok) {
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              }
            });
          }}
        >
          <Copy className="h-3.5 w-3.5" />
          {copied ? "已复制" : "复制正文"}
        </Button>
      ) : null}
    </div>
  );
}

export function BatchOutreachDialog({
  influencers,
  open,
  onClose,
  onComplete,
}: BatchOutreachDialogProps) {
  const [intent] = useState("首次合作邀约");
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [preview, setPreview] = useState<OutreachBatchPreviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [confirmSend, setConfirmSend] = useState(false);

  const ids = influencers.map((item) => item.id);
  const sendableCount = preview ? countSendablePreviewItems(preview.items) : 0;

  const loadPreview = useCallback(async () => {
    setLoading(true);
    setError(null);
    setMessage(null);
    setConfirmSend(false);
    try {
      const data = await previewOutreachBatch({
        influencer_ids: ids,
        user_intent: intent,
        limit: 20,
      });
      setPreview(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "预览失败");
      setPreview(null);
    } finally {
      setLoading(false);
    }
  }, [ids, intent]);

  useEffect(() => {
    if (!open) return;
    queueMicrotask(() => {
      void loadPreview();
    });
  }, [open, loadPreview]);

  async function handleDryRun() {
    setSending(true);
    setError(null);
    setMessage(null);
    try {
      const result = await sendOutreachBatch({
        influencer_ids: ids,
        user_intent: intent,
        dry_run: true,
      });
      setMessage(buildDryRunSuccessMessage({ ...result.summary, pending: result.summary.pending }));
      onComplete?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "测试生成失败");
    } finally {
      setSending(false);
    }
  }

  async function handleRealSend() {
    if (!shouldProceedRealSend(confirmSend)) {
      setConfirmSend(true);
      return;
    }
    setSending(true);
    setError(null);
    setMessage(null);
    try {
      const result = await sendOutreachBatch({
        influencer_ids: ids,
        user_intent: intent,
        dry_run: false,
      });
      setMessage(buildRealSendSuccessMessage(result.summary));
      setConfirmSend(false);
      onComplete?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "发送失败");
    } finally {
      setSending(false);
    }
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <Card className="max-h-[92vh] w-full max-w-4xl overflow-y-auto">
        <CardHeader className="border-b sticky top-0 bg-card z-10">
          <div className="flex items-start justify-between gap-4">
            <div>
              <CardTitle className="flex items-center gap-2 text-lg">
                <Sparkles className="h-5 w-5 text-primary" />
                批量 AI 邮件预览
              </CardTitle>
              <CardDescription className="mt-1">
                已选 {influencers.length} 位红人 · 每位独立生成 subject/body · 默认仅测试生成
              </CardDescription>
            </div>
            <Button variant="ghost" size="sm" onClick={onClose}>
              关闭
            </Button>
          </div>
        </CardHeader>

        <CardContent className="space-y-4 pt-4">
          {error ? <ErrorAlert message={error} /> : null}
          {message ? <SuccessAlert message={message} /> : null}

          {loading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground py-8 justify-center">
              <Loader2 className="h-4 w-4 animate-spin" />
              正在为每位红人生成个性化邮件…
            </div>
          ) : preview ? (
            <>
              <p className="text-sm text-muted-foreground">
                预览 {preview.summary.generated}/{preview.summary.total} · 缺邮箱{" "}
                {preview.summary.missing_email} · 失败 {preview.summary.failed}
              </p>
              <div className="space-y-3">
                {preview.items.map((item) => (
                  <PreviewCard key={item.influencer_id} item={item} />
                ))}
              </div>
            </>
          ) : null}

          <div className="flex flex-wrap gap-2 pt-2 border-t sticky bottom-0 bg-card pb-1">
            <Button variant="outline" onClick={() => void loadPreview()} disabled={loading || sending}>
              重新预览
            </Button>
            <Button
              variant="secondary"
              onClick={() => void handleDryRun()}
              disabled={loading || sending || !preview}
            >
              <Mail className="h-4 w-4" />
              仅测试生成
            </Button>
            <Button
              variant={confirmSend ? "destructive" : "default"}
              onClick={() => void handleRealSend()}
              disabled={loading || sending || !preview || sendableCount === 0}
            >
              <Send className="h-4 w-4" />
              {realSendButtonLabel(confirmSend, sendableCount)}
            </Button>
            {confirmSend ? (
              <Button variant="ghost" size="sm" onClick={() => setConfirmSend(false)}>
                取消确认
              </Button>
            ) : null}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
