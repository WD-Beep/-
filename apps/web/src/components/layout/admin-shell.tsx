import { Sidebar } from "@/components/layout/sidebar";

type AdminShellProps = {
  children: React.ReactNode;
  title: string;
  description?: string;
};

export function AdminShell({ children, title, description }: AdminShellProps) {
  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-16 shrink-0 items-center justify-between border-b bg-background px-8">
          <div className="min-w-0">
            <h1 className="text-lg font-semibold">{title}</h1>
            {description ? (
              <p className="text-sm text-muted-foreground">{description}</p>
            ) : null}
          </div>
        </header>
        <main className="min-w-0 flex-1 overflow-x-auto p-8">{children}</main>
      </div>
    </div>
  );
}
