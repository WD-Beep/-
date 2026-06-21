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
