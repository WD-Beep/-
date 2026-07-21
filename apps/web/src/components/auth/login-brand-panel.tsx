// 文件说明：前端页面组件；当前文件：login brand panel
"use client";

import { Globe2, MessageCircle, PackageCheck, Sparkles, TrendingUp } from "lucide-react";

const CHANNELS = ["Amazon", "TikTok Shop", "Instagram", "YouTube"] as const;

const WORKFLOW = [
  { label: "商品线索", description: "发现热卖切入点" },
  { label: "达人筛选", description: "沉淀可触达人群" },
  { label: "商务触达", description: "跟进回复与意向" },
] as const;

export function LoginBrandPanel() {
  return (
    <div className="flex h-full flex-col justify-between gap-8">
      <div>
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-[#245E4F] text-white shadow-sm shadow-emerald-900/18">
            <Sparkles className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-[28px] font-bold leading-tight tracking-normal text-slate-950">红人智采</h1>
            <p className="mt-1 text-[14px] text-slate-600">海外电商达人数据工作台</p>
          </div>
        </div>

        <p className="mt-6 max-w-[310px] text-sm leading-6 text-slate-600">
          从商品线索、社媒渠道到邮件回复，把达人发现、筛选和触达收在同一个运营节奏里。
        </p>

        <div className="mt-7 grid grid-cols-1 gap-2 sm:grid-cols-3">
          {WORKFLOW.map((item) => (
            <div key={item.label} className="min-w-0 rounded-lg border border-white/70 bg-white/45 px-3 py-2.5">
              <p className="text-sm font-semibold leading-none text-slate-800">{item.label}</p>
              <p className="mt-1.5 text-[11px] leading-4 text-slate-500">{item.description}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-lg border border-white/72 bg-white/42 p-3.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <PackageCheck className="h-4 w-4 text-[#245E4F]" />
            <span className="text-xs font-medium text-slate-700">新品推广批次</span>
          </div>
          <span className="rounded-md bg-orange-100 px-2 py-1 text-[11px] font-medium text-orange-700">ROI 追踪中</span>
        </div>
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
          <div className="min-w-0">
            <div className="h-2 rounded bg-slate-900/10">
              <div className="h-2 w-[68%] rounded bg-[#245E4F]" />
            </div>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {CHANNELS.map((item) => (
                <span key={item} className="rounded-md bg-white/65 px-2 py-1 text-[10px] text-slate-500">
                  {item}
                </span>
              ))}
            </div>
          </div>
          <div className="text-right">
            <div className="flex items-center justify-end gap-1 text-[11px] font-medium text-emerald-700">
              <TrendingUp className="h-3.5 w-3.5" />
              进行中
            </div>
            <p className="mt-1 text-[10px] text-slate-500">完成度</p>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 text-[11px] text-slate-500">
        <span className="inline-flex items-center gap-1.5 rounded-md bg-white/44 px-2.5 py-1.5">
          <Globe2 className="h-3.5 w-3.5" />
          跨境渠道
        </span>
        <span className="inline-flex items-center gap-1.5 rounded-md bg-white/44 px-2.5 py-1.5">
          <MessageCircle className="h-3.5 w-3.5" />
          回复线索
        </span>
      </div>
    </div>
  );
}
