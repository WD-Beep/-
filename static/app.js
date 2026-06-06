const els = {
  llmStatus: document.querySelector("#llmStatus"),
  sheetInput: document.querySelector("#sheetInput"),
  imageInput: document.querySelector("#imageInput"),
  composerDock: document.querySelector("#composerDock"),
  composerAttachBtn: document.querySelector("#composerAttachBtn"),
  composerAttachMenu: document.querySelector("#composerAttachMenu"),
  attachmentStrip: document.querySelector("#attachmentStrip"),
  composerStatusLine: document.querySelector("#composerStatusLine"),
  composerStatusSlot: document.querySelector("#composerStatusSlot"),
  userPrompt: document.querySelector("#userPrompt"),
  sendBtn: document.querySelector("#sendBtn"),
  messageList: document.querySelector("#messageList"),
  chatMessages: document.querySelector("#chatMessages"),
  adminCorrectionResultPanel: document.getElementById("adminCorrectionResultPanel"),
  myQuotesPanel: document.querySelector("#myQuotesPanel"),
  myQuotesList: document.querySelector("#myQuotesList"),
  myQuotesStats: document.querySelector("#myQuotesStats"),
  myQuotesSearch: document.querySelector("#myQuotesSearch"),
  myQuotesPreview: document.querySelector("#myQuotesPreview"),
  btnMyQuotesManage: document.getElementById("btnMyQuotesManage"),
  myQuotesBatchBar: document.getElementById("myQuotesBatchBar"),
  myQuotesBatchCount: document.getElementById("myQuotesBatchCount"),
  btnMyQuotesBatchCancel: document.getElementById("btnMyQuotesBatchCancel"),
  btnMyQuotesBatchDelete: document.getElementById("btnMyQuotesBatchDelete"),
  navMyQuotes: document.querySelector("#navMyQuotes"),
  navAdminUpdates: document.getElementById("navAdminUpdates"),
  adminUpdatesBadge: document.getElementById("adminUpdatesBadge"),
  adminUpdatesPreview: document.getElementById("adminUpdatesPreview"),
  adminUpdatesBanner: document.getElementById("adminUpdatesBanner"),
  btnAdminUpdatesBanner: document.getElementById("btnAdminUpdatesBanner"),
  workspaceAdminUpdates: document.getElementById("workspaceAdminUpdates"),
  adminUpdatesStats: document.getElementById("adminUpdatesStats"),
  adminUpdatesReadFilter: document.getElementById("adminUpdatesReadFilter"),
  adminUpdatesBatchBar: document.getElementById("adminUpdatesBatchBar"),
  adminUpdatesSelectAll: document.getElementById("adminUpdatesSelectAll"),
  adminUpdatesBatchCount: document.getElementById("adminUpdatesBatchCount"),
  btnAdminUpdatesBatchMarkRead: document.getElementById("btnAdminUpdatesBatchMarkRead"),
  btnAdminUpdatesBatchDelete: document.getElementById("btnAdminUpdatesBatchDelete"),
  btnAdminUpdatesBatchCancel: document.getElementById("btnAdminUpdatesBatchCancel"),
  adminUpdatesList: document.getElementById("adminUpdatesList"),
  adminUpdatesListView: document.getElementById("adminUpdatesListView"),
  adminUpdatesDetailView: document.getElementById("adminUpdatesDetailView"),
  adminUpdatesDetail: document.getElementById("adminUpdatesDetail"),
  btnAdminUpdatesBack: document.getElementById("btnAdminUpdatesBack"),
  workspaceChat: document.querySelector("#workspaceChat"),
  workspaceMyQuotes: document.querySelector("#workspaceMyQuotes"),
  workspaceQuote: document.querySelector("#workspaceQuote"),
};

const MAX_COMPOSER_ATTACHMENTS = 3;
const MAX_SHEET_BYTES = 20 * 1024 * 1024;
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;

/** 输入区 toast：防抖 id + 定时自动收起 */
let composerToastOpId = 0;
let composerToastDismissTimer = null;

/** 与 server.py DEFAULT_HTTP_PORT 对齐，仅用于提示文案 */
const WORKBENCH_DEFAULT_HTTP_PORT = "8776";
/** /api/quote 双模式统一 intent（业务流见 flow_intent） */
const DUAL_ROUTE_INTENTS = new Set(["quote", "qa", "hybrid", "clarify"]);

/** 报价引擎流 intent：试算/换料/agent_trial 等（双模式后勿用顶层 intent 判断） */
function quoteFlowIntent(payload) {
  if (!payload || typeof payload !== "object") {
    return "";
  }
  const flow = String(payload.flow_intent || "").trim();
  if (flow) {
    return flow;
  }
  const raw = String(payload.intent || "").trim();
  if (!raw || DUAL_ROUTE_INTENTS.has(raw)) {
    return "";
  }
  return raw;
}
/** 特例：磁盘打开 HTML 时需手动写入 API 根，如 http://127.0.0.1:8776 */
const LS_QUOTE_API_ORIGIN_KEY = "quote_workbench_api_origin";

function normalizeApiOrigin(raw) {
  if (!raw || typeof raw !== "string") {
    return "";
  }
  const s = raw.trim().replace(/\/+$/, "");
  if (!s || !/^https?:\/\//i.test(s)) {
    return "";
  }
  try {
    const u = new URL(s);
    return `${u.protocol}//${u.hostname}${u.port ? `:${u.port}` : ""}`;
  } catch {
    return "";
  }
}

function resolveQuoteApiOrigin() {
  if (typeof window.__QUOTE_API_ORIGIN__ === "string") {
    const fromGlobal = normalizeApiOrigin(window.__QUOTE_API_ORIGIN__);
    if (fromGlobal) {
      return fromGlobal;
    }
  }
  try {
    const fromLs = normalizeApiOrigin(localStorage.getItem(LS_QUOTE_API_ORIGIN_KEY));
    if (fromLs) {
      return fromLs;
    }
  } catch {
    // ignore storage
  }
  const { protocol, host } = window.location;
  if (protocol === "http:" || protocol === "https:") {
    return `${protocol}//${host}`;
  }
  return "";
}

function quoteApiUrl(path) {
  const origin = resolveQuoteApiOrigin();
  if (!origin) {
    throw new Error(
      `无法连接接口：当前页面不是通过 python server.py 提供的地址打开的（例如直接双击了 index.html → file://）。请在「自报项目」目录运行 python server.py，然后浏览器打开 http://127.0.0.1:${WORKBENCH_DEFAULT_HTTP_PORT}/（若改过端口，以终端里打印的为准）。`,
    );
  }
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${origin}${p}`;
}

function humanizeNetworkError(error) {
  const raw = error instanceof Error ? error.message : String(error);
  if (!/\bFailed to fetch\b|NetworkError\b|Load failed|Network request failed|^TypeError:/i.test(raw)) {
    return raw;
  }
  return `${raw} 请确认：① 终端里已运行 python server.py；② 用 http://127.0.0.1:${WORKBENCH_DEFAULT_HTTP_PORT}/ 打开（不要用「本地文件」方式）；③ 若端口不是 ${WORKBENCH_DEFAULT_HTTP_PORT}，请使用终端打印的完整地址。`;
}

const QUOTE_FETCH_TIMEOUT_MS = 90000;
const QUOTE_TIMEOUT_USER_MESSAGE =
  "报价生成超时，可能是本地模型或网络不可用，请稍后重试或联系管理员。";

function quoteFetch(path, options = {}) {
  const url = quoteApiUrl(path);
  return fetch(url, { credentials: "include", ...options });
}

function quoteFetchWithTimeout(path, options = {}, timeoutMs = QUOTE_FETCH_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  const merged = { ...options, signal: controller.signal };
  return quoteFetch(path, merged).finally(() => window.clearTimeout(timer));
}

function humanizeQuoteFetchError(error) {
  if (error && error.name === "AbortError") {
    return QUOTE_TIMEOUT_USER_MESSAGE;
  }
  return humanizeNetworkError(error instanceof Error ? error : new Error(String(error)));
}

function isWecomBrowser() {
  const ua = String(navigator.userAgent || "");
  return /wxwork/i.test(ua);
}

function humanizeUploadError(error, context = "upload") {
  const raw = error instanceof Error ? error.message : String(error || "");
  const lower = raw.toLowerCase();
  if (state.isWecomBrowser) {
    if (/cancel|aborted|empty|0 byte|not readable|security/i.test(lower)) {
      return "未能读取文件。请先将聊天中的表格保存到手机，再通过「+ → 上传表格」从本机选择。";
    }
    if (/exceed|20mb|10mb|大小|limit/i.test(lower)) {
      return raw.includes("超过") || raw.includes("MB") ? raw : `文件过大：${raw}`;
    }
    return "文件读取失败。建议先将文件保存到手机本地，再通过「+ → 上传表格」重新选择。";
  }
  if (/exceed|20mb|10mb/i.test(lower)) {
    return raw;
  }
  return raw.startsWith("读取失败") ? raw : `读取失败：${raw}`;
}

const WECOM_ENTRY_BLOCKED_MESSAGE = "请从企业微信进入报价系统";

function wecomAuthExpiredUserMessage() {
  if (state.isWecomBrowser) {
    return "登录已过期，请重新进入企业微信应用，或点击上方「企业微信登录」。";
  }
  return WECOM_ENTRY_BLOCKED_MESSAGE;
}

function wecomLoginRequiredUserMessage() {
  if (state.isWecomBrowser) {
    return "正在使用企业微信，系统将自动完成登录；若未跳转请点击「企业微信登录」。";
  }
  return WECOM_ENTRY_BLOCKED_MESSAGE;
}

function isFrontEntryBlocked() {
  const st = state.authStatus;
  return !!(st?.wecom_enabled && !state.isWecomBrowser);
}

function renderWecomEntryGate() {
  const blocked = isFrontEntryBlocked();
  document.body.classList.toggle("wecom-entry-blocked", blocked);
  const gateId = "wecomEntryGate";
  let gate = document.getElementById(gateId);
  if (!blocked) {
    gate?.remove();
    return;
  }
  if (!gate) {
    gate = document.createElement("div");
    gate.id = gateId;
    gate.className = "wecom-entry-gate";
    gate.setAttribute("role", "alertdialog");
    gate.setAttribute("aria-modal", "true");
    gate.setAttribute("aria-label", WECOM_ENTRY_BLOCKED_MESSAGE);
    document.body.appendChild(gate);
  }
  gate.innerHTML = `<div class="wecom-entry-gate-card">
    <p class="wecom-entry-gate-title">${escapeHtml(WECOM_ENTRY_BLOCKED_MESSAGE)}</p>
    <p class="wecom-entry-gate-desc">业务员工作台仅支持在企业微信应用内打开，普通浏览器无法查看报价、审批结果与管理员修正通知。</p>
  </div>`;
}

function handleWecomAuthUrlErrors() {
  const params = new URLSearchParams(window.location.search);
  const err = params.get("wecom_auth_error");
  const msg = params.get("wecom_auth_message");
  if (!err && !msg) return;
  const text = String(msg || "").trim() || "企业微信登录失败，请重新从企业微信进入应用。";
  setComposerStatusLine(text, "err", { ttlMs: 0 });
  sessionStorage.removeItem("wecom_oauth_redirected");
  const url = new URL(window.location.href);
  url.searchParams.delete("wecom_auth_error");
  url.searchParams.delete("wecom_auth_message");
  const next = `${url.pathname}${url.search}${url.hash}`;
  window.history.replaceState({}, "", next);
}

function maybeAutoWecomLogin() {
  if (!state.isWecomBrowser || isFrontEntryBlocked()) return;
  const st = state.authStatus;
  if (!st?.wecom_enabled || st?.authenticated) {
    if (st?.authenticated) {
      sessionStorage.removeItem("wecom_oauth_redirected");
    }
    return;
  }
  if (st.wecom_misconfigured || st.wecom_configured === false) {
    setComposerStatusLine("企业微信登录未配置或配置不完整，请联系管理员。", "err", { ttlMs: 0 });
    return;
  }
  const loginUrl = wecomLoginUrl();
  if (!loginUrl) {
    setComposerStatusLine("无法获取企业微信登录地址，请联系管理员。", "err", { ttlMs: 0 });
    return;
  }
  if (sessionStorage.getItem("wecom_oauth_redirected") === "1") {
    setComposerStatusLine("企业微信登录未完成，请点击上方「企业微信登录」重试。", "warn", { ttlMs: 12000 });
    return;
  }
  sessionStorage.setItem("wecom_oauth_redirected", "1");
  window.location.href = loginUrl;
}

function readCookieValue(name) {
  const prefix = `${name}=`;
  return document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix))
    ?.slice(prefix.length) || "";
}

function getWorkbenchThreadId() {
  if (!state.threadId) {
    state.threadId = `thread-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  }
  return state.threadId;
}

function buildSessionContext(extra = {}) {
  const currentQuoteId = state.sessionContext?.currentQuoteId || restoreActiveQuoteContextFromVisibleCards();
  return {
    currentQuoteId,
    activeQuoteId: currentQuoteId,
    quoteId: currentQuoteId,
    sessionId: readCookieValue("aq_session_id"),
    threadId: getWorkbenchThreadId(),
    fileName: state.sessionContext?.fileName || "",
    primaryQuoteMsgId: state.sessionContext?.primaryQuoteMsgId || "",
    ...extra,
  };
}

/**
 * 从纯文字输入猜测 product_name（无表格附件时使用）。
 * 追问/寒暄类短句返回空串，便于沿用侧栏或上一轮已识别的 product_name。
 */
function inferProductName(prompt) {
  const raw = String(prompt || "").trim();
  if (!raw) {
    return "";
  }
  const firstLine = raw.split(/\r?\n/)[0].trim();
  // 核算解释、寒暄、纯问号等 —— 不设新品名
  if (
    /你怎么算的?$|^你怎么算|^怎么算|^为何|^为什么|^多少[钱元]?$|^算算|^对吗|^对不对|^对吗|^帮忙|^谢谢|^您好|^请问[\s\S]{0,12}$/.test(
      firstLine,
    ) ||
    (/^[？?！!。\s…·]+$/.test(firstLine) && firstLine.length <= 8)
  ) {
    return "";
  }
  // 很短且不像在描述物料/包型
  if (firstLine.length <= 8 && !/[包袋箱旅拉双单肩背革布皮料尼龙牛津涤棉麻]/.test(firstLine)) {
    return "";
  }
  let line = firstLine.replace(/^(帮我|请|麻烦|想要|需要|报价|核算|做一个|定制)\s*/u, "").trim();
  if (!line || line.length > 120) {
    return "";
  }
  return line.length > 80 ? `${line.slice(0, 80).trim()}…` : line;
}

function ensureWorkbenchServingNotice() {
  const cw = document.querySelector(".chat-window");
  if (!cw) {
    return;
  }
  const origin = resolveQuoteApiOrigin();
  const existing = document.getElementById("workbenchServingNotice");
  if (origin) {
    if (existing) {
      existing.remove();
    }
    return;
  }
  if (existing) {
    return;
  }
  const header = cw.querySelector(".chat-header");
  if (!header) {
    return;
  }
  const bar = document.createElement("div");
  bar.id = "workbenchServingNotice";
  bar.className = "workbench-serving-notice";
  bar.setAttribute("role", "alert");
  bar.innerHTML = [
    "<strong>未连接到工作台后端</strong>：检测到当前页面无法访问 <code>/api/*</code>（常见于用资源管理器直接打开 HTML）。",
    "<br>",
    "请在项目目录执行 <code>python server.py</code>，再在浏览器访问 ",
    `<a href="http://127.0.0.1:${WORKBENCH_DEFAULT_HTTP_PORT}/" target="_blank" rel="noopener noreferrer">`,
    `http://127.0.0.1:${WORKBENCH_DEFAULT_HTTP_PORT}/`,
    "</a>",
    "（端口以终端输出为准）。",
    `<span class="workbench-notice-muted"> 特例可在控制台执行：`,
    `<code>localStorage.setItem(&quot;${LS_QUOTE_API_ORIGIN_KEY}&quot;,&quot;http://127.0.0.1:${WORKBENCH_DEFAULT_HTTP_PORT}&quot;)</code>`,
    " 然后刷新。</span>",
  ].join("");
  header.insertAdjacentElement("afterend", bar);
}

const DEFERRED_QUOTE_HINT =
  "您好，请先说明需要报价的产品类型、数量或主要材质等信息；也可以上传物料/BOM 表格，我会在识别后生成明细与三档价格。";

const COMPOSER_PLACEHOLDER_DEFAULT =
  "可上传 BOM 自动报价，也可以问材料替换、报价解释、业务建议。";

const NON_QUOTE_REPLY_TYPES = new Set([
  "business_qa",
  "qa",
  "quote_explain",
  "material_substitution",
  "clarify",
  "clarify_question",
  "capability_help",
  "process_card",
  "structure_confirmation",
]);

function isDeferredUploadHint(text) {
  const t = String(text || "").trim();
  if (!t) {
    return true;
  }
  return (
    t === DEFERRED_QUOTE_HINT ||
    /请先上传|上传\s*BOM|上传物料|上传表格|请先说明需要报价的产品/.test(t)
  );
}

function formatQuoteExplanationText(body) {
  if (!body || typeof body !== "object") {
    return "";
  }
  const msg = String(body.assistant_message || "").trim();
  if (msg) {
    return msg;
  }
  const summary = String(body.summary || "").trim();
  return summary;
}

function formatMaterialSubstitutionFallback(result) {
  const patch = result.quote_patch;
  if (!patch || typeof patch !== "object") {
    return "";
  }
  const parts = [];
  const msg = String(patch.message || patch.summary || "").trim();
  if (msg) {
    parts.push(msg);
  }
  const delta = patch.cost_delta_per_piece ?? patch.material_total_delta;
  if (delta != null && delta !== "") {
    parts.push(`单件成本变化约：${delta}`);
  }
  return parts.join("\n");
}

function resolveAssistantTextFromQuoteResult(result) {
  const replyType = String(result?.reply_type || "").trim();
  const raw = String(result?.answer || result?.assistant_message || "").trim();

  if (replyType === "quote_explain") {
    return (
      raw ||
      formatQuoteExplanationText(result.quote_explanation) ||
      "暂无报价解释内容，请先生成报价后再追问。"
    );
  }
  if (replyType === "material_substitution") {
    return raw || formatMaterialSubstitutionFallback(result) || "暂无替料或差价说明。";
  }
  if (replyType === "business_qa" || replyType === "qa") {
    return raw || "暂时没有查到相关内容，请换种说法或补充材料名称。";
  }
  if (replyType === "clarify" || replyType === "clarify_question") {
    return raw || "我还需要一点信息，请补充说明。";
  }
  if (replyType === "capability_help") {
    return raw || "我可以帮你上传表格报价、解释报价、对比差异、试算换料等。";
  }
  if (raw && (replyType || !isDeferredUploadHint(raw))) {
    return raw;
  }
  if (replyType && NON_QUOTE_REPLY_TYPES.has(replyType)) {
    return raw || "已收到，请补充一句更具体的问题。";
  }
  return DEFERRED_QUOTE_HINT;
}

function statusLineForNonQuoteReply(replyType) {
  switch (String(replyType || "").trim()) {
    case "business_qa":
    case "qa":
      return { text: "已回复业务答疑", tone: "ok" };
    case "quote_explain":
      return { text: "已生成报价解释", tone: "ok" };
    case "material_substitution":
      return { text: "已返回替料/差价说明", tone: "ok" };
    case "clarify":
    case "clarify_question":
      return { text: "请补充信息后继续", tone: "warn" };
    case "capability_help":
      return { text: "已说明可用能力", tone: "ok" };
    default:
      return { text: "本轮未生成新报价", tone: "warn" };
  }
}

function shouldRestoreComposerOnNonQuote(result) {
  const rt = String(result?.reply_type || "").trim();
  if (rt && NON_QUOTE_REPLY_TYPES.has(rt)) {
    return false;
  }
  const text = resolveAssistantTextFromQuoteResult(result);
  return isDeferredUploadHint(text);
}

function loadingLabelForQuoteRequest(prompt, quoteFileLabel) {
  if (quoteFileLabel) {
    return `正在处理 📎 ${quoteFileLabel} …`;
  }
  const p = String(prompt || "").trim();
  if (!p) {
    return "正在处理…";
  }
  if (/(为什么|解释|怎么算|太贵|发给客户|替代|风险|什么意思|能不能|业务|材料)/.test(p)) {
    return "正在整理回复…";
  }
  return "正在核算报价…";
}

const state = {
  baseConfig: {
    product_name: "",
    mold_fee: 1000,
    processing_fee: 12,
    system_overhead: 4,
    gross_margin_rate: 35,
    quantities: "300,500,1000",
    enable_kimi_autofill: true,
  },
  sessionContext: {
    currentQuoteId: "",
    fileName: "",
    quoteData: null,
    primaryQuoteMsgId: "",
  },
  pendingStructureConfirm: null,
  threadId: "",
  composerAttachments: [],
  isRequesting: false,
  llmStatus: null,
  lastQuoteAudit: null,
  lastQaAudit: null,
  myQuotesFilter: "",
  myQuotesSearch: "",
  myQuotesItems: [],
  myQuotesStatsItems: [],
  myQuotesNeedsRefresh: false,
  myQuotesBatchMode: false,
  myQuotesSelectedUids: new Set(),
  currentView: "chat",
  activeMyQuoteSeriesUid: "",
  adminCorrectionPanelDetail: null,
  adminUpdatesItems: [],
  adminUpdatesUnread: 0,
  adminUpdatesSelectedUids: new Set(),
  adminUpdatesReadFilter: "",
  activeAdminUpdateUid: "",
  authStatus: null,
  isWecomBrowser: isWecomBrowser(),
  messages: [
    {
      role: "assistant",
      type: "text",
      text: "您好，报价以物料表为准：请先上传 BOM / 物料明细后再发送；勿仅凭一句话生成真实明细，以免与示例混淆。",
      time: formatNowTime(),
    },
  ],
};

function newLoadingToken() {
  return `lq-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function newQuoteMsgId() {
  return `qc-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function findQuoteMessageByMsgId(msgId) {
  return state.messages.find((m) => m.type === "quote_card" && m.msgId === msgId);
}

function getRecentQuotesSummaries(limit = 3) {
  const out = [];
  for (let i = state.messages.length - 1; i >= 0 && out.length < limit; i -= 1) {
    const m = state.messages[i];
    if (m.type !== "quote_card" || !m.data) {
      continue;
    }
    out.push({
      file_name: m.fileName || "",
      product_name: m.data.product_name || "",
      material_total_text: m.data.material_total_text || "",
    });
  }
  return out;
}

function restoreActiveQuoteContextFromVisibleCards() {
  if (state.sessionContext?.currentQuoteId) {
    return state.sessionContext.currentQuoteId;
  }
  for (let i = state.messages.length - 1; i >= 0; i -= 1) {
    const msg = state.messages[i];
    const quote = msg?.type === "quote_card" && msg?.data ? msg.data : null;
    const qid = String(quote?.quote_id || "").trim();
    if (!qid || quoteFlowIntent(quote) === "agent_trial") {
      continue;
    }
    state.sessionContext = {
      ...state.sessionContext,
      currentQuoteId: qid,
      fileName: String(msg.fileName || state.sessionContext?.fileName || ""),
      quoteData: quote,
      primaryQuoteMsgId: String(msg.msgId || state.sessionContext?.primaryQuoteMsgId || ""),
    };
    return qid;
  }
  return "";
}

function hasAnyQuoteCardInChat() {
  return state.messages.some((m) => m.type === "quote_card" && m.data);
}

function composerHasSheet() {
  return state.composerAttachments.some((a) => a.kind === "sheet");
}

function syncComposerPlaceholder() {
  if (!els.userPrompt) {
    return;
  }
  if (composerHasSheet()) {
    els.userPrompt.placeholder =
      "补充说明后发送；Enter 发送，Shift+Enter 换行，Ctrl+V 可贴附件，最多 3 个文件。";
  } else if (hasAnyQuoteCardInChat()) {
    els.userPrompt.placeholder =
      "补充说明或通过 @文件名 引用；点 + 上传表格/图片（最多 3、表≤20MB·图≤10MB）。";
  } else {
    els.userPrompt.placeholder = COMPOSER_PLACEHOLDER_DEFAULT;
  }
}

function replaceLoadingByToken(loadingToken, replacement) {
  const idx = state.messages.findIndex(
    (m) => m.type === "loading_quote" && m.loadingToken === loadingToken,
  );
  const next = {
    role: replacement.role || "assistant",
    type: replacement.type || "text",
    time: replacement.time || formatNowTime(),
    ...replacement,
  };
  if (idx !== -1) {
    state.messages.splice(idx, 1, next);
  } else {
    state.messages.push(next);
  }
  renderMessages();
  if (next.type === "quote_card" && next.data) {
    scheduleQuoteApprovalHydration(next);
  }
  syncComposerPlaceholder();
  scrollToBottom();
}

function buildQuoteRequestPayload(prompt, attSnap, extra = {}) {
  const hasSheet = attSnap.some((x) => x.kind === "sheet");
  const payload = {
    ...state.baseConfig,
    message_text: prompt,
    user_prompt: prompt,
    prompt,
    product_name: hasSheet
      ? state.baseConfig.product_name
      : inferProductName(prompt) || state.baseConfig.product_name,
    session_context: buildSessionContext(),
    ...extra,
  };
  if (attSnap.length > 0) {
    payload.attachments = attSnap.map((a) => ({
      name: a.name,
      mime_type: a.mime_type || (a.kind === "sheet" ? "application/octet-stream" : "image/png"),
      content_base64: a.content_base64,
    }));
  }
  const firstSheet = attSnap.find((x) => x.kind === "sheet");
  if (firstSheet) {
    payload.uploaded_sheet = {
      name: firstSheet.name,
      content_base64: firstSheet.content_base64,
    };
  }
  return payload;
}

async function requestQuote(options = {}) {
  const { allowEmpty = false, skipUserEcho = false } = options;
  if (state.isRequesting) {
    return;
  }
  if (isFrontEntryBlocked()) {
    addMessage("assistant", WECOM_ENTRY_BLOCKED_MESSAGE);
    return;
  }
  if (state.authStatus?.wecom_enabled && !state.authStatus?.authenticated) {
    addMessage("assistant", wecomLoginRequiredUserMessage());
    return;
  }

  const prompt = (els.userPrompt?.value || "").trim();
  const attSnap = state.composerAttachments.map((a) => ({
    name: a.name,
    kind: a.kind,
    mime_type: a.mime_type,
    content_base64: a.content_base64,
    sizeLabel: a.sizeLabel,
  }));
  const hasAttachments = attSnap.length > 0;
  const hasSheet = attSnap.some((x) => x.kind === "sheet");
  const shouldEchoTurn = Boolean(!skipUserEcho && (prompt || hasAttachments));
  const quoteFileLabel =
    String(attSnap.find((x) => x.kind === "sheet")?.name || "").trim() ||
    String(attSnap[0]?.name || "").trim() ||
    String(state.sessionContext?.fileName || "").trim();

  let echoPromptHeld = "";

  if (!allowEmpty && !prompt && !hasAttachments) {
    addMessage("assistant", "请先输入说明，或点左侧「+」添加附件后再发送。");
    return;
  }

  if (shouldEchoTurn) {
    echoPromptHeld = prompt;
    let attachmentViews = [];
    try {
      attachmentViews = await buildAttachmentEchoViews(attSnap.map((x) => ({ ...x })));
    } catch {
      attachmentViews = attSnap.map((a) =>
        a.kind === "image"
          ? { name: a.name, kind: "image", sizeLabel: a.sizeLabel, thumbUrl: "" }
          : { name: a.name, kind: "sheet", sizeLabel: a.sizeLabel, thumbUrl: "" },
      );
    }
    state.messages.push({
      role: "user",
      type: "user_turn",
      text: prompt,
      attachmentViews,
      time: formatNowTime(),
    });
    els.userPrompt.value = "";
    clearComposerAttachments();
    renderMessages();
    scrollToBottom();
  }

  const loadingToken = newLoadingToken();
  const loadingText = loadingLabelForQuoteRequest(prompt, quoteFileLabel);
  state.messages.push({
    role: "assistant",
    type: "loading_quote",
    loadingToken,
    text: loadingText,
    time: formatNowTime(),
  });
  renderMessages();
  scrollToBottom();

  setRequesting(true);
  setComposerStatusLine("正在提交本轮消息（文字 + 附件）…", "busy");

  try {
    const payload = buildQuoteRequestPayload(prompt, attSnap);

    const response = await quoteFetchWithTimeout("/api/quote", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const result = await readResponseJson(response);
    if (!response.ok) {
      if (result.llm_status) {
        state.llmStatus = result.llm_status;
        renderLlmStatus();
      }
      throw new Error(result.message || result.error || `请求失败（HTTP ${response.status}）`);
    }

    if (result.quote_ready === false) {
      state.llmStatus = result.llm_status || null;
      state.lastQaAudit = result.qa_audit || null;
      renderLlmStatus();
      if (result.reply_type === "structure_confirmation") {
        const token = `sc-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
        const confirmSnap =
          Array.isArray(result.items_confirmation) && result.items_confirmation.length > 0
            ? result.items_confirmation.map((r) =>
                r && typeof r === "object" ? { ...r } : {},
              ).filter((r) => !isReferenceOnlyRowName(r.name))
            : Array.isArray(result.items_preview)
              ? result.items_preview
                  .map((r) => (r && typeof r === "object" ? { ...r } : {}))
                  .filter((r) => !isReferenceOnlyRowName(r.name))
              : [];
        state.pendingStructureConfirm = {
          token,
          prompt,
          attachments: attSnap.map((a) => ({ ...a })),
          fileName: quoteFileLabel,
          confirmRowsSnap: confirmSnap,
          structureEditMode: false,
          structureSavedForQuote: true,
          structureDirty: false,
          pendingScrollToNewRowIndex: null,
          structureRowOverrides: {},
          structureAddedRows: [],
          structureSelectedRowIndex: null,
          confirmedStructureGapIds: {},
          data: result,
        };
        replaceLoadingByToken(loadingToken, {
          role: "assistant",
          type: "structure_confirmation",
          data: result,
          confirmToken: token,
          fileName: quoteFileLabel,
        });
        setComposerStatusLine("请先确认结构，确认后再生成正式报价", "warn");
        return;
      }
      if (result.reply_type === "process_card" && result.process) {
        replaceLoadingByToken(loadingToken, {
          role: "assistant",
          type: "process_card",
          title: result.title || "计算过程拆解",
          file_hint: result.file_hint || quoteFileLabel || "",
          process: result.process,
        });
        setComposerStatusLine("已生成计算过程拆解", "ok");
        return;
      }
      const replyType = String(result.reply_type || "").trim();
      const assistantText = resolveAssistantTextFromQuoteResult(result);
      const statusMeta = statusLineForNonQuoteReply(replyType);
      replaceLoadingByToken(loadingToken, {
        role: "assistant",
        type: "text",
        text: assistantText,
        replyType: replyType || "assistant",
      });
      setComposerStatusLine(statusMeta.text, statusMeta.tone);
      if (echoPromptHeld && shouldRestoreComposerOnNonQuote(result)) {
        if (els.userPrompt) {
          els.userPrompt.value = echoPromptHeld;
        }
        syncComposerTextareaHeight();
        setComposerStatusLine("本轮未生成报价：已填回文字；图片等附件需重新选择。", "warn");
      }
      return;
    }

    const flowIntent = quoteFlowIntent(result);
    const isAgentTrial = flowIntent === "agent_trial";
    const isExtraCalc =
      result.metadata &&
      result.metadata.is_extra_calc === true &&
      (flowIntent === "extra_quantity_calc" ||
        (isAgentTrial && result.metadata.is_extra_material_calc !== true));

    if (isExtraCalc) {
      state.llmStatus = result.llm_status || null;
      renderLlmStatus();
      const md = result.metadata || {};
      replaceLoadingByToken(loadingToken, {
        role: "assistant",
        type: "quote_card",
        subtype: "extra_calc",
        fileName: quoteFileLabel,
        data: result,
        msgId: newQuoteMsgId(),
        originalQuantity: md.original_quantity,
        calcQuantity: md.calc_quantity,
        costDelta: md.cost_delta_per_piece,
        baseQuoteServerId: md.base_quote_id,
        baseQuoteMsgId: state.sessionContext?.primaryQuoteMsgId || "",
      });
      return;
    }

    const isExtraMaterialCalc =
      result.metadata &&
      result.metadata.is_extra_material_calc === true &&
      (flowIntent === "extra_material_calc" || isAgentTrial);

    if (isExtraMaterialCalc) {
      state.llmStatus = result.llm_status || null;
      renderLlmStatus();
      const md = result.metadata || {};
      replaceLoadingByToken(loadingToken, {
        role: "assistant",
        type: "quote_card",
        subtype: "extra_material_calc",
        fileName: quoteFileLabel,
        data: result,
        msgId: newQuoteMsgId(),
        materialTotalDelta: md.material_total_delta,
        costDelta: md.cost_delta_per_piece,
        oldMaterialLabel: md.old_material_label,
        newMaterialLabel: md.new_material_label,
        baseQuoteServerId: md.base_quote_id,
        trialItemsSnapshot: result.trial_items_snapshot || null,
        baseQuoteMsgId: state.sessionContext?.primaryQuoteMsgId || "",
      });
      return;
    }

    state.llmStatus = result.llm_status || null;
    renderLlmStatus();
    const primaryMsgId = newQuoteMsgId();
    const embeddedAgentProcess =
      result.agent_process && result.agent_process.process
        ? {
            title: result.agent_process.title || "计算过程拆解",
            file_hint: result.agent_process.file_hint || quoteFileLabel || "",
            process: result.agent_process.process,
          }
        : null;
    const fallbackTrialMd = result.metadata || {};
    replaceLoadingByToken(loadingToken, {
      role: "assistant",
      type: "quote_card",
      subtype: isAgentTrial ? "extra_calc" : "primary",
      fileName: quoteFileLabel,
      data: result,
      msgId: primaryMsgId,
      originalQuantity: fallbackTrialMd.original_quantity,
      calcQuantity: fallbackTrialMd.calc_quantity,
      costDelta: fallbackTrialMd.cost_delta_per_piece,
      baseQuoteServerId: fallbackTrialMd.base_quote_id,
      quoteProcess: embeddedAgentProcess,
      quoteProcessExpanded: Boolean(embeddedAgentProcess),
    });

    const resolvedName =
      quoteFileLabel ||
      (result.sheet_parse && result.sheet_parse.file_name) ||
      state.sessionContext?.fileName ||
      "";
    if (result.quote_id && flowIntent !== "agent_trial") {
      state.sessionContext = {
        currentQuoteId: result.quote_id,
        fileName: resolvedName,
        quoteData: result,
        primaryQuoteMsgId: primaryMsgId,
      };
    }

    syncPricingGateSnapshotFromQuote(result);

    if (typeof window !== "undefined") {
      const rUsd = Number(result.usd_cny_rate);
      const fobPc = Number(result.settings && result.settings.fob_addition_per_piece);
      window.__quoteUsdSnapshot = {
        usdCnyRate: Number.isFinite(rUsd) && rUsd > 0 ? rUsd : 7.15,
        fobYuanPerPc: Number.isFinite(fobPc) && fobPc >= 0 ? fobPc : 4,
        includeFob: result.include_fob !== false,
        tiers: Array.isArray(result.tiers) ? result.tiers : [],
        productName: result.product_name || "",
      };
      const rateInput = document.getElementById("qsUsdCnyRate");
      if (rateInput && Number.isFinite(rUsd) && rUsd > 0) {
        rateInput.value = String(rUsd);
      }
      const fobInput = document.getElementById("qsFobYuanPerPc");
      if (fobInput && Number.isFinite(fobPc) && fobPc >= 0) {
        fobInput.value = String(fobPc);
      }
    }

    setComposerStatusLine("已提交", "ok");
    void persistQuoteSessionMessages(result.quote_series_uid || result.quote_id);
    state.myQuotesNeedsRefresh = true;
    void refreshMyQuotesPreview();
  } catch (error) {
    const message = humanizeQuoteFetchError(error instanceof Error ? error : new Error(String(error)));
    replaceLoadingByToken(loadingToken, {
      role: "assistant",
      type: "text",
      text: `请求失败：${message}`,
    });
    if (echoPromptHeld && els.userPrompt) {
      els.userPrompt.value = echoPromptHeld;
      syncComposerTextareaHeight();
    }
    setComposerStatusLine(`发送失败：${message}`, "err");
  } finally {
    if (state.isRequesting) {
      setRequesting(false);
    }
    scrollToBottom();
  }
}

function costOverviewHtml(overview) {
  if (!overview || !Array.isArray(overview.components) || overview.components.length === 0) {
    return "";
  }
  const compRows = overview.components
    .map(
      (c) =>
        `<tr><td class="cost-overview-label">${escapeHtml(c.label)}</td>` +
        `<td class="cost-overview-amt">${escapeHtml(c.amount_display)}</td>` +
        `<td class="cost-overview-hint">${escapeHtml(c.hint || "")}</td></tr>`,
    )
    .join("");

  return (
    `<section class="table-section cost-overview-section">` +
    `<h4>本单有哪些成本项（和报价表数字一致）</h4>` +
    `<p class="cost-overview-lead">先把「一件货」的钱拆开：物料钱、杂费、加工费、模具分摊；下表各项与报价卡口径一致。</p>` +
    `<div class="cost-overview-table-wrap"><table class="cost-overview-table"><thead><tr>` +
    `<th>项目</th><th>金额</th><th>帮您理解</th>` +
    `</tr></thead><tbody>${compRows}</tbody></table></div>` +
    `</section>`
  );
}

/** 物料明细：紧凑表格（来源/规格/用量/单价/计算式/小计/状态；备注跨列） */
function renderProcessMaterialLines(materialLines) {
  if (!Array.isArray(materialLines) || materialLines.length === 0) {
    return "";
  }
  const thead =
    "<thead><tr>" +
    "<th>物料名称</th><th>来源</th><th>规格</th><th>用量</th><th>单价</th><th>计算式</th><th>小计</th><th>状态</th>" +
    "</tr></thead>";
  const tbody = materialLines
    .map((line) => {
      const mt = line.material_table;
      if (!mt) {
        const parts = line.formula_parts;
        let body = "";
        if (Array.isArray(parts) && parts.length > 0) {
          body = parts
            .map((p) => {
              const cls = escapeHtml(p.kind || "detail");
              return `<div class="quote-calc-block quote-calc-${cls}">${escapeNl(p.text)}</div>`;
            })
            .join("");
        } else {
          body = `<div class="quote-calc-block quote-calc-fallback">${escapeNl(line.formula || "")}</div>`;
        }
        return `<tr class="process-material-legacy"><td colspan="8"><div class="quote-calc-line-title">${escapeHtml(
          line.name || "-",
        )}</div>${body}</td></tr>`;
      }
      const srcTitle = escapeHtml(String(mt.source_title || ""));
      const src = `<span class="mat-src-label" title="${srcTitle}">${escapeHtml(String(mt.source_display || ""))}</span>`;
      let statusHtml = "";
      const st = mt.verify_state;
      if (st === "ok") {
        statusHtml = `<span class="mat-verify-icon mat-verify-ok" title="验算正确">✅</span>`;
      } else if (st === "warn") {
        statusHtml = `<span class="mat-verify-icon mat-verify-warn" title="建议人工核对">⚠️</span>`;
      } else {
        statusHtml = `<span class="mat-verify-icon mat-verify-err" title="请检查数据">❌</span>`;
      }
      const mainRow =
        `<tr class="process-material-row">` +
        `<td class="mat-col-name">${escapeHtml(line.name || "-")}</td>` +
        `<td class="mat-col-src">${src}</td>` +
        `<td>${escapeHtml(formatMeasureNumbersTwoDecimals(String(mt.spec != null ? mt.spec : "-")))}</td>` +
        `<td>${escapeHtml(formatMeasureNumbersTwoDecimals(String(mt.usage != null ? mt.usage : "-")))}</td>` +
        `<td>${escapeHtml(formatNumbersInDisplayText(String(mt.unit_price != null ? mt.unit_price : "—")))}</td>` +
        `<td class="mat-col-formula">${escapeHtml(formatNumbersInDisplayText(String(mt.formula_short != null ? mt.formula_short : "—")))}</td>` +
        `<td class="mat-col-sub">${escapeHtml(formatNumbersInDisplayText(String(mt.subtotal != null ? mt.subtotal : "—")))}</td>` +
        `<td class="mat-col-status">${statusHtml}</td>` +
        `</tr>`;
      return mainRow;
    })
    .join("");
  return `<div class="process-material-table-wrap"><table class="process-material-table">${thead}<tbody>${tbody}</tbody></table></div>`;
}

function quotedProcessInnerHtml(processPayload, title, fileHint) {
  const fh = String(fileHint || "").trim()
    ? `<p class="quote-source-label">${escapeHtml(String(fileHint))}</p>`
    : "";
  const proc = processPayload;
  const mat = renderProcessMaterialLines(proc?.material_lines);
  const rawHint = proc && proc.raw_hint ? String(proc.raw_hint).trim() : "";
  const hintBlock = rawHint
    ? `<p class="note quote-calc-foot">${escapeHtml(rawHint)}</p>`
    : "";
  const productBlock =
    proc && proc.product_name
      ? `<p class="process-product">${escapeHtml(proc.product_name)}</p>`
      : "";

  const overviewBlock = costOverviewHtml(proc?.cost_overview);

  const footerHelp = proc?.footer_help
    ? `<p class="quote-process-footer-help">${escapeNl(proc.footer_help)}</p>`
    : "";

  const hasBody = Boolean(productBlock || overviewBlock || mat || hintBlock || footerHelp);
  if (!hasBody) {
    return `${fh}<p class="note">${escapeHtml(String(title || "计算过程拆解"))}</p>`;
  }

  let bodySections = "";
  if (overviewBlock) {
    bodySections += overviewBlock;
  }
  bodySections += `<section class="table-section process-material-section"><h4>物料明细（每一行怎么算出小计）</h4>${mat}</section>`;
  if (hintBlock) {
    bodySections += `<section class="table-section quote-calc-hint-section"><h4>填写完整度提示</h4>${hintBlock}</section>`;
  }
  if (footerHelp) {
    bodySections += `<section class="table-section quote-process-help-section">${footerHelp}</section>`;
  }
  return `${fh}${productBlock}${bodySections}`;
}

function embeddedQuotePanelExpanded(msg) {
  if (!msg || msg.quoteProcessLoading) {
    return true;
  }
  return msg.quoteProcessExpanded === true;
}

function buildEmbeddedQuoteProcessCollapse(cardOpts, msgId) {
  const id = escapeHtml(msgId || "");
  if (!id) {
    return "";
  }
  const qp = cardOpts.quoteProcess;
  const titleText = qp?.title ? qp.title : "计算过程拆解";
  const title = escapeHtml(titleText);
  const loading = Boolean(cardOpts.quoteProcessLoading);
  const errText = String(cardOpts.quoteProcessError || "").trim();
  const proc = qp?.process;
  const fh = qp?.file_hint || "";

  const expanded = embeddedQuotePanelExpanded(cardOpts);

  let bodyInner = "";
  if (loading) {
    bodyInner = '<p class="quote-process-loading">正在梳理本单推导说明…</p>';
  } else if (errText && !proc) {
    bodyInner = `<p class="note note-warn">${escapeHtml(errText)}</p><p class="quote-process-error-hint">收起后再点击标题可重试。</p>`;
  } else if (proc) {
    bodyInner = quotedProcessInnerHtml(proc, titleText, fh);
  } else {
    bodyInner =
      '<p class="note note-info quote-process-tip">首次点击「展开」将加载本单完整拆解：成本项总览、物料逐行、分档公式（由引擎汇总，无需等待模型）。</p>';
  }

  const ctrl = loading ? "…" : expanded ? "收起 ▲" : "展开 ▼";
  const panelCollapsedClass = expanded ? "" : "is-collapsed";

  return `
    <div class="process-card-collapse quote-embedded-process ${panelCollapsedClass}" data-quote-process-root data-quote-msg-id="${id}">
      <button type="button" class="process-card-collapse-head" data-quote-process-head aria-expanded="${expanded ? "true" : "false"}">
        <span class="process-card-collapse-title">📋 ${title}</span>
        <span class="process-card-collapse-ctrl">${ctrl}</span>
      </button>
      <div class="process-card-collapse-panel">
        <div class="process-card-collapse-body">${bodyInner}</div>
      </div>
    </div>
  `;
}

async function loadQuoteProcessIntoMessage(msgId) {
  const preset = {
    text: "请给出本单计算过程拆解（物料与档位成本逻辑）。",
    interaction: "process",
  };
  const target = findQuoteMessageByMsgId(msgId);
  if (!target?.data) {
    return;
  }
  if (target.quoteProcessLoading) {
    return;
  }

  target.quoteProcessLoading = true;
  target.quoteProcessError = "";
  target.quoteProcessExpanded = true;
  renderMessages();

  try {
    const body = JSON.stringify({
      user_message: preset.text,
      interaction: preset.interaction,
      quote_snapshot: target.data,
      file_hint: String(target.fileName || ""),
      recent_quotes_context: getRecentQuotesSummaries(3),
      session_context: buildSessionContext(),
    });
    const response = await quoteFetch("/api/quote/advise", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
    const result = await readResponseJson(response);
    if (!response.ok) {
      throw new Error(result.message || result.error || `请求失败 HTTP ${response.status}`);
    }
    if (result.llm_status) {
      state.llmStatus = result.llm_status;
      renderLlmStatus();
    }
    if (result.reply_type === "process_card" && result.process) {
      target.quoteProcess = {
        title: result.title || "计算过程拆解",
        file_hint: result.file_hint || "",
        process: result.process,
      };
      target.quoteProcessError = "";
    } else {
      target.quoteProcess = null;
      target.quoteProcessError =
        String(result.text || "（未返回说明内容）").trim() || "（未返回说明内容）";
    }
  } catch (error) {
    target.quoteProcess = null;
    target.quoteProcessError = humanizeNetworkError(
      error instanceof Error ? error : new Error(String(error)),
    );
  } finally {
    target.quoteProcessLoading = false;
    renderMessages();
  }
}

function handleQuoteProcessHeadClick(msgIdRaw) {
  const msgId = String(msgIdRaw || "").trim();
  if (!msgId) {
    return;
  }
  const msg = findQuoteMessageByMsgId(msgId);
  if (!msg || msg.type !== "quote_card") {
    return;
  }

  const hasProcessBody = Boolean(msg.quoteProcess?.process);
  const hasErr = Boolean(String(msg.quoteProcessError || "").trim());

  if (msg.quoteProcessLoading) {
    return;
  }

  if (!hasProcessBody && !hasErr) {
    loadQuoteProcessIntoMessage(msgId);
    return;
  }

  if (!hasProcessBody && hasErr) {
    if (embeddedQuotePanelExpanded(msg)) {
      msg.quoteProcessExpanded = false;
      renderMessages();
      return;
    }
    msg.quoteProcessError = "";
    loadQuoteProcessIntoMessage(msgId);
    return;
  }

  if (hasProcessBody) {
    msg.quoteProcessExpanded = !embeddedQuotePanelExpanded(msg);
    renderMessages();
  }
}

function extraQuoteActionRowHtml(message) {
  const msgId = escapeHtml(message.msgId || "");
  const q = Number(message.calcQuantity);
  if (!msgId || !Number.isFinite(q) || q <= 0) {
    return "";
  }
  const qtyAttr = escapeHtml(String(q));
  return `
    <div class="quote-extra-actions" data-calc-quantity="${qtyAttr}">
      <button type="button" class="extra-action-btn extra-action-primary" data-extra-action="promote">以此数量为准</button>
      <button type="button" class="extra-action-btn" data-extra-action="again">再试其他数量</button>
    </div>
  `;
}

function extraMaterialQuoteActionsHtml(message) {
  const msgId = escapeHtml(message.msgId || "");
  if (!msgId) {
    return "";
  }
  return `
    <div class="quote-extra-actions quote-material-extra-actions" data-material-msg-id="${msgId}">
      <button type="button" class="extra-action-btn extra-action-primary" data-material-action="promote">以此方案为准</button>
      <button type="button" class="extra-action-btn" data-material-action="again-mat">再换其他材料</button>
      <button type="button" class="extra-action-btn" data-material-action="again-qty">试算其他数量</button>
    </div>
  `;
}

function isUniformGrossMargin(quote) {
  const tiers = quote.tiers;
  if (!tiers?.length) {
    return true;
  }
  const flag = quote.settings && quote.settings.gross_margin_uniform;
  if (typeof flag === "boolean") {
    return flag;
  }
  const first = tiers[0].margin_rate_text;
  return tiers.every((row) => row.margin_rate_text === first);
}

function buildSalesSheetCheckpointsHtml(quote) {
  const rows = Array.isArray(quote.sales_sheet_checkpoints)
    ? quote.sales_sheet_checkpoints
    : [];
  if (!rows.length) {
    return "";
  }

  /** 两行（毛前成本 / 含毛利报价）× 两列（仅人工脚注 vs 仅 Agent），避免与「并排双卡」视觉混读。 */

  function gapLabel(gapPc) {
    const g = Number(gapPc);
    if (!Number.isFinite(g) || Math.abs(g) <= 0.02) return "基本持平";
    if (g > 0) return `Agent 较人工高 ${formatDisplayNumber(g)}`;
    return `Agent 较人工低 ${formatDisplayNumber(Math.abs(g))}`;
  }

  function gapQuoteLabel(qgNum) {
    const g = Number(qgNum);
    if (!Number.isFinite(g) || Math.abs(g) <= 0.02) return "基本持平";
    if (g > 0) return `Agent 较人工高 ${formatDisplayNumber(g)}`;
    return `Agent 较人工低 ${formatDisplayNumber(Math.abs(g))}`;
  }

  const explainSet = new Set();
  rows.forEach((r) => {
    [String(r.gap_explain_cn || "").trim(), String(r.quote_gap_explain_cn || "").trim()]
      .filter(Boolean)
      .forEach((t) => explainSet.add(t));
  });
  const mergedExplain = [...explainSet].map((t) => escapeHtml(t)).join(" ");

  const tierTables = rows
    .map((r) => {
      const qty = escapeHtml(String(r.quantity_text || r.quantity || "?"));
      const hPre = escapeHtml(String(r.ref_cost_before_margin_text || "—"));
      const aPre = escapeHtml(String(r.computed_cost_before_margin_text || "—"));
      const hasRefQ = String(r.ref_quote_text || "").trim().length > 0;
      const hPost = escapeHtml(hasRefQ ? String(r.ref_quote_text || "").trim() : "—（表内未写此行）");
      const hasAgentExw = String(r.computed_exw_quote_text || "").trim().length > 0;
      const aPost = escapeHtml(hasAgentExw ? String(r.computed_exw_quote_text || "").trim() : "—");

      const dPreLabel = escapeHtml(`${gapLabel(r.gap_pc)} 元/件`);
      const dPostLabel =
        hasRefQ && hasAgentExw ? escapeHtml(`${gapQuoteLabel(r.gap_exw_quote_pc)} 元/件`) : escapeHtml("—");

      return `
        <div class="mas-matrix-block">
          <div class="mas-matrix-qty">${qty}档</div>
          <div class="table-wrap mas-matrix-wrap">
            <table class="mas-matrix">
              <thead>
                <tr>
                  <th scope="col" class="mas-m-h">计价口径</th>
                  <th scope="col" class="mas-m-colh mas-m-human">业务员（人工）<span class="mas-col-sub">仅表内脚注，非系统代入</span></th>
                  <th scope="col" class="mas-m-colh mas-m-agent">本系统（Agent）<span class="mas-col-sub">引擎按同口径单独重算</span></th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th scope="row" class="mas-m-rowh">每件 · 毛利前「全成本」</th>
                  <td class="numeric mas-m-human">${hPre}</td>
                  <td class="numeric mas-m-agent">${aPre}</td>
                </tr>
                <tr>
                  <th scope="row" class="mas-m-rowh">每件 · 含毛利「参考出厂价」*</th>
                  <td class="numeric mas-m-human">${hPost}</td>
                  <td class="numeric mas-m-agent">${aPost}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="mas-diff-row">
            <span><strong>毛利前差额：</strong>${dPreLabel}</span>
            <span><strong>含毛利差额：</strong>${dPostLabel}</span>
          </div>
        </div>`;
    })
    .join("");

  const footStar = escapeHtml(
    "* 含毛利价：人工列取表内脚注；Agent 列取本系统 EXW（与脚注毛利率档对齐时才有可比性）。",
  );

  return `
    <section class="manual-agent-strip">
      <p class="note note-info mas-context">
        ${escapeHtml(
          "下表按「计价口径」分行：毛利前一行、含毛利一行；左右两列分别为「仅限业务员脚注」与「仅限本系统核算」，互不混填。上方「物料合计」仅物料行之和，与本表两行口径均不同。",
        )}
      </p>
      ${tierTables}
      <p class="mas-footnote">${footStar}</p>
      ${
        mergedExplain
          ? `<div class="mas-why mas-why-merged">${mergedExplain}</div>`
          : ""
      }
    </section>
  `;
}

/** 报价单为 EXW-only（未展示 FOB）时，对「成本/件」侧展示 13% 含税参考价。 */
function quoteIsExwCostVatMode(quote) {
  return !!(quote && quote.include_fob === false);
}

/** 含税价/件（毛利前成本×1.13）；兼容旧快照无 taxed_price。 */
function taxedUnitPriceFromTier(tier) {
  const fromApi = Number(tier.taxed_price);
  if (Number.isFinite(fromApi)) return fromApi;
  const cbm = Number(tier.cost_before_margin ?? tier.total_cost);
  return Number.isFinite(cbm) ? Math.round(cbm * 1.13 * 100) / 100 : NaN;
}

const STRUCTURE_RISK_ORDER = { high: 0, medium: 1, low: 2 };

function structureItemDisplayStatus(item) {
  const us = String(item?.user_status || "pending");
  if (us === "ignored") return { label: "已忽略", tone: "muted" };
  if (us === "edited") return { label: "需修改", tone: "warn" };
  if (us === "confirmed") return { label: "已确认", tone: "ok" };
  const costIds = Array.isArray(item?.cost_item_ids) ? item.cost_item_ids : [];
  if (!costIds.length && item?.affects_cost !== false) {
    return { label: "可能漏算", tone: "high" };
  }
  if (item?.estimate_status === "ai_estimated") return { label: "AI估算", tone: "medium" };
  if (
    item?.estimate_status === "needs_manual" ||
    (Array.isArray(item?.missing_fields) && item.missing_fields.length > 0)
  ) {
    return { label: "待补信息", tone: "warn" };
  }
  return { label: "已计入成本", tone: "ok" };
}

function resolveStructureCostLabels(item, detailRows) {
  const ids = Array.isArray(item?.cost_item_ids) ? item.cost_item_ids : [];
  const labels = [];
  for (const cid of ids) {
    const m = /^row:(\d+)$/.exec(String(cid));
    if (!m) {
      labels.push(String(cid));
      continue;
    }
    const row = detailRows[Number(m[1])];
    labels.push(String(row?.name || cid).trim() || cid);
  }
  return labels;
}

function buildStructureChecklistPanelHtml(quote, detailRootKey, msgId) {
  // Keep the structure checklist in the API result, but do not render the large
  // post-quote panel in the chat card. The cost rows and pricing gate remain visible.
  return "";
  const checklist = quote?.structure_checklist;
  const items = Array.isArray(checklist?.items) ? checklist.items : [];
  if (!checklist?.is_bag_product || !items.length) {
    return "";
  }
  const detailRows = Array.isArray(quote?.detail_rows) ? quote.detail_rows : [];
  const summary = checklist.summary || {};
  const hasHigh = items.some((it) => String(it?.risk_level || "") === "high");
  const expanded = hasHigh || Number(summary.possible_leak || 0) > 0;
  const collapsedClass = expanded ? "" : " is-collapsed";
  const ctrl = expanded ? "收起 ▲" : "展开 ▼";
  const recalcHint = String(quote?.structure_checklist_recalc_hint || "").trim();

  const sorted = [...items].sort((a, b) => {
    const ra = STRUCTURE_RISK_ORDER[String(a?.risk_level || "low")] ?? 9;
    const rb = STRUCTURE_RISK_ORDER[String(b?.risk_level || "low")] ?? 9;
    if (ra !== rb) return ra - rb;
    return String(a?.name || "").localeCompare(String(b?.name || ""), "zh-CN");
  });

  const rowsHtml = sorted
    .map((item) => {
      const sid = escapeHtml(String(item.structure_id || ""));
      const st = structureItemDisplayStatus(item);
      const costLabels = resolveStructureCostLabels(item, detailRows);
      const costText =
        costLabels.length > 0
          ? `${costLabels.length} 项：${escapeHtml(costLabels.slice(0, 3).join("、"))}${costLabels.length > 3 ? "…" : ""}`
          : "未关联成本项";
      const source = String(item.source_text || "").trim();
      const riskReason = String(item.risk_reason || "").trim();
      const msgAttr = escapeHtml(String(msgId || ""));
      return `
        <li class="structure-cl-item structure-cl-item--${escapeHtml(st.tone)}" data-structure-id="${sid}">
          <div class="structure-cl-item-head">
            <strong class="structure-cl-name">${escapeHtml(item.name || "-")}</strong>
            <span class="structure-cl-badge structure-cl-badge--${escapeHtml(st.tone)}">${escapeHtml(st.label)}</span>
            <span class="structure-cl-cat muted">${escapeHtml(item.category_label || item.category || "")}</span>
          </div>
          ${source ? `<div class="structure-cl-source muted">来源：${escapeHtml(source)}</div>` : ""}
          <div class="structure-cl-cost">关联成本：${costText}</div>
          ${riskReason ? `<div class="structure-cl-risk">${escapeHtml(riskReason)}</div>` : ""}
          <div class="structure-cl-actions">
            <button type="button" class="btn-structure-cl-action" data-structure-action="confirmed" data-structure-id="${sid}" data-msg-id="${msgAttr}">确认</button>
            <button type="button" class="btn-structure-cl-action" data-structure-action="ignored" data-structure-id="${sid}" data-msg-id="${msgAttr}">忽略</button>
            <button type="button" class="btn-structure-cl-action" data-structure-action="edited" data-structure-id="${sid}" data-msg-id="${msgAttr}">标记需修改</button>
          </div>
        </li>`;
    })
    .join("");

  const hintHtml = recalcHint
    ? `<div class="structure-cl-recalc-hint" role="status">${escapeHtml(recalcHint)}</div>`
    : "";

  return `
    <div class="process-card-collapse structure-checklist-panel${collapsedClass}" data-structure-checklist-root data-quote-detail-root="${escapeHtml(detailRootKey)}">
      <button type="button" class="process-card-collapse-head" data-process-collapse-toggle aria-expanded="${expanded ? "true" : "false"}">
        <span class="process-card-collapse-title">🧩 识别结构清单</span>
        <span class="process-card-collapse-meta muted">${escapeHtml(String(summary.total || items.length))} 项 · 已计入 ${escapeHtml(String(summary.costed || 0))} · 待核 ${escapeHtml(String(summary.pending_confirm || 0))}${Number(summary.possible_leak || 0) > 0 ? ` · <strong class="structure-cl-leak">可能漏算 ${escapeHtml(String(summary.possible_leak))}</strong>` : ""}</span>
        <span class="process-card-collapse-ctrl">${ctrl}</span>
      </button>
      <div class="process-card-collapse-panel">
        <div class="process-card-collapse-body structure-cl-body">
          ${hintHtml}
          <ul class="structure-cl-list">${rowsHtml}</ul>
        </div>
      </div>
    </div>`;
}

function formatSizeVariantTierSummary(quoteResult) {
  const tiers = Array.isArray(quoteResult?.tiers) ? quoteResult.tiers : [];
  if (!tiers.length) return "";
  return tiers
    .map((tier) => {
      const qty = String(tier.quantity_text || tier.quantity || "-");
      const exw = String(tier.exw_price_text || "-");
      return `${qty} EXW ${exw}`;
    })
    .join(" · ");
}

function buildMultiSizeQuoteCardHtml(quote, fileName, msgId, cardOpts = {}) {
  const variants = quote.size_variants || [];
  const lead = `同一份 BOM 共 ${variants.length} 个尺寸，分别核算如下：`;
  const sections = variants
    .map((variant, idx) => {
      const qr = variant.quote_result && typeof variant.quote_result === "object" ? variant.quote_result : {};
      const merged = {
        ...quote,
        ...qr,
        multi_size: false,
        size_variants: undefined,
      };
      const label = String(variant.label || `尺寸${idx + 1}`).trim();
      const sizeText = String(variant.size_text || "").trim();
      const title = sizeText ? `${label}（${sizeText}）` : label;
      const tierSummary = formatSizeVariantTierSummary(qr);
      const inner = buildQuoteCardInnerHtml(merged, fileName, `${msgId || "q"}_sz${idx}`, {
        ...cardOpts,
        skipMultiSizeWrap: true,
        displayTitle: title,
      });
      return `<section class="size-variant-block" aria-label="${escapeHtml(title)}">
        <header class="size-variant-head">
          <h4 class="size-variant-title">${escapeHtml(title)}</h4>
          ${tierSummary ? `<p class="size-variant-tier-summary muted">${escapeHtml(tierSummary)}</p>` : ""}
        </header>
        ${inner}
      </section>`;
    })
    .join("");
  return `<div class="multi-size-quote-card"><p class="multi-size-quote-lead">${escapeHtml(lead)}</p>${sections}</div>`;
}

function buildQuoteCardInnerHtml(quote, fileName, msgId, cardOpts = {}) {
  const opts = cardOpts || {};
  if (
    !opts.skipMultiSizeWrap &&
    Array.isArray(quote?.size_variants) &&
    quote.size_variants.length > 1
  ) {
    return buildMultiSizeQuoteCardHtml(quote, fileName, msgId, opts);
  }
  const isExtraMaterial = Boolean(opts.isExtraMaterial);
  const isExtra = Boolean(opts.isExtra);
  const cleanedRows = cleanDetailRowsForDisplay(quote.detail_rows || []).filter(
    (row) => !isReferenceOnlyRowName(row?.name),
  );
  const cleanedMaterialTotalNum = cleanedRows.reduce(
    (sum, row) => sum + parseAmountValue(row.amount),
    0,
  );
  const cleanedMaterialTotal = formatDisplayNumber(cleanedMaterialTotalNum);
  const rawTitle = String(quote.product_name || state.baseConfig.product_name || "").trim();
  const productTitle = escapeHtml(rawTitle || "报价核算");
  const sourceLabel = fileName
    ? `📎 ${escapeHtml(fileName)} 的核算结果`
    : "本次文字需求的核算结果";

  const topBanners = isExtraMaterial
    ? `<div class="quote-material-banner">本结果为材料替换试算，原报价及数量试算仍有效。</div>`
    : isExtra && opts.originalQuantity != null
      ? `<div class="quote-extra-banner">本结果为额外试算，原 <strong>${escapeHtml(
          String(opts.originalQuantity),
        )}件</strong> 报价仍有效。</div>`
      : "";

  const extraSubtitleHtml =
    (isExtraMaterial || isExtra) && opts.displayTitle
      ? `<p class="quote-extra-subtitle">${escapeHtml(opts.displayTitle)}</p>`
      : "";

  const tagLine = isExtraMaterial ? "材料替料试算" : isExtra ? "补充试算" : "自动报价结果";

  const pg = quote.pricing_gate || {};
  const pricingGateBypass = Boolean(pg.confirmation_bypassed);
  const gateBlocked =
    (!pricingGateBypass && pg.final_price_allowed === false) || pg.confirm_required === true;
  const mediumRiskBanner =
    !pricingGateBypass &&
    pg.risk_level === "MEDIUM" &&
    pg.final_price_allowed !== false &&
    Boolean(pg.hint_cn);
  const gateBannerHtml = gateBlocked
    ? `<div class="pricing-gate-banner pricing-gate-banner-high" role="status">${escapeHtml(
        pg.hint_cn ||
          "高风险：当前报价含待核对明细；可打开报价单，但对外发送前请先复核用量、单价和计算方式。",
      )}</div>`
    : mediumRiskBanner
      ? `<div class="pricing-gate-banner pricing-gate-banner-medium" role="status">${escapeHtml(String(pg.hint_cn || "").trim())}</div>`
      : "";
  const gateTierCaptionHtml = gateBlocked
    ? `<p class="note note-warn pricing-tier-estimated">${escapeHtml(
        "以下 EXW/FOB 含风险提醒；报价单可打开，对外发送前请复核明细口径。",
      )}</p>`
    : !pricingGateBypass && pg.risk_level === "MEDIUM"
      ? `<p class="note note-info pricing-tier-medium">${escapeHtml(
          "以下为系统已自动放行的最终价（中风险已记入审计）；对外发送前建议复核。",
        )}</p>`
      : "";
  const gateActionsHtml = "";
  const approvalBannerHtml = buildQuoteApprovalBannerHtml(quote);

  const detailRootKey =
    String(msgId || quote.quote_id || "detail").trim().replace(/[^\w.-]/g, "_") || "detail";

  const detailBody = cleanedRows
    .map((row) => {
      const specUsage = `${escapeHtml(formatMeasureNumbersTwoDecimals(String(row.spec != null ? row.spec : "-")))} / ${escapeHtml(formatMeasureNumbersTwoDecimals(String(row.usage != null ? row.usage : "-")))}`;
      const trClassExtra = row.extra_material_trial ? " row-extra-material" : "";
      const trialNote = row.trial_price_note
        ? `<div class="trial-price-note">${escapeHtml(row.trial_price_note)}</div>`
        : "";
      const upDisp = formatNumbersInDisplayText(String(row.unit_price || "-"));
      const upHtml = trialNote
        ? `${escapeHtml(upDisp)}${trialNote}`
        : escapeHtml(upDisp);
      const autoKbBadge = buildMaterialRecognitionBadge(row);
      const calcRaw = String(row.calc_note ?? row.calc_method ?? "").trim() || "—";
      const calcHtml = calcRaw === "—" ? escapeHtml("—") : escapeNl(calcRaw);
      const flatLen = calcRaw.replace(/\s+/g, " ").length;
      const needsCalcToggle = calcRaw !== "—" && (flatLen > 56 || calcRaw.includes("\n"));
      const calcCell = `
          <td class="detail-calc-cell">
            <div class="calc-note-box${needsCalcToggle ? "" : " calc-note-box--short"}">
              <div class="calc-note-text${needsCalcToggle ? " is-clamped" : ""}">${calcHtml}</div>${
                needsCalcToggle
                  ? `<button type="button" class="link-inline calc-expand-btn" aria-expanded="false">展开</button>`
                  : ""
              }
            </div>
          </td>`;
      const mainTr = `
        <tr class="quote-mat-main${trClassExtra}">
          <td class="col-mat-name"><span class="quote-mat-name-text">${escapeHtml(row.name || "-")}</span>${autoKbBadge}</td>
          ${calcCell}
          <td class="col-spec-use">${specUsage}</td>
          <td class="col-unit-price">${upHtml}</td>
          <td class="col-subtotal numeric"><strong>${escapeHtml(displayQuoteAmountText(row))}</strong></td>
        </tr>`;
      return mainTr + buildQuoteMatMetaRowHtml(row);
    })
    .join("");

  const marginUniform = isUniformGrossMargin(quote);
  let exwThContent = "";
  let exwThClass = "exw-th-hint";
  if (marginUniform && quote.tiers?.[0]?.margin_rate_text) {
    exwThContent = `毛利 ${escapeHtml(quote.tiers[0].margin_rate_text)}`;
    exwThClass = "exw-margin-hint";
  } else if (!marginUniform) {
    exwThContent = "各档毛利见金额下方";
    exwThClass = "exw-th-hint";
  }

  const showFob = quote.include_fob !== false;
  const costUsdMode = showFob;
  const usdRateRaw = Number(
    quote.usd_cny_rate ??
      quote.settings?.usd_cny_rate ??
      (typeof window !== "undefined" ? window.__quoteUsdSnapshot?.usdCnyRate : NaN),
  );
  const usdRate = Number.isFinite(usdRateRaw) && usdRateRaw > 0 ? usdRateRaw : 7.15;
  const toUsd = (v) => (Number.isFinite(v) ? v / usdRate : NaN);
  const fmtUsd = (v) => (Number.isFinite(v) ? `$${formatDisplayNumber(v)}` : "-");
  const tier0CostNum = Number(quote.tiers?.[0]?.cost_before_margin ?? quote.tiers?.[0]?.total_cost);
  const systemCostDisplay = costUsdMode
    ? fmtUsd(toUsd(tier0CostNum))
    : quote.system_cost_text || "-";
  const costHeaderText = costUsdMode ? "成本 / 件 (USD)" : "成本 / 件";

  const taxHeaderTh = quoteIsExwCostVatMode(quote)
    ? `<th class="numeric">含税价（13%）</th>`
    : `<th class="numeric muted">含税说明</th>`;

  const tierBody = (quote.tiers || [])
    .map((tier) => {
      const marginTag =
        !marginUniform && tier.margin_rate_text
          ? `<span class="exw-tier-margin">毛利 ${escapeHtml(tier.margin_rate_text)}</span>`
          : "";
      const exwInner = marginTag
        ? `<div class="exw-price-line"><strong>${escapeHtml(tier.exw_price_text || "-")}</strong></div>${marginTag}`
        : `<strong>${escapeHtml(tier.exw_price_text || "-")}</strong>`;
      const fobTd = showFob
        ? `<td class="numeric">${escapeHtml(tier.fob_price_text || "-")}</td>`
        : "";

      let taxTd = "";
      if (quoteIsExwCostVatMode(quote)) {
        const tp = taxedUnitPriceFromTier(tier);
        const show =
          String(tier.taxed_price_text || "").trim() ||
          (Number.isFinite(tp) ? formatDisplayMoneyCny(tp) : "—");
        taxTd = `<td class="numeric quote-tier-tax-cell"><strong>${escapeHtml(show)}</strong></td>`;
      } else {
        taxTd = `<td class="numeric muted quote-tier-tax-cell">${escapeHtml(
          String(tier.taxed_price_text || "FOB口径：不加税"),
        )}</td>`;
      }

      const tierCostNum = Number(tier.cost_before_margin ?? tier.total_cost);
      const tierCostDisplay = costUsdMode
        ? fmtUsd(toUsd(tierCostNum))
        : tier.cost_before_margin_text || "-";
      return `
        <tr>
          <td class="numeric"><strong>${escapeHtml(tier.quantity_text || "-")}</strong></td>
          <td class="numeric">${escapeHtml(tier.mold_share_text || "-")}</td>
          <td class="numeric">${escapeHtml(tier.processing_fee_text || "-")}</td>
          <td class="numeric"><strong>${escapeHtml(tierCostDisplay)}</strong></td>
          ${taxTd}
          <td class="numeric ${marginTag ? "exw-cell" : ""}">${exwInner}</td>
          ${fobTd}
        </tr>
      `;
    })
    .join("");

  const dataNotice = String(quote.data_notice || "").trim();
  const dataNoticeHtml = buildQuoteDataNoticeHtml(dataNotice);

  const consultantBlurb = String(quote.consultant_summary || "").trim();
  const consultantHtml = consultantBlurb
    ? `<p class="quote-consultant-summary"><strong>栢博简评：</strong>${escapeHtml(consultantBlurb)}</p>`
    : "";

  let formulaNoticeHtml = "";
  if (quote.tiers && quote.tiers.length > 0) {
    const multi = !marginUniform;
    let formulaText;
    if (multi) {
      formulaText = showFob
        ? "各档毛利率可不同：EXW = 成本÷(1−该档毛利率)，FOB = EXW + 4元/件。美金对外报价请到「报价单」页导出 FOB 美金 PDF。"
        : "各档毛利率可不同：EXW = 成本÷(1−该档毛利率)。本单未选 FOB，不展示 FOB 列。";
    } else {
      formulaText = showFob
        ? `毛利公式：${quote.tiers[0].quote_formula}，FOB = EXW + 4元/件。`
        : `毛利公式：${quote.tiers[0].quote_formula}（本单未选 FOB，无 FOB 价）。`;
    }
    const taxExplain = quoteIsExwCostVatMode(quote)
      ? "含税参考（独立于 EXW/FOB 报价）：含税列为元/件，按毛利前成本加计 13% 派生展示；不改变系统已算出厂价。"
      : "含税说明：本单报价口径含 FOB 时，不按成本加计增值税含税展示（FOB口径：不加税）。";
    formulaNoticeHtml = `<p class="note note-info">${escapeHtml(formulaText)}</p><p class="note note-info quote-tax-footnote">${escapeHtml(taxExplain)}</p>`;
  }

  const fobHeaderRow = showFob
    ? `<th class="numeric">FOB 报价（+4元）</th>`
    : "";

  const embeddedProcessHtml = buildEmbeddedQuoteProcessCollapse(opts, msgId);
  const extraActionsHtml = opts.extraActionsHtml || "";

  const tierSectionTitle =
    isExtra && !isExtraMaterial ? "试算数量报价" : "三档数量报价";

  let compareRowHtml = "";
  if (
    isExtra &&
    !isExtraMaterial &&
    opts.originalQuantity != null &&
    opts.calcQuantity != null
  ) {
    const d = Number(opts.costDelta);
    const sign = Number.isFinite(d) && d > 0 ? "+" : "";
    const dv = Number.isFinite(d) ? formatDisplayNumber(d) : "-";
    compareRowHtml = `<p class="quote-extra-compare">与原始 <strong>${escapeHtml(
      String(opts.originalQuantity),
    )}件</strong> 相比：单包系统成本差异 <strong>${sign}${escapeHtml(dv)}元/件</strong>（未计毛利前）</p>`;
  } else if (
    isExtraMaterial &&
    opts.materialTotalDelta != null &&
    opts.costDelta != null
  ) {
    const mtd = Number(opts.materialTotalDelta);
    const cd = Number(opts.costDelta);
    const s1 = Number.isFinite(mtd) && mtd > 0 ? "+" : "";
    const s2 = Number.isFinite(cd) && cd > 0 ? "+" : "";
    const mv = Number.isFinite(mtd) ? formatDisplayNumber(mtd) : "-";
    const cv = Number.isFinite(cd) ? formatDisplayNumber(cd) : "-";
    compareRowHtml = `<p class="quote-material-compare">与原始方案相比：物料合计差异 <strong>${s1}${escapeHtml(
      mv,
    )}元</strong>；单包系统成本差异 <strong>${s2}${escapeHtml(cv)}元/件</strong>（未计毛利前）</p>`;
  }

  return `
    ${topBanners}
    <p class="assistant-tag">${escapeHtml(tagLine)}</p>
    ${extraSubtitleHtml}
    <p class="quote-source-label">${sourceLabel}</p>
    <h3>${productTitle}</h3>
    ${approvalBannerHtml}
    ${gateBannerHtml}
    ${consultantHtml}
    <div class="summary-grid summary-grid--with-tax">
      <div>
        <span>物料合计</span>
        <strong>${escapeHtml(cleanedMaterialTotal)}元</strong>
      </div>
      <div>
        <span>单包系统成本</span>
        <strong>${escapeHtml(systemCostDisplay)}</strong>
      </div>
      ${
        quoteIsExwCostVatMode(quote) && quote.tiers?.[0]
          ? (() => {
              const t0 = quote.tiers[0];
              const tp = taxedUnitPriceFromTier(t0);
              const show =
                escapeHtml(
                  String(t0.taxed_price_text || "").trim() ||
                    (Number.isFinite(tp) ? formatDisplayMoneyCny(tp) : "—"),
                );
              return `<div>
        <span>含税参考（一档·13%）</span>
        <strong>${show}</strong>
      </div>`;
            })()
          : `<div>
        <span>含税说明</span>
        <strong class="muted">${escapeHtml(
          String(quote.tiers?.[0]?.taxed_price_text || "FOB口径：不加税"),
        )}</strong>
      </div>`
      }
    </div>
    ${buildSalesSheetCheckpointsHtml(quote)}
    ${
      quote.cost_bridge && typeof quote.cost_bridge === "object"
        ? (() => {
            const b = quote.cost_bridge;
            const mbBridge =
              typeof b.material_bundle_incl_mgmt_text === "string" &&
              b.material_bundle_incl_mgmt_text
                ? ` 与需求表中「底料+管理损耗并进物料总成」类比：<strong>${escapeHtml(
                    b.material_bundle_incl_mgmt_text,
                  )}</strong>（明细物料 ${escapeHtml(
                    quote.material_total_text || `${cleanedMaterialTotal}元`,
                  )}${
                    typeof b.management_loss_pct_on_material_display === "number"
                      ? ` + 管理损耗约 ${escapeHtml(
                          String(b.management_loss_pct_on_material_display),
                        )}%`
                      : ""
                  }）。`
                : "";
            const note = [
              `相较物料合计多出：加工费 ${b.processing_fee_text ?? "-"}；`,
              `杂费/管理费（${escapeHtml(String(b.system_overhead_rule || "规则"))}）${typeof b.system_overhead_per_pc === "number" ? `${formatDisplayNumber(b.system_overhead_per_pc)}元/件` : "-"}；`,
              `${b.tier_quantity_ref ?? "?"}件档模具均摊 ${b.mold_share_text ?? "-"}。`,
              `附加合计（未计毛利前）≈ ${b.addons_sum_text ?? "-"}`,
              mbBridge,
            ].join("");
            return `<p class="note note-info quote-cost-bridge">${note}</p>`;
          })()
        : ""
    }
    ${buildStructureGapHintsHtml(quote.structure_gap_hints, { compact: true })}
    ${buildAnomalyReviewHintsHtml(quote.anomaly_review_hints)}
    ${buildStructureChecklistPanelHtml(quote, detailRootKey, msgId)}
    <section class="table-section quote-detail-section" data-quote-detail-root="${escapeHtml(detailRootKey)}">
      <div class="quote-detail-toolbar">
        <h4>明细数据表</h4>
        <label class="quote-detail-toggle-label">
          <input type="checkbox" class="quote-detail-validation-toggle" />
          <span>查看详细校验</span>
        </label>
      </div>
      <div class="table-wrap table-wrap-quote-detail">
        <table class="quote-detail-mat quote-detail-mat--simple">
          <thead>
            <tr>
              <th>物料名称</th>
              <th>计算方式</th>
              <th>规格 / 用量</th>
              <th>单价参考</th>
              <th class="numeric col-subtotal-th">小计</th>
            </tr>
          </thead>
          <tbody>${detailBody}</tbody>
        </table>
      </div>
      ${dataNoticeHtml}
    </section>
    ${gateActionsHtml}
    <section class="table-section">
      <h4>${tierSectionTitle}</h4>
      ${gateTierCaptionHtml}
      <div class="table-wrap">
        <table class="quote-tier-table">
          <thead>
            <tr>
              <th class="numeric">数量</th>
              <th class="numeric">开模均摊</th>
              <th class="numeric">加工费</th>
              <th class="numeric">${costHeaderText}</th>
              ${taxHeaderTh}
              <th class="numeric">EXW 报价<br /><span class="${exwThClass}">${exwThContent}</span></th>
              ${fobHeaderRow}
            </tr>
          </thead>
          <tbody>${tierBody}</tbody>
        </table>
      </div>
      ${formulaNoticeHtml}
    </section>
    ${compareRowHtml}
    ${embeddedProcessHtml}
    ${extraActionsHtml}
  `;
}

function getStructureConfirmationTableRows(data) {
  const rows =
    Array.isArray(data.items_confirmation) && data.items_confirmation.length > 0
      ? data.items_confirmation
      : Array.isArray(data.items_preview)
        ? data.items_preview
        : [];
  return rows.filter((r) => r && typeof r === "object" && !isReferenceOnlyRowName(r.name));
}

function isReferenceOnlyRowName(name) {
  const text = String(name || "").trim();
  if (!text) {
    return false;
  }
  return /^(?:\u6210\u672c\u53c2\u8003(?:\u4ef7)?|\u6210\u54c1\u5c3a\u5bf8|\u5907\u6ce8|\u8bf4\u660e|\u5efa\u8bae|\u53c2\u8003(?:\u8bf4\u660e|\u4fe1\u606f)?|\u4ef7\u683c\u53c2\u8003|\u5c3a\u5bf8\u8bf4\u660e)(?:[:\uff1a].*)?$/.test(
    text,
  );
}

function displayQuoteAmountText(row) {
  if (!row || typeof row !== "object") {
    return "-";
  }
  if (row.amount_in_cost === false || row.exclude_from_cost === true || isReferenceOnlyRowName(row.name)) {
    return "-";
  }
  const text = String(row.amount_text || "").trim();
  const amountNum = Number(row.amount);
  const usage = String(row.usage || "").trim();
  if (
    Number.isFinite(amountNum) &&
    Math.abs(amountNum) < 0.000001 &&
    /^0(?:\.0+)?(?:\s*\u5143)?$/.test(text.replace(/,/g, "")) &&
    (!usage || usage === "-")
  ) {
    return "-";
  }
  return formatNumbersInDisplayText(text || "-");
}

function mergedStructureConfirmationRow(rows, overrides, idx) {
  const base = rows[idx] || {};
  const key = String(idx);
  const ov = overrides[key] || {};
  const next = typeof ov === "object" ? { ...base, ...ov } : base;
  return next;
}

function getPendingStructureRows(data, pending) {
  const baseRows = getStructureConfirmationTableRows(data);
  const added =
    pending && Array.isArray(pending.structureAddedRows)
      ? pending.structureAddedRows.filter((r) => r && typeof r === "object")
      : [];
  if (!added.length) {
    return baseRows;
  }
  const result = baseRows.slice();
  const sorted = [...added].sort(
    (a, b) => (Number(a.index) || 0) - (Number(b.index) || 0),
  );
  for (const ar of sorted) {
    const at = Number(ar.index);
    const pos = Number.isFinite(at) ? Math.min(Math.max(0, at), result.length) : result.length;
    result.splice(pos, 0, ar);
  }
  return result;
}

function shiftStructureRowIndicesUp(pend, fromIndex) {
  const from = Number(fromIndex);
  if (!pend || Number.isNaN(from)) {
    return;
  }
  const shiftMap = (obj) => {
    if (!obj || typeof obj !== "object") {
      return {};
    }
    const next = {};
    for (const [k, v] of Object.entries(obj)) {
      const i = Number.parseInt(k, 10);
      if (Number.isNaN(i)) {
        continue;
      }
      next[i >= from ? String(i + 1) : String(i)] = v;
    }
    return next;
  };
  pend.structureRowOverrides = shiftMap(pend.structureRowOverrides);
  pend.structureDeletedRows = shiftMap(pend.structureDeletedRows);
  if (Array.isArray(pend.structureAddedRows)) {
    for (const row of pend.structureAddedRows) {
      if (row && typeof row.index === "number" && row.index >= from) {
        row.index += 1;
      }
    }
  }
  if (pend.structureSelectedRowIndex != null && pend.structureSelectedRowIndex >= from) {
    pend.structureSelectedRowIndex += 1;
  }
}

function markStructurePreviewDirty(token) {
  const pend = state.pendingStructureConfirm;
  const tok = String(token || "").trim();
  if (!pend || pend.token !== tok || !pend.structureEditMode) {
    return;
  }
  pend.structureDirty = true;
  pend.structureSavedForQuote = false;
  syncStructureConfirmToolbarUi(tok);
}

function syncStructureConfirmToolbarUi(token) {
  const card = findStructureConfirmationCard(token);
  const pend = state.pendingStructureConfirm;
  if (!card || !pend || pend.token !== token) {
    return;
  }
  const editing = Boolean(pend.structureEditMode);
  const dirty = Boolean(pend.structureDirty);
  const savedOk = Boolean(pend.structureSavedForQuote);
  const saveBtn = card.querySelector(".btn-structure-sc-save");
  if (saveBtn) {
    saveBtn.classList.toggle("btn-structure-sc-save-ready", editing && dirty);
    saveBtn.classList.toggle("btn-structure-sc-save-idle", editing && !dirty);
  }
  const confirmBtn = card.querySelector(".btn-structure-confirm");
  if (confirmBtn) {
    confirmBtn.disabled = editing || !savedOk;
    confirmBtn.title = editing || !savedOk ? "请先保存明细修改" : "";
  }
  const hint = card.querySelector(".structure-confirm-actions-hint");
  if (hint) {
    hint.textContent =
      editing || !savedOk
        ? dirty || editing
          ? "请先保存修改后再确认"
          : "请先「保存」后再确认。"
        : "确认后将按当前表格内容进行正式计价。";
  }
}

function captureStructureConfirmScrollSnapshot() {
  const snapshot = {
    listScrollTop: els.messageList?.scrollTop ?? 0,
    tableScrollByToken: {},
  };
  document.querySelectorAll(".structure-confirm-card[data-structure-card-token]").forEach((card) => {
    const tok = card.getAttribute("data-structure-card-token") || "";
    const wrap = card.querySelector(".structure-confirm-table-wrap");
    if (tok && wrap) {
      snapshot.tableScrollByToken[tok] = wrap.scrollTop;
    }
  });
  return snapshot;
}

function restoreStructureConfirmScrollSnapshot(snapshot) {
  if (!snapshot) {
    return;
  }
  window.requestAnimationFrame(() => {
    if (els.messageList && Number.isFinite(snapshot.listScrollTop)) {
      els.messageList.scrollTop = snapshot.listScrollTop;
    }
    for (const [tok, top] of Object.entries(snapshot.tableScrollByToken || {})) {
      const card = findStructureConfirmationCard(tok);
      const wrap = card?.querySelector(".structure-confirm-table-wrap");
      if (wrap && Number.isFinite(top)) {
        wrap.scrollTop = top;
      }
    }
  });
}

function shouldPreserveStructureConfirmScroll() {
  const pend = state.pendingStructureConfirm;
  return Boolean(pend && pend.pendingScrollToNewRowIndex == null);
}

function scrollStructurePreviewRowIntoView(token, rowIndex, options = {}) {
  const { focus = false, highlight = false } = options;
  const card = findStructureConfirmationCard(token);
  if (!card) {
    return;
  }
  const idx = Number(rowIndex);
  if (Number.isNaN(idx)) {
    return;
  }
  const tr = card.querySelector(
    `tr.structure-confirm-data-row[data-structure-row-index="${idx}"]`,
  );
  if (!tr) {
    return;
  }
  const wrap = card.querySelector(".structure-confirm-table-wrap");
  if (wrap) {
    const trTop = tr.offsetTop;
    const trH = tr.offsetHeight;
    const wrapH = wrap.clientHeight;
    wrap.scrollTop = Math.max(0, trTop - wrapH / 2 + trH / 2);
  }
  if (highlight) {
    tr.classList.add("structure-confirm-data-row-new");
    window.setTimeout(() => tr.classList.remove("structure-confirm-data-row-new"), 1800);
  }
  if (focus) {
    const nameInput = tr.querySelector('[data-structure-field="name"]');
    if (nameInput && !nameInput.readOnly) {
      nameInput.focus({ preventScroll: true });
      if (typeof nameInput.select === "function") {
        nameInput.select();
      }
    }
  }
}

function focusStructurePreviewRow(token, rowIndex) {
  scrollStructurePreviewRowIntoView(token, rowIndex, { focus: true, highlight: true });
}

function syncStructurePreviewRowSelectionUi(token) {
  const card = findStructureConfirmationCard(token);
  const pend = state.pendingStructureConfirm;
  if (!card || !pend || pend.token !== token) {
    return;
  }
  const selectedIdx = pend.structureSelectedRowIndex;
  card.querySelectorAll(".structure-confirm-data-row[data-structure-row-select]").forEach((tr) => {
    const idx = Number.parseInt(tr.getAttribute("data-structure-row-index") || "", 10);
    const on = !Number.isNaN(idx) && selectedIdx === idx;
    tr.classList.toggle("structure-confirm-data-row-selected", on);
  });
  const deleteBtn = card.querySelector(".btn-structure-sc-delete");
  if (deleteBtn) {
    deleteBtn.disabled = selectedIdx == null;
  }
}

function renderStructureConfirmView(options = {}) {
  const pend = state.pendingStructureConfirm;
  const scrollToNewRow = pend?.pendingScrollToNewRowIndex != null;
  const afterScrollRowIndex = options.afterScrollRowIndex;

  renderMessages();

  if (scrollToNewRow) {
    return;
  }
  if (afterScrollRowIndex != null && pend?.token) {
    window.requestAnimationFrame(() => {
      scrollStructurePreviewRowIntoView(pend.token, afterScrollRowIndex, {
        focus: false,
        highlight: false,
      });
    });
  }
}

function afterStructureConfirmRender() {
  const pend = state.pendingStructureConfirm;
  if (!pend || pend.pendingScrollToNewRowIndex == null) {
    return;
  }
  const focusIdx = pend.pendingScrollToNewRowIndex;
  const tok = pend.token;
  pend.pendingScrollToNewRowIndex = null;
  window.requestAnimationFrame(() => {
    focusStructurePreviewRow(tok, focusIdx);
    syncStructureConfirmToolbarUi(tok);
  });
}

function findStructureConfirmationCard(tok) {
  const want = String(tok || "").trim();
  if (!want) {
    return null;
  }
  const cards = document.querySelectorAll(".structure-confirm-card[data-structure-card-token]");
  for (const c of cards) {
    if ((c.getAttribute("data-structure-card-token") || "") === want) {
      return c;
    }
  }
  return null;
}

function structurePreviewRowFieldFromDom(inp) {
  if (!inp) {
    return {};
  }
  const rowIdx = inp.getAttribute("data-structure-row-index");
  if (!rowIdx) {
    return {};
  }
  const field = String(inp.getAttribute("data-structure-field") || "").trim();
  if (!field || !["name", "spec", "usage", "unit_price", "calc_note"].includes(field)) {
    return {};
  }
  const raw = inp.value != null ? String(inp.value).trim() : "";
  return { rowIdx: String(Number.parseInt(rowIdx, 10)), field, raw };
}

function enterStructurePreviewEditMode(token) {
  const pend = state.pendingStructureConfirm;
  const tok = String(token || "").trim();
  if (!pend || pend.token !== tok) {
    addMessage("assistant", "结构确认已过期，请重新上传表格。");
    return;
  }
  pend.structureEditMode = true;
  pend.structureSavedForQuote = false;
  pend.structureDirty = false;
  renderStructureConfirmView();
  setComposerStatusLine("已进入编辑模式，修改后请先「保存」再开始报价", "warn");
}

function selectStructurePreviewRow(token, rowIndex) {
  const pend = state.pendingStructureConfirm;
  const tok = String(token || "").trim();
  const idx = Number.parseInt(rowIndex, 10);
  if (!pend || pend.token !== tok || Number.isNaN(idx)) {
    return;
  }
  if (!pend.structureEditMode) {
    return;
  }
  const key = String(idx);
  if (pend.structureDeletedRows && pend.structureDeletedRows[key]) {
    return;
  }
  pend.structureSelectedRowIndex = pend.structureSelectedRowIndex === idx ? null : idx;
  syncStructurePreviewRowSelectionUi(tok);
  if (pend.structureSelectedRowIndex != null) {
    setComposerStatusLine("已选中一行，点击上方「删除」可移除无效数据", "warn");
  }
}

function deleteSelectedStructurePreviewRow(token) {
  const pend = state.pendingStructureConfirm;
  const tok = String(token || "").trim();
  if (!pend || pend.token !== tok) {
    addMessage("assistant", "结构确认已过期，请重新上传表格。");
    return;
  }
  const idx = pend.structureSelectedRowIndex;
  if (idx == null || Number.isNaN(Number(idx))) {
    setComposerStatusLine("请先点击要删除的物料行", "warn");
    return;
  }
  pend.structureSelectedRowIndex = null;
  deleteStructurePreviewRow(tok, idx);
}

function deleteStructurePreviewRow(token, rowIndex) {
  const pend = state.pendingStructureConfirm;
  const tok = String(token || "").trim();
  const idx = Number.parseInt(rowIndex, 10);
  if (!pend || pend.token !== tok || Number.isNaN(idx)) {
    addMessage("assistant", "结构确认已过期，请重新上传表格。");
    return;
  }
  if (!pend.structureEditMode) {
    pend.structureEditMode = true;
  }
  const rows = getPendingStructureRows(pend.data, pend);
  const overridesBefore =
    pend.structureRowOverrides && typeof pend.structureRowOverrides === "object"
      ? pend.structureRowOverrides
      : {};
  const targetRow = mergedStructureConfirmationRow(rows, overridesBefore, idx);
  const gapHintId = String(targetRow?.structure_gap_hint_id || "").trim();
  if (gapHintId && targetRow?.from_structure_gap_hint) {
    ensurePendingStructureGapState(pend);
    delete pend.confirmedStructureGapIds[gapHintId];
    if (Array.isArray(pend.structureAddedRows)) {
      pend.structureAddedRows = pend.structureAddedRows.filter(
        (r) => String(r?.structure_gap_hint_id || "").trim() !== gapHintId,
      );
    }
  }
  const del = pend.structureDeletedRows && typeof pend.structureDeletedRows === "object" ? { ...pend.structureDeletedRows } : {};
  del[String(idx)] = true;
  pend.structureDeletedRows = del;
  const overrides = { ...overridesBefore };
  overrides[String(idx)] = { ...(overrides[String(idx)] || {}), deleted: true };
  pend.structureRowOverrides = overrides;
  pend.structureSavedForQuote = false;
  pend.structureDirty = true;
  const rowsBefore = getPendingStructureRows(pend.data, pend).length;
  const scrollTarget = Math.max(0, Math.min(idx, rowsBefore - 2));
  renderStructureConfirmView({ afterScrollRowIndex: scrollTarget });
  setComposerStatusLine("已删除该行，请点击「保存」后再开始报价", "warn");
}

function addStructurePreviewRow(token) {
  const pend = state.pendingStructureConfirm;
  const tok = String(token || "").trim();
  if (!pend || pend.token !== tok) {
    addMessage("assistant", "结构确认已过期，请重新上传表格。");
    return;
  }
  if (!pend.structureEditMode) {
    pend.structureEditMode = true;
  }
  const rows = getPendingStructureRows(pend.data, pend);
  let insertAt = rows.length;
  const sel = pend.structureSelectedRowIndex;
  if (sel != null && !Number.isNaN(Number(sel))) {
    insertAt = Number(sel) + 1;
  }
  insertAt = Math.max(0, Math.min(insertAt, rows.length));
  shiftStructureRowIndicesUp(pend, insertAt);
  const row = {
    index: insertAt,
    name: "",
    spec: "-",
    usage: "",
    unit_price: "",
    amount: "",
    calc_note: "",
    calc_method: "",
    added: true,
  };
  const added = Array.isArray(pend.structureAddedRows) ? pend.structureAddedRows.slice() : [];
  added.push(row);
  pend.structureAddedRows = added;
  pend.structureSavedForQuote = false;
  pend.structureDirty = true;
  pend.structureSelectedRowIndex = insertAt;
  pend.pendingScrollToNewRowIndex = insertAt;
  renderStructureConfirmView();
  setComposerStatusLine("已新增一行，请填写物料、用量和单价后保存。", "warn");
}

function saveStructurePreviewEdits(token) {
  const pend = state.pendingStructureConfirm;
  const tok = String(token || "").trim();
  if (!pend || pend.token !== tok) {
    addMessage("assistant", "结构确认已过期，请重新上传表格。");
    return;
  }
  const card = findStructureConfirmationCard(tok);
  if (!card) {
    renderStructureConfirmView();
    return;
  }
  const nextOverrides = pend.structureRowOverrides && typeof pend.structureRowOverrides === "object" ? { ...pend.structureRowOverrides } : {};
  if (pend.structureDeletedRows && typeof pend.structureDeletedRows === "object") {
    for (const [idx, deleted] of Object.entries(pend.structureDeletedRows)) {
      if (!deleted) {
        continue;
      }
      if (!nextOverrides[idx]) {
        nextOverrides[idx] = {};
      }
      nextOverrides[idx].deleted = true;
    }
  }
  const inputs = card.querySelectorAll("[data-structure-row-field]");
  for (const el of inputs) {
    const { rowIdx, field, raw } = structurePreviewRowFieldFromDom(el);
    if (rowIdx == null || field == null || Number.isNaN(Number(rowIdx))) {
      continue;
    }
    if (!nextOverrides[rowIdx]) {
      nextOverrides[rowIdx] = {};
    }
    nextOverrides[rowIdx][field] = raw;
  }
  pend.structureRowOverrides = nextOverrides;
  pend.structureEditMode = false;
  pend.structureSavedForQuote = true;
  pend.structureDirty = false;
  pend.structureSelectedRowIndex = null;
  renderStructureConfirmView();
  setComposerStatusLine("明细已保存，可点击「确认结构并开始报价」", "ok");
}

function buildStructureConfirmationItemsForQuote(pending) {
  const data = pending?.data || {};
  const rows = getPendingStructureRows(data, pending);
  const overrides =
    pending && pending.structureRowOverrides && typeof pending.structureRowOverrides === "object"
      ? pending.structureRowOverrides
      : {};
  if (!rows.length) {
    return [];
  }
  return rows.map((baseRow, idx) => {
    const merged =
      mergedStructureConfirmationRow(rows, overrides, idx) ||
      (baseRow && typeof baseRow === "object" ? baseRow : {});
    const calcTxt = merged.calc_note != null ? merged.calc_note : merged.calc_method != null ? merged.calc_method : "";
    const patch = {
      index: idx,
      name: String(merged.name != null ? merged.name : "").trim(),
      spec: String(merged.spec != null ? merged.spec : "").trim(),
      usage: String(merged.usage != null ? merged.usage : "").trim(),
      unit_price: String(merged.unit_price != null ? merged.unit_price : "").trim(),
      calc_note: String(calcTxt || "").trim(),
      calc_method: String(calcTxt || "").trim(),
    };
    if (merged.from_structure_gap_hint) {
      patch.from_structure_gap_hint = true;
      patch.confirmation_source = "structure_confirmed";
      patch.source = "structure_confirmed";
      const hid = String(merged.structure_gap_hint_id || "").trim();
      if (hid) {
        patch.structure_gap_hint_id = hid;
      }
      const readyForCost = structureGapRowHasPricing(merged);
      const aiEstimated = structureGapRowHasAiEstimate(merged);
      patch.exclude_from_cost = !readyForCost;
      patch.amount_in_cost = readyForCost;
      if (aiEstimated) {
        patch.usage_ai = Boolean(merged.usage_ai);
        patch.unit_price_ai = Boolean(merged.unit_price_ai);
        patch.amount_ai = Boolean(merged.amount_ai);
        patch.pricing_review_required = true;
        patch.recognition_status = "candidate_review";
        patch.recognition_reason = String(merged.recognition_reason || "AI估算用量/单价，待管理员复核").trim();
        patch.source = "ai";
      }
    }
    if (merged.deleted === true) {
      patch.deleted = true;
    }
    // 结构确认表无小计列：勿把模型旧 amount 带给正式报价，避免只改单价仍按旧小计核算
    return patch;
  });
}

function ensurePendingStructureGapState(pend) {
  if (!pend) {
    return;
  }
  if (!pend.confirmedStructureGapIds || typeof pend.confirmedStructureGapIds !== "object") {
    pend.confirmedStructureGapIds = {};
  }
}

function isMissingStructureQuoteField(value) {
  const text = String(value ?? "").trim().toLowerCase();
  return !text || text === "-" || text === "—" || text === "无" || text === "空";
}

function structureGapRowHasPricing(row) {
  if (!row || typeof row !== "object") {
    return false;
  }
  const usage = String(row.usage ?? "").trim();
  const unitPrice = String(row.unit_price ?? "").trim();
  return !isMissingStructureQuoteField(usage) && !isMissingStructureQuoteField(unitPrice);
}

function structureGapRowHasAiEstimate(row) {
  if (!row || typeof row !== "object") {
    return false;
  }
  const hasAiFlag = Boolean(row.usage_ai || row.unit_price_ai || row.amount_ai || row.pricing_review_required);
  return hasAiFlag && structureGapRowHasPricing(row);
}

function estimateStructureGapRowLocally(row) {
  const out = { ...(row || {}) };
  const blob = `${String(out.name || "")} ${String(out.calc_note || "")} ${String(out.role || "")}`.toLowerCase();
  let usage = String(out.usage || "").trim();
  if (isMissingStructureQuoteField(usage)) {
    if (/丝印|烫印|热转|印刷|刺绣|logo/.test(blob)) {
      out.usage = "1处";
      out.usage_ai = true;
    } else if (/车缝|缝纫|加工|工艺费/.test(blob)) {
      out.usage = "1道工序";
      out.usage_ai = true;
    } else if (/织带|webbing|包边/.test(blob)) {
      out.usage = "1条";
      out.usage_ai = true;
    } else {
      out.usage = "1处";
      out.usage_ai = true;
    }
  }
  let unitPrice = String(out.unit_price || "").trim();
  if (isMissingStructureQuoteField(unitPrice)) {
    if (/丝印|烫印|热转|印刷|刺绣|logo/.test(blob)) {
      out.unit_price = "4元/处";
      out.unit_price_ai = true;
    } else if (/车缝|缝纫|加工|工艺费/.test(blob)) {
      out.unit_price = "3元/处";
      out.unit_price_ai = true;
    } else if (/织带|webbing/.test(blob)) {
      out.unit_price = "1.5元/条";
      out.unit_price_ai = true;
    } else if (/插扣|d扣|扣具|buckle/.test(blob)) {
      out.unit_price = "0.6元/个";
      out.unit_price_ai = true;
    }
  }
  if (structureGapRowHasPricing(out)) {
    out.exclude_from_cost = false;
    out.amount_in_cost = true;
    out.structure_gap_pending_pricing = false;
    out.needs_manual_confirm = true;
    out.pricing_review_required = true;
    out.recognition_reason = "AI估算用量/单价，待管理员复核";
    const note = "AI估算价，待管理员复核";
    const cn = String(out.calc_note || "").trim();
    out.calc_note = cn && !cn.includes(note) ? `${cn}；${note}` : cn || note;
    out.source = "ai";
  }
  return out;
}

function structureGapCategoryToRole(category) {
  const text = String(category || "").trim();
  const map = {
    主料: "外料",
    里料: "里料",
    辅料: "辅料",
    织带: "织带",
    五金: "五金",
    "工艺/人工": "工艺费",
    海绵: "辅料",
    网布: "辅料",
    PE板: "辅料",
    皮革: "辅料",
    加固片: "辅料",
    包边带: "织带",
    车缝工艺: "工艺费",
    贴合或车缝工艺: "工艺费",
    "贴合/车缝工艺": "工艺费",
  };
  return map[text] || "辅料";
}

function buildStructureGapBomName(hint) {
  const label = String(hint?.detected_text || hint?.name || "结构缺项").trim();
  const candidates = Array.isArray(hint?.category_candidates)
    ? hint.category_candidates.map((c) => String(c || "").trim()).filter(Boolean)
    : [];
  const confidence = Number(hint?.category_confidence || 0);
  const processLabels = new Set([
    "工艺/人工",
    "车缝工艺",
    "贴合或车缝工艺",
    "贴合/车缝工艺",
  ]);
  const abstractLabels = new Set(["主料", "辅料", "五金", "工艺/人工"]);
  if (confidence < 0.75 || !candidates.length) {
    return label;
  }
  let materialHints = candidates.filter((c) => !processLabels.has(c) && !abstractLabels.has(c));
  if (!materialHints.length) {
    materialHints = candidates.filter((c) => !processLabels.has(c));
  }
  if (materialHints.length >= 2) {
    return `${label}-${materialHints[0]}/${materialHints[1]}`;
  }
  if (materialHints.length === 1) {
    return `${label}-${materialHints[0]}`;
  }
  return label;
}

function buildStructureGapBomCalcNote(hint) {
  const direction = String(hint?.suggested_direction || "").trim();
  const categoryDisplay = String(hint?.category_hint_display || "").trim();
  const parts = ["结构确认缺项"];
  if (categoryDisplay) {
    parts.push(categoryDisplay);
  }
  if (direction) {
    parts.push(`确认方向：${direction}`);
  }
  return parts.join("；");
}

function buildStructureGapRowFromHint(hint) {
  const suggestedCategory = String(hint?.suggested_category || "").trim();
  const hid = String(hint?.id || "").trim();
  const calcNote = buildStructureGapBomCalcNote(hint);
  return {
    name: buildStructureGapBomName(hint),
    role: structureGapCategoryToRole(suggestedCategory),
    spec: "-",
    usage: "-",
    unit_price: "-",
    amount: 0,
    calc_note: calcNote,
    calc_method: calcNote,
    suggested_category: suggestedCategory,
    category_candidates: Array.isArray(hint?.category_candidates) ? hint.category_candidates.slice() : [],
    material_category_hint: String(hint?.material_category_hint || ""),
    category_hint_display: String(hint?.category_hint_display || ""),
    category_needs_confirmation: Boolean(hint?.category_needs_confirmation),
    confirmation_source: "structure_confirmed",
    from_structure_gap_hint: true,
    structure_gap_hint_id: hid,
    source: "structure_confirmed",
    exclude_from_cost: true,
    amount_in_cost: false,
    needs_manual_confirm: true,
    recognition_status: "candidate_review",
    recognition_reason: "结构缺项，待补用量/单价，暂不参与金额",
    added: true,
    structure_gap_pending_pricing: true,
  };
}

function syncStructureGapRowsFromSelection(pend) {
  if (!pend) {
    return { added: 0, removed: 0 };
  }
  ensurePendingStructureGapState(pend);
  const hints = getUncoveredStructureGapHints(pend);
  const hintById = Object.fromEntries(
    hints.map((h) => [String(h.id || "").trim(), h]).filter(([id]) => Boolean(id)),
  );
  const confirmedIds = new Set(getConfirmedStructureGapIdList(pend));
  const added = Array.isArray(pend.structureAddedRows) ? pend.structureAddedRows.slice() : [];
  const manualRows = added.filter((r) => !r?.from_structure_gap_hint || !String(r.structure_gap_hint_id || "").trim());
  const keptGapRows = added.filter((r) => {
    const hid = String(r?.structure_gap_hint_id || "").trim();
    return Boolean(r?.from_structure_gap_hint && hid && confirmedIds.has(hid));
  });
  const keptIds = new Set(keptGapRows.map((r) => String(r.structure_gap_hint_id || "").trim()));
  const newGapRows = [];
  for (const hid of confirmedIds) {
    if (keptIds.has(hid)) {
      continue;
    }
    const hint = hintById[hid];
    if (!hint) {
      continue;
    }
    newGapRows.push(estimateStructureGapRowLocally(buildStructureGapRowFromHint(hint)));
  }
  const removed = added.length - manualRows.length - keptGapRows.length;
  pend.structureAddedRows = [...manualRows, ...keptGapRows, ...newGapRows];
  return { added: newGapRows.length, removed: Math.max(0, removed) };
}

function getIncompleteStructureGapRows(pend) {
  if (!pend) {
    return [];
  }
  const rows = getPendingStructureRows(pend.data, pend);
  const overrides =
    pend.structureRowOverrides && typeof pend.structureRowOverrides === "object"
      ? pend.structureRowOverrides
      : {};
  const incomplete = [];
  rows.forEach((baseRow, idx) => {
    const merged = mergedStructureConfirmationRow(rows, overrides, idx);
    if (merged.deleted === true) {
      return;
    }
    if (!merged.from_structure_gap_hint) {
      return;
    }
    if (!structureGapRowHasPricing(merged) && !structureGapRowHasAiEstimate(merged)) {
      incomplete.push({
        index: idx,
        name: String(merged.name || "").trim() || `第${idx + 1}行`,
        hintId: String(merged.structure_gap_hint_id || "").trim(),
      });
    }
  });
  return incomplete;
}

function countStructureGapAiEstimateRows(pend) {
  if (!pend) {
    return 0;
  }
  const rows = getPendingStructureRows(pend.data, pend);
  const overrides =
    pend.structureRowOverrides && typeof pend.structureRowOverrides === "object"
      ? pend.structureRowOverrides
      : {};
  let count = 0;
  rows.forEach((_, idx) => {
    const merged = mergedStructureConfirmationRow(rows, overrides, idx);
    if (merged.deleted === true || !merged.from_structure_gap_hint) {
      return;
    }
    if (structureGapRowHasAiEstimate(merged)) {
      count += 1;
    }
  });
  return count;
}

function buildStructureConfirmActionsHint(pend, { editing, savedOk, dirty }) {
  if (editing || !savedOk) {
    return dirty || editing ? "请先保存修改后再确认" : "请先「保存」后再确认。";
  }
  const incompleteGaps = getIncompleteStructureGapRows(pend);
  if (incompleteGaps.length > 0) {
    return "仍有缺项未能自动估算，请补充用量/单价或取消勾选后再报价。";
  }
  const aiEstimateCount = countStructureGapAiEstimateRows(pend);
  const confirmedGapCount = getConfirmedStructureGapIdList(pend).length;
  if (aiEstimateCount > 0) {
    return `有 ${aiEstimateCount} 项缺项已用 AI 市场参考价估算，可继续报价；结果将标记「待管理员复核」。`;
  }
  if (confirmedGapCount > 0) {
    return `已加入 ${confirmedGapCount} 项结构缺项到明细表，保存后可生成正式报价。`;
  }
  return "确认后将按当前表格内容进行正式计价；未勾选的缺项仅作风险提示。";
}

function getUncoveredStructureGapHints(pend) {
  const hints = Array.isArray(pend?.data?.structure_gap_hints) ? pend.data.structure_gap_hints : [];
  return hints.filter((h) => h && typeof h === "object" && h.bom_covered !== true);
}

function getConfirmedStructureGapIdList(pend) {
  if (!pend) {
    return [];
  }
  ensurePendingStructureGapState(pend);
  const uncoveredIds = new Set(
    getUncoveredStructureGapHints(pend)
      .map((h) => String(h.id || "").trim())
      .filter(Boolean),
  );
  return Object.entries(pend.confirmedStructureGapIds)
    .filter(([id, on]) => Boolean(on) && uncoveredIds.has(String(id).trim()))
    .map(([id]) => String(id).trim());
}

function toggleStructureGapConfirm(token, hintId, checked) {
  const pend = state.pendingStructureConfirm;
  const tok = String(token || "").trim();
  const hid = String(hintId || "").trim();
  if (!pend || pend.token !== tok || !hid) {
    return;
  }
  ensurePendingStructureGapState(pend);
  if (checked) {
    pend.confirmedStructureGapIds[hid] = true;
  } else {
    delete pend.confirmedStructureGapIds[hid];
  }
  const syncMeta = syncStructureGapRowsFromSelection(pend);
  if (checked && syncMeta.added > 0) {
    pend.structureEditMode = true;
    pend.structureSavedForQuote = false;
    pend.structureDirty = true;
    const rows = getPendingStructureRows(pend.data, pend);
    const idx = rows.findIndex((r) => String(r?.structure_gap_hint_id || "").trim() === hid);
    if (idx >= 0) {
      pend.pendingScrollToNewRowIndex = idx;
    }
    setComposerStatusLine("缺项已加入明细表，系统已尝试 AI 估算；请核对后点击「保存」。", "ok");
  } else if (!checked && syncMeta.removed > 0) {
    if (!pend.structureEditMode) {
      pend.structureSavedForQuote = true;
      pend.structureDirty = false;
    }
    setComposerStatusLine("已从结构/明细预览表移除对应缺项行。", "ok");
  }
  renderStructureConfirmView();
}

function buildStructureGapHintsHtml(gapHints, opts = {}) {
  const hints = Array.isArray(gapHints) ? gapHints.filter((h) => h && typeof h === "object") : [];
  if (!hints.length) return "";
  const compact = Boolean(opts.compact);
  const interactive = Boolean(opts.interactive) && !compact;
  const token = String(opts.token || "").trim();
  const selectedIds =
    opts.selectedIds && typeof opts.selectedIds === "object" ? opts.selectedIds : {};
  const rows = hints
    .map((h) => {
      const hintId = String(h.id || "").trim();
      const detected = escapeHtml(String(h.detected_text || h.name || "-"));
      const notice = escapeHtml(String(h.user_notice || h.reason || ""));
      const covered = h.bom_covered === true;
      const badge = covered
        ? `<span class="structure-gap-badge structure-gap-badge--ok">已覆盖</span>`
        : `<span class="structure-gap-badge structure-gap-badge--warn">待确认</span>`;
      const costImpact = h.cost_impact_reason
        ? `<div class="structure-gap-impact muted">成本影响：${escapeHtml(String(h.cost_impact_reason))}</div>`
        : "";
      const direction = h.suggested_direction
        ? `<div class="structure-gap-direction muted">确认后方向：${escapeHtml(String(h.suggested_direction))}</div>`
        : "";
      const categoryDisplay = String(h.category_hint_display || "").trim();
      const categoryHtml = categoryDisplay
        ? `<div class="structure-gap-category${h.category_needs_confirmation ? " structure-gap-category--uncertain" : ""}">${escapeHtml(categoryDisplay)}</div>`
        : "";
      const participates = covered || h.participates_in_cost === true ? "已参与报价" : "未参与报价";
      let controlHtml = "";
      if (interactive && hintId) {
        if (covered) {
          controlHtml = `<div class="structure-gap-covered-note muted">BOM 可能已覆盖此项，请核对是否完整；无需重复加入。</div>`;
        } else {
          const checked = Boolean(selectedIds[hintId]);
          controlHtml = `<label class="structure-gap-confirm-label">
            <input type="checkbox" class="structure-gap-confirm-checkbox"
              data-structure-gap-confirm="${escapeHtml(token)}"
              data-structure-gap-id="${escapeHtml(hintId)}"
              ${checked ? " checked" : ""} />
            <span class="structure-gap-confirm-text">加入正式 BOM</span>
            <span class="muted structure-gap-confirm-hint">勾选后立即出现在结构/明细预览表，请补充用量/单价后保存</span>
          </label>`;
        }
      }
      return `<li class="structure-gap-item${covered ? " structure-gap-item--covered" : ""}" data-structure-gap-id="${escapeHtml(hintId)}">
        <div class="structure-gap-head"><strong>${detected}</strong> ${badge} <span class="muted structure-gap-participates">${escapeHtml(participates)}</span></div>
        <div class="structure-gap-notice">${notice}</div>
        ${costImpact}
        ${categoryHtml}
        ${direction}
        ${controlHtml}
      </li>`;
    })
    .join("");
  const title = compact ? "结构缺项提示" : "AI 结构缺项识别（默认不自动计价）";
  let lead = "";
  if (!compact) {
    lead = interactive
      ? `<p class="muted structure-gap-lead">以下项来自结构说明/备注，<strong>默认不勾选、不参与报价</strong>。勾选「加入正式 BOM」后会<strong>立即追加到上方明细表</strong>，请补充用量/单价并保存。</p>`
      : `<p class="muted structure-gap-lead">以下项来自结构说明/备注，系统仅提示风险；确认补项后才会进入正式 BOM。</p>`;
  }
  return `<section class="structure-gap-panel${compact ? " structure-gap-panel--compact" : " structure-gap-panel--interactive"}">
    <h4>${escapeHtml(title)}</h4>
    ${lead}
    <ul class="structure-gap-list">${rows}</ul>
  </section>`;
}

function buildAnomalyReviewHintsHtml(anomalyHints) {
  const hints = Array.isArray(anomalyHints) ? anomalyHints.filter((h) => h && h.user_notice) : [];
  if (!hints.length) return "";
  const rows = hints.map((h) => `<li>${escapeHtml(String(h.user_notice))}</li>`).join("");
  return `<section class="anomaly-review-panel">
    <h4>人工复核提醒</h4>
    <ul class="anomaly-review-list">${rows}</ul>
  </section>`;
}

function buildStructureChecklistConfirmPreviewHtml(data, token, pend) {
  const gapHtml = buildStructureGapHintsHtml(data?.structure_gap_hints, {
    interactive: true,
    token: String(token || "").trim(),
    selectedIds: pend?.confirmedStructureGapIds || {},
  });
  if (gapHtml) return gapHtml;
  // The editable structure/material preview already shows the actionable rows.
  // Avoid duplicating a second structure checklist block before quote generation.
  return "";
  const checklist = data?.structure_checklist;
  const items = Array.isArray(checklist?.items) ? checklist.items : [];
  if (!checklist?.is_bag_product || !items.length) {
    return "";
  }
  const sorted = [...items].sort((a, b) => {
    const ra = STRUCTURE_RISK_ORDER[String(a?.risk_level || "low")] ?? 9;
    const rb = STRUCTURE_RISK_ORDER[String(b?.risk_level || "low")] ?? 9;
    return ra !== rb ? ra - rb : String(a?.name || "").localeCompare(String(b?.name || ""), "zh-CN");
  });
  const rows = sorted
    .map((item) => {
      const st = structureItemDisplayStatus(item);
      const costN = Array.isArray(item.cost_item_ids) ? item.cost_item_ids.length : 0;
      return `<li class="structure-cl-confirm-item structure-cl-item--${escapeHtml(st.tone)}">
        <strong>${escapeHtml(item.name || "-")}</strong>
        <span class="structure-cl-badge structure-cl-badge--${escapeHtml(st.tone)}">${escapeHtml(st.label)}</span>
        <span class="muted">${escapeHtml(item.category_label || item.category || "")}</span>
        ${costN ? `<span class="muted"> · 已关联 ${costN} 成本行</span>` : `<span class="structure-cl-leak"> · 待补成本</span>`}
        ${item.risk_reason ? `<div class="structure-cl-risk">${escapeHtml(String(item.risk_reason))}</div>` : ""}
      </li>`;
    })
    .join("");
  const leakN = Array.isArray(checklist.extraction_leaks) ? checklist.extraction_leaks.length : 0;
  return `
    <section class="structure-confirm-section structure-cl-confirm-section">
      <h4>识别结构清单（包类 skill 提取）</h4>
      <p class="muted structure-cl-confirm-lead">报价前已从结构说明提取以下结构件；确认明细后正式报价须覆盖每一项。</p>
      ${leakN ? `<p class="structure-cl-recalc-hint">提取警告：${leakN} 个结构词可能漏提取，请核对。</p>` : ""}
      <ul class="structure-cl-list structure-cl-confirm-list">${rows}</ul>
    </section>`;
}

function buildStructureConfirmationHtml(data, token) {
  const pend = state.pendingStructureConfirm;
  const tok = String(token || "").trim();
  const isPending = pend && pend.token === tok;
  const rows = getPendingStructureRows(data, isPending ? pend : null);
  const editing = isPending ? Boolean(pend.structureEditMode) : false;
  const savedOk = isPending ? Boolean(pend.structureSavedForQuote) : true;
  const dirty = isPending ? Boolean(pend.structureDirty) : false;
  const overrides =
    isPending && pend.structureRowOverrides && typeof pend.structureRowOverrides === "object"
      ? pend.structureRowOverrides
      : {};
  const selectedIdx =
    isPending && editing && pend.structureSelectedRowIndex != null ? Number(pend.structureSelectedRowIndex) : null;

  const roAttr = editing ? "" : " readonly";

  const body = rows
    .map((r, i) => {
      const mr = mergedStructureConfirmationRow(rows, overrides, i);
      if (mr.deleted === true) {
        return "";
      }
      const nm = mr.name != null ? String(mr.name) : "";
      const sp = mr.spec != null ? String(mr.spec) : "";
      const us = mr.usage != null ? String(mr.usage) : "";
      const up = mr.unit_price != null ? String(mr.unit_price) : "";
      const calcTxt = mr.calc_note != null ? mr.calc_note : mr.calc_method != null ? mr.calc_method : "";
      const recStatus = String(mr.recognition_status || "").trim();
      const gapPending =
        mr.from_structure_gap_hint && structureGapRowHasAiEstimate(mr)
          ? `<span class="material-recognition-badge candidate_review structure-gap-row-badge structure-gap-row-badge--ai" title="AI估算用量/单价，可继续报价，待管理员复核">AI估算待复核</span>`
          : mr.from_structure_gap_hint && !structureGapRowHasPricing(mr)
            ? `<span class="material-recognition-badge candidate_review structure-gap-row-badge" title="未能自动估算，请补充用量/单价">待补用量/单价</span>`
            : "";
      const recBadge = gapPending || buildMaterialRecognitionBadge(mr);
      const recReason = String(mr.recognition_reason || "").trim();
      const recReasonHtml = recReason
        ? `<span class="structure-recognition-reason">${escapeHtml(recReason)}</span>`
        : "";
      const ignoredCls = recStatus === "ignored" ? " structure-confirm-data-row-ignored" : "";
      const selectedCls = selectedIdx === i ? " structure-confirm-data-row-selected" : "";
      const editingCls = editing ? " structure-confirm-data-row-editable" : "";
      const rowDeleteBtn = editing
        ? `<button type="button" class="btn-structure-row-delete" data-structure-row-delete="${escapeHtml(tok)}" data-structure-row-index="${i}" title="删除这一行，不参与报价" aria-label="删除这一行">×</button>`
        : "";
      const rowTitle = editing ? ' title="点击选中此行，再用上方「删除」移除"' : "";
      const gapRowCls = mr.from_structure_gap_hint ? " structure-confirm-data-row-gap" : "";
      return `<tr class="structure-confirm-data-row${gapRowCls}${editingCls}${selectedCls}${ignoredCls}" data-structure-row-select="${escapeHtml(tok)}" data-structure-row-index="${i}"${rowTitle}>
        <td class="structure-confirm-name-cell">
          <div class="structure-confirm-name-row">
            ${rowDeleteBtn}
            <input type="text" class="structure-confirm-cell-input" name="name-${i}" autocomplete="off" data-structure-field="name" data-structure-row-field data-structure-row-index="${i}"
              value="${escapeHtml(nm)}"${roAttr} placeholder="物料名称" />
          </div>
        </td>
        <td class="structure-recognition-cell">${recBadge}${recReasonHtml}</td>
        <td>
          <div class="structure-confirm-spec-grid">
            <div class="structure-confirm-field-line">
              <span class="structure-confirm-mute-k">规格</span>
              <input type="text" class="structure-confirm-cell-input" name="spec-${i}" autocomplete="off" data-structure-field="spec" data-structure-row-field data-structure-row-index="${i}"
                value="${escapeHtml(sp)}"${roAttr} />
            </div>
            <div class="structure-confirm-field-line">
              <span class="structure-confirm-mute-k">用量</span>
              <input type="text" class="structure-confirm-cell-input" name="usage-${i}" autocomplete="off" data-structure-field="usage" data-structure-row-field data-structure-row-index="${i}"
                value="${escapeHtml(us)}"${roAttr} />
            </div>
          </div>
        </td>
        <td>
          <input type="text" class="structure-confirm-cell-input" name="unit_price-${i}" autocomplete="off" data-structure-field="unit_price" data-structure-row-field data-structure-row-index="${i}"
            value="${escapeHtml(up)}"${roAttr} />
        </td>
        <td class="structure-confirm-calc-cell">
          <textarea class="structure-confirm-cell-textarea" name="calc_note-${i}" rows="2" autocomplete="off" data-structure-field="calc_note" data-structure-row-field data-structure-row-index="${i}"
            ${editing ? "" : "readonly"}>${escapeHtml(calcTxt)}</textarea>
        </td>
      </tr>`;
    })
    .join("");

  const confirmDisabled = editing || !savedOk ? " disabled" : "";
  const saveDisabled = editing ? "" : " disabled";
  const saveBtnClass = editing ? (dirty ? " btn-structure-sc-save-ready" : " btn-structure-sc-save-idle") : "";
  const deleteDisabled = editing && selectedIdx != null ? "" : " disabled";
  const confirmHint = isPending
    ? buildStructureConfirmActionsHint(pend, { editing, savedOk, dirty })
    : "确认后将按当前表格内容进行正式计价；未勾选的缺项仅作风险提示。";
  const activeRowCount = rows.filter((_, i) => {
    const mr = mergedStructureConfirmationRow(rows, overrides, i);
    return mr.deleted !== true && String(mr.recognition_status || "").trim() !== "ignored";
  }).length;

  return `
    <div class="structure-confirm-card" data-structure-card-token="${escapeHtml(tok)}">
      <p class="assistant-tag">结构确认</p>
      <h3>${escapeHtml(data.title || "结构确认后再报价")}</h3>
      <p class="structure-confirm-lead">系统已解析表格结构，但还没有跑正式最终报价。请先确认下面的产品结构、用量、单价和计算方式。</p>
      <div class="structure-confirm-summary">
        <div><span>文件</span><strong>${escapeHtml(data.file_name || "上传表格")}</strong></div>
        <div><span>产品</span><strong>${escapeHtml(data.product_name || "-")}</strong></div>
        <div><span>物料行</span><strong>${escapeHtml(String(activeRowCount || rows.length || data.item_count || 0))}</strong></div>
      </div>
      ${buildStructureChecklistConfirmPreviewHtml(data, tok, isPending ? pend : null)}
      <section class="structure-confirm-section structure-confirm-workspace">
        <div class="structure-confirm-edit-shell">
          <div class="structure-confirm-toolbar-sticky">
            <div class="structure-confirm-section-head structure-confirm-toolbar">
              <h4>结构/明细预览</h4>
              <div class="structure-confirm-toolbar-actions">
                <button type="button" class="btn-structure-sc-add" data-structure-sc-add="${escapeHtml(tok)}">添加一行</button>
                <button type="button" class="btn-structure-sc-edit" data-structure-sc-edit="${escapeHtml(tok)}"${editing ? " disabled" : ""}>编辑</button>
                <button type="button" class="btn-structure-sc-save${saveBtnClass}" data-structure-sc-save="${escapeHtml(tok)}"${saveDisabled}>保存</button>
                <button type="button" class="btn-structure-sc-delete" data-structure-sc-delete="${escapeHtml(tok)}"${deleteDisabled} title="先点击表格中的物料行选中，再删除">删除</button>
              </div>
            </div>
            <p class="structure-confirm-edit-hint muted">
              ${editing
                ? "正在编辑：<strong>修改或删除后请先点「保存」</strong>，再确认报价。"
                : "要修改字段或删除物料行，请先点「编辑」。"
              }
            </p>
          </div>
          <div class="table-wrap structure-confirm-table-wrap">
            <table class="structure-confirm-table">
              <thead><tr><th>物料</th><th>识别状态</th><th>规格 / 用量</th><th>单价</th><th>计算方式</th></tr></thead>
              <tbody>${body || `<tr><td colspan="5">未解析到可展示物料行</td></tr>`}</tbody>
            </table>
          </div>
          <div class="structure-confirm-actions structure-confirm-actions-sticky">
            <button type="button" class="btn-structure-confirm"${confirmDisabled}
              data-structure-confirm-token="${escapeHtml(tok)}"
              ${!savedOk || editing ? ' title="请先保存明细修改"' : ''}>
              确认结构并开始报价
            </button>
            <span class="muted structure-confirm-actions-hint">${confirmHint}</span>
          </div>
        </div>
      </section>
    </div>
  `;
}

function renderMessagesOnly() {
  const snap = shouldPreserveStructureConfirmScroll() ? captureStructureConfirmScrollSnapshot() : null;
  els.chatMessages.innerHTML = state.messages.map(renderMessageCard).join("");
  if (snap) {
    restoreStructureConfirmScrollSnapshot(snap);
  }
}

function renderMessages() {
  renderMessagesOnly();
  afterStructureConfirmRender();
  if (collectQuoteCardMessages().length) {
    scheduleQuoteCardsApprovalRefresh("render");
  }
}

function renderMessageCard(message) {
  const timeHtml = message.time
    ? `<time class="msg-meta-time">${escapeHtml(message.time)}</time>`
    : "";

  if (message.role === "user") {
    const textBlock = String(message.text || "").trim()
      ? `<p class="user-msg-text">${escapeHtml(message.text || "").replaceAll("\n", "<br />")}</p>`
      : `<p class="user-msg-text muted">（未输入文字）</p>`;
    const av = Array.isArray(message.attachmentViews) ? message.attachmentViews : [];
    const chips =
      av.length > 0
        ? `<div class="user-attachments" aria-label="附件">${av
            .map((v) => {
              const nm = escapeHtml(v.name || "");
              const sz = escapeHtml(v.sizeLabel || "");
              if (v.kind === "image" && v.thumbUrl) {
                const u = escapeAttrSafe(v.thumbUrl);
                return `<div class="user-att user-att-img">
                  <img src="${u}" alt="" loading="lazy"/>
                  <span class="user-att-cap muted">${nm} · ${sz}</span>
                </div>`;
              }
              return `<div class="user-att user-att-sheet"><span class="user-att-chip">${nm}</span><span class="muted">${sz}</span></div>`;
            })
            .join("")}</div>`
        : "";
    return `
      <article class="message user">
        <div class="bubble user-bubble user-bubble-rich">
          ${chips}
          ${textBlock}
          ${timeHtml ? `<span class="user-msg-time">${timeHtml}</span>` : ""}
        </div>
        <div class="avatar user-avatar">用户</div>
      </article>
    `;
  }

  if (message.type === "loading_quote") {
    return `
      <article class="message assistant loading-quote-msg">
        <div class="avatar assistant-avatar">栢博</div>
        <div class="bubble assistant-bubble typing-bubble">
          <span class="typing-label">${escapeHtml(message.text || "正在核算报价…")}</span>
          <span class="typing-dots" aria-hidden="true"><span></span><span></span><span></span></span>
        </div>
      </article>
    `;
  }

  if (message.type === "quote_card" && message.data) {
    const fn = String(message.fileName || "").trim();
    const isExtra = message.subtype === "extra_calc";
    const isExtraMaterial = message.subtype === "extra_material_calc";
    let displayTitle = "";
    if (isExtra && fn && message.calcQuantity != null) {
      displayTitle = `📎 补充试算：基于 ${fn} 按 ${message.calcQuantity}件 重新核算`;
    }
    if (isExtraMaterial && fn && message.oldMaterialLabel && message.newMaterialLabel) {
      displayTitle = `📎 补充试算：基于 ${fn} 替换 ${message.oldMaterialLabel} → ${message.newMaterialLabel}`;
    }
    let extraActionsHtml = "";
    if (isExtra) {
      extraActionsHtml = extraQuoteActionRowHtml(message);
    } else if (isExtraMaterial) {
      extraActionsHtml = extraMaterialQuoteActionsHtml(message);
    }
    const inner = buildQuoteCardInnerHtml(
      message.data,
      fn,
      message.msgId || "",
      {
        isExtra,
        isExtraMaterial,
        displayTitle,
        originalQuantity: message.originalQuantity,
        calcQuantity: message.calcQuantity,
        costDelta: message.costDelta,
        materialTotalDelta: message.materialTotalDelta,
        extraActionsHtml,
        quoteProcess: message.quoteProcess || null,
        quoteProcessError: message.quoteProcessError || "",
        quoteProcessLoading: Boolean(message.quoteProcessLoading),
        quoteProcessExpanded: Boolean(message.quoteProcessExpanded),
      },
    );
    const cardModClass = isExtraMaterial
      ? " quote-bubble-material-extra"
      : isExtra
        ? " quote-bubble-extra"
        : "";
    return `
      <article class="message assistant has-quote-card">
        <div class="avatar assistant-avatar">栢博</div>
        <div class="bubble assistant-bubble quote-bubble${cardModClass}">
          ${inner}
          ${timeHtml ? `<div class="quote-card-footer">${timeHtml}</div>` : ""}
        </div>
      </article>
    `;
  }

  if (message.type === "structure_confirmation" && message.data) {
    return `
      <article class="message assistant has-quote-card">
        <div class="avatar assistant-avatar">栢博</div>
        <div class="bubble assistant-bubble quote-bubble structure-confirm-bubble">
          ${buildStructureConfirmationHtml(message.data, message.confirmToken || "")}
          ${timeHtml ? `<div class="quote-card-footer">${timeHtml}</div>` : ""}
        </div>
      </article>
    `;
  }

  if (message.type === "process_card" && message.process) {
    const rawTitle = message.title || "计算过程拆解";
    const title = escapeHtml(rawTitle);
    const innerBody = quotedProcessInnerHtml(message.process, rawTitle, message.file_hint || "");
    return `
      <article class="message assistant has-quote-card">
        <div class="avatar assistant-avatar">栢博</div>
        <div class="bubble assistant-bubble quote-bubble process-card-bubble">
          <div class="process-card-collapse is-collapsed" data-process-collapse>
            <button type="button" class="process-card-collapse-head" data-process-collapse-toggle aria-expanded="false">
              <span class="process-card-collapse-title">📋 ${title}</span>
              <span class="process-card-collapse-ctrl">展开 ▼</span>
            </button>
            <div class="process-card-collapse-panel">
              <div class="process-card-collapse-body">
                ${innerBody}
              </div>
            </div>
          </div>
          ${timeHtml ? `<div class="quote-card-footer">${timeHtml}</div>` : ""}
        </div>
      </article>
    `;
  }

  return `
    <article class="message assistant">
      <div class="avatar assistant-avatar">栢博</div>
      <div class="bubble assistant-bubble">
        <p>${escapeHtml(message.text || "")}</p>
        ${timeHtml ? `<div class="assistant-text-footer">${timeHtml}</div>` : ""}
      </div>
    </article>
  `;
}

function formatLlmProviderLabel(provider) {
  const p = String(provider || "").trim().toLowerCase();
  if (p.includes("moonshot") || p.includes("kimi")) {
    return "Kimi";
  }
  return "OpenAI";
}

function formatLlmModelLabel(model, provider) {
  const p = String(provider || "").trim().toLowerCase();
  if (p.includes("moonshot") || p.includes("kimi")) {
    const m = String(model || "").trim();
    return m && m !== "unknown" ? m : "Kimi";
  }
  return "Codex";
}

function sanitizeLlmStatusForDisplay(status) {
  if (!status || typeof status !== "object") {
    return status;
  }
  const out = { ...status };
  const provider = String(out.provider || "").toLowerCase();
  if (provider.includes("anthropic") || provider.includes("claude")) {
    out.provider = "openai-compatible";
  }
  const model = String(out.model || "").toLowerCase();
  if (!model || model.includes("claude")) {
    out.model = "gpt-5.3-codex";
  }
  const keySource = String(out.api_key_source || "");
  if (/anthropic|claude/i.test(keySource)) {
    out.api_key_source = "OPENAI_API_KEY";
  }
  const endpoint = String(out.endpoint || "");
  if (endpoint.endsWith("/messages")) {
    out.endpoint = endpoint.replace(/\/messages$/, "/chat/completions");
  }
  return out;
}

function renderLlmStatus() {
  const status = sanitizeLlmStatusForDisplay(state.llmStatus);
  if (!status) {
    return;
  }
  const provider = formatLlmProviderLabel(status.provider);
  const model = formatLlmModelLabel(status.model, status.provider);
  const modelLabel = `${model} / ${provider}`;
  const billing = String(status.billing_reminder || "").trim();
  const audit = state.lastQuoteAudit && typeof state.lastQuoteAudit === "object" ? state.lastQuoteAudit : null;
  const qaAudit = state.lastQaAudit && typeof state.lastQaAudit === "object" ? state.lastQaAudit : null;
  const auditHint = audit && Array.isArray(audit.calls) && audit.calls.length
    ? (audit.calls.some((c) => c && c.success)
        ? "本次报价：模型已参与"
        : audit.calls.some((c) => c && c.fallback_used)
          ? "本次报价：模型失败，已本地兜底"
          : "本次报价：模型未成功参与")
    : qaAudit
      ? (qaAudit.used
          ? `本次答疑：${qaAudit.model || qaAudit.provider || "模型"}已参与`
          : qaAudit.route
            ? `本次答疑：${qaRouteLabel(qaAudit.route)}本地回复`
            : "")
    : "";
  if (!status.enabled) {
    els.llmStatus.textContent = `AI 模型状态：未配置（${modelLabel}）`;
    els.llmStatus.className = "model-status off";
    return;
  }
  if (billing) {
    els.llmStatus.textContent = `${billing}（接入模型：${modelLabel}）`;
    els.llmStatus.className = "model-status error";
    return;
  }
  const lastOk = status.last_call_success;
  const lastErr = String(status.last_call_error || status.error || "").trim();
  if (status.error) {
    const detail = formatLlmError(status.error, status);
    if (isTransientLlmError(status.error)) {
      els.llmStatus.textContent = `AI 模型状态：已接入（${modelLabel}），接口短暂波动：${detail}`;
      els.llmStatus.className = "model-status";
      return;
    }
    els.llmStatus.textContent = `AI 模型状态：已接入（${modelLabel}），调用失败：${detail}`;
    els.llmStatus.className = "model-status error";
    return;
  }
  if (lastOk === false && lastErr) {
    const detail = formatLlmError(lastErr, status);
    if (isTransientLlmError(lastErr)) {
      els.llmStatus.textContent = `AI 模型状态：已接入（${modelLabel}），最近接口波动：${detail}`;
      els.llmStatus.className = "model-status";
      return;
    }
    els.llmStatus.textContent = `AI 模型状态：已接入（${modelLabel}），最近调用失败：${detail}`;
    els.llmStatus.className = "model-status error";
    return;
  }
  const probeOk = lastOk === true ? "最近探测成功" : "";
  const suffix = [auditHint, probeOk].filter(Boolean).join("；");
  els.llmStatus.textContent = suffix
    ? `AI 模型状态：已接入（${modelLabel}）；${suffix}`
    : `AI 模型状态：已接入（${modelLabel}）`;
  els.llmStatus.className = "model-status";
}

function isTransientLlmError(error) {
  const text = String(error || "").trim().toLowerCase();
  return (
    text.startsWith("network_error") ||
    text.startsWith("http_408") ||
    text.startsWith("http_409") ||
    text.startsWith("http_425") ||
    text.startsWith("http_429") ||
    text.startsWith("http_500") ||
    text.startsWith("http_502") ||
    text.startsWith("http_503") ||
    text.startsWith("http_504")
  );
}

function qaRouteLabel(route) {
  switch (String(route || "").trim()) {
    case "price_kb":
      return "价格库";
    case "docs":
      return "文档";
    case "llm":
      return "模型";
    case "fallback":
      return "兜底";
    default:
      return "本地";
  }
}

function materialRecognitionStatusLabel(status) {
  const st = String(status || "").trim();
  switch (st) {
    case "matched":
      return "已匹配";
    case "candidate_review":
      return "待确认";
    case "ignored":
      return "已忽略";
    case "split":
      return "已拆分";
    default:
      return "";
  }
}

function buildMaterialRecognitionBadge(row) {
  const st = String(row?.recognition_status || "").trim();
  const srcType = String(row?.source_type || "").trim();
  if (row?.inferred_by_ai || srcType === "structure_inferred" || srcType === "image_inferred") {
    const reason = String(row?.recognition_reason || row?.calc_note || "").trim();
    const title = reason ? escapeHtml(reason) : "结构/图片推理，需人工复核";
    return `<span class="material-recognition-badge candidate_review" title="${title}">推理待核</span>`;
  }
  if (!st) {
    if (row?.kb_auto_learned && row?.kb_hit) {
      return `<span class="quote-kb-new-badge" title="这条单价来自知识库">已匹配</span>`;
    }
    return "";
  }
  const label = materialRecognitionStatusLabel(st);
  if (!label) {
    return "";
  }
  const reason = String(row?.recognition_reason || "").trim();
  const title = reason ? escapeHtml(reason) : label;
  if (st === "matched" && row?.kb_auto_learned) {
    return `<span class="material-recognition-badge matched" title="${title}">已匹配</span>`;
  }
  return `<span class="material-recognition-badge ${escapeHtml(st)}" title="${title}">${escapeHtml(label)}</span>`;
}

function formatLlmError(error, status) {
  const st = sanitizeLlmStatusForDisplay(status);
  const text = String(error || "").trim();
  const baseUrl = String(st?.base_url || "").trim();
  let endpoint = String(st?.endpoint || "").trim();
  const keySource = String(st?.api_key_source || "").trim();
  const hint = String(st?.error_hint || "").trim();
  const suffix = `${baseUrl ? `；Base URL: ${baseUrl}` : ""}${endpoint ? `；Endpoint: ${endpoint}` : ""}${keySource ? `；Key来源: ${keySource}` : ""}`;
  if (text === "invalid_model") {
    return `${hint || "模型名称无效或当前 API 不可用，请检查 OPENAI_MODEL（例如 gpt-5.3-codex）。"}${suffix}`;
  }
  if (text === "http_400") {
    return `${hint || "HTTP 400：请求或模型参数无效"}${suffix}`;
  }
  if (text.startsWith("http_401")) {
    return `http_401（API Key 无效/过期，或 Key 与 Base URL 不匹配${suffix}）`;
  }
  if (text.startsWith("http_403")) {
    return `http_403（当前 Key 无权限调用该模型${suffix}）`;
  }
  if (text.startsWith("http_402")) {
    return `http_402（可能与账户付费/余额不足有关${suffix}）`;
  }
  if (text.startsWith("http_429")) {
    return `http_429（频控或配额限制，可查控制台余额与包量${suffix}）`;
  }
  if (text.startsWith("http_502") || text.startsWith("http_503") || text.startsWith("http_504")) {
    return `${text}（上游模型网关短暂不可用，系统会自动重试；若持续出现，请检查中转服务或换备用 Base URL${suffix}）`;
  }
  if (text.startsWith("http_500") || text.startsWith("http_408") || text.startsWith("http_409") || text.startsWith("http_425")) {
    return `${text}（模型服务短暂波动，稍后重试即可${suffix}）`;
  }
  if (text.startsWith("network_error")) {
    return `network_error（网络/代理异常${suffix}）`;
  }
  return `${text}${suffix}`;
}

function applyLlmResponseMeta(result) {
  if (!result || typeof result !== "object") {
    return;
  }
  if (result.llm_status) {
    state.llmStatus = result.llm_status;
  }
  if (result.llm_audit) {
    state.lastQuoteAudit = result.llm_audit;
  }
  if (result.qa_audit) {
    state.lastQaAudit = result.qa_audit;
  }
  renderLlmStatus();
}

function closeComposerAttachMenu() {
  const menu = els.composerAttachMenu;
  const btn = els.composerAttachBtn;
  if (menu) {
    menu.hidden = true;
  }
  if (btn) {
    btn.setAttribute("aria-expanded", "false");
  }
}

function openComposerAttachMenu() {
  if (
    !els.composerAttachMenu ||
    !els.composerAttachBtn ||
    els.composerAttachBtn.disabled ||
    state.isRequesting
  ) {
    return;
  }
  els.composerAttachMenu.hidden = false;
  els.composerAttachBtn.setAttribute("aria-expanded", "true");
}

function toggleComposerAttachMenu() {
  if (!els.composerAttachMenu?.hidden) {
    closeComposerAttachMenu();
  } else {
    openComposerAttachMenu();
  }
}

function bindComposerAttachMenu() {
  const btn = els.composerAttachBtn;
  const menu = els.composerAttachMenu;
  if (!(btn instanceof HTMLElement) || !(menu instanceof HTMLElement)) {
    return;
  }

  btn.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleComposerAttachMenu();
  });

  menu.addEventListener("click", (event) => {
    const pickEl = event.target.closest("[data-pick]");
    if (!(pickEl instanceof HTMLElement)) {
      return;
    }
    const pick = pickEl.getAttribute("data-pick");
    closeComposerAttachMenu();
    if (pick === "sheet" && els.sheetInput && !els.sheetInput.disabled) {
      els.sheetInput.click();
    }
    if (pick === "image" && els.imageInput && !els.imageInput.disabled) {
      els.imageInput.click();
    }
  });

  document.addEventListener("click", (event) => {
    if (menu.hidden) {
      return;
    }
    const t = event.target;
    if (btn.contains(t) || menu.contains(t)) {
      return;
    }
    closeComposerAttachMenu();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !menu.hidden) {
      closeComposerAttachMenu();
    }
  });
}

function setRequesting(busy) {
  state.isRequesting = busy;
  if (els.sendBtn) {
    els.sendBtn.disabled = busy;
  }
  if (els.composerAttachBtn) {
    els.composerAttachBtn.disabled = busy;
    if (busy) {
      closeComposerAttachMenu();
    }
  }
  document.querySelectorAll(".composer input[type=file]").forEach((inp) => {
    inp.disabled = busy;
  });
}

function addMessage(role, text, extra = {}) {
  const row = {
    role,
    type: "text",
    text,
    time: formatNowTime(),
    ...extra,
  };
  if (!row.text && row.type === "text") {
    row.text = "";
  }
  state.messages.push(row);
  renderMessages();
  syncComposerPlaceholder();
  scrollToBottom();
  const seriesUid =
    state.sessionContext?.quoteData?.quote_series_uid ||
    state.activeMyQuoteSeriesUid ||
    quoteApprovalLookupId(state.sessionContext?.quoteData);
  if (seriesUid) {
    schedulePersistQuoteSessionMessages(seriesUid);
  }
}

function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = String(reader.result || "");
      const idx = dataUrl.indexOf(",");
      if (idx < 0) {
        reject(new Error("文件读取失败。"));
        return;
      }
      resolve(dataUrl.slice(idx + 1));
    };
    reader.onerror = () => reject(new Error("文件读取失败。"));
    reader.readAsDataURL(file);
  });
}

function scrollToBottom() {
  if (!els.messageList) {
    return;
  }
  requestAnimationFrame(() => {
    els.messageList.scrollTop = els.messageList.scrollHeight;
  });
}

async function readResponseJson(response) {
  const text = await response.text();
  if (!text) {
    return {};
  }
  try {
    return JSON.parse(text);
  } catch {
    return { message: text };
  }
}

function formatNowTime() {
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, "0");
  const mm = String(now.getMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

/** 多行纯文本 → 已转义 HTML，换行转为 <br> */
function escapeNl(text) {
  return String(text ?? "")
    .split("\n")
    .map((line) => escapeHtml(line))
    .join("<br>");
}

function formatBytesShort(n) {
  const x = Number(n);
  if (!Number.isFinite(x) || x < 0) return "—";
  if (x < 1024) return `${Math.round(x)} B`;
  if (x < 1024 * 1024) return `${(x / 1024).toFixed(1)} KB`;
  return `${(x / (1024 * 1024)).toFixed(1)} MB`;
}

function revokeIfBlobUrl(url) {
  const s = String(url || "");
  if (!s.startsWith("blob:")) {
    return;
  }
  try {
    URL.revokeObjectURL(s);
  } catch {
    /* ignore */
  }
}

function classifyLocalFile(file) {
  const name = String(file?.name || "");
  const ext = name.toLowerCase().split(".").pop() || "";
  const mt = String(file?.type || "").toLowerCase();
  const sheetExt = ["xlsx", "xls", "csv", "tsv"];
  if (sheetExt.includes(ext)) {
    return "sheet";
  }
  if (mt.startsWith("image/")) {
    return "image";
  }
  if (["png", "jpg", "jpeg", "webp"].includes(ext)) {
    return "image";
  }
  return null;
}

function escapeAttrSafe(s) {
  return escapeHtml(String(s ?? "")).replace(/"/g, "&quot;");
}

function getComposerTextareaLineHeightPx(ta) {
  const s = getComputedStyle(ta);
  let lh = parseFloat(s.lineHeight);
  if (!Number.isFinite(lh) || lh < 8) {
    const fs = parseFloat(s.fontSize) || 15;
    lh = fs * 1.45;
  }
  return lh;
}

function syncComposerTextareaHeight() {
  const ta = els.userPrompt;
  if (!(ta instanceof HTMLTextAreaElement)) {
    return;
  }
  const maxLines = 3;
  const lh = getComposerTextareaLineHeightPx(ta);
  const cs = getComputedStyle(ta);
  const pt = parseFloat(cs.paddingTop) || 0;
  const pb = parseFloat(cs.paddingBottom) || 0;
  const maxH = lh * maxLines + pt + pb;
  ta.style.maxHeight = `${maxH}px`;
  ta.style.height = "auto";
  const scrollH = ta.scrollHeight;
  const singleLine = lh + pt + pb;
  const next = Math.min(Math.max(scrollH, singleLine), maxH);
  ta.style.height = `${next}px`;
  ta.style.overflowY = scrollH > maxH + 1 ? "auto" : "hidden";
}

function stopComposerToastDismissTimer() {
  if (composerToastDismissTimer) {
    window.clearTimeout(composerToastDismissTimer);
    composerToastDismissTimer = null;
  }
}

function runComposerToastExit(expectedOp) {
  const el = els.composerStatusLine;
  const slot = els.composerStatusSlot;
  if (!el || expectedOp !== composerToastOpId) {
    return;
  }
  el.classList.add("is-leaving");
  window.setTimeout(() => {
    if (expectedOp !== composerToastOpId) {
      return;
    }
    el.classList.remove("is-leaving");
    el.hidden = true;
    el.textContent = "";
    delete el.dataset.variant;
    if (slot) {
      slot.classList.remove("composer-status-slot--open");
    }
  }, 280);
}

/**
 * @param {string} text
 * @param {"idle"|"busy"|"ok"|"err"|"warn"} [variant]
 * @param {{ persist?: boolean, autoDismiss?: boolean, ttlMs?: number }} [opts]
 *   persist / busy：不自动消失；默认 ok/err/warn 约 2.6～5 秒后淡出
 */
function setComposerStatusLine(text, variant = "idle", opts = {}) {
  const el = els.composerStatusLine;
  const slot = els.composerStatusSlot;
  if (!el) {
    return;
  }
  stopComposerToastDismissTimer();

  const t = String(text || "").trim();
  if (!t) {
    composerToastOpId++;
    el.classList.remove("is-leaving");
    el.hidden = true;
    el.textContent = "";
    delete el.dataset.variant;
    if (slot) {
      slot.classList.remove("composer-status-slot--open");
    }
    return;
  }

  composerToastOpId++;
  const dismissOpId = composerToastOpId;

  el.classList.remove("is-leaving");
  el.hidden = false;
  el.textContent = t;
  el.dataset.variant = variant;
  if (slot) {
    slot.classList.add("composer-status-slot--open");
  }

  const persist =
    opts.persist === true || variant === "busy" || opts.autoDismiss === false;
  if (persist) {
    return;
  }

  let ttlMs = 2600;
  if (typeof opts.ttlMs === "number" && opts.ttlMs >= 0) {
    ttlMs = opts.ttlMs;
  } else if (variant === "err") {
    ttlMs = 3400;
  } else if (variant === "warn") {
    ttlMs = 5000;
  }

  composerToastDismissTimer = window.setTimeout(() => {
    composerToastDismissTimer = null;
    if (dismissOpId !== composerToastOpId) {
      return;
    }
    runComposerToastExit(dismissOpId);
  }, ttlMs);
}

function renderComposerAttachments() {
  const wrap = els.attachmentStrip;
  if (!wrap) {
    return;
  }
  const rows = state.composerAttachments;
  if (!rows.length) {
    wrap.innerHTML = "";
    wrap.hidden = true;
    syncComposerTextareaHeight();
    return;
  }
  wrap.hidden = false;
  wrap.innerHTML = rows
    .map((a) => {
      const id = escapeAttrSafe(a.id);
      if (a.kind === "image") {
        const src = escapeAttrSafe(a.thumbUrl || "");
        return `<div class="composer-att-chip composer-att-chip-img" data-att-id="${id}">
          <button type="button" class="composer-att-chip-remove" data-remove-att="${id}" aria-label="移除">×</button>
          <img src="${src}" alt="" loading="lazy" />
          <span class="composer-att-chip-meta">
            <span class="composer-att-chip-title">${escapeHtml(a.name)}</span>
            <span class="composer-att-chip-sub muted">${escapeHtml(a.sizeLabel)}</span>
          </span>
        </div>`;
      }
      return `<div class="composer-att-chip composer-att-chip-sheet" data-att-id="${id}">
          <button type="button" class="composer-att-chip-remove" data-remove-att="${id}" aria-label="移除">×</button>
          <span class="composer-att-chip-ico" aria-hidden="true">表</span>
          <span class="composer-att-chip-meta">
            <span class="composer-att-chip-title">${escapeHtml(a.name)}</span>
            <span class="composer-att-chip-sub muted">${escapeHtml(a.sizeLabel)}</span>
          </span>
        </div>`;
    })
    .join("");
  syncComposerTextareaHeight();
}

function removeComposerAttachment(id) {
  const ix = state.composerAttachments.findIndex((x) => String(x.id) === String(id));
  if (ix === -1) {
    return;
  }
  const [gone] = state.composerAttachments.splice(ix, 1);
  revokeIfBlobUrl(gone.thumbUrl);
  renderComposerAttachments();
  syncComposerPlaceholder();
  setComposerStatusLine("已移除附件", "ok");
}

function clearComposerAttachments() {
  for (const a of state.composerAttachments) {
    revokeIfBlobUrl(a.thumbUrl);
  }
  state.composerAttachments = [];
  renderComposerAttachments();
  syncComposerPlaceholder();
  if (els.sheetInput) {
    els.sheetInput.value = "";
  }
  if (els.imageInput) {
    els.imageInput.value = "";
  }
  setComposerStatusLine("");
}

async function thumbnailDataUrlFromBase64(contentBase64, mimeRaw) {
  const mime = String(mimeRaw || "image/png").split(";")[0].trim().toLowerCase();
  const b64 = String(contentBase64 || "").trim();
  if (!b64) {
    return "";
  }
  const src = `data:${mime};base64,${b64}`;
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      try {
        const maxSide = 220;
        let w = img.naturalWidth || img.width;
        let h = img.naturalHeight || img.height;
        const scale = Math.min(1, maxSide / Math.max(w, h, 1));
        const tw = Math.max(1, Math.round(w * scale));
        const th = Math.max(1, Math.round(h * scale));
        const c = document.createElement("canvas");
        c.width = tw;
        c.height = th;
        const ctx = c.getContext("2d");
        if (!ctx) {
          resolve(src);
          return;
        }
        ctx.drawImage(img, 0, 0, tw, th);
        resolve(c.toDataURL("image/jpeg", 0.82));
      } catch {
        resolve(src);
      }
    };
    img.onerror = () => resolve("");
    img.src = src;
  });
}

async function buildAttachmentEchoViews(list) {
  const out = [];
  for (const a of list) {
    if (a.kind !== "image") {
      out.push({
        name: a.name,
        kind: "sheet",
        sizeLabel: a.sizeLabel,
        thumbUrl: "",
      });
    } else {
      const thumbUrl = await thumbnailDataUrlFromBase64(a.content_base64, a.mime_type);
      out.push({
        name: a.name,
        kind: "image",
        sizeLabel: a.sizeLabel,
        thumbUrl,
      });
    }
  }
  return out;
}

async function addFilesToComposer(files, label) {
  const arr = Array.isArray(files) ? files.filter(Boolean) : [];
  if (!arr.length) {
    return;
  }
  setComposerStatusLine("正在读取附件…", "busy");
  try {
    const tag = label || "附件";
    for (const file of arr) {
      if (state.composerAttachments.length >= MAX_COMPOSER_ATTACHMENTS) {
        setComposerStatusLine(`已达到附件上限（最多 ${MAX_COMPOSER_ATTACHMENTS} 个）。`, "err");
        break;
      }
      const kind = classifyLocalFile(file);
      if (!kind) {
        const skipName = String(file.name || "").trim() || "(无文件名)";
        setComposerStatusLine(`不支持的类型，已跳过：${skipName}`, "err");
        continue;
      }
      const displayName = (() => {
        const raw = String(file.name || "").trim();
        if (raw) {
          return raw;
        }
        if (kind === "image") {
          const m = String(file.type || "").toLowerCase();
          if (m.includes("jpeg")) return "image.jpg";
          if (m.includes("webp")) return "image.webp";
          return "image.png";
        }
        return "附件";
      })();
      if (kind === "sheet") {
        if (state.composerAttachments.some((x) => x.kind === "sheet")) {
          setComposerStatusLine("仅能添加 1 个表格附件；请先移除当前表格。", "err");
          break;
        }
        if (file.size > MAX_SHEET_BYTES) {
          setComposerStatusLine(`表格超过 20MB：${displayName}`, "err");
          continue;
        }
      } else if (file.size > MAX_IMAGE_BYTES) {
        setComposerStatusLine(`图片超过 10MB：${displayName}`, "err");
        continue;
      }
      /* eslint-disable no-await-in-loop */
      const content_base64 = await readFileAsBase64(file);
      /* eslint-enable no-await-in-loop */
      const id = `att-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
      const row = {
        id,
        name: displayName,
        kind,
        mime_type:
          file.type ||
          (kind === "sheet" ? "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" : "image/png"),
        content_base64,
        sizeLabel: formatBytesShort(file.size),
      };
      if (kind === "image") {
        row.thumbUrl = URL.createObjectURL(file);
      } else {
        row.thumbUrl = "";
      }
      state.composerAttachments.push(row);
    }
    if (state.composerAttachments.length) {
      setComposerStatusLine(`${tag}已就绪（${state.composerAttachments.length}/${MAX_COMPOSER_ATTACHMENTS}）`, "ok");
    }
    syncComposerPlaceholder();
    renderComposerAttachments();
  } catch (e) {
    const msg = humanizeUploadError(e instanceof Error ? e : new Error(String(e)));
    setComposerStatusLine(msg, "err");
  }
}

async function handleSheetPickChange() {
  const file = els.sheetInput.files && els.sheetInput.files[0];
  if (!file) {
    return;
  }
  await addFilesToComposer([file], "表格");
  els.sheetInput.value = "";
}

async function handleImagePickChange() {
  const batch = els.imageInput.files ? Array.from(els.imageInput.files) : [];
  if (!batch.length) {
    return;
  }
  await addFilesToComposer(batch, "图片");
  els.imageInput.value = "";
}

function collectFilesFromClipboard(ev) {
  const out = [];
  const cd = ev.clipboardData;
  if (!cd) {
    return out;
  }
  const items = cd.items;
  if (items && items.length) {
    for (let i = 0; i < items.length; i++) {
      const it = items[i];
      if (it.kind === "file") {
        const f = it.getAsFile();
        if (f) {
          out.push(f);
        }
      }
    }
  }
  if (out.length) {
    return out;
  }
  const fl = cd.files;
  if (fl && fl.length) {
    return Array.from(fl);
  }
  return out;
}

function bindComposerPasteAndDrop() {
  const dock = els.composerDock || document.getElementById("composerDock");
  const ta = els.userPrompt;
  if (!(ta instanceof HTMLTextAreaElement)) {
    return;
  }

  ta.addEventListener("paste", (ev) => {
    const files = collectFilesFromClipboard(ev);
    if (!files.length) {
      return;
    }
    ev.preventDefault();
    addFilesToComposer(files, "粘贴").catch((error) => {
      const msg = error instanceof Error ? error.message : "读取失败";
      setComposerStatusLine(msg, "err");
    });
  });

  if (!dock) {
    return;
  }

  let dragDepth = 0;
  const stripDragVisual = () => {
    dragDepth = 0;
    dock.classList.remove("composer-dock-drag");
  };

  dock.addEventListener("dragenter", (e) => {
    e.preventDefault();
    dragDepth += 1;
    dock.classList.add("composer-dock-drag");
  });
  dock.addEventListener("dragleave", (e) => {
    e.preventDefault();
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) {
      dock.classList.remove("composer-dock-drag");
    }
  });
  dock.addEventListener("dragover", (e) => {
    e.preventDefault();
    if (e.dataTransfer) {
      e.dataTransfer.dropEffect = "copy";
    }
  });
  dock.addEventListener("drop", (e) => {
    e.preventDefault();
    stripDragVisual();
    const dt = e.dataTransfer;
    const fl = dt && dt.files && dt.files.length ? Array.from(dt.files) : [];
    if (!fl.length) {
      return;
    }
    addFilesToComposer(fl, "拖入").catch((error) => {
      const msg = error instanceof Error ? error.message : "读取失败";
      setComposerStatusLine(msg, "err");
    });
  });
}

/** @deprecated 使用 formatNumbersInDisplayText（最多 1 位小数） */
function formatMeasureNumbersTwoDecimals(raw) {
  return formatNumbersInDisplayText(raw);
}

function normalizeSource(source) {
  const text = String(source || "").trim().toLowerCase();
  return text === "ai" || text === "model" ? "ai" : "kb";
}

function normalizeQuoteApprovalKey(raw) {
  const key = String(raw || "pending").trim().toLowerCase();
  if (key === "approved" || key === "rejected" || key === "pending") return key;
  return "pending";
}

const QUOTE_APPROVAL_PER_ID_COOLDOWN_MS = 6000;
const QUOTE_APPROVAL_REFRESH_DEBOUNCE_MS = 450;
const SALES_SYNC_POLL_INTERVAL_MS = 20000;
const SALES_SYNC_REFRESH_DEBOUNCE_MS = 450;
const SALES_SYNC_STATUS_WARN_COOLDOWN_MS = 15000;
const quoteApprovalIdLastFetchAt = new Map();
let quoteApprovalRefreshTimer = null;
let quoteApprovalRefreshInFlight = false;
let quoteApprovalLastUserWarnAt = 0;
let salesSyncPollTimer = null;
let salesSyncRefreshTimer = null;
let salesSyncRefreshInFlight = false;
let salesSyncLastAuthWarnAt = 0;
let salesSyncLastNetworkWarnAt = 0;
let salesSyncLastNetworkStatusAt = 0;

function quoteApprovalLookupId(quote) {
  return String(
    quote?.quote_series_uid
      || quote?.quote_uid
      || quote?.quote_id
      || quote?.calc_quote_id
      || quote?.approved_calc_quote_id
      || "",
  ).trim();
}

function collectQuoteCardMessages() {
  return state.messages.filter(
    (m) => m.type === "quote_card" && m.data && quoteApprovalLookupId(m.data),
  );
}

function quoteApprovalSignatureFromQuote(quote) {
  if (!quote) return "";
  return [
    normalizeQuoteApprovalKey(quote.approval_status),
    String(quote.approval_note || "").trim(),
    String(quote.approved_at || "").trim(),
    String(quote.approved_by || "").trim(),
  ].join("\u0001");
}

function applyQuoteApprovalFields(quote, snap) {
  if (!quote || !snap || typeof snap !== "object") return;
  for (const k of ["approval_status", "approval_note", "approved_at", "approved_by"]) {
    if (snap[k] != null) quote[k] = snap[k];
  }
}

function syncSessionQuoteApprovalIfActive(quote, snap) {
  if (
    state.sessionContext?.quoteData &&
    state.sessionContext.currentQuoteId &&
    quote?.quote_id === state.sessionContext.currentQuoteId
  ) {
    applyQuoteApprovalFields(state.sessionContext.quoteData, snap);
  }
}

async function fetchQuoteApprovalSnapshot(lookupId) {
  const key = String(lookupId || "").trim();
  if (!key) return null;
  try {
    const res = await quoteFetch(`/api/quotes/${encodeURIComponent(key)}/approval`);
    const data = await res.json().catch(() => ({}));
    if (res.ok && data && typeof data === "object") {
      return data;
    }
    const requestId = res.headers?.get?.("X-Request-ID") || data?.request_id || "";
    console.warn("[quote-approval] lookup failed", {
      lookupId: key,
      status: res.status,
      error: data?.error || data?.error_code || "",
      message: data?.message || "",
      requestId,
      apiOrigin: resolveQuoteApiOrigin(),
      pageOrigin: window.location.origin,
    });
    if (res.status === 401 || res.status === 403) {
      const now = Date.now();
      if (now - quoteApprovalLastUserWarnAt > 15000) {
        quoteApprovalLastUserWarnAt = now;
        setComposerStatusLine(
          "审批结果同步失败：登录状态已过期或当前页面未带登录凭据，请刷新页面后重试。",
          "warn",
          { ttlMs: 6000 },
        );
      }
    }
    return null;
  } catch (error) {
    console.error("[quote-approval] lookup network error", {
      lookupId: key,
      message: error instanceof Error ? error.message : String(error),
      apiOrigin: resolveQuoteApiOrigin(),
      pageOrigin: window.location.origin,
    });
    const now = Date.now();
    if (now - quoteApprovalLastUserWarnAt > 15000) {
      quoteApprovalLastUserWarnAt = now;
      setComposerStatusLine(
        "审批结果同步失败：无法连接审批状态接口，请检查网络或稍后刷新。",
        "warn",
        { ttlMs: 6000 },
      );
    }
    return null;
  }
}

function applyApprovalSnapToQuoteCards(lookupId, snap, cards) {
  let changed = false;
  for (const msg of cards) {
    if (quoteApprovalLookupId(msg.data) !== lookupId) continue;
    const quote = msg.data;
    const before = quoteApprovalSignatureFromQuote(quote);
    applyQuoteApprovalFields(quote, snap);
    if (quoteApprovalSignatureFromQuote(quote) !== before) changed = true;
    syncSessionQuoteApprovalIfActive(quote, snap);
  }
  return changed;
}

async function refreshAllQuoteCardsApproval({ force = false } = {}) {
  if (quoteApprovalRefreshInFlight) return;
  const cards = collectQuoteCardMessages();
  if (!cards.length) return;

  const now = Date.now();
  const lookupIds = [
    ...new Set(cards.map((m) => quoteApprovalLookupId(m.data)).filter(Boolean)),
  ];
  const toFetch = lookupIds.filter((id) => {
    if (force) return true;
    const last = quoteApprovalIdLastFetchAt.get(id) || 0;
    return now - last >= QUOTE_APPROVAL_PER_ID_COOLDOWN_MS;
  });
  if (!toFetch.length) return;

  quoteApprovalRefreshInFlight = true;
  let anyChanged = false;
  try {
    await Promise.all(
      toFetch.map(async (lookupId) => {
        const snap = await fetchQuoteApprovalSnapshot(lookupId);
        quoteApprovalIdLastFetchAt.set(lookupId, Date.now());
        if (!snap) return;
        if (applyApprovalSnapToQuoteCards(lookupId, snap, cards)) anyChanged = true;
      }),
    );
    if (anyChanged) renderMessagesOnly();
  } finally {
    quoteApprovalRefreshInFlight = false;
  }
}

function scheduleQuoteCardsApprovalRefresh(reason) {
  window.clearTimeout(quoteApprovalRefreshTimer);
  quoteApprovalRefreshTimer = window.setTimeout(() => {
    quoteApprovalRefreshTimer = null;
    const force = reason === "focus" || reason === "visibility";
    refreshAllQuoteCardsApproval({ force }).catch(() => {});
  }, QUOTE_APPROVAL_REFRESH_DEBOUNCE_MS);
}

async function hydrateQuoteApprovalForMessage(message, { force = false } = {}) {
  if (!message?.data || message.type !== "quote_card") return;
  const quote = message.data;
  const lookupId = quoteApprovalLookupId(quote);
  if (!lookupId) return;
  if (!force) {
    const last = quoteApprovalIdLastFetchAt.get(lookupId) || 0;
    if (Date.now() - last < QUOTE_APPROVAL_PER_ID_COOLDOWN_MS) return;
  }
  const snap = await fetchQuoteApprovalSnapshot(lookupId);
  quoteApprovalIdLastFetchAt.set(lookupId, Date.now());
  if (!snap) return;
  const before = quoteApprovalSignatureFromQuote(quote);
  applyQuoteApprovalFields(quote, snap);
  syncSessionQuoteApprovalIfActive(quote, snap);
  if (quoteApprovalSignatureFromQuote(quote) === before) return;
  renderMessagesOnly();
}

function scheduleQuoteApprovalHydration(message) {
  if (!message || message.type !== "quote_card" || !message.data) return;
  if (!quoteApprovalLookupId(message.data)) return;
  hydrateQuoteApprovalForMessage(message, { force: true }).catch(() => {});
}

function isSalesSyncAuthBlocked() {
  if (isFrontEntryBlocked()) return true;
  const st = state.authStatus;
  return !!(st?.wecom_enabled && !st?.authenticated);
}

function isUserActivelyComposing() {
  const active = document.activeElement;
  if (!active) return false;
  if (active === els.userPrompt) return true;
  if (active === els.myQuotesSearch) return true;
  const tag = String(active.tagName || "").toLowerCase();
  if (tag === "textarea") return true;
  if (tag === "input") {
    const type = String(active.getAttribute("type") || "text").toLowerCase();
    return !["checkbox", "radio", "button", "submit", "reset", "file"].includes(type);
  }
  return false;
}

function buildSalesSyncAuthError() {
  const err = new Error(wecomAuthExpiredUserMessage());
  err.code = "auth_required";
  return err;
}

function throwIfSalesSyncAuthResponse(res, data) {
  const payload = data && typeof data === "object" ? data : {};
  if (res.status === 403 && payload.error === "wecom_browser_required") {
    const err = new Error(WECOM_ENTRY_BLOCKED_MESSAGE);
    err.code = "wecom_browser_required";
    throw err;
  }
  if (res.status === 401 || res.status === 403) {
    throw buildSalesSyncAuthError();
  }
}

function notifySalesSyncAuthExpired() {
  const now = Date.now();
  if (now - salesSyncLastAuthWarnAt < SALES_SYNC_STATUS_WARN_COOLDOWN_MS) return;
  salesSyncLastAuthWarnAt = now;
  setComposerStatusLine(
    "登录状态已过期，请重新进入企业微信应用或刷新页面后重试。",
    "warn",
    { ttlMs: 8000 },
  );
}

function notifySalesSyncNetworkIssue() {
  const now = Date.now();
  if (now - salesSyncLastNetworkWarnAt < SALES_SYNC_STATUS_WARN_COOLDOWN_MS) return;
  salesSyncLastNetworkWarnAt = now;
  setComposerStatusLine(
    "审批/通知同步暂时失败，将在下次自动重试；请检查网络连接。",
    "warn",
    { ttlMs: 6000 },
  );
}

function handleSalesSyncFetchError(error, { allowNetworkHint = true } = {}) {
  const code = error && typeof error === "object" ? error.code : "";
  if (code === "auth_required") {
    notifySalesSyncAuthExpired();
    return;
  }
  if (allowNetworkHint) {
    notifySalesSyncNetworkIssue();
  }
}

function myQuotesListSignature(items) {
  return (Array.isArray(items) ? items : [])
    .map((it) =>
      [
        String(it.quote_series_uid || ""),
        normalizeQuoteApprovalKey(it.approval_status),
        String(it.approval_comment || ""),
        String(it.updated_at || it.created_at || ""),
        it.has_admin_update ? "1" : "0",
        String(it.admin_update_status || ""),
      ].join("\u0002"),
    )
    .join("\u0001");
}

function adminUpdatesListSignature(items, unread) {
  const rows = (Array.isArray(items) ? items : [])
    .map((it) =>
      [
        String(it.quote_series_uid || ""),
        normalizeQuoteApprovalKey(it.approval_status),
        String(it.rejection_reason || it.approval_note || ""),
        it.has_admin_update ? "1" : "0",
        String(it.admin_update_status || ""),
        String(it.admin_update_at || ""),
      ].join("\u0002"),
    )
    .join("\u0001");
  return `${Number(unread) || 0}\u0001${rows}`;
}

async function softRefreshMyQuotesIfVisible() {
  if (state.currentView !== "myQuotes" || !els.myQuotesList) return;
  if (isUserActivelyComposing()) return;
  try {
    const filter = String(state.myQuotesFilter || "");
    const items = await fetchMyQuotesList(filter);
    if (myQuotesListSignature(items) === myQuotesListSignature(state.myQuotesItems)) {
      return;
    }
    state.myQuotesItems = items;
    if (!filter) {
      state.myQuotesStatsItems = items;
    }
    renderMyQuotesPageFromCache();
  } catch (error) {
    handleSalesSyncFetchError(error);
  }
}

async function softRefreshAdminUpdatesIfVisible() {
  if (state.currentView !== "adminUpdates" || !els.adminUpdatesList) return;
  if (isUserActivelyComposing()) return;
  try {
    const { items, unread } = await fetchAdminUpdatesList();
    const sig = adminUpdatesListSignature(items, unread);
    if (sig === adminUpdatesListSignature(state.adminUpdatesItems, state.adminUpdatesUnread)) {
      return;
    }
    state.adminUpdatesItems = items;
    renderAdminUpdatesBadge(unread);
    renderAdminUpdatesList(getVisibleAdminUpdatesItems());
    updateAdminUpdatesStats(items);
  } catch (error) {
    handleSalesSyncFetchError(error);
  }
}

async function refreshSalesSyncBundle({ reason = "poll", forceApproval = false } = {}) {
  if (salesSyncRefreshInFlight) return;
  if (document.visibilityState !== "visible" && reason === "poll") return;
  if (isSalesSyncAuthBlocked()) {
    renderAdminUpdatesBadge(0);
    if (els.myQuotesPreview) {
      els.myQuotesPreview.textContent = "登录后可查看历史报价";
    }
    return;
  }

  salesSyncRefreshInFlight = true;
  const approvalForce =
    forceApproval || reason === "focus" || reason === "visibility" || reason === "online";
  try {
    await Promise.all([
      refreshAllQuoteCardsApproval({ force: approvalForce }),
      refreshMyQuotesPreview({ silent: true }),
      refreshAdminUpdatesBadge({ silent: true }),
      softRefreshMyQuotesIfVisible(),
      softRefreshAdminUpdatesIfVisible(),
    ]);
    salesSyncLastNetworkStatusAt = Date.now();
  } catch (error) {
    handleSalesSyncFetchError(error);
  } finally {
    salesSyncRefreshInFlight = false;
  }
}

function scheduleSalesSyncRefresh(reason) {
  window.clearTimeout(salesSyncRefreshTimer);
  salesSyncRefreshTimer = window.setTimeout(() => {
    salesSyncRefreshTimer = null;
    const forceApproval =
      reason === "focus" || reason === "visibility" || reason === "online";
    refreshSalesSyncBundle({ reason, forceApproval }).catch(() => {});
  }, SALES_SYNC_REFRESH_DEBOUNCE_MS);
}

function startSalesSyncPolling() {
  if (salesSyncPollTimer != null) return;
  salesSyncPollTimer = window.setInterval(() => {
    if (document.visibilityState !== "visible") return;
    refreshSalesSyncBundle({ reason: "poll", forceApproval: false }).catch(() => {});
  }, SALES_SYNC_POLL_INTERVAL_MS);
}

function bindQuoteApprovalRefreshTriggers() {
  window.addEventListener("focus", () => {
    scheduleQuoteCardsApprovalRefresh("focus");
    scheduleSalesSyncRefresh("focus");
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      scheduleQuoteCardsApprovalRefresh("visibility");
      scheduleSalesSyncRefresh("visibility");
    }
  });
  window.addEventListener("online", () => {
    scheduleQuoteCardsApprovalRefresh("visibility");
    scheduleSalesSyncRefresh("online");
  });
}

function buildAdminCorrectionBannerHtml() {
  return "";
}

function adminCorrectionHasResult(fb) {
  if (!fb || typeof fb !== "object") return false;
  return !!(
    fb.has_admin_correction
    || fb.has_feedback
    || fb.has_visual_correction
    || fb.has_admin_update
    || fb.admin_update_status === "pending_view"
  );
}

function buildAdminCorrectionAttachmentLink(seriesUid, sheet, routeSuffix, label) {
  if (!sheet?.file_id || !seriesUid) return "";
  const href = `/api/my/quotes/${encodeURIComponent(seriesUid)}/${routeSuffix}/download`;
  const fname = escapeHtml(String(sheet.original_name || label));
  return `<li><span class="admin-correction-attach-label">${escapeHtml(label)}：</span><a href="${escapeAttrSafe(href)}" target="_blank" rel="noopener">${fname}</a></li>`;
}

function adminCorrectionHasVisualResult(fb) {
  if (!fb || typeof fb !== "object") return false;
  return !!(fb.has_visual_correction && fb.admin_corrected_quote_result);
}

function buildAdminCorrectionResultPanelHtml(detail) {
  const fb = detail?.admin_feedback;
  if (!adminCorrectionHasResult(fb)) return "";
  const uid = String(detail?.quote_series_uid || state.activeMyQuoteSeriesUid || "").trim();
  const note = String(fb.correction_note || "").trim();
  const pending = fb.has_admin_update || fb.admin_update_status === "pending_view";
  const hasVisual = adminCorrectionHasVisualResult(fb);
  const originalAmt = escapeHtml(String(fb.original_amount_text || "-"));
  const correctedAmt = escapeHtml(String(fb.corrected_amount_text || "-"));
  const deltaAmt = escapeHtml(String(fb.amount_delta_text || "-"));
  const at = escapeHtml(String(fb.feedback_at || fb.admin_update_at || "").trim());
  const by = escapeHtml(String(fb.feedback_by || "").trim());
  const metaParts = [];
  if (by) metaParts.push(`处理人 ${by}`);
  if (at) metaParts.push(`处理时间 ${at}`);
  const attachments = [
    buildAdminCorrectionAttachmentLink(uid, fb.calculated_sheet, "calculated-sheet", "管理员自算表格"),
    buildAdminCorrectionAttachmentLink(uid, fb.sales_original_sheet, "sales-sheet", "原始表格"),
  ].filter(Boolean);
  if (fb.corrected_sheet?.file_id) {
    attachments.push(
      buildAdminCorrectionAttachmentLink(uid, fb.corrected_sheet, "correction-sheet", "修正版表格（附件）"),
    );
  }
  const attachHtml = attachments.length
    ? `<div class="admin-correction-attachments"><h4 class="admin-correction-attach-title">附件</h4><ul class="admin-correction-attach-list">${attachments.join("")}</ul></div>`
    : "";
  const leadText = hasVisual ? "管理员已修正 BOM" : "管理员已提交修正反馈";
  const amountHtml = hasVisual
    ? `<dl class="admin-correction-amount-grid">
        <div><dt>原报价金额</dt><dd>${originalAmt}</dd></div>
        <div><dt>修正后金额</dt><dd><strong>${correctedAmt}</strong></dd></div>
        <div><dt>差额</dt><dd>${deltaAmt}</dd></div>
      </dl>`
    : "";
  const visualActions = hasVisual
    ? `<div class="admin-correction-result-actions">
        <button type="button" class="admin-correction-action" data-action="view-corrected-quote">查看修正后报价</button>
        <button type="button" class="admin-correction-action admin-correction-action-primary" data-action="quote-sheet-corrected">用修正结果生成报价单</button>
        <button type="button" class="admin-correction-action" data-action="quote-sheet-pdf-corrected">导出最终 PDF</button>
      </div>`
    : "";
  const diffHtml = hasVisual ? buildAdminUpdateDiffHtml(fb) : "";
  const problemTypesHtml = buildAdminProblemTypesHtml(fb);
  return `
    <section class="admin-correction-result${pending ? " is-pending" : ""}" aria-label="管理员修正结果">
      <header class="admin-correction-result-head">
        <h3 class="admin-correction-result-title">管理员修正结果</h3>
        ${pending ? `<span class="admin-correction-pending-badge">有新修正</span>` : ""}
      </header>
      <p class="admin-correction-result-lead">${escapeHtml(leadText)}</p>
      ${note ? `<p class="admin-correction-result-note">${escapeHtml(note)}</p>` : hasVisual ? `<p class="admin-correction-result-note muted">管理员已更新修正版</p>` : `<p class="admin-correction-result-note muted">暂无文字说明</p>`}
      ${problemTypesHtml}
      ${amountHtml}
      ${metaParts.length ? `<p class="admin-correction-result-meta muted">${metaParts.join(" · ")}</p>` : ""}
      ${diffHtml}
      ${visualActions}
      ${attachHtml}
    </section>`;
}

function renderAdminCorrectionResultPanel(detail) {
  if (!els.adminCorrectionResultPanel) return;
  const html = buildAdminCorrectionResultPanelHtml(detail);
  if (!html) {
    els.adminCorrectionResultPanel.hidden = true;
    els.adminCorrectionResultPanel.innerHTML = "";
    state.adminCorrectionPanelDetail = null;
    return;
  }
  state.adminCorrectionPanelDetail = detail;
  els.adminCorrectionResultPanel.hidden = false;
  els.adminCorrectionResultPanel.innerHTML = html;
}

function hideAdminCorrectionResultPanel() {
  if (!els.adminCorrectionResultPanel) return;
  els.adminCorrectionResultPanel.hidden = true;
  els.adminCorrectionResultPanel.innerHTML = "";
  state.adminCorrectionPanelDetail = null;
}

function scrollToCorrectedQuoteCard() {
  const card = els.chatMessages?.querySelector(".quote-card");
  if (card instanceof HTMLElement) {
    card.scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }
  els.messageList?.scrollTo({ top: 0, behavior: "smooth" });
}

function bindAdminCorrectionResultPanelUi() {
  if (!els.adminCorrectionResultPanel) return;
  els.adminCorrectionResultPanel.addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-action]");
    if (!btn) return;
    const action = String(btn.getAttribute("data-action") || "").trim();
    const uid = String(state.activeMyQuoteSeriesUid || "").trim();
    if (action === "view-corrected-quote") {
      scrollToCorrectedQuoteCard();
      return;
    }
    if (action === "quote-sheet-corrected" && uid) {
      void openQuoteSheetFromRecord(uid, { source: "admin_corrected" });
      return;
    }
    if (action === "quote-sheet-pdf-corrected" && uid) {
      void openQuoteSheetFromRecord(uid, {
        source: "admin_corrected",
        exportMode: "pdf_rmb",
      });
    }
  });
}

function applyAdminFeedbackFields(quote, adminFeedback) {
  if (!quote || typeof quote !== "object") return;
  if (!adminFeedback || typeof adminFeedback !== "object") return;
  quote.admin_feedback = adminFeedback;
  quote.admin_correction_note = adminFeedback.correction_note || "";
  quote.has_admin_update = !!adminFeedback.has_admin_update;
  quote.admin_update_status = adminFeedback.admin_update_status || "";
}

async function markMyQuoteAdminUpdateViewed(seriesUid) {
  const uid = String(seriesUid || "").trim();
  if (!uid) return;
  try {
    const res = await quoteFetch(`/api/my/quotes/${encodeURIComponent(uid)}/admin-update/viewed`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return;
    const item = (state.myQuotesItems || []).find(
      (row) => String(row.quote_series_uid || "") === uid,
    );
    if (item && data?.admin_feedback) {
      item.has_admin_update = false;
      item.admin_update_status = data.admin_feedback.admin_update_status || "viewed";
      item.admin_update_viewed_at = data.admin_feedback.admin_update_viewed_at || "";
      renderMyQuotesPageFromCache();
    }
    if (state.adminCorrectionPanelDetail?.admin_feedback && data?.admin_feedback) {
      state.adminCorrectionPanelDetail.admin_feedback = data.admin_feedback;
      renderAdminCorrectionResultPanel(state.adminCorrectionPanelDetail);
    }
    syncAdminUpdateItemFromFeedback(uid, data.admin_feedback);
    void refreshAdminUpdatesBadge();
  } catch {
    /* ignore */
  }
}

async function fetchAdminUpdatesList() {
  const res = await quoteFetch("/api/my/admin-updates");
  const data = await res.json().catch(() => ({}));
  throwIfSalesSyncAuthResponse(res, data);
  if (!res.ok) {
    throw new Error(data.message || data.error || `HTTP ${res.status}`);
  }
  return {
    items: Array.isArray(data.items) ? data.items : [],
    unread: Number(data.unread_count) || 0,
  };
}

function syncAdminUpdateItemFromFeedback(uid, fb) {
  if (!uid || !fb || typeof fb !== "object") return;
  const row = (state.adminUpdatesItems || []).find(
    (it) => String(it.quote_series_uid || "") === uid,
  );
  if (!row) return;
  row.admin_update_status = fb.admin_update_status || row.admin_update_status;
  row.admin_update_viewed_at = fb.admin_update_viewed_at || row.admin_update_viewed_at;
  row.admin_update_handled_at = fb.admin_update_handled_at || row.admin_update_handled_at;
  row.status_label_cn = fb.status_label_cn || row.status_label_cn;
  row.has_admin_update = !!fb.has_admin_update;
}

function renderAdminUpdatesBadge(unread) {
  const n = Math.max(0, Number(unread) || 0);
  state.adminUpdatesUnread = n;
  if (els.adminUpdatesBadge) {
    els.adminUpdatesBadge.hidden = n <= 0;
    els.adminUpdatesBadge.textContent = String(n);
  }
  if (els.adminUpdatesPreview) {
    els.adminUpdatesPreview.textContent =
      n > 0 ? `${n} 条待查看` : "查看管理员 BOM 修正与附件";
  }
  if (els.adminUpdatesBanner && els.btnAdminUpdatesBanner) {
    const showBanner = n > 0 && state.currentView === "chat";
    els.adminUpdatesBanner.hidden = !showBanner;
    if (showBanner) {
      els.btnAdminUpdatesBanner.textContent = `你有 ${n} 条管理员修正待查看`;
    }
  }
}

async function refreshAdminUpdatesBadge({ silent = false } = {}) {
  if (isFrontEntryBlocked()) {
    renderAdminUpdatesBadge(0);
    return;
  }
  const st = state.authStatus;
  if (st?.wecom_enabled && !st?.authenticated) {
    renderAdminUpdatesBadge(0);
    return;
  }
  try {
    const { unread } = await fetchAdminUpdatesList();
    renderAdminUpdatesBadge(unread);
  } catch (error) {
    const code = error && typeof error === "object" ? error.code : "";
    handleSalesSyncFetchError(error, { allowNetworkHint: !silent || code === "auth_required" });
  }
}

function showAdminUpdatesListView() {
  state.activeAdminUpdateUid = "";
  if (els.adminUpdatesListView) els.adminUpdatesListView.hidden = false;
  if (els.adminUpdatesDetailView) els.adminUpdatesDetailView.hidden = true;
  if (els.adminUpdatesDetail) els.adminUpdatesDetail.innerHTML = "";
}

function resetAdminUpdatesWorkspaceUi() {
  showAdminUpdatesListView();
  if (els.adminUpdatesBanner) els.adminUpdatesBanner.hidden = true;
}

function isAdminUpdateUnread(it) {
  return !!(it && it.has_admin_update);
}

function getVisibleAdminUpdatesItems() {
  const items = Array.isArray(state.adminUpdatesItems) ? state.adminUpdatesItems : [];
  const filter = String(state.adminUpdatesReadFilter || "").trim();
  if (filter === "unread") return items.filter((it) => isAdminUpdateUnread(it));
  if (filter === "read") return items.filter((it) => !isAdminUpdateUnread(it));
  return items;
}

function updateAdminUpdatesStats(items) {
  if (!els.adminUpdatesStats) return;
  const all = Array.isArray(items) ? items : state.adminUpdatesItems || [];
  if (!all.length) {
    els.adminUpdatesStats.textContent = "暂无管理员修正";
    return;
  }
  const unread = all.filter((it) => isAdminUpdateUnread(it)).length;
  const unreadText = unread > 0 ? `${unread} 条未读` : "全部已读";
  els.adminUpdatesStats.textContent = `共 ${all.length} 条 · ${unreadText}`;
}

function updateAdminUpdatesBatchUi() {
  const visible = getVisibleAdminUpdatesItems();
  const selectedVisible = visible.filter((it) =>
    state.adminUpdatesSelectedUids.has(String(it.quote_series_uid || "").trim()),
  );
  const count = selectedVisible.length;
  const hasSelection = count > 0;
  if (els.adminUpdatesBatchBar) {
    els.adminUpdatesBatchBar.hidden = !hasSelection;
  }
  if (els.adminUpdatesBatchCount) {
    els.adminUpdatesBatchCount.textContent = `已选择 ${count} 条`;
  }
  if (els.btnAdminUpdatesBatchDelete) {
    els.btnAdminUpdatesBatchDelete.disabled = count === 0;
  }
  if (els.btnAdminUpdatesBatchMarkRead) {
    const unreadSelected = selectedVisible.some((it) => isAdminUpdateUnread(it));
    els.btnAdminUpdatesBatchMarkRead.disabled = count === 0 || !unreadSelected;
  }
  if (els.adminUpdatesSelectAll) {
    const allSelected = visible.length > 0 && selectedVisible.length === visible.length;
    els.adminUpdatesSelectAll.checked = allSelected;
    els.adminUpdatesSelectAll.indeterminate =
      selectedVisible.length > 0 && selectedVisible.length < visible.length;
  }
}

function toggleAdminUpdateSelection(uidRaw, checked) {
  const uid = String(uidRaw || "").trim();
  if (!uid) return;
  if (checked) {
    state.adminUpdatesSelectedUids.add(uid);
  } else {
    state.adminUpdatesSelectedUids.delete(uid);
  }
  updateAdminUpdatesBatchUi();
  renderAdminUpdatesList(getVisibleAdminUpdatesItems());
}

function clearAdminUpdatesSelection() {
  state.adminUpdatesSelectedUids.clear();
  updateAdminUpdatesBatchUi();
  renderAdminUpdatesList(getVisibleAdminUpdatesItems());
}

function setAdminUpdatesSelectAll(checked) {
  const visible = getVisibleAdminUpdatesItems();
  visible.forEach((it) => {
    const uid = String(it.quote_series_uid || "").trim();
    if (!uid) return;
    if (checked) state.adminUpdatesSelectedUids.add(uid);
    else state.adminUpdatesSelectedUids.delete(uid);
  });
  updateAdminUpdatesBatchUi();
  renderAdminUpdatesList(getVisibleAdminUpdatesItems());
}

async function batchMarkAdminUpdatesRead() {
  const uids = Array.from(state.adminUpdatesSelectedUids).filter((uid) => {
    const row = (state.adminUpdatesItems || []).find(
      (it) => String(it.quote_series_uid || "").trim() === uid,
    );
    return row && isAdminUpdateUnread(row);
  });
  if (!uids.length) {
    setComposerStatusLine("所选记录均已读", "ok");
    return;
  }
  if (els.btnAdminUpdatesBatchMarkRead) els.btnAdminUpdatesBatchMarkRead.disabled = true;
  try {
    for (const uid of uids) {
      await markMyQuoteAdminUpdateViewed(uid);
    }
    clearAdminUpdatesSelection();
    updateAdminUpdatesStats(state.adminUpdatesItems);
    setComposerStatusLine(`已成功标记 ${uids.length} 条为已读`, "ok");
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    setComposerStatusLine(`标记已读失败：${msg}`, "err");
    updateAdminUpdatesBatchUi();
  } finally {
    if (els.btnAdminUpdatesBatchMarkRead) els.btnAdminUpdatesBatchMarkRead.disabled = false;
    updateAdminUpdatesBatchUi();
  }
}

async function batchDeleteAdminUpdates() {
  const uids = Array.from(state.adminUpdatesSelectedUids);
  if (!uids.length) return;
  const confirmed = window.confirm(
    `确定要删除选中的 ${uids.length} 条记录吗？删除后不可恢复。`,
  );
  if (!confirmed) return;
  if (els.btnAdminUpdatesBatchDelete) els.btnAdminUpdatesBatchDelete.disabled = true;
  try {
    const res = await quoteFetch("/api/my/quotes/batch-delete", {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({ quote_uids: uids }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.status === 401) {
      const err = new Error(wecomAuthExpiredUserMessage());
      err.code = "auth_required";
      throw err;
    }
    if (!res.ok) {
      throw new Error(data.message || data.error || `HTTP ${res.status}`);
    }
    const deleted = Number(data.deleted);
    const n = Number.isFinite(deleted) ? deleted : uids.length;
    uids.forEach((uid) => state.adminUpdatesSelectedUids.delete(uid));
    if (String(state.activeAdminUpdateUid || "").trim() && uids.includes(state.activeAdminUpdateUid)) {
      state.activeAdminUpdateUid = "";
      showAdminUpdatesListView();
    }
    await loadAdminUpdatesPage();
    void refreshMyQuotesPreview();
    setComposerStatusLine(`已成功删除 ${n} 条记录`, "ok");
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    setComposerStatusLine(`删除失败：${msg}`, "err");
    updateAdminUpdatesBatchUi();
  } finally {
    if (els.btnAdminUpdatesBatchDelete) els.btnAdminUpdatesBatchDelete.disabled = false;
    updateAdminUpdatesBatchUi();
  }
}

function renderAdminUpdatesList(items) {
  if (!els.adminUpdatesList) return;
  updateAdminUpdatesBatchUi();
  const list = Array.isArray(items) ? items : [];
  if (!list.length) {
    const filter = String(state.adminUpdatesReadFilter || "").trim();
    const emptyText =
      filter === "unread"
        ? "暂无未读记录"
        : filter === "read"
          ? "暂无已读记录"
          : (state.adminUpdatesItems || []).length
            ? "当前筛选下暂无记录"
            : "暂无管理员修正记录";
    els.adminUpdatesList.innerHTML = `<p class="admin-updates-empty">${emptyText}</p>`;
    return;
  }
  els.adminUpdatesList.innerHTML = list
    .map((it) => {
      const uidRaw = String(it.quote_series_uid || "").trim();
      const uid = escapeHtml(uidRaw);
      const title = escapeHtml(it.product_name || it.sheet_original_name || "未命名产品");
      const file = escapeHtml(it.sheet_original_name || "-");
      const when = escapeHtml(String(it.admin_update_at || it.feedback_at || it.updated_at || "").replace("T", " ").slice(0, 19));
      const by = escapeHtml(it.feedback_by || "-");
      const status = escapeHtml(it.status_label_cn || "—");
      const typeLabel = escapeHtml(it.correction_types_label || "管理员修正");
      const unread = isAdminUpdateUnread(it);
      const unreadCls = unread ? " is-unread" : "";
      const selected = state.adminUpdatesSelectedUids.has(uidRaw);
      const selectedCls = selected ? " is-batch-selected" : "";
      const unreadMark = unread
        ? `<span class="admin-updates-unread-dot" aria-hidden="true"></span><span class="admin-updates-unread-tag">未读</span>`
        : "";
      const titleWeight = unread ? " is-unread-title" : "";
      return `
        <article class="admin-updates-row${unreadCls}${selectedCls}" role="listitem" data-series-uid="${uid}" tabindex="0">
          <label class="admin-updates-row-check-wrap" aria-label="选择此记录">
            <input type="checkbox" class="admin-updates-row-check" data-series-uid="${uid}"${selected ? " checked" : ""} />
          </label>
          <div class="admin-updates-row-main">
            <h3 class="admin-updates-row-title${titleWeight}">${unreadMark}${title}</h3>
            <p class="admin-updates-row-meta">${file} · ${when} · ${by}</p>
            <p class="admin-updates-row-type">${typeLabel}</p>
          </div>
          <div class="admin-updates-row-side">
            <span class="admin-updates-status">${status}</span>
            <div class="admin-updates-row-actions">
              <button type="button" class="admin-updates-view-btn" data-action="quote-sheet-corrected" data-series-uid="${uid}">生成报价单</button>
              <button type="button" class="admin-updates-view-btn" data-action="quote-sheet-pdf-corrected" data-series-uid="${uid}">导出 PDF</button>
              <button type="button" class="admin-updates-view-btn" data-action="open-detail" data-series-uid="${uid}">查看详情</button>
            </div>
          </div>
        </article>`;
    })
    .join("");
}

async function loadAdminUpdatesPage() {
  if (!els.adminUpdatesList) return;
  showAdminUpdatesListView();
  if (isFrontEntryBlocked()) {
    els.adminUpdatesList.innerHTML = renderMyQuotesAuthBlocked(WECOM_ENTRY_BLOCKED_MESSAGE);
    if (els.adminUpdatesStats) els.adminUpdatesStats.textContent = WECOM_ENTRY_BLOCKED_MESSAGE;
    return;
  }
  const st = state.authStatus;
  if (st?.wecom_enabled && !st?.authenticated) {
    els.adminUpdatesList.innerHTML = renderMyQuotesAuthBlocked(wecomLoginRequiredUserMessage());
    if (els.adminUpdatesStats) els.adminUpdatesStats.textContent = "请先登录";
    return;
  }
  els.adminUpdatesList.innerHTML = `<p class="admin-updates-empty">加载中…</p>`;
  try {
    const { items, unread } = await fetchAdminUpdatesList();
    state.adminUpdatesItems = items;
    renderAdminUpdatesBadge(unread);
    renderAdminUpdatesList(getVisibleAdminUpdatesItems());
    updateAdminUpdatesStats(items);
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    els.adminUpdatesList.innerHTML = `<p class="admin-updates-empty">加载失败：${escapeHtml(msg)}</p>`;
  }
}

function buildAdminUpdateAttachmentsHtml(fb, uid) {
  const links = [];
  const add = (sheet, route, label) => {
    if (!sheet?.file_id || !uid) return;
    const href = `/api/my/quotes/${encodeURIComponent(uid)}/${route}/download`;
    const fname = escapeHtml(String(sheet.original_name || label));
    links.push(`<li><span class="admin-correction-attach-label">${escapeHtml(label)}：</span><a href="${escapeAttrSafe(href)}" target="_blank" rel="noopener">${fname}</a></li>`);
  };
  add(fb.calculated_sheet, "calculated-sheet", "管理员自算表格");
  add(fb.sales_original_sheet, "sales-sheet", "原始业务员表格");
  add(fb.corrected_sheet, "correction-sheet", "修正版附件");
  if (!links.length) return "";
  return `<div class="admin-correction-attachments"><h4 class="admin-correction-attach-title">附件</h4><ul class="admin-correction-attach-list">${links.join("")}</ul></div>`;
}

function buildAdminUpdateDiffHtml(fb) {
  const diff = fb?.bom_diff;
  const lines = Array.isArray(diff?.lines) ? diff.lines : [];
  if (!lines.length) return "";
  return `<div class="admin-updates-diff"><h4 class="admin-updates-diff-title">修改摘要</h4><ul class="admin-updates-diff-list">${lines
    .map((line) => `<li>${escapeHtml(String(line))}</li>`)
    .join("")}</ul></div>`;
}

function buildAdminProblemTypesHtml(fb) {
  const labels = Array.isArray(fb?.correction_problem_types_label)
    ? fb.correction_problem_types_label
    : [];
  if (!labels.length) return "";
  return `<p class="admin-updates-problem-types"><strong>问题类型：</strong>${labels.map((t) => escapeHtml(String(t))).join("、")}</p>`;
}

function buildAdminApprovalHtml(fb) {
  if (!fb || typeof fb !== "object") return "";
  const status = normalizeQuoteApprovalKey(fb.approval_status);
  if (status !== "approved" && status !== "rejected") return "";
  const note = String(fb.rejection_reason || fb.approval_note || fb.correction_note || "").trim();
  const label = status === "rejected" ? "驳回原因" : "审批说明";
  const statusLabel = status === "rejected" ? "未通过" : "已通过";
  const noteHtml = note
    ? `<p class="admin-updates-detail-note"><strong>${escapeHtml(label)}：</strong>${escapeHtml(note)}</p>`
    : `<p class="admin-updates-detail-note muted">暂无${escapeHtml(label)}</p>`;
  return `<section class="admin-updates-approval-block">
    <p class="admin-updates-approval-status"><strong>审批结果：</strong><span class="my-quotes-status ${status}">${escapeHtml(statusLabel)}</span></p>
    ${noteHtml}
  </section>`;
}

function renderAdminUpdateDetail(detail) {
  if (!els.adminUpdatesDetail) return;
  const uid = String(
    state.activeAdminUpdateUid || detail?.quote_series_uid || "",
  ).trim();
  const fb = detail?.admin_feedback;
  if (!uid || !fb || typeof fb !== "object") {
    console.warn("[admin-updates] skip empty detail render", {
      activeAdminUpdateUid: state.activeAdminUpdateUid,
      uid,
      hasDetail: !!detail,
      hasFeedback: !!fb,
    });
    els.adminUpdatesDetail.innerHTML = `<p class="admin-updates-empty">暂无修正详情</p>`;
    return;
  }
  const noteText = String(fb.correction_note || fb.rejection_reason || "").trim();
  const hasVisualCorrection = adminCorrectionHasVisualResult(fb);
  const noteFallback = noteText || (hasVisualCorrection ? "管理员已更新修正版" : "暂无文字说明");
  const note = escapeHtml(noteFallback);
  const metaParts = [];
  if (fb.feedback_by || fb.approved_by) {
    metaParts.push(`处理人 ${escapeHtml(fb.feedback_by || fb.approved_by)}`);
  }
  const at = String(fb.feedback_at || fb.admin_update_at || fb.approved_at || "").replace("T", " ").slice(0, 19);
  if (at) metaParts.push(`处理时间 ${escapeHtml(at)}`);
  const pending = fb.has_admin_update || fb.admin_update_status === "pending_view";
  let amountHtml = "";
  if (hasVisualCorrection) {
    amountHtml = `<dl class="admin-correction-amount-grid admin-updates-amount-grid">
      <div><dt>原报价金额</dt><dd>${escapeHtml(String(fb.original_amount_text || "-"))}</dd></div>
      <div><dt>修正后金额</dt><dd><strong>${escapeHtml(String(fb.corrected_amount_text || "-"))}</strong></dd></div>
      <div><dt>差额</dt><dd>${escapeHtml(String(fb.amount_delta_text || "-"))}</dd></div>
    </dl>`;
  }
  let quoteHtml = "";
  if (hasVisualCorrection) {
    quoteHtml = `<div class="admin-updates-quote-card"><h4 class="admin-updates-quote-title">修正后可视化报价</h4><div class="quote-card quote-card-inbox">${buildQuoteCardInnerHtml(
      fb.admin_corrected_quote_result,
      detail.sheet_original_name || "",
      `admin-update-${uid}`,
      { displayTitle: "管理员修正版" },
    )}</div></div>`;
  }
  const visualActions = hasVisualCorrection
    ? `<button type="button" class="admin-correction-action" data-action="view-corrected-quote" data-series-uid="${escapeHtml(uid)}">查看修正后报价</button>
       <button type="button" class="admin-correction-action admin-correction-action-primary" data-action="quote-sheet-corrected" data-series-uid="${escapeHtml(uid)}">用修正结果生成报价单</button>
       <button type="button" class="admin-correction-action" data-action="quote-sheet-pdf-corrected" data-series-uid="${escapeHtml(uid)}">导出最终 PDF</button>`
    : "";
  els.adminUpdatesDetail.innerHTML = `
    <section class="admin-updates-detail-head">
      <h3 class="admin-updates-detail-title">管理员修正详情</h3>
      ${pending ? `<span class="admin-correction-pending-badge">未读</span>` : ""}
    </section>
    ${buildAdminApprovalHtml(fb)}
    <p class="admin-updates-detail-note"><strong>修正说明：</strong>${note}</p>
    ${buildAdminProblemTypesHtml(fb)}
    ${metaParts.length ? `<p class="admin-updates-detail-meta muted">${metaParts.join(" · ")}</p>` : ""}
    ${amountHtml}
    ${hasVisualCorrection ? buildAdminUpdateDiffHtml(fb) : ""}
    ${quoteHtml}
    ${buildAdminUpdateAttachmentsHtml(fb, uid)}
    <div class="admin-updates-detail-actions">
      ${visualActions}
      <button type="button" class="admin-correction-action" data-action="mark-handled" data-series-uid="${escapeHtml(uid)}">我已知晓</button>
    </div>`;
}

async function openAdminUpdateDetail(seriesUid) {
  const uid = String(seriesUid || "").trim();
  if (!uid) {
    console.warn("[admin-updates] skip empty detail render", { seriesUid, reason: "no_uid" });
    return;
  }
  if (state.currentView !== "adminUpdates") {
    switchWorkspaceView("adminUpdates");
  }
  state.activeAdminUpdateUid = uid;
  if (els.adminUpdatesListView) els.adminUpdatesListView.hidden = true;
  if (els.adminUpdatesDetailView) els.adminUpdatesDetailView.hidden = false;
  if (els.adminUpdatesDetail) {
    els.adminUpdatesDetail.innerHTML = `<p class="admin-updates-empty">加载详情中…</p>`;
  }
  try {
    const res = await quoteFetch(`/api/my/quotes/${encodeURIComponent(uid)}`);
    const detail = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(detail.message || detail.error || `HTTP ${res.status}`);
    if (detail.latest_quote_result) {
      applyAdminFeedbackFields(detail.latest_quote_result, detail.admin_feedback);
    }
    renderAdminUpdateDetail(detail);
    const fb = detail.admin_feedback;
    if (fb && (fb.has_admin_update || fb.admin_update_status === "pending_view")) {
      await markMyQuoteAdminUpdateViewed(uid);
      renderAdminUpdatesList(getVisibleAdminUpdatesItems());
      updateAdminUpdatesStats(state.adminUpdatesItems);
    }
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    if (els.adminUpdatesDetail) {
      els.adminUpdatesDetail.innerHTML = `<p class="admin-updates-empty">加载失败：${escapeHtml(msg)}</p>`;
    }
  }
}

async function markAdminUpdateHandled(seriesUid) {
  const uid = String(seriesUid || "").trim();
  if (!uid) return;
  try {
    const res = await quoteFetch(`/api/my/quotes/${encodeURIComponent(uid)}/admin-update/handled`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.message || data.error || `HTTP ${res.status}`);
    syncAdminUpdateItemFromFeedback(uid, data.admin_feedback);
    renderAdminUpdatesList(getVisibleAdminUpdatesItems());
    updateAdminUpdatesStats(state.adminUpdatesItems);
    void refreshAdminUpdatesBadge();
    setComposerStatusLine("已标记为已处理", "ok");
    if (state.activeAdminUpdateUid === uid) {
      const res2 = await quoteFetch(`/api/my/quotes/${encodeURIComponent(uid)}`);
      const detail = await res2.json().catch(() => ({}));
      if (res2.ok) renderAdminUpdateDetail(detail);
    }
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    setComposerStatusLine(`操作失败：${msg}`, "err");
  }
}

function bindAdminUpdatesUi() {
  if (els.navAdminUpdates) {
    els.navAdminUpdates.addEventListener("click", () => switchWorkspaceView("adminUpdates"));
  }
  if (els.btnAdminUpdatesBanner) {
    els.btnAdminUpdatesBanner.addEventListener("click", () => switchWorkspaceView("adminUpdates"));
  }
  if (els.btnAdminUpdatesBack) {
    els.btnAdminUpdatesBack.addEventListener("click", () => {
      showAdminUpdatesListView();
      renderAdminUpdatesList(getVisibleAdminUpdatesItems());
    });
  }
  if (els.adminUpdatesReadFilter) {
    els.adminUpdatesReadFilter.addEventListener("change", () => {
      state.adminUpdatesReadFilter = String(els.adminUpdatesReadFilter.value || "").trim();
      clearAdminUpdatesSelection();
      renderAdminUpdatesList(getVisibleAdminUpdatesItems());
    });
  }
  if (els.adminUpdatesSelectAll) {
    els.adminUpdatesSelectAll.addEventListener("change", (ev) => {
      setAdminUpdatesSelectAll(!!ev.target.checked);
    });
  }
  if (els.btnAdminUpdatesBatchCancel) {
    els.btnAdminUpdatesBatchCancel.addEventListener("click", () => clearAdminUpdatesSelection());
  }
  if (els.btnAdminUpdatesBatchMarkRead) {
    els.btnAdminUpdatesBatchMarkRead.addEventListener("click", () => {
      void batchMarkAdminUpdatesRead();
    });
  }
  if (els.btnAdminUpdatesBatchDelete) {
    els.btnAdminUpdatesBatchDelete.addEventListener("click", () => {
      void batchDeleteAdminUpdates();
    });
  }
  if (els.adminUpdatesList) {
    els.adminUpdatesList.addEventListener("change", (ev) => {
      const cb = ev.target.closest(".admin-updates-row-check");
      if (!cb) return;
      ev.stopPropagation();
      toggleAdminUpdateSelection(cb.getAttribute("data-series-uid"), cb.checked);
    });
    els.adminUpdatesList.addEventListener("click", (ev) => {
      if (ev.target.closest(".admin-updates-row-check-wrap") || ev.target.closest(".admin-updates-row-check")) {
        return;
      }
      const actionBtn = ev.target.closest("[data-action]");
      if (actionBtn) {
        const action = String(actionBtn.getAttribute("data-action") || "").trim();
        const uid = String(actionBtn.getAttribute("data-series-uid") || "").trim();
        if (action === "quote-sheet-corrected" && uid) {
          ev.preventDefault();
          void openQuoteSheetFromRecord(uid, { source: "admin_corrected" });
          return;
        }
        if (action === "quote-sheet-pdf-corrected" && uid) {
          ev.preventDefault();
          void openQuoteSheetFromRecord(uid, {
            source: "admin_corrected",
            exportMode: "pdf_rmb",
          });
          return;
        }
        if (action === "open-detail" && uid) {
          ev.preventDefault();
          void openAdminUpdateDetail(uid);
          return;
        }
      }
      const row = ev.target.closest(".admin-updates-row[data-series-uid]");
      const uid = String(row && row.getAttribute("data-series-uid") || "").trim();
      if (uid) void openAdminUpdateDetail(uid);
    });
  }
  if (els.adminUpdatesDetail) {
    els.adminUpdatesDetail.addEventListener("click", (ev) => {
      const btn = ev.target.closest("[data-action]");
      if (!btn) return;
      const action = String(btn.getAttribute("data-action") || "").trim();
      const uid = String(btn.getAttribute("data-series-uid") || state.activeAdminUpdateUid || "").trim();
      if (action === "quote-sheet-corrected" && uid) {
        void openQuoteSheetFromRecord(uid, { source: "admin_corrected" });
        return;
      }
      if (action === "quote-sheet-pdf-corrected" && uid) {
        void openQuoteSheetFromRecord(uid, {
          source: "admin_corrected",
          exportMode: "pdf_rmb",
        });
        return;
      }
      if (action === "view-corrected-quote") {
        const card = els.adminUpdatesDetail?.querySelector(".admin-updates-quote-card");
        card?.scrollIntoView({ behavior: "smooth", block: "start" });
        return;
      }
      if (action === "mark-handled" && uid) {
        void markAdminUpdateHandled(uid);
      }
    });
  }
}

function buildQuoteApprovalBannerHtml(quote) {
  const key = normalizeQuoteApprovalKey(quote?.approval_status);
  const note = String(quote?.approval_note || quote?.approval_comment || "").trim();
  const at = String(quote?.approved_at || "").trim();
  const byRaw = String(quote?.approved_by || "").trim();
  const by =
    byRaw && byRaw.toLowerCase() !== "admin" && byRaw.toLowerCase() !== "administrator"
      ? byRaw
      : "";
  let cls = "quote-approval-banner quote-approval-pending";
  let main = "管理员尚未审批";
  let extra = "";
  if (key === "approved") {
    cls = "quote-approval-banner quote-approval-approved";
    main = "管理员已通过";
  } else if (key === "rejected") {
    cls = "quote-approval-banner quote-approval-rejected";
    main = note ? `管理员驳回：${note}` : "管理员已驳回";
    extra = note
      ? `<p class="quote-approval-note">${escapeHtml(note)}</p>`
      : `<p class="quote-approval-note muted">（后台未填写驳回原因）</p>`;
  }
  const metaParts = [];
  if (at) metaParts.push(`核实时间：${escapeHtml(at)}`);
  if (by) metaParts.push(`核实人：${escapeHtml(by)}`);
  const meta =
    metaParts.length > 0
      ? `<p class="quote-approval-meta muted">${metaParts.join(" · ")}</p>`
      : "";
  return `<div class="${cls}" role="status" aria-label="报价表后台核实"><strong>${escapeHtml(main)}</strong>${extra}${meta}</div>`;
}

function formatValidationBadge(row) {
  const st = String(row?.validation_status || "OK").trim();
  const map = {
    OK: "通过",
    UNIT_CONFLICT: "冲突",
    INCOMPLETE: "待补全",
    HIGH_RISK: "高风险",
  };
  const label = map[st] || st;
  let cls = "validation-badge val-ok";
  if (st === "UNIT_CONFLICT" || st === "HIGH_RISK") cls = "validation-badge val-bad";
  else if (st === "INCOMPLETE") cls = "validation-badge val-warn";
  const detail = row?.validation_detail ? String(row.validation_detail).trim() : "";
  const titleAttr = detail ? ` title="${escapeHtml(detail)}"` : "";
  return `<span class="${cls}"${titleAttr}>${escapeHtml(label)}</span>`;
}

/** 数据提醒：过长时默认摘要 + 展开 */
function buildQuoteDataNoticeHtml(noticeText) {
  const t = String(noticeText || "").trim();
  if (!t) return "";
  const limit = 96;
  if (t.length <= limit) {
    return `<p class="note note-warn quote-data-notice">${escapeHtml(t)}</p>`;
  }
  return `
    <div class="quote-data-notice-wrap">
      <p class="note note-warn quote-data-notice quote-data-notice-preview">
        ${escapeHtml(t.slice(0, limit))}…
        <button type="button" class="link-inline quote-data-notice-toggle" aria-expanded="false">展开提醒</button>
      </p>
      <div class="note note-warn quote-data-notice quote-data-notice-full is-collapsed" hidden>${escapeHtml(t)}</div>
    </div>`;
}

/** 校验详情：仅在「查看详细校验」开启时展示（不占固定列） */
function buildQuoteMatMetaRowHtml(row) {
  const hints = Array.isArray(row.accuracy_hints) ? row.accuracy_hints.filter((h) => h != null && String(h).trim()) : [];
  const hintsBlock =
    hints.length > 0
      ? `<div class="quote-meta-block"><span class="quote-meta-k">准确性</span><ul class="quote-meta-hints">${hints
          .map((h) => `<li>${escapeHtml(String(h))}</li>`)
          .join("")}</ul></div>`
      : "";
  const vDetail = row.validation_detail
    ? `<div class="quote-meta-detail">${escapeHtml(String(row.validation_detail))}</div>`
    : "";
  const aiR = row.ai_reason ? `<div class="quote-meta-ai">${escapeHtml(String(row.ai_reason))}</div>` : "";
  const kbAuto = row.kb_auto_learned
    ? `<div class="quote-meta-block"><span class="quote-meta-k">知识库标记</span> <span class="quote-kb-new-text">自动回流补录</span></div>`
    : "";
  const amb = row.ambiguous_material_classification;
  let ambBlock = "";
  if (amb && typeof amb === "object") {
    const detected = escapeHtml(String(amb.detected_text || row.name || "—"));
    const category = escapeHtml(String(amb.resolved_category || "—"));
    const basis = escapeHtml(String(amb.calculation_basis || "—"));
    const notice = escapeHtml(String(amb.user_notice || ""));
    const conf =
      amb.confidence != null && Number.isFinite(Number(amb.confidence))
        ? `${Math.round(Number(amb.confidence) * 100)}%`
        : "—";
    const needsConfirm = amb.needs_confirmation === true;
    const participates = amb.participates_in_cost === false ? "未参与报价" : "已参与报价";
    const confirmBadge = needsConfirm
      ? `<span class="quote-amb-badge quote-amb-badge--warn">需人工确认</span>`
      : `<span class="quote-amb-badge quote-amb-badge--ok">已归类</span>`;
    ambBlock = `<div class="quote-meta-block quote-meta-amb">
      <span class="quote-meta-k">歧义归类</span> ${confirmBadge}
      <ul class="quote-meta-amb-list">
        <li><span class="quote-meta-amb-k">识别词</span> ${detected}</li>
        <li><span class="quote-meta-amb-k">归类</span> ${category}</li>
        <li><span class="quote-meta-amb-k">计算依据</span> ${basis}</li>
        <li><span class="quote-meta-amb-k">置信度</span> ${escapeHtml(conf)} · ${escapeHtml(participates)}</li>
        ${notice ? `<li class="quote-meta-amb-notice">${notice}</li>` : ""}
      </ul>
    </div>`;
  }
  return `
    <tr class="quote-mat-meta-row is-collapsed" aria-hidden="true">
      <td colspan="5" class="quote-mat-meta-cell">
        <div class="quote-mat-meta-inner">
          <div class="quote-meta-block"><span class="quote-meta-k">数据来源</span> <span>${escapeHtml(String(row.data_origin_label || "—"))}</span></div>
          ${kbAuto}
          <div class="quote-meta-block"><span class="quote-meta-k">校验</span> ${formatValidationBadge(row)}</div>
          ${ambBlock}
          ${hintsBlock}
          ${vDetail}
          ${aiR}
        </div>
      </td>
    </tr>`;
}

function updateQuoteSheetNavFromPricingGate(pg) {
  const nav = document.getElementById("navQuoteSheet");
  if (!nav || nav.tagName !== "BUTTON") {
    return;
  }
  const flagged = pg && pg.final_price_allowed === false;
  nav.disabled = false;
  nav.classList.toggle("quote-nav-disabled", false);
  nav.title = flagged ? "当前报价含风险提醒，报价单可打开，导出前请复核明细" : "";
}

function syncPricingGateSnapshotFromQuote(result) {
  if (!result || typeof result !== "object") {
    return;
  }
  window.__pricingGateSnapshot = result.pricing_gate || null;
  updateQuoteSheetNavFromPricingGate(result.pricing_gate);
}

async function confirmPricingGateUnlock(btn) {
  if (state.isRequesting) {
    return;
  }
  setRequesting(true);
  try {
    const response = await quoteFetch("/api/session/pricing-gate/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const data = await readResponseJson(response);
    if (!response.ok || !data.ok) {
      throw new Error(data.error || data.message || `HTTP ${response.status}`);
    }
    const quote = data.quote;
    syncPricingGateSnapshotFromQuote(quote);
    const msgId =
      btn && btn.dataset && btn.dataset.msgId ? String(btn.dataset.msgId).trim() : "";
    const ctx = state.sessionContext;
    if (ctx?.quoteData && ctx.currentQuoteId && quote.quote_id === ctx.currentQuoteId) {
      Object.assign(ctx.quoteData, quote);
    }
    if (msgId) {
      const msg = state.messages.find((m) => m.msgId === msgId && m.type === "quote_card");
      if (msg && msg.data) {
        Object.assign(msg.data, quote);
      }
    }
    renderMessages();
    syncComposerPlaceholder();
    scrollToBottom();
  } catch (error) {
    const msg = humanizeNetworkError(error instanceof Error ? error : new Error(String(error)));
    addMessage("assistant", `解锁失败：${msg}`);
  } finally {
    setRequesting(false);
  }
}

async function patchStructureChecklistItem(btn) {
  if (state.isRequesting) {
    return;
  }
  const structureId = String(btn?.dataset?.structureId || "").trim();
  const action = String(btn?.dataset?.structureAction || "").trim();
  const msgId = String(btn?.dataset?.msgId || "").trim();
  if (!structureId || !action) {
    return;
  }
  setRequesting(true);
  try {
    const response = await quoteFetch("/api/session/structure-checklist/patch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        structure_id: structureId,
        user_status: action,
      }),
    });
    const data = await readResponseJson(response);
    if (!response.ok || !data.ok) {
      throw new Error(data.error || data.message || `HTTP ${response.status}`);
    }
    const quote = data.quote;
    syncPricingGateSnapshotFromQuote(quote);
    const ctx = state.sessionContext;
    if (ctx?.quoteData && ctx.currentQuoteId && quote.quote_id === ctx.currentQuoteId) {
      Object.assign(ctx.quoteData, quote);
    }
    if (msgId) {
      const msg = state.messages.find((m) => m.msgId === msgId && m.type === "quote_card");
      if (msg && msg.data) {
        Object.assign(msg.data, quote);
      }
    }
    renderMessages();
    syncComposerPlaceholder();
    scrollToBottom();
  } catch (error) {
    const msg = humanizeNetworkError(error instanceof Error ? error : new Error(String(error)));
    addMessage("assistant", `结构清单更新失败：${msg}`);
  } finally {
    setRequesting(false);
  }
}

function cleanDetailRowsForDisplay(rows) {
  if (!Array.isArray(rows)) {
    return [];
  }
  const result = [];
  const seen = new Set();
  for (const row of rows) {
    if (!row || typeof row !== "object") {
      continue;
    }
    const name = String(row.name || "").trim();
    const spec = String(row.spec || "-").trim() || "-";
    if (!isValidDisplayMaterialName(name)) {
      continue;
    }
    const dedupeKey = `${name.toLowerCase()}|${spec.toLowerCase()}`;
    if (seen.has(dedupeKey)) {
      continue;
    }
    seen.add(dedupeKey);
    const usageRaw = String(row.usage || "-").trim() || "-";
    const specDisp =
      spec === "-" ? "-" : formatMeasureNumbersTwoDecimals(spec);
    result.push({
      ...row,
      name,
      spec: specDisp,
      usage: formatMeasureNumbersTwoDecimals(usageRaw),
      unit_price: formatNumbersInDisplayText(String(row.unit_price || "-").replaceAll("(AI)", "")),
      amount_text: formatNumbersInDisplayText(String(row.amount_text || "-").replaceAll("(AI)", "")),
    });
  }
  return result;
}

function isValidDisplayMaterialName(name) {
  const text = String(name || "").trim();
  if (!text) {
    return false;
  }
  const lowered = text.toLowerCase();
  const blocked = ["图片", "报价资料", "填写说明", "版本"];
  if (blocked.some((kw) => lowered.includes(kw))) {
    return false;
  }
  if (/^-?\d+(\.\d+)?$/.test(text)) {
    return false;
  }
  if (/[元¥￥]/.test(text) && /^\s*(?:￥|¥)?\s*-?\d+(?:\.\d+)?\s*(?:元)?\s*(?:\/\s*[\u4e00-\u9fffA-Za-z0-9#]+)?\s*$/.test(text)) {
    return false;
  }
  return true;
}

function parseAmountValue(value) {
  const text = String(value ?? "").trim();
  if (!text) {
    return 0;
  }
  const cleaned = text.replaceAll(",", "").replace(/[^\d.-]/g, "");
  const parsed = Number.parseFloat(cleaned);
  return Number.isFinite(parsed) ? parsed : 0;
}

function focusTrialQuantityInput() {
  if (!els.userPrompt) {
    return;
  }
  els.userPrompt.placeholder = "试算其他数量，如600件";
  els.userPrompt.focus();
}

function focusTrialMaterialInput() {
  if (!els.userPrompt) {
    return;
  }
  els.userPrompt.placeholder = "试算其他材料，如「里料换涤纶」";
  els.userPrompt.focus();
}

async function confirmStructureAndQuote(btn) {
  const token = btn?.getAttribute("data-structure-confirm-token") || "";
  const pending = state.pendingStructureConfirm;
  if (!pending || pending.token !== token) {
    addMessage("assistant", "结构确认已过期，请重新上传表格。");
    return;
  }
  if (pending.structureEditMode || !pending.structureSavedForQuote) {
    addMessage("assistant", "请先点击「保存」，保存明细修改后再开始报价。");
    return;
  }
  const incompleteGaps = getIncompleteStructureGapRows(pending);
  if (incompleteGaps.length > 0) {
    const names = incompleteGaps
      .map((g) => g.name)
      .filter(Boolean)
      .slice(0, 3)
      .join("、");
    const tail = names ? `（${names}）` : "";
    addMessage(
      "assistant",
      `还有 ${incompleteGaps.length} 行结构缺项未能自动估算用量/单价${tail}。请手动补全并保存，或取消勾选「加入正式 BOM」后再生成正式报价。`,
    );
    setComposerStatusLine("部分缺项无法自动估算，请补全用量/单价或取消勾选。", "warn");
    return;
  }
  setRequesting(true);
  setComposerStatusLine("已确认结构，正在生成正式报价…", "busy");
  btn.disabled = true;
  btn.textContent = "正在生成报价…";
  const loadingToken = newLoadingToken();
  state.messages.push({
    role: "assistant",
    type: "loading_quote",
    loadingToken,
    text: "已确认结构，正在核算正式报价…",
    time: formatNowTime(),
  });
  renderMessages();
  scrollToBottom();
  try {
    const patchItems = buildStructureConfirmationItemsForQuote(pending);
    const aiEstimateCount = countStructureGapAiEstimateRows(pending);
    const payloadExtra = {
      structure_confirmed: true,
      structure_confirmed_by_user: true,
      allow_estimate_with_incomplete_items: true,
    };
    if (aiEstimateCount > 0) {
      payloadExtra.structure_ai_estimate_count = aiEstimateCount;
    }
    if (patchItems.length > 0) {
      payloadExtra.structure_confirmation_items = patchItems;
      payloadExtra.items = patchItems.filter((row) => row && row.deleted !== true);
    }
    if (pending.data?.structure_checklist) {
      payloadExtra.structure_checklist = pending.data.structure_checklist;
    }
    ensurePendingStructureGapState(pending);
    const confirmedGapIds = getConfirmedStructureGapIdList(pending);
    if (confirmedGapIds.length > 0) {
      payloadExtra.confirmed_structure_gap_ids = confirmedGapIds;
    }
    if (Array.isArray(pending.data?.structure_gap_hints) && pending.data.structure_gap_hints.length > 0) {
      payloadExtra.structure_gap_hints = pending.data.structure_gap_hints;
    }
    const attSnap = Array.isArray(pending.attachments)
      ? pending.attachments.map((a) => ({ ...a }))
      : [];
    const payload = buildQuoteRequestPayload(pending.prompt || "确认结构并报价", attSnap, payloadExtra);
    const response = await quoteFetchWithTimeout("/api/quote", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await readResponseJson(response);
    if (!response.ok) {
      throw new Error(result.message || result.error || `请求失败（HTTP ${response.status}）`);
    }
    if (result.quote_ready === false) {
      replaceLoadingByToken(loadingToken, {
        role: "assistant",
        type: "text",
        text: result.assistant_message || "结构已确认，但仍未生成报价，请检查表格数据。",
      });
      return;
    }
    state.pendingStructureConfirm = null;
    applyLlmResponseMeta(result);
    const primaryMsgId = newQuoteMsgId();
    replaceLoadingByToken(loadingToken, {
      role: "assistant",
      type: "quote_card",
      subtype: "primary",
      fileName: pending.fileName || "",
      data: result,
      msgId: primaryMsgId,
    });
    if (result.quote_id) {
      state.sessionContext = {
        currentQuoteId: result.quote_id,
        fileName: pending.fileName || "",
        quoteData: result,
        primaryQuoteMsgId: primaryMsgId,
      };
    }
    syncPricingGateSnapshotFromQuote(result);
    setComposerStatusLine("结构已确认，正式报价已生成", "ok");
  } catch (error) {
    const message = humanizeQuoteFetchError(error instanceof Error ? error : new Error(String(error)));
    replaceLoadingByToken(loadingToken, {
      role: "assistant",
      type: "text",
      text: `确认结构后生成报价失败：${message}`,
    });
    setComposerStatusLine(`生成报价失败：${message}`, "err");
  } finally {
    setRequesting(false);
    if (state.pendingStructureConfirm && state.pendingStructureConfirm.token === token) {
      renderMessages();
      scrollToBottom();
    }
  }
}

async function promoteMaterialToPrimary(msgId) {
  const target = findQuoteMessageByMsgId(msgId);
  const items = target?.trialItemsSnapshot;
  if (!items || !Array.isArray(items) || !items.length) {
    addMessage("assistant", "无法以此方案为准：缺少试算物料明细，请重新试算。");
    return;
  }
  if (state.isRequesting) {
    return;
  }
  setRequesting(true);
  try {
    const response = await quoteFetchWithTimeout("/api/quote", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...state.baseConfig,
        client_action: "promote_material_to_primary",
        trial_items: items,
        session_context: buildSessionContext(),
      }),
    });
    const result = await readResponseJson(response);
    if (!response.ok) {
      throw new Error(result.message || result.error || `请求失败（HTTP ${response.status}）`);
    }
    if (result.quote_ready === false) {
      addMessage("assistant", result.assistant_message || "升级主报价失败。");
      return;
    }
    state.llmStatus = result.llm_status || null;
    renderLlmStatus();
    const primaryMsgId = newQuoteMsgId();
    state.messages.push({
      role: "assistant",
      type: "quote_card",
      subtype: "primary",
      fileName: state.sessionContext?.fileName || "",
      data: result,
      msgId: primaryMsgId,
      time: formatNowTime(),
    });
    if (result.quote_id) {
      state.sessionContext = {
        ...state.sessionContext,
        currentQuoteId: result.quote_id,
        quoteData: result,
        primaryQuoteMsgId: primaryMsgId,
      };
    }
    syncPricingGateSnapshotFromQuote(result);
    renderMessages();
    syncComposerPlaceholder();
    scrollToBottom();
  } catch (error) {
    const message = humanizeNetworkError(error instanceof Error ? error : new Error(String(error)));
    addMessage("assistant", `升级主报价失败：${message}`);
  } finally {
    setRequesting(false);
  }
}

async function promoteExtraToPrimary(calcQty) {
  if (state.isRequesting || !calcQty) {
    return;
  }
  setRequesting(true);
  try {
    const response = await quoteFetchWithTimeout("/api/quote", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...state.baseConfig,
        client_action: "promote_extra_to_primary",
        promote_quantity: calcQty,
        session_context: buildSessionContext(),
      }),
    });
    const result = await readResponseJson(response);
    if (!response.ok) {
      throw new Error(result.message || result.error || `请求失败（HTTP ${response.status}）`);
    }
    if (result.quote_ready === false) {
      addMessage("assistant", result.assistant_message || "升级主报价失败。");
      return;
    }
    state.llmStatus = result.llm_status || null;
    renderLlmStatus();
    const primaryMsgId = newQuoteMsgId();
    state.messages.push({
      role: "assistant",
      type: "quote_card",
      subtype: "primary",
      fileName: state.sessionContext?.fileName || "",
      data: result,
      msgId: primaryMsgId,
      time: formatNowTime(),
    });
    if (result.quote_id) {
      state.sessionContext = {
        ...state.sessionContext,
        currentQuoteId: result.quote_id,
        quoteData: result,
        primaryQuoteMsgId: primaryMsgId,
      };
    }
    syncPricingGateSnapshotFromQuote(result);
    renderMessages();
    syncComposerPlaceholder();
    scrollToBottom();
  } catch (error) {
    const message = humanizeNetworkError(error instanceof Error ? error : new Error(String(error)));
    addMessage("assistant", `升级主报价失败：${message}`);
  } finally {
    setRequesting(false);
  }
}

function approvalStatusLabelCn(raw) {
  const key = normalizeQuoteApprovalKey(raw);
  if (key === "approved") return "已通过";
  if (key === "rejected") return "已驳回";
  return "待审批";
}

function serializeMessageForPersist(msg) {
  if (!msg || typeof msg !== "object") return null;
  if (msg.type === "loading_quote") return null;
  const mid =
    String(msg.msgId || msg.message_id || "").trim() ||
    `m-${String(msg.role || "assistant")}-${String(msg.time || Date.now())}`;
  const meta = {
    type: msg.type || "text",
    msgId: msg.msgId || mid,
    fileName: msg.fileName || "",
    subtype: msg.subtype || "",
    replyType: msg.replyType || "",
  };
  if (msg.type === "quote_card" && msg.data) {
    meta.quote_id = msg.data.quote_id || "";
    meta.quote_series_uid = msg.data.quote_series_uid || "";
  }
  return {
    message_id: mid,
    role: msg.role || "assistant",
    content: String(msg.text || msg.content || ""),
    metadata: meta,
    created_at: msg.time || "",
  };
}

let persistQuoteMessagesTimer = null;

function schedulePersistQuoteSessionMessages(seriesUid) {
  if (!seriesUid) return;
  if (persistQuoteMessagesTimer) {
    clearTimeout(persistQuoteMessagesTimer);
  }
  persistQuoteMessagesTimer = setTimeout(() => {
    persistQuoteMessagesTimer = null;
    void persistQuoteSessionMessages(seriesUid);
  }, 600);
}

async function persistQuoteSessionMessages(seriesUid) {
  const uid = String(seriesUid || "").trim();
  if (!uid) return;
  const messages = state.messages.map(serializeMessageForPersist).filter(Boolean);
  if (!messages.length) return;
  try {
    await quoteFetch("/api/quote/messages", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ quote_series_uid: uid, messages }),
    });
  } catch {
    // ignore background persist errors
  }
}

async function fetchAuthStatus() {
  try {
    const res = await quoteFetch("/api/auth/status");
    const data = await res.json().catch(() => ({}));
    if (res.ok && data && typeof data === "object") {
      state.authStatus = data;
      renderWecomEntryGate();
      renderWecomAuthBanner();
      syncWecomComposerHints();
      handleWecomAuthUrlErrors();
      maybeAutoWecomLogin();
    } else if (!res.ok && data && typeof data === "object") {
      const text = String(data.message || data.error || `认证状态获取失败（HTTP ${res.status}）`);
      setComposerStatusLine(text, "err", { ttlMs: 10000 });
    }
  } catch (error) {
    const msg = humanizeNetworkError(error instanceof Error ? error : new Error(String(error)));
    setComposerStatusLine(`无法获取登录状态：${msg}`, "err", { ttlMs: 8000 });
  }
}

function wecomLoginUrl() {
  const st = state.authStatus;
  return String(st?.login_url || "/api/auth/wecom/login").trim() || "/api/auth/wecom/login";
}

function renderWecomAuthBanner() {
  const st = state.authStatus;
  if (!st || !st.wecom_enabled) {
    document.getElementById("wecomAuthBanner")?.remove();
    document.getElementById("wecomAuthBannerMyQuotes")?.remove();
    return;
  }
  const mountBanner = (anchorEl, id) => {
    if (!anchorEl || !anchorEl.parentNode) {
      return null;
    }
    let banner = document.getElementById(id);
    if (!banner) {
      banner = document.createElement("div");
      banner.id = id;
      banner.className = "wecom-auth-banner";
      anchorEl.parentNode.insertBefore(banner, anchorEl.nextSibling);
    }
    return banner;
  };
  const chatBanner = mountBanner(document.querySelector(".chat-header"), "wecomAuthBanner");
  const myQuotesBanner = mountBanner(
    document.querySelector(".my-quotes-page-head"),
    "wecomAuthBannerMyQuotes",
  );
  const banners = [chatBanner, myQuotesBanner].filter(Boolean);
  if (!banners.length) {
    return;
  }
  if (st.authenticated) {
    const who = String(st.sales_user_name || st.sales_user_id || "").trim();
    const html = `<span class="wecom-auth-banner-text">已登录：${escapeHtml(who)}</span> <a class="link-inline wecom-auth-logout" href="/api/auth/wecom/logout">退出</a>`;
    for (const banner of banners) {
      banner.innerHTML = html;
      banner.classList.remove("wecom-auth-warn");
    }
    return;
  }
  const loginUrl = escapeHtml(wecomLoginUrl());
  const msg = escapeHtml(wecomLoginRequiredUserMessage());
  const html = `<span class="wecom-auth-banner-text">${msg}</span> <a class="btn-wecom-login" href="${loginUrl}">企业微信登录</a>`;
  for (const banner of banners) {
    banner.innerHTML = html;
    banner.classList.add("wecom-auth-warn");
  }
}

function syncWecomComposerHints() {
  const st = state.authStatus;
  if (!state.isWecomBrowser || !st?.wecom_enabled) {
    document.getElementById("composerWecomUploadHint")?.remove();
    return;
  }
  if (!els.composerDock) {
    return;
  }
  let hint = document.getElementById("composerWecomUploadHint");
  if (!hint) {
    hint = document.createElement("p");
    hint.id = "composerWecomUploadHint";
    hint.className = "composer-wecom-upload-hint";
    const stack = els.composerDock.querySelector(".composer-stack");
    if (stack) {
      stack.insertBefore(hint, stack.firstChild);
    } else {
      els.composerDock.prepend(hint);
    }
  }
  hint.textContent =
    "企业微信内上传：若从聊天文件选择失败，请先将表格保存到手机，再通过「+ → 上传表格」从本机选择。";
}

function renderMyQuotesAuthBlocked(message) {
  const text = escapeHtml(message || wecomAuthExpiredUserMessage());
  const loginUrl = escapeHtml(wecomLoginUrl());
  const loginBtn =
    state.authStatus?.wecom_enabled && !state.authStatus?.authenticated
      ? `<a class="btn-wecom-login my-quotes-auth-login" href="${loginUrl}">企业微信登录</a>`
      : "";
  return `<div class="my-quotes-auth-block"><p class="my-quotes-empty">${text}</p>${loginBtn}</div>`;
}

async function fetchMyQuotesList(statusFilter = "") {
  const qs = statusFilter ? `?status=${encodeURIComponent(statusFilter)}` : "";
  const res = await quoteFetch(`/api/my/quotes${qs}`);
  const data = await res.json().catch(() => ({}));
  throwIfSalesSyncAuthResponse(res, data);
  if (!res.ok) {
    throw new Error(data.message || data.error || `HTTP ${res.status}`);
  }
  return Array.isArray(data.items) ? data.items : [];
}

async function refreshMyQuotesPreview({ silent = false } = {}) {
  if (!els.myQuotesPreview) return;
  if (isFrontEntryBlocked()) {
    els.myQuotesPreview.textContent = WECOM_ENTRY_BLOCKED_MESSAGE;
    return;
  }
  const st = state.authStatus;
  if (st?.wecom_enabled && !st?.authenticated) {
    els.myQuotesPreview.textContent = "登录后可查看历史报价";
    return;
  }
  try {
    const items = await fetchMyQuotesList("");
    const pending = items.filter((it) => normalizeQuoteApprovalKey(it.approval_status) === "pending").length;
    els.myQuotesPreview.textContent =
      items.length > 0 ? `共 ${items.length} 条 · ${pending} 条待审批` : "查看历史报价与审批状态";
  } catch (error) {
    const code = error && typeof error === "object" ? error.code : "";
    handleSalesSyncFetchError(error, { allowNetworkHint: !silent || code === "auth_required" });
    if (!String(els.myQuotesPreview.textContent || "").trim()) {
      els.myQuotesPreview.textContent = "查看历史报价与审批状态";
    }
  }
}

function countMyQuotesByStatus(items) {
  const counts = { all: items.length, pending: 0, approved: 0, rejected: 0 };
  for (const it of items) {
    const k = normalizeQuoteApprovalKey(it.approval_status);
    if (k === "pending" || k === "approved" || k === "rejected") {
      counts[k] += 1;
    }
  }
  return counts;
}

function formatMyQuoteTimestamp(it) {
  return String(it.created_at || it.updated_at || "")
    .replace("T", " ")
    .replace("Z", "")
    .slice(0, 19);
}

function deriveMyQuoteRiskHint(it) {
  const status = normalizeQuoteApprovalKey(it.approval_status);
  const comment = String(it.approval_comment || "").trim();
  const hasUpdate = !!(it.has_admin_update || it.admin_update_status === "pending_view");
  if (hasUpdate) {
    if (status === "rejected") {
      return comment
        ? `审批未通过：${comment.slice(0, 72)} · 请至「管理员修正」查看`
        : "审批未通过，请至「管理员修正」查看驳回原因";
    }
    if (status === "approved") {
      return comment
        ? `审批已通过：${comment.slice(0, 72)}`
        : "审批已通过，请查看审批结果";
    }
    return "管理员有新的修正或反馈，请及时查看";
  }
  if (status === "rejected" && comment) {
    return `驳回：${comment.slice(0, 72)} · 请至「管理员修正」查看原因`;
  }
  if (status === "pending") {
    if (comment) {
      return comment.slice(0, 72);
    }
    return "等待管理员审批";
  }
  return "";
}

function deriveMyQuoteUpdateBadge(it) {
  const hasUpdate = !!(it.has_admin_update || it.admin_update_status === "pending_view");
  if (!hasUpdate) return "";
  const status = normalizeQuoteApprovalKey(it.approval_status);
  if (status === "rejected") return "查看原因";
  if (status === "approved") return "有新审批";
  return "有新修正";
}

function renderMyQuotesStats(items) {
  if (!els.myQuotesStats) return;
  const counts = countMyQuotesByStatus(items);
  if (!items.length) {
    els.myQuotesStats.textContent = "暂无报价记录";
    return;
  }
  els.myQuotesStats.textContent =
    `全部 ${counts.all} · 待审批 ${counts.pending} · 已通过 ${counts.approved} · 已驳回 ${counts.rejected}`;
}

function filterMyQuotesItems(items, query) {
  const q = String(query || "").trim().toLowerCase();
  if (!q) {
    return items;
  }
  return items.filter((it) => {
    const hay = [
      it.product_name,
      it.sheet_original_name,
      it.quote_id,
      it.quote_series_uid,
    ]
      .map((s) => String(s || "").toLowerCase())
      .join(" ");
    return hay.includes(q);
  });
}

function getVisibleMyQuotesItems() {
  const base = Array.isArray(state.myQuotesItems) ? state.myQuotesItems : [];
  return filterMyQuotesItems(base, state.myQuotesSearch);
}

function updateMyQuotesBatchUi() {
  const count = state.myQuotesSelectedUids.size;
  if (els.myQuotesBatchBar) {
    els.myQuotesBatchBar.hidden = !state.myQuotesBatchMode;
  }
  if (els.btnMyQuotesManage) {
    els.btnMyQuotesManage.hidden = state.myQuotesBatchMode;
  }
  if (els.myQuotesBatchCount) {
    els.myQuotesBatchCount.textContent = `已选择 ${count} 条`;
  }
  if (els.btnMyQuotesBatchDelete) {
    els.btnMyQuotesBatchDelete.disabled = count === 0;
  }
  const toolbar = document.querySelector(".my-quotes-toolbar");
  if (toolbar) {
    toolbar.classList.toggle("is-batch-hidden", state.myQuotesBatchMode);
  }
}

function enterMyQuotesBatchMode() {
  state.myQuotesBatchMode = true;
  state.myQuotesSelectedUids = new Set();
  renderMyQuotesPageFromCache();
}

function exitMyQuotesBatchMode() {
  state.myQuotesBatchMode = false;
  state.myQuotesSelectedUids = new Set();
  renderMyQuotesPageFromCache();
}

function toggleMyQuotesSelection(uidRaw, checked) {
  const uid = String(uidRaw || "").trim();
  if (!uid) return;
  if (checked) {
    state.myQuotesSelectedUids.add(uid);
  } else {
    state.myQuotesSelectedUids.delete(uid);
  }
  renderMyQuotesList(getVisibleMyQuotesItems());
}

async function batchDeleteMyQuotes() {
  const uids = Array.from(state.myQuotesSelectedUids);
  if (!uids.length) return;
  const confirmed = window.confirm(
    `确定删除选中的 ${uids.length} 条报价记录吗？删除后将不会在我的报价记录中显示。`,
  );
  if (!confirmed) return;
  if (els.btnMyQuotesBatchDelete) {
    els.btnMyQuotesBatchDelete.disabled = true;
  }
  try {
    const res = await quoteFetch("/api/my/quotes/batch-delete", {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({ quote_uids: uids }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.status === 401) {
      const err = new Error(wecomAuthExpiredUserMessage());
      err.code = "auth_required";
      throw err;
    }
    if (!res.ok) {
      throw new Error(data.message || data.error || `HTTP ${res.status}`);
    }
    const hiddenUid = String(state.activeMyQuoteSeriesUid || "").trim();
    if (hiddenUid && uids.includes(hiddenUid)) {
      state.activeMyQuoteSeriesUid = "";
    }
    exitMyQuotesBatchMode();
    await loadMyQuotesPage(state.myQuotesFilter);
    void refreshMyQuotesPreview();
    const deleted = Number(data.deleted);
    setComposerStatusLine(
      `已删除 ${Number.isFinite(deleted) ? deleted : uids.length} 条报价记录`,
      "ok",
    );
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    setComposerStatusLine(`删除失败：${msg}`, "err");
    updateMyQuotesBatchUi();
  }
}

function renderMyQuotesList(items) {
  if (!els.myQuotesList) return;
  updateMyQuotesBatchUi();
  if (!items.length) {
    const emptyText = state.myQuotesSearch.trim()
      ? "没有匹配的报价记录。"
      : state.myQuotesBatchMode
        ? "当前没有可选择的报价记录。"
        : "暂无报价记录，上传表格后会自动保存到这里。";
    els.myQuotesList.innerHTML = `<p class="my-quotes-empty">${emptyText}</p>`;
    return;
  }
  const activeUid = String(state.activeMyQuoteSeriesUid || "").trim();
  const batchMode = !!state.myQuotesBatchMode;
  els.myQuotesList.innerHTML = items
    .map((it) => {
      const statusKey = normalizeQuoteApprovalKey(it.approval_status);
      const comment = String(it.approval_comment || "").trim();
      const title = escapeHtml(it.product_name || it.sheet_original_name || "未命名产品");
      const file = escapeHtml(it.sheet_original_name || "-");
      const quoteId = escapeHtml(it.quote_id || "-");
      const when = escapeHtml(formatMyQuoteTimestamp(it));
      const amount = escapeHtml(it.latest_amount_text || "-");
      const uidRaw = String(it.quote_series_uid || "").trim();
      const uid = escapeHtml(uidRaw);
      const riskRaw = deriveMyQuoteRiskHint(it);
      const riskHtml = riskRaw
        ? `<p class="my-quotes-row-risk${statusKey === "pending" ? " is-warn" : statusKey === "rejected" ? " is-danger" : ""}">${escapeHtml(riskRaw)}</p>`
        : "";
      const rejectNoteHtml =
        statusKey === "rejected" && comment
          ? `<p class="my-quotes-reject-note" title="${escapeHtml(comment)}">${escapeHtml(comment)}</p>`
          : "";
      const selectedCls = activeUid && uidRaw === activeUid ? " is-selected" : "";
      const batchSelected = batchMode && state.myQuotesSelectedUids.has(uidRaw);
      const hasAdminUpdate = !!(it.has_admin_update || it.admin_update_status === "pending_view");
      const updateBadgeText = deriveMyQuoteUpdateBadge(it);
      const adminUpdateBadge = updateBadgeText
        ? `<span class="my-quotes-update-badge" title="管理员有新的审批结果或修正待查看">${escapeHtml(updateBadgeText)}</span>`
        : "";
      const checkHtml = batchMode
        ? `<label class="my-quotes-row-check-wrap" aria-label="选择此报价">
            <input type="checkbox" class="my-quotes-row-check" data-series-uid="${uid}"${batchSelected ? " checked" : ""} />
          </label>`
        : "";
      const actionsHtml = batchMode
        ? ""
        : `<div class="my-quotes-row-actions">
              <button type="button" class="my-quotes-action" data-action="view" data-series-uid="${uid}">查看详情</button>
              <button type="button" class="my-quotes-action" data-action="continue" data-series-uid="${uid}">继续报价</button>
              <button type="button" class="my-quotes-action my-quotes-action-primary" data-action="sheet" data-series-uid="${uid}">生成报价单</button>
              <button type="button" class="my-quotes-action" data-action="sheet-pdf-rmb" data-series-uid="${uid}">导出 PDF</button>
            </div>`;
      return `
        <article class="my-quotes-row${selectedCls}${hasAdminUpdate ? " has-admin-update" : ""}${batchSelected ? " is-batch-selected" : ""}${batchMode ? " is-batch-mode" : ""}" role="listitem" data-series-uid="${uid}" tabindex="0" aria-label="${title} 报价记录">
          <div class="my-quotes-row-grid${batchMode ? " has-batch-check" : ""}">
            ${checkHtml}
            <div class="my-quotes-row-primary">
              <h3 class="my-quotes-row-title">${title}${adminUpdateBadge}</h3>
              <p class="my-quotes-row-meta">
                <span class="my-quotes-row-file" title="${file}">${file}</span>
                <span class="my-quotes-row-sep" aria-hidden="true">·</span>
                <span class="my-quotes-row-id">${quoteId}</span>
                <span class="my-quotes-row-sep" aria-hidden="true">·</span>
                <time class="my-quotes-row-time">${when}</time>
              </p>
              ${riskHtml}
              ${rejectNoteHtml}
            </div>
            <div class="my-quotes-row-amount">
              <span class="my-quotes-row-amount-label">最新金额</span>
              <strong class="my-quotes-row-amount-value">${amount}</strong>
            </div>
            <div class="my-quotes-row-status-col">
              <span class="my-quotes-status ${statusKey}">${escapeHtml(approvalStatusLabelCn(statusKey))}</span>
            </div>
            ${actionsHtml}
          </div>
        </article>`;
    })
    .join("");
}

function renderMyQuotesPageFromCache() {
  renderMyQuotesList(getVisibleMyQuotesItems());
  renderMyQuotesStats(state.myQuotesStatsItems.length ? state.myQuotesStatsItems : state.myQuotesItems);
}

async function loadMyQuotesPage(statusFilter = "") {
  if (!els.myQuotesList) return;
  if (isFrontEntryBlocked()) {
    els.myQuotesList.innerHTML = renderMyQuotesAuthBlocked(WECOM_ENTRY_BLOCKED_MESSAGE);
    if (els.myQuotesStats) {
      els.myQuotesStats.textContent = WECOM_ENTRY_BLOCKED_MESSAGE;
    }
    return;
  }
  const st = state.authStatus;
  if (st?.wecom_enabled && !st?.authenticated) {
    els.myQuotesList.innerHTML = renderMyQuotesAuthBlocked(wecomLoginRequiredUserMessage());
    if (els.myQuotesStats) {
      els.myQuotesStats.textContent = "请先完成企业微信登录";
    }
    return;
  }
  els.myQuotesList.innerHTML = `<p class="my-quotes-empty">加载中…</p>`;
  try {
    const filter = String(statusFilter || "");
    const [items, allItems] = await Promise.all([
      fetchMyQuotesList(filter),
      filter ? fetchMyQuotesList("") : Promise.resolve(null),
    ]);
    state.myQuotesItems = items;
    if (!filter) {
      state.myQuotesStatsItems = items;
    } else if (Array.isArray(allItems)) {
      state.myQuotesStatsItems = allItems;
    }
    state.myQuotesNeedsRefresh = false;
    renderMyQuotesPageFromCache();
  } catch (error) {
    const code = error && typeof error === "object" ? error.code : "";
    if (code === "auth_required") {
      els.myQuotesList.innerHTML = renderMyQuotesAuthBlocked(
        error instanceof Error ? error.message : wecomAuthExpiredUserMessage(),
      );
      if (els.myQuotesStats) {
        els.myQuotesStats.textContent = "登录已过期";
      }
      return;
    }
    const msg = error instanceof Error ? error.message : String(error);
    els.myQuotesList.innerHTML = `<p class="my-quotes-empty">加载失败：${escapeHtml(msg)}</p>`;
  }
}

function syncWorkspaceNavActive(view) {
  document.querySelectorAll(".session-item[data-route]").forEach((btn) => {
    const route = btn.getAttribute("data-route");
    const active =
      (view === "chat" && route === "chat") ||
      (view === "myQuotes" && route === "my-quotes") ||
      (view === "adminUpdates" && route === "admin-updates") ||
      (view === "quoteSheet" && route === "quote-sheet");
    btn.classList.toggle("active", active);
  });
}

function setWorkspacePaneVisible(pane, visible) {
  if (!pane) return;
  pane.hidden = !visible;
  pane.classList.toggle("workspace-pane-visible", visible);
}

function switchWorkspaceView(view) {
  const next =
    view === "myQuotes"
      ? "myQuotes"
      : view === "adminUpdates"
        ? "adminUpdates"
        : view === "quoteSheet"
          ? "quoteSheet"
          : "chat";
  state.currentView = next;
  setWorkspacePaneVisible(els.workspaceChat, next === "chat");
  setWorkspacePaneVisible(els.workspaceMyQuotes, next === "myQuotes");
  setWorkspacePaneVisible(els.workspaceAdminUpdates, next === "adminUpdates");
  setWorkspacePaneVisible(els.workspaceQuote, next === "quoteSheet");
  syncWorkspaceNavActive(next);
  if (next === "myQuotes") {
    hideAdminCorrectionResultPanel();
    void loadMyQuotesPage(state.myQuotesFilter);
  } else if (next === "adminUpdates") {
    hideAdminCorrectionResultPanel();
    if (els.adminUpdatesBanner) els.adminUpdatesBanner.hidden = true;
    void loadAdminUpdatesPage();
  } else if (next === "chat") {
    showAdminUpdatesListView();
    renderAdminUpdatesBadge(state.adminUpdatesUnread);
  } else if (next !== "chat" && next !== "quoteSheet") {
    hideAdminCorrectionResultPanel();
  }
}

window.switchWorkspaceView = switchWorkspaceView;

function hydrateMessageFromPersisted(row, quoteResult) {
  const meta = row.metadata && typeof row.metadata === "object" ? row.metadata : {};
  const type = String(meta.type || row.type || "text").trim() || "text";
  const msgId = String(meta.msgId || row.message_id || newQuoteMsgId());
  if (type === "quote_card" && quoteResult) {
    return {
      role: row.role || "assistant",
      type: "quote_card",
      subtype: meta.subtype || "primary",
      fileName: meta.fileName || quoteResult.sheet_original_name || "",
      data: quoteResult,
      msgId,
      time: row.created_at || formatNowTime(),
    };
  }
  if (type === "approval_notice" || row.role === "admin") {
    return {
      role: "assistant",
      type: "text",
      text: String(row.content || ""),
      time: row.created_at || formatNowTime(),
      replyType: "approval_notice",
    };
  }
  if (type === "user_turn") {
    return {
      role: "user",
      type: "user_turn",
      text: String(row.content || ""),
      attachmentViews: [],
      time: row.created_at || formatNowTime(),
    };
  }
  return {
    role: row.role || "assistant",
    type: type === "text" ? "text" : type,
    text: String(row.content || ""),
    time: row.created_at || formatNowTime(),
  };
}

async function openQuoteSheetFromRecord(seriesUid, options = {}) {
  const uid = String(seriesUid || "").trim();
  if (!uid) return false;
  const bridge = typeof window !== "undefined" ? window.QuoteSheetBridge : null;
  if (bridge && typeof bridge.openFromQuoteRecord === "function") {
    switchWorkspaceView("quoteSheet");
    return bridge.openFromQuoteRecord(uid, options);
  }
  setComposerStatusLine("报价单模块未加载，请刷新页面后重试", "err");
  return false;
}

async function restoreMyQuoteSession(seriesUid, options = {}) {
  const uid = String(seriesUid || "").trim();
  if (!uid) return;
  const targetView = String(options.targetView || "chat").trim() || "chat";
  try {
    const res = await quoteFetch(`/api/my/quotes/${encodeURIComponent(uid)}`);
    const detail = await res.json().catch(() => ({}));
    if (!res.ok) {
      if (res.status === 401) {
        throw Object.assign(new Error(wecomAuthExpiredUserMessage()), { code: "auth_required" });
      }
      throw new Error(detail.message || detail.error || `HTTP ${res.status}`);
    }
    state.activeMyQuoteSeriesUid = uid;
    switchWorkspaceView(targetView);
    const quote = detail.latest_quote_result && typeof detail.latest_quote_result === "object"
      ? detail.latest_quote_result
      : null;
    if (quote) {
      applyQuoteApprovalFields(quote, {
        approval_status: detail.approval_status,
        approval_note: detail.approval_comment,
        approved_at: detail.approved_at,
        approved_by: detail.approved_by,
      });
      applyAdminFeedbackFields(quote, detail.admin_feedback);
      quote.quote_series_uid = uid;
    }
    const restored = [];
    const rows = Array.isArray(detail.messages) ? detail.messages : [];
    if (rows.length) {
      for (const row of rows) {
        if (row.metadata?.type === "quote_card" && quote) {
          restored.push(hydrateMessageFromPersisted(row, quote));
        } else if (row.role === "admin" || row.metadata?.type === "approval_notice") {
          restored.push(hydrateMessageFromPersisted(row, null));
        } else {
          restored.push(hydrateMessageFromPersisted(row, null));
        }
      }
    } else if (quote) {
      restored.push({
        role: "assistant",
        type: "quote_card",
        subtype: "primary",
        fileName: detail.sheet_original_name || "",
        data: quote,
        msgId: newQuoteMsgId(),
        time: formatNowTime(),
      });
    }
    if (restored.length) {
      state.messages = restored;
    }
    if (quote?.quote_id) {
      const primary = restored.find((m) => m.type === "quote_card");
      state.sessionContext = {
        currentQuoteId: quote.quote_id,
        fileName: detail.sheet_original_name || primary?.fileName || "",
        quoteData: quote,
        primaryQuoteMsgId: primary?.msgId || "",
      };
    }
    renderMessages();
    scrollToBottom();
    renderAdminCorrectionResultPanel(detail);
    scheduleQuoteCardsApprovalRefresh("restore");
    setComposerStatusLine("已恢复历史报价会话", "ok");
    const fb = detail.admin_feedback;
    if (fb && (fb.has_admin_update || fb.admin_update_status === "pending_view")) {
      void markMyQuoteAdminUpdateViewed(uid);
    }
    if (targetView === "myQuotes") {
      renderMyQuotesPageFromCache();
    }
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    setComposerStatusLine(`恢复失败：${msg}`, "err");
  }
}

function bindMyQuotesUi() {
  if (els.navMyQuotes) {
    els.navMyQuotes.addEventListener("click", () => {
      switchWorkspaceView("myQuotes");
    });
  }
  document.querySelectorAll(".session-item[data-route='chat']").forEach((btn) => {
    btn.addEventListener("click", () => {
      switchWorkspaceView("chat");
    });
  });
  document.querySelectorAll(".my-quotes-filter").forEach((btn) => {
    btn.addEventListener("click", () => {
      const status = String(btn.getAttribute("data-status") || "");
      state.myQuotesFilter = status;
      document.querySelectorAll(".my-quotes-filter").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      void loadMyQuotesPage(status);
    });
  });
  if (els.myQuotesSearch) {
    els.myQuotesSearch.addEventListener("input", () => {
      state.myQuotesSearch = els.myQuotesSearch.value || "";
      renderMyQuotesPageFromCache();
    });
  }
  if (els.btnMyQuotesManage) {
    els.btnMyQuotesManage.addEventListener("click", () => enterMyQuotesBatchMode());
  }
  if (els.btnMyQuotesBatchCancel) {
    els.btnMyQuotesBatchCancel.addEventListener("click", () => exitMyQuotesBatchMode());
  }
  if (els.btnMyQuotesBatchDelete) {
    els.btnMyQuotesBatchDelete.addEventListener("click", () => {
      void batchDeleteMyQuotes();
    });
  }
  if (els.myQuotesList) {
    els.myQuotesList.addEventListener("change", (ev) => {
      const cb = ev.target.closest(".my-quotes-row-check");
      if (!cb || !state.myQuotesBatchMode) return;
      toggleMyQuotesSelection(cb.getAttribute("data-series-uid"), cb.checked);
    });
    els.myQuotesList.addEventListener("click", (ev) => {
      if (state.myQuotesBatchMode) {
        if (ev.target.closest(".my-quotes-row-check-wrap")) return;
        const row = ev.target.closest(".my-quotes-row[data-series-uid]");
        if (!row) return;
        const uid = String(row.getAttribute("data-series-uid") || "").trim();
        const cb = row.querySelector(".my-quotes-row-check");
        const next = !(cb instanceof HTMLInputElement && cb.checked);
        toggleMyQuotesSelection(uid, next);
        ev.preventDefault();
        return;
      }
      const actionBtn = ev.target.closest(".my-quotes-action[data-action]");
      const row = ev.target.closest(".my-quotes-row[data-series-uid]");
      const uid = String(
        (actionBtn && actionBtn.getAttribute("data-series-uid")) ||
          (row && row.getAttribute("data-series-uid")) ||
          "",
      ).trim();
      if (!uid) return;
      if (actionBtn) {
        ev.stopPropagation();
        const action = String(actionBtn.getAttribute("data-action") || "").trim();
        if (action === "sheet") {
          void openQuoteSheetFromRecord(uid, { source: "record" });
          return;
        }
        if (action === "sheet-pdf-rmb") {
          void openQuoteSheetFromRecord(uid, { source: "record", exportMode: "pdf_rmb" });
          return;
        }
        void restoreMyQuoteSession(uid, { targetView: "chat" });
        return;
      }
      if (row) {
        void restoreMyQuoteSession(uid, { targetView: "chat" });
      }
    });
    els.myQuotesList.addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter" && ev.key !== " ") return;
      const row = ev.target.closest(".my-quotes-row[data-series-uid]");
      if (!row || ev.target.closest(".my-quotes-action")) return;
      if (state.myQuotesBatchMode) {
        ev.preventDefault();
        const uid = String(row.getAttribute("data-series-uid") || "").trim();
        const cb = row.querySelector(".my-quotes-row-check");
        const next = !(cb instanceof HTMLInputElement && cb.checked);
        toggleMyQuotesSelection(uid, next);
        return;
      }
      ev.preventDefault();
      const uid = String(row.getAttribute("data-series-uid") || "").trim();
      if (uid) void restoreMyQuoteSession(uid, { targetView: "chat" });
    });
  }
}

function initialize() {
  els.chatMessages.addEventListener("change", (event) => {
    const inp = event.target;
    if (!(inp instanceof HTMLInputElement) || !inp.classList.contains("quote-detail-validation-toggle")) {
      return;
    }
    const root = inp.closest("[data-quote-detail-root]");
    if (!root) {
      return;
    }
    root.querySelectorAll("tr.quote-mat-meta-row").forEach((tr) => {
      if (inp.checked) {
        tr.classList.remove("is-collapsed");
        tr.setAttribute("aria-hidden", "false");
      } else {
        tr.classList.add("is-collapsed");
        tr.setAttribute("aria-hidden", "true");
      }
    });
  });

  els.chatMessages.addEventListener("input", (event) => {
    const inp = event.target;
    if (!(inp instanceof HTMLInputElement || inp instanceof HTMLTextAreaElement)) {
      return;
    }
    if (!inp.hasAttribute("data-structure-row-field")) {
      return;
    }
    const card = inp.closest(".structure-confirm-card[data-structure-card-token]");
    if (!card) {
      return;
    }
    const tok = String(card.getAttribute("data-structure-card-token") || "").trim();
    if (tok) {
      markStructurePreviewDirty(tok);
    }
  });

  els.chatMessages.addEventListener("click", (event) => {
    const calcBtn = event.target.closest(".calc-expand-btn");
    if (calcBtn) {
      const box = calcBtn.closest(".calc-note-box");
      if (box) {
        const expanded = box.classList.toggle("is-expanded");
        calcBtn.setAttribute("aria-expanded", expanded ? "true" : "false");
        calcBtn.textContent = expanded ? "收起" : "展开";
      }
      return;
    }

    const dnTog = event.target.closest(".quote-data-notice-toggle");
    if (dnTog) {
      const wrap = dnTog.closest(".quote-data-notice-wrap");
      if (wrap) {
        const prev = wrap.querySelector(".quote-data-notice-preview");
        const full = wrap.querySelector(".quote-data-notice-full");
        const exp = !wrap.classList.contains("is-notice-expanded");
        wrap.classList.toggle("is-notice-expanded", exp);
        if (full) full.toggleAttribute("hidden", !exp);
        if (prev) prev.toggleAttribute("hidden", exp);
        dnTog.textContent = exp ? "收起提醒" : "展开提醒";
        dnTog.setAttribute("aria-expanded", exp ? "true" : "false");
      }
      return;
    }

    const procHead = event.target.closest("[data-quote-process-head]");
    if (procHead) {
      const root = procHead.closest("[data-quote-process-root]");
      const msgId = root && root.dataset && root.dataset.quoteMsgId ? String(root.dataset.quoteMsgId) : "";
      if (msgId) {
        handleQuoteProcessHeadClick(msgId);
      }
      return;
    }

    const collapseToggle = event.target.closest("[data-process-collapse-toggle]");
    if (collapseToggle) {
      const wrap = collapseToggle.closest("[data-process-collapse]");
      if (wrap && !wrap.closest(".quote-embedded-process")) {
        wrap.classList.toggle("is-collapsed");
        const collapsed = wrap.classList.contains("is-collapsed");
        collapseToggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
        const ctrl = collapseToggle.querySelector(".process-card-collapse-ctrl");
        if (ctrl) {
          ctrl.textContent = collapsed ? "展开 ▼" : "收起 ▲";
        }
      }
      return;
    }

    const matBtn = event.target.closest("[data-material-action]");
    if (matBtn && !state.isRequesting) {
      const wrap = matBtn.closest(".quote-material-extra-actions");
      const mid =
        wrap && wrap.dataset && wrap.dataset.materialMsgId
          ? String(wrap.dataset.materialMsgId)
          : "";
      const action = matBtn.getAttribute("data-material-action");
      if (action === "promote" && mid) {
        promoteMaterialToPrimary(mid).catch((err) => {
          const msg = humanizeNetworkError(err instanceof Error ? err : new Error(String(err)));
          addMessage("assistant", msg);
        });
        return;
      }
      if (action === "again-mat") {
        focusTrialMaterialInput();
        return;
      }
      if (action === "again-qty") {
        focusTrialQuantityInput();
        return;
      }
    }

    const exBtn = event.target.closest("[data-extra-action]");
    if (exBtn && !state.isRequesting) {
      const row = exBtn.closest(".quote-extra-actions");
      const q = row && row.dataset ? Number(row.dataset.calcQuantity) : NaN;
      const action = exBtn.getAttribute("data-extra-action");
      if (action === "promote" && Number.isFinite(q) && q > 0) {
        promoteExtraToPrimary(q).catch((err) => {
          const msg = humanizeNetworkError(err instanceof Error ? err : new Error(String(err)));
          addMessage("assistant", msg);
        });
        return;
      }
      if (action === "again") {
        focusTrialQuantityInput();
        return;
      }
    }

    const pgBtn = event.target.closest(".btn-pricing-gate-confirm");
    if (pgBtn && !state.isRequesting) {
      event.preventDefault();
      confirmPricingGateUnlock(pgBtn).catch((err) => {
        const msg = humanizeNetworkError(err instanceof Error ? err : new Error(String(err)));
        addMessage("assistant", `解锁失败：${msg}`);
      });
      return;
    }

    const scPatchBtn = event.target.closest(".btn-structure-cl-action");
    if (scPatchBtn && !state.isRequesting) {
      event.preventDefault();
      patchStructureChecklistItem(scPatchBtn).catch((err) => {
        const msg = humanizeNetworkError(err instanceof Error ? err : new Error(String(err)));
        addMessage("assistant", `结构清单更新失败：${msg}`);
      });
      return;
    }

    const gapChk = event.target.closest(".structure-gap-confirm-checkbox");
    if (gapChk && !state.isRequesting) {
      const t = String(gapChk.getAttribute("data-structure-gap-confirm") || "").trim();
      const hid = String(gapChk.getAttribute("data-structure-gap-id") || "").trim();
      toggleStructureGapConfirm(t, hid, Boolean(gapChk.checked));
      return;
    }

    const scBtn = event.target.closest(".btn-structure-confirm");
    if (scBtn && !state.isRequesting) {
      event.preventDefault();
      confirmStructureAndQuote(scBtn).catch((err) => {
        const msg = humanizeNetworkError(err instanceof Error ? err : new Error(String(err)));
        addMessage("assistant", `结构确认失败：${msg}`);
      });
      return;
    }

    const scEdit = event.target.closest(".btn-structure-sc-edit");
    if (scEdit && !state.isRequesting) {
      event.preventDefault();
      const t = String(scEdit.getAttribute("data-structure-sc-edit") || "").trim();
      if (t) {
        enterStructurePreviewEditMode(t);
      }
      return;
    }

    const scSave = event.target.closest(".btn-structure-sc-save");
    if (scSave && !state.isRequesting && !scSave.disabled) {
      event.preventDefault();
      const t = String(scSave.getAttribute("data-structure-sc-save") || "").trim();
      if (t) {
        saveStructurePreviewEdits(t);
      }
      return;
    }

    const scAdd = event.target.closest(".btn-structure-sc-add");
    if (scAdd && !state.isRequesting) {
      event.preventDefault();
      const t = String(scAdd.getAttribute("data-structure-sc-add") || "").trim();
      if (t) {
        addStructurePreviewRow(t);
      }
      return;
    }

    const scDelete = event.target.closest(".btn-structure-sc-delete");
    if (scDelete && !state.isRequesting && !scDelete.disabled) {
      event.preventDefault();
      const t = String(scDelete.getAttribute("data-structure-sc-delete") || "").trim();
      if (t) {
        deleteSelectedStructurePreviewRow(t);
      }
      return;
    }

    const rowDelete = event.target.closest(".btn-structure-row-delete");
    if (rowDelete && !state.isRequesting) {
      event.preventDefault();
      const t = String(rowDelete.getAttribute("data-structure-row-delete") || "").trim();
      const idx = String(rowDelete.getAttribute("data-structure-row-index") || "").trim();
      if (t && idx) {
        deleteStructurePreviewRow(t, idx);
      }
      return;
    }

    const scRow = event.target.closest(".structure-confirm-data-row[data-structure-row-select]");
    if (scRow && !state.isRequesting) {
      const field = event.target.closest("input, textarea, button");
      if (field) {
        if (field.tagName === "BUTTON") {
          return;
        }
        const ro = field.readOnly || field.hasAttribute("readonly");
        if (!ro) {
          return;
        }
      }
      const t = String(scRow.getAttribute("data-structure-row-select") || "").trim();
      const idx = String(scRow.getAttribute("data-structure-row-index") || "").trim();
      if (t && idx) {
        selectStructurePreviewRow(t, idx);
      }
      return;
    }
  });

  if (els.sheetInput) {
    els.sheetInput.addEventListener("change", () => {
      handleSheetPickChange().catch((error) => {
        const msg = humanizeUploadError(error instanceof Error ? error : new Error(String(error)));
        setComposerStatusLine(msg, "err");
      });
    });
  }
  if (els.imageInput) {
    els.imageInput.addEventListener("change", () => {
      handleImagePickChange().catch((error) => {
        const msg = humanizeUploadError(error instanceof Error ? error : new Error(String(error)));
        setComposerStatusLine(msg, "err");
      });
    });
  }

  bindComposerPasteAndDrop();
  bindComposerAttachMenu();

  if (els.userPrompt) {
    els.userPrompt.addEventListener("input", () => syncComposerTextareaHeight());
  }

  if (els.attachmentStrip) {
    els.attachmentStrip.addEventListener("click", (ev) => {
      const rm = ev.target.closest("[data-remove-att]");
      if (!rm || !rm.getAttribute("data-remove-att")) {
        return;
      }
      removeComposerAttachment(String(rm.getAttribute("data-remove-att")));
      setComposerStatusLine("已移除附件", "ok");
    });
  }

  if (els.sendBtn) {
    els.sendBtn.addEventListener("click", () => {
      requestQuote().catch((error) => {
        const msg = humanizeNetworkError(error instanceof Error ? error : new Error(String(error)));
        addMessage("assistant", `发送失败：${msg}`);
      });
    });
  }

  if (els.userPrompt) {
    els.userPrompt.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        requestQuote().catch((error) => {
          const msg = humanizeNetworkError(error instanceof Error ? error : new Error(String(error)));
          addMessage("assistant", `发送失败：${msg}`);
        });
      }
    });
  }

  bindQuoteApprovalRefreshTriggers();
  startSalesSyncPolling();
  bindMyQuotesUi();
  bindAdminUpdatesUi();
  bindAdminCorrectionResultPanelUi();
  resetAdminUpdatesWorkspaceUi();
  document.body.classList.toggle("is-wecom-browser", state.isWecomBrowser);
  ensureWorkbenchServingNotice();
  renderMessages();
  renderComposerAttachments();
  syncComposerPlaceholder();
  syncComposerTextareaHeight();
  fetchLlmStatusOnly().catch(() => {});
  fetchAuthStatus().catch(() => {});
  refreshMyQuotesPreview().catch(() => {});
  refreshAdminUpdatesBadge().catch(() => {});
}

async function fetchLlmStatusOnly() {
  try {
    const response = await quoteFetch("/api/llm/status?probe=1");
    const result = await readResponseJson(response);
    if (response.ok) {
      state.llmStatus = result;
      renderLlmStatus();
    }
  } catch {
    // ignore
  }
}

initialize();
