// 文件说明：前端公共工具和业务辅助函数；当前文件：email address cell
import { formatEmailDisplay } from "@/lib/email-display-helpers";

type EmailAddressCellProps = {
  email: string | null | undefined;
  displayName?: string | null;
  className?: string;
};

export function EmailAddressCell({ email, displayName, className = "" }: EmailAddressCellProps) {
  const full = formatEmailDisplay(email, displayName);
  if (full === "-") {
    return <span className="text-muted-foreground">-</span>;
  }
  return (
    <span
      className={`block max-w-[280px] truncate text-sm ${className}`}
      title={full}
    >
      {full}
    </span>
  );
}
