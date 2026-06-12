"use client";

/** 分层背景：柔和渐变 + 低对比网格 + 朦胧光感 + 抽象线条 */
export function LoginPageBackdrop() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
      <div className="absolute inset-0 bg-gradient-to-br from-[#eef2f8] via-[#f3f6fb] to-[#e9eef6]" />

      {/* 低对比网格 */}
      <div
        className="absolute inset-0 opacity-[0.28]"
        style={{
          backgroundImage: `
            linear-gradient(to right, rgba(100, 116, 139, 0.08) 1px, transparent 1px),
            linear-gradient(to bottom, rgba(100, 116, 139, 0.08) 1px, transparent 1px)
          `,
          backgroundSize: "56px 56px",
        }}
      />

      {/* 朦胧光斑 */}
      <div className="absolute -left-20 top-[15%] h-80 w-80 rounded-full bg-blue-200/20 blur-3xl" />
      <div className="absolute -right-16 bottom-[10%] h-96 w-96 rounded-full bg-indigo-200/15 blur-3xl" />
      <div className="absolute left-1/2 top-0 h-64 w-[480px] -translate-x-1/2 rounded-full bg-slate-200/25 blur-3xl" />

      {/* 抽象流动线条 */}
      <svg
        className="absolute inset-0 h-full w-full text-slate-400/[0.07]"
        viewBox="0 0 1440 900"
        fill="none"
        preserveAspectRatio="xMidYMid slice"
      >
        <path
          d="M-40 520 C 200 420, 360 680, 620 560 S 980 380, 1200 480 S 1520 620, 1500 400"
          stroke="currentColor"
          strokeWidth="1.2"
        />
        <path
          d="M-20 680 C 240 580, 420 760, 700 640 S 1040 520, 1300 600"
          stroke="currentColor"
          strokeWidth="0.8"
          opacity="0.6"
        />
      </svg>
    </div>
  );
}
