// 文件说明：前端管理员后台组件；当前文件：admin placeholder panel
type AdminPlaceholderPanelProps = {
  title: string;
  label: string;
  description: string;
};

export function AdminPlaceholderPanel({ title, label, description }: AdminPlaceholderPanelProps) {
  return (
    <div className="space-y-4">
      <section>
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#4F6B8A]">{label}</p>
        <h1 className="mt-2 text-2xl font-semibold tracking-normal text-[#102033]">{title}</h1>
        <p className="mt-1 text-sm text-[#667085]">{description}</p>
      </section>
      <div className="rounded-md border border-[#DDE6F0] bg-white p-6 text-sm text-[#667085]">
        第一版先提供后台导航占位，后续再接入详细管理视图。
      </div>
    </div>
  );
}
