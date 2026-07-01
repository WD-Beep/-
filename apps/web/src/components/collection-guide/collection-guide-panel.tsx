"use client";

import Link from "next/link";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardList,
  ExternalLink,
  HelpCircle,
  Link2,
  ListChecks,
  Search,
  ShieldCheck,
} from "lucide-react";

import { AdminShell } from "@/components/layout/admin-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const collectionChoices = [
  {
    title: "有红人主页链接",
    badge: "优先选择",
    icon: Link2,
    action: "用链接导入或采集任务里的主页 URL 模式",
    why: "主页链接最明确，系统不用猜账号，通常比纯关键词更容易拿到有效主页、邮箱和社媒资料。",
    examples: ["Instagram / TikTok / YouTube / Facebook 主页链接", "竞品官网里出现的 creator 主页链接", "LTK / ShopMy / Pinterest seed 链接"],
  },
  {
    title: "只有产品或类目方向",
    badge: "先小批量",
    icon: Search,
    action: "用关键词采集，先跑 20 条验证关键词质量",
    why: "关键词越具体，候选越接近业务需求。太泛的词会带来大量低相关账号，容易出现无效果或部分成功。",
    examples: ["travel toiletry bag creator", "amazon travel finds", "mom travel organizer", "camping storage bag review"],
  },
  {
    title: "想找竞品或同类带货人",
    badge: "适合扩量",
    icon: ClipboardList,
    action: "用竞品商品、品牌词、ASIN 或 Amazon 链接采集",
    why: "竞品线索能把系统带到更接近购买场景的人群，比宽泛行业词更容易找到可触达红人。",
    examples: ["竞品品牌名 + product type", "Amazon 商品链接或 ASIN", "产品核心卖点词 + finds / review"],
  },
];

const goodInputs = [
  "travel toiletry bag creator",
  "amazon travel finds",
  "mom travel organizer",
  "https://www.instagram.com/example_creator/",
  "https://www.tiktok.com/@example_creator",
  "竞品 Amazon 链接或 ASIN",
];

const weakInputs = [
  "travel",
  "beauty",
  "good influencer",
  "只填品牌名但没有产品词",
  "短链、跳转链接、搜索结果页",
  "一次勾选太多平台并把数量拉很大",
];

const platformTips = [
  {
    platform: "Instagram",
    bestFor: "主页资料、公开邮箱、生活方式和带货红人",
    input: "主页链接、具体 hashtag、产品场景词",
    avoid: "只用大词，比如 travel、fashion、home",
  },
  {
    platform: "TikTok",
    bestFor: "内容发现、近期热视频、短视频带货账号",
    input: "产品使用场景、痛点词、测评词",
    avoid: "只看粉丝量，不看内容是否真的相关",
  },
  {
    platform: "YouTube",
    bestFor: "测评、教程、长视频种草和频道邮箱",
    input: "review、unboxing、how to、best + 产品词",
    avoid: "太短的关键词，容易跑到泛娱乐频道",
  },
  {
    platform: "Facebook",
    bestFor: "Page、社区内容、品牌或组织型账号",
    input: "Page 链接、帖子链接、明确品牌词",
    avoid: "把个人主页和不可公开访问链接当成采集入口",
  },
];

const problemRows = [
  {
    status: "无效果",
    reason: "关键词太泛、链接不是主页、筛选过严、目标平台没有公开邮箱或可用主页。",
    fix: "换成产品词 + 人群词 + 场景词，或先准备一批主页链接再采集。",
  },
  {
    status: "部分成功",
    reason: "多平台同时运行、部分外部平台限流、部分链接不可访问、部分账号没有公开联系方式。",
    fix: "拆成单平台小批量运行，先确认结果质量，再扩大数量。",
  },
  {
    status: "失败",
    reason: "采集源未配置、链接格式错误、外部平台接口异常、任务并发太高。",
    fix: "先到系统设置确认 Apify/API 配置，再降低数量或换链接重试。",
  },
];

const workflow = [
  "先在左侧选择正确产品，避免数据进错产品。",
  "优先准备 20 到 50 个主页链接，链接导入通常比关键词更稳定。",
  "没有链接时，用具体关键词先跑 20 条，不要一上来跑大批量。",
  "看候选结果里的邮箱、平台、粉丝量和相关性，再决定是否扩大采集。",
  "出现部分成功时先拆平台、降数量、放宽筛选，不要反复跑同一个大任务。",
];

function SectionTitle({
  icon: Icon,
  title,
  description,
}: {
  icon: typeof HelpCircle;
  title: string;
  description: string;
}) {
  return (
    <div className="flex items-start gap-3">
      <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border bg-slate-50">
        <Icon className="h-4.5 w-4.5 text-blue-600" />
      </span>
      <div>
        <h2 className="text-base font-semibold text-slate-950">{title}</h2>
        <p className="mt-1 text-sm leading-6 text-slate-600">{description}</p>
      </div>
    </div>
  );
}

export function CollectionGuidePanel() {
  return (
    <AdminShell
      title="采集说明"
      description="给业务员的红人采集操作指南，减少无效果、部分成功和失败任务。"
      actions={
        <Link href="/collection-tasks">
          <Button>
            去创建采集任务
            <ExternalLink className="h-4 w-4" />
          </Button>
        </Link>
      }
    >
      <div className="h-full min-h-0 overflow-auto pb-6">
        <div className="mx-auto flex max-w-6xl flex-col gap-4">
          <section className="ops-panel overflow-hidden">
            <div className="border-b bg-slate-50/70 px-5 py-4">
              <SectionTitle
                icon={ShieldCheck}
                title="先选对采集入口"
                description="不要所有需求都用关键词采集。入口越明确，系统越容易产出可联系、可判断、可入库的红人。"
              />
            </div>
            <div className="grid gap-3 p-4 lg:grid-cols-3">
              {collectionChoices.map((item) => {
                const Icon = item.icon;
                return (
                  <article key={item.title} className="rounded-lg border bg-background p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex items-center gap-2">
                        <span className="flex h-8 w-8 items-center justify-center rounded-md bg-blue-50 text-blue-700">
                          <Icon className="h-4 w-4" />
                        </span>
                        <h3 className="font-semibold text-slate-950">{item.title}</h3>
                      </div>
                      <Badge variant="secondary">{item.badge}</Badge>
                    </div>
                    <p className="mt-3 text-sm font-medium text-slate-800">{item.action}</p>
                    <p className="mt-2 text-sm leading-6 text-slate-600">{item.why}</p>
                    <div className="mt-3 space-y-1.5">
                      {item.examples.map((example) => (
                        <div key={example} className="flex gap-2 text-xs leading-5 text-slate-600">
                          <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600" />
                          <span>{example}</span>
                        </div>
                      ))}
                    </div>
                  </article>
                );
              })}
            </div>
          </section>

          <section className="grid gap-4 lg:grid-cols-2">
            <div className="ops-panel overflow-hidden">
              <div className="border-b bg-slate-50/70 px-5 py-4">
                <SectionTitle
                  icon={CheckCircle2}
                  title="推荐这样填"
                  description="这些输入更接近真实业务场景，采出来的账号更容易判断是否可合作。"
                />
              </div>
              <div className="grid gap-2 p-4">
                {goodInputs.map((item) => (
                  <div key={item} className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900">
                    {item}
                  </div>
                ))}
              </div>
            </div>

            <div className="ops-panel overflow-hidden">
              <div className="border-b bg-slate-50/70 px-5 py-4">
                <SectionTitle
                  icon={AlertTriangle}
                  title="尽量不要这样填"
                  description="这些输入会让系统猜得太多，容易出现无结果、低相关或任务失败。"
                />
              </div>
              <div className="grid gap-2 p-4">
                {weakInputs.map((item) => (
                  <div key={item} className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                    {item}
                  </div>
                ))}
              </div>
            </div>
          </section>

          <section className="ops-panel overflow-hidden">
            <div className="border-b bg-slate-50/70 px-5 py-4">
              <SectionTitle
                icon={ListChecks}
                title="各平台怎么用"
                description="平台能力不同，业务员可以按目标选择，不需要每次都全平台一起跑。"
              />
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[920px] text-sm">
                <thead className="bg-slate-50 text-left text-slate-600">
                  <tr className="border-b">
                    <th className="px-4 py-3">平台</th>
                    <th className="px-4 py-3">适合找什么</th>
                    <th className="px-4 py-3">建议输入</th>
                    <th className="px-4 py-3">常见误区</th>
                  </tr>
                </thead>
                <tbody>
                  {platformTips.map((row) => (
                    <tr key={row.platform} className="border-b last:border-0">
                      <td className="px-4 py-3 font-semibold text-slate-950">{row.platform}</td>
                      <td className="px-4 py-3 text-slate-700">{row.bestFor}</td>
                      <td className="px-4 py-3 text-slate-700">{row.input}</td>
                      <td className="px-4 py-3 text-slate-600">{row.avoid}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="ops-panel overflow-hidden">
            <div className="border-b bg-slate-50/70 px-5 py-4">
              <SectionTitle
                icon={HelpCircle}
                title="看到异常结果时怎么处理"
                description="先看问题类型，再按对应动作调整。不要重复运行同一个低质量任务。"
              />
            </div>
            <div className="grid gap-3 p-4 lg:grid-cols-3">
              {problemRows.map((row) => (
                <article key={row.status} className="rounded-lg border bg-background p-4">
                  <Badge variant={row.status === "失败" ? "destructive" : row.status === "部分成功" ? "warning" : "secondary"}>
                    {row.status}
                  </Badge>
                  <p className="mt-3 text-sm leading-6 text-slate-600">{row.reason}</p>
                  <div className="mt-3 rounded-md bg-slate-50 px-3 py-2 text-sm leading-6 text-slate-800">
                    处理：{row.fix}
                  </div>
                </article>
              ))}
            </div>
          </section>

          <section className="ops-panel overflow-hidden">
            <div className="border-b bg-slate-50/70 px-5 py-4">
              <SectionTitle
                icon={ClipboardList}
                title="一套稳妥流程"
                description="新业务员按这套流程走，能明显减少无效任务。"
              />
            </div>
            <ol className="grid gap-3 p-4 lg:grid-cols-5">
              {workflow.map((step, index) => (
                <li key={step} className="rounded-lg border bg-background p-4">
                  <span className="flex h-7 w-7 items-center justify-center rounded-full bg-blue-600 text-xs font-semibold text-white">
                    {index + 1}
                  </span>
                  <p className="mt-3 text-sm leading-6 text-slate-700">{step}</p>
                </li>
              ))}
            </ol>
          </section>
        </div>
      </div>
    </AdminShell>
  );
}
