// 文件说明：前端页面组件；当前文件：login background
"use client";

export function LoginPageBackdrop() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
      <div className="absolute inset-0 bg-[linear-gradient(135deg,#f4f7f2_0%,#eef4ec_42%,#f8f2e8_100%)]" />

      <div className="absolute inset-x-0 top-0 h-28 bg-[linear-gradient(180deg,rgba(255,255,255,0.84),rgba(255,255,255,0))]" />
      <div className="absolute inset-x-0 bottom-0 h-40 bg-[linear-gradient(0deg,rgba(229,236,222,0.68),rgba(229,236,222,0))]" />

      <div
        className="absolute inset-0 opacity-[0.2]"
        style={{
          backgroundImage: `
            linear-gradient(to right, rgba(85, 99, 73, 0.11) 1px, transparent 1px),
            linear-gradient(to bottom, rgba(85, 99, 73, 0.11) 1px, transparent 1px)
          `,
          backgroundSize: "48px 48px",
        }}
      />

      <div className="absolute left-[7%] top-[16%] h-[520px] w-[360px] rotate-[-8deg] rounded-lg border border-emerald-900/[0.06] bg-emerald-100/28" />
      <div className="absolute right-[6%] top-[18%] h-[560px] w-[410px] rotate-[7deg] rounded-lg border border-orange-900/[0.06] bg-orange-100/26" />

      <svg
        className="absolute inset-0 h-full w-full text-[#556349]/[0.12]"
        viewBox="0 0 1440 900"
        fill="none"
        preserveAspectRatio="xMidYMid slice"
      >
        <path
          d="M-60 585 C 170 505, 330 612, 535 530 S 865 405, 1080 485 S 1320 600, 1500 490"
          stroke="currentColor"
          strokeWidth="1"
        />
        <path
          d="M-40 710 C 230 615, 430 745, 720 650 S 1055 555, 1335 628"
          stroke="currentColor"
          strokeWidth="1"
          opacity="0.5"
        />
      </svg>

      <div className="absolute left-[9%] top-[21%] hidden w-56 rounded-lg border border-white/68 bg-white/48 p-3 shadow-sm shadow-slate-900/[0.04] lg:block">
        <div className="flex items-center justify-between text-[11px] text-slate-500">
          <span>Amazon Deals</span>
          <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-emerald-700">Live</span>
        </div>
        <div className="mt-3 flex gap-2">
          <div className="h-12 w-12 rounded-md bg-[linear-gradient(135deg,#f3d6a4,#d78145)]" />
          <div className="min-w-0 flex-1">
            <div className="h-2.5 w-24 rounded bg-slate-700/20" />
            <div className="mt-2 h-2 w-32 rounded bg-slate-700/12" />
            <div className="mt-3 h-1.5 w-full rounded bg-emerald-600/22" />
          </div>
        </div>
      </div>

      <div className="absolute right-[8%] top-[27%] hidden w-60 rounded-lg border border-white/70 bg-white/50 p-3 shadow-sm shadow-slate-900/[0.04] xl:block">
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-slate-500">Creator replies</span>
          <span className="rounded bg-orange-100 px-1.5 py-0.5 text-[11px] font-medium text-orange-700">Active</span>
        </div>
        <div className="mt-3 space-y-2">
          <div className="h-2.5 w-44 rounded bg-slate-700/18" />
          <div className="h-2.5 w-36 rounded bg-slate-700/12" />
          <div className="h-2.5 w-48 rounded bg-slate-700/10" />
        </div>
      </div>
    </div>
  );
}
