"use client";

import { Sparkles } from "lucide-react";

const TAGS = ["达人线索采集", "外链识别", "商务触达"] as const;

const PLATFORMS = ["Amazon", "TikTok", "Instagram", "YouTube"] as const;

export function LoginBrandPanel() {
  return (
    <div className="flex flex-col justify-center">
      <div className="flex items-center gap-3">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[#2563EB] text-white shadow-sm shadow-blue-500/20">
          <Sparkles className="h-5 w-5" />
        </div>
        <div>
          <h1 className="text-[28px] font-bold leading-tight tracking-tight text-slate-900">
            红人智采
          </h1>
          <p className="mt-1 text-[15px] text-slate-500">海外红人数据管理平台</p>
        </div>
      </div>

      <p className="mt-6 max-w-[280px] text-sm leading-relaxed text-slate-400">
        连接全球社交电商渠道，助力品牌高效发现、评估与触达海外红人。
      </p>

      <div className="mt-8 flex flex-wrap gap-2">
        {TAGS.map((label) => (
          <span
            key={label}
            className="rounded-full border border-slate-200/80 bg-white/50 px-3 py-1 text-[11px] text-slate-500"
          >
            {label}
          </span>
        ))}
      </div>

      <p className="mt-10 text-[11px] tracking-wide text-slate-400/80">
        {PLATFORMS.join(" · ")}
      </p>
    </div>
  );
}
