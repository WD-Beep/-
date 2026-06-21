"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorAlert, SuccessAlert } from "@/components/shared/page-states";
import {
  saveEmailLogAsMessageTemplate,
  type EmailLog,
  type SaveEmailLogAsTemplatePayload,
} from "@/lib/api";
import {
  MESSAGE_TEMPLATE_SCENARIO_OPTIONS,
  translateErrorMessage,
} from "@/lib/labels";

type SaveEmailAsTemplateDialogProps = {
  log: EmailLog;
  open: boolean;
  onClose: () => void;
  onSaved?: () => void;
  duplicateHint?: boolean;
};

export function SaveEmailAsTemplateDialog({
  log,
  open,
  onClose,
  onSaved,
  duplicateHint = false,
}: SaveEmailAsTemplateDialogProps) {
  const [title, setTitle] = useState(log.subject || "");
  const [scenario, setScenario] = useState("first_contact");
  const [language, setLanguage] = useState("en");
  const [tags, setTags] = useState("ai_outreach, saved_from_email");
  const [content, setContent] = useState(log.body || "");
  const [saveAsCopy, setSaveAsCopy] = useState(duplicateHint);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  if (!open) return null;

  async function handleSubmit() {
    setLoading(true);
    setError(null);
    setSuccess(null);
    const payload: SaveEmailLogAsTemplatePayload = {
      title: title.trim(),
      scenario,
      language,
      tags: tags
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean),
      content: content.trim(),
      save_as_copy: saveAsCopy,
    };
    try {
      const result = await saveEmailLogAsMessageTemplate(log.id, payload);
      if (result.duplicate && !result.created) {
        setError(result.message);
        setSaveAsCopy(true);
        return;
      }
      if (result.created) {
        setSuccess(result.message);
        onSaved?.();
      } else {
        setError(result.message);
      }
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "保存失败"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <Card className="max-h-[92vh] w-full max-w-lg overflow-y-auto">
        <CardHeader className="border-b">
          <CardTitle className="text-lg">保存为话术</CardTitle>
          <CardDescription>将已发送的 AI 邮件保存到当前产品话术库</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 pt-4">
          {error ? <ErrorAlert message={error} /> : null}
          {success ? <SuccessAlert message={success} /> : null}
          {duplicateHint ? (
            <p className="text-sm text-amber-700">检测到相同标题和正文，可勾选「另存为副本」后保存。</p>
          ) : null}

          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">标题</label>
            <input
              className="w-full rounded-md border bg-background px-3 py-2 text-sm"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">场景</label>
              <select
                className="flex h-9 w-full rounded-md border bg-background px-3 text-sm"
                value={scenario}
                onChange={(e) => setScenario(e.target.value)}
              >
                {MESSAGE_TEMPLATE_SCENARIO_OPTIONS.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">语言</label>
              <select
                className="flex h-9 w-full rounded-md border bg-background px-3 text-sm"
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
              >
                <option value="en">英文</option>
                <option value="zh">中文</option>
                <option value="other">其他</option>
              </select>
            </div>
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">标签（逗号分隔）</label>
            <input
              className="w-full rounded-md border bg-background px-3 py-2 text-sm"
              value={tags}
              onChange={(e) => setTags(e.target.value)}
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">正文</label>
            <textarea
              className="min-h-[180px] w-full rounded-md border bg-background px-3 py-2 text-sm"
              value={content}
              onChange={(e) => setContent(e.target.value)}
            />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={saveAsCopy}
              onChange={(e) => setSaveAsCopy(e.target.checked)}
            />
            另存为副本（标题自动加「副本」后缀）
          </label>
          <div className="flex gap-2 border-t pt-3">
            <Button onClick={() => void handleSubmit()} disabled={loading || !!success}>
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              保存
            </Button>
            <Button variant="ghost" onClick={onClose}>
              {success ? "关闭" : "取消"}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
