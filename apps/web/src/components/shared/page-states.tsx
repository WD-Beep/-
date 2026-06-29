import { AlertCircle, Inbox, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function LoadingState({ label = "加载中..." }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" />
      {label}
    </div>
  );
}

export function EmptyState({
  title = "暂无数据",
  description,
  action,
  secondaryAction,
}: {
  title?: string;
  description?: string;
  action?: React.ReactNode;
  secondaryAction?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-12 text-center">
      <span className="flex h-11 w-11 items-center justify-center rounded-lg border border-slate-200 bg-slate-50">
        <Inbox className="h-6 w-6 text-slate-400" />
      </span>
      <div className="space-y-1">
        <p className="font-medium text-foreground">{title}</p>
        {description ? <p className="max-w-md text-sm leading-6 text-muted-foreground">{description}</p> : null}
      </div>
      {action || secondaryAction ? (
        <div className="flex flex-wrap items-center justify-center gap-2">
          {action}
          {secondaryAction}
        </div>
      ) : null}
    </div>
  );
}

export function ErrorAlert({
  message,
  className,
  onRetry,
}: {
  message: string;
  className?: string;
  onRetry?: () => void;
}) {
  return (
    <div
      className={cn(
        "asset-inline-alert",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-2">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{message}</span>
        </div>
        {onRetry ? (
          <Button type="button" size="sm" variant="outline" onClick={onRetry}>
            重试
          </Button>
        ) : null}
      </div>
    </div>
  );
}

export function SuccessAlert({
  message,
  className,
}: {
  message: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800",
        className,
      )}
    >
      {message}
    </div>
  );
}
