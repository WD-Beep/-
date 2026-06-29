import { Sidebar } from "@/components/layout/sidebar";

type AdminShellProps = {
  children: React.ReactNode;
  title: string;
  description?: string;
  actions?: React.ReactNode;
};

export function AdminShell({ children, title, description, actions }: AdminShellProps) {
  return (
    <div className="flex h-screen overflow-hidden bg-[hsl(214_30%_95%)]">
      <Sidebar />
      <main className="min-w-0 flex-1 overflow-hidden">
        <section className="flex h-full min-h-0 flex-col overflow-hidden">
          <header className="admin-page-header shrink-0 px-6 py-3 lg:px-8">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <h1 className="text-[22px] font-semibold tracking-normal text-slate-950">{title}</h1>
                {description ? (
                  <p className="mt-0.5 max-w-3xl text-[13px] leading-5 text-slate-600">{description}</p>
                ) : null}
              </div>
              {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
            </div>
          </header>
          <div className="min-h-0 flex-1 overflow-hidden px-6 py-4 lg:px-8">{children}</div>
        </section>
      </main>
    </div>
  );
}
