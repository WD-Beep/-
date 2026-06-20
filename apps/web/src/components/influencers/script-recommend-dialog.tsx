"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Bot,
  Copy,
  Loader2,
  RefreshCw,
  Sparkles,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  recommendScript,
  type Influencer,
  type ScriptRecommendResponse,
} from "@/lib/api";
import { platformLabel, translateErrorMessage } from "@/lib/labels";

const INTENT_OPTIONS = [
  "首次联系",
  "报价沟通",
  "追问合作",
  "解释品牌",
  "发送产品亮点",
];

type ScriptRecommendDialogProps = {
  influencer: Influencer;
  open: boolean;
  onClose: () => void;
};

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export function ScriptRecommendDialog({
  influencer,
  open,
  onClose,
}: ScriptRecommendDialogProps) {
  const [intent, setIntent] = useState("首次联系");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ScriptRecommendResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const requestIdRef = useRef(0);

  const loadRecommendation = useCallback(async () => {
    const requestId = ++requestIdRef.current;
    setResult(null);
    setError(null);
    setCopied(false);
    setLoading(true);
    try {
      const data = await recommendScript({
        influencer_id: influencer.id,
        user_intent: intent,
        followup_status: influencer.lead_status ?? influencer.follow_status,
        contact_status: influencer.email || influencer.final_email ? "has_email" : "no_email",
      });
      if (requestId !== requestIdRef.current) return;
      setResult(data);
      if (data.error_message && !data.final_message) {
        setError(data.error_message);
      }
    } catch (err) {
      if (requestId !== requestIdRef.current) return;
      setError(translateErrorMessage(err instanceof Error ? err.message : "推荐失败"));
      setResult(null);
    } finally {
      if (requestId === requestIdRef.current) {
        setLoading(false);
      }
    }
  }, [influencer, intent]);

  useEffect(() => {
    if (!open) return;
    queueMicrotask(() => {
      void loadRecommendation();
    });
  }, [open, loadRecommendation]);

  if (!open) return null;

  const displayName = influencer.display_name || influencer.username;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <Card className="max-h-[90vh] w-full max-w-2xl overflow-y-auto">
        <CardHeader className="border-b">
          <div className="flex items-start justify-between gap-4">
            <div>
              <CardTitle className="flex items-center gap-2 text-lg">
                <Bot className="h-5 w-5 text-primary" />
                AI 推荐话术
              </CardTitle>
              <CardDescription className="mt-1">
                {displayName} · {platformLabel(influencer.platform)} ·{" "}
                {influencer.followers_count?.toLocaleString() ?? "-"} 粉丝
              </CardDescription>
            </div>
            <Button variant="ghost" size="sm" onClick={onClose}>
              关闭
            </Button>
          </div>
        </CardHeader>

        <CardContent className="space-y-4 pt-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-muted-foreground">沟通意图</span>
            <select
              value={intent}
              onChange={(e) => setIntent(e.target.value)}
              className="h-9 rounded-md border border-input bg-background px-3 text-sm"
              disabled={loading}
            >
              {INTENT_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
            <Button
              size="sm"
              variant="outline"
              disabled={loading}
              onClick={() => void loadRecommendation()}
            >
              {loading ? (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="mr-1 h-4 w-4" />
              )}
              重新推荐
            </Button>
          </div>

          {loading ? (
            <div className="flex items-center gap-2 rounded-lg border bg-muted/30 px-4 py-8 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              正在结合知识库与话术库生成推荐…
            </div>
          ) : null}

          {result && !result.configured ? (
            <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950">
              未配置 OpenAI，仅返回候选话术，未进行 AI 改写。配置 OPENAI_API_KEY 后可获得基于知识库的 AI 改写推荐。
            </div>
          ) : null}

          {error ? (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
              {error}
            </div>
          ) : null}

          {result ? (
            <div className="space-y-4">
              {result.recommended_script_title ? (
                <div>
                  <p className="text-xs font-medium text-muted-foreground">推荐话术模板</p>
                  <p className="text-sm font-medium">{result.recommended_script_title}</p>
                </div>
              ) : null}

              <div>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <p className="text-xs font-medium text-muted-foreground">最终话术</p>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!result.final_message}
                    onClick={async () => {
                      if (!result.final_message) return;
                      const ok = await copyText(result.final_message);
                      setCopied(ok);
                      window.setTimeout(() => setCopied(false), 2000);
                    }}
                  >
                    <Copy className="mr-1 h-3.5 w-3.5" />
                    {copied ? "已复制" : "复制"}
                  </Button>
                </div>
                <div className="rounded-lg border bg-muted/20 p-4 text-sm leading-relaxed whitespace-pre-wrap">
                  {result.final_message || "暂无推荐话术"}
                </div>
              </div>

              {result.reason ? (
                <div>
                  <p className="mb-1 text-xs font-medium text-muted-foreground">推荐理由</p>
                  <p className="text-sm text-foreground/90">{result.reason}</p>
                </div>
              ) : null}

              {result.matched_knowledge.length > 0 ? (
                <div>
                  <p className="mb-2 flex items-center gap-1 text-xs font-medium text-muted-foreground">
                    <Sparkles className="h-3.5 w-3.5" />
                    引用知识库
                  </p>
                  <div className="space-y-2">
                    {result.matched_knowledge.map((item, index) => (
                      <div key={`${item.document}-${index}`} className="rounded-lg border px-3 py-2 text-sm">
                        <p className="font-medium">
                          {item.document}
                          {item.section ? ` · ${item.section}` : ""}
                        </p>
                        <p className="mt-1 text-muted-foreground">{item.summary}</p>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}

              <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                <span>语气：{result.tone}</span>
                <span>·</span>
                <span>模型：{result.provider}</span>
                {!result.configured ? <span className="text-amber-700">· 未配置 OpenAI</span> : null}
              </div>

              {result.risk_notes.length > 0 ? (
                <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700">
                  <p className="font-medium">注意</p>
                  <ul className="mt-1 list-disc pl-4">
                    {result.risk_notes.map((note) => (
                      <li key={note}>{note}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
