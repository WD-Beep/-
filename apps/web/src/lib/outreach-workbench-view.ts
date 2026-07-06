export function outreachWorkbenchStatusLabel({
  status,
  loading,
  hasWorkbench,
  hasError,
}: {
  status?: string;
  loading: boolean;
  hasWorkbench: boolean;
  hasError: boolean;
}): string {
  if (loading) return "检查中";
  if (!hasWorkbench && hasError) return "检查失败";
  if (!hasWorkbench) return "待检查";
  if (status === "normal") return "正常";
  if (status === "not_configured") return "未配置";
  if (status === "error") return "异常";
  return status || "待检查";
}
