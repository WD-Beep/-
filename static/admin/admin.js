function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

const ADMIN_API_DEBUG =
  localStorage.getItem("admin_api_debug") === "1" ||
  new URLSearchParams(location.search).get("debug") === "1";

const LIST_EMPTY_DEFAULT = "暂无归档记录；前台完成报价后将自动入库。";

function adminApiLog(label, detail) {
  if (!ADMIN_API_DEBUG) return;
  const cookieNames = document.cookie
    ? document.cookie.split(";").map((p) => p.trim().split("=")[0]).filter(Boolean)
    : [];
  console.debug(`[admin-api] ${label}`, {
    ...detail,
    cookiePresent: cookieNames.includes("aq_admin_sess"),
    cookieNames,
  });
}

async function apiJson(url, opts = {}) {
  const method = String(opts.method || "GET").toUpperCase();
  adminApiLog("request", { url, method, hasBody: opts.body != null });
  const res = await fetch(url, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  const text = await res.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = {};
  }
  adminApiLog("response", { url, method, status: res.status, ok: res.ok });
  return { ok: res.ok, status: res.status, data };
}

function gotoLogin() {
  window.location.replace("/admin/login");
}

const els = {
  statTotal: document.getElementById("statTotal"),
  statToday: document.getElementById("statToday"),
  statLatest: document.getElementById("statLatest"),
  filterSearch: document.getElementById("filterSearch"),
  filterDateFrom: document.getElementById("filterDateFrom"),
  filterDateTo: document.getElementById("filterDateTo"),
  filterVerMin: document.getElementById("filterVerMin"),
  filterStatus: document.getElementById("filterStatus"),
  filterSalesUser: document.getElementById("filterSalesUser"),
  btnApplyFilters: document.getElementById("btnApplyFilters"),
  btnClearFilters: document.getElementById("btnClearFilters"),
  listBody: document.getElementById("listBody"),
  listEmpty: document.getElementById("listEmpty"),
  pageLabel: document.getElementById("pageLabel"),
  btnPrev: document.getElementById("btnPrev"),
  btnNext: document.getElementById("btnNext"),
  btnLogout: document.getElementById("btnLogout"),
  btnRefresh: document.getElementById("btnRefresh"),
  newQuotesAlert: document.getElementById("newQuotesAlert"),
  btnNewQuotesAlert: document.getElementById("btnNewQuotesAlert"),
  newQuotesAlertText: document.getElementById("newQuotesAlertText"),
  pendingWatchPanel: document.getElementById("pendingWatchPanel"),
  btnTogglePendingWatch: document.getElementById("btnTogglePendingWatch"),
  pendingWatchBadge: document.getElementById("pendingWatchBadge"),
  pendingWatchBody: document.getElementById("pendingWatchBody"),
  pendingWatchListBody: document.getElementById("pendingWatchListBody"),
  pendingWatchEmpty: document.getElementById("pendingWatchEmpty"),
  btnWatchUnseenOnly: document.getElementById("btnWatchUnseenOnly"),
  btnWatchMarkAllSeen: document.getElementById("btnWatchMarkAllSeen"),
  btnWatchClearSeen: document.getElementById("btnWatchClearSeen"),
  btnBatchDelete: document.getElementById("btnBatchDelete"),
  btnDeleteFilteredAll: document.getElementById("btnDeleteFilteredAll"),
  chkSelectPage: document.getElementById("chkSelectPage"),
  batchSelectHint: document.getElementById("batchSelectHint"),
  detailPlaceholder: document.getElementById("detailPlaceholder"),
  detailWorkspace: document.getElementById("detailWorkspace"),
  detailTitle: document.getElementById("detailTitle"),
  detailSubtitle: document.getElementById("detailSubtitle"),
  quoteApprovalPanel: document.getElementById("quoteApprovalPanel"),
  quoteApprovalStatusBadge: document.getElementById("quoteApprovalStatusBadge"),
  approvalReviewerInput: document.getElementById("approvalReviewerInput"),
  approvalStatusSelect: document.getElementById("approvalStatusSelect"),
  approvalNoteInput: document.getElementById("approvalNoteInput"),
  quoteApprovalMeta: document.getElementById("quoteApprovalMeta"),
  btnSaveQuoteApproval: document.getElementById("btnSaveQuoteApproval"),
  quoteApprovalSaveHint: document.getElementById("quoteApprovalSaveHint"),
  chkSimpleMode: document.getElementById("chkSimpleMode"),
  btnToggleTech: document.getElementById("btnToggleTech"),
  detailTechPanel: document.getElementById("detailTechPanel"),
  detailMetaDl: document.getElementById("detailMetaDl"),
  btnCopyUid: document.getElementById("btnCopyUid"),
  btnExportJson: document.getElementById("btnExportJson"),
  btnOpenVersionsFiles: document.getElementById("btnOpenVersionsFiles"),
  btnOpenSheet: document.getElementById("btnOpenSheet"),
  btnDeleteQuote: document.getElementById("btnDeleteQuote"),
  tierSummaryTitle: document.getElementById("tierSummaryTitle"),
  overviewHealth: document.getElementById("overviewHealth"),
  overviewHeroMount: document.getElementById("overviewHeroMount"),
  overviewCostMix: document.getElementById("overviewCostMix"),
  tierCompareMount: document.getElementById("tierCompareMount"),
  overviewSuggestions: document.getElementById("overviewSuggestions"),
  overviewCredibility: document.getElementById("overviewCredibility"),
  overviewEmbeddedDetailBody: document.getElementById("overviewEmbeddedDetailBody"),
  overviewEmbedWrap: document.getElementById("overviewEmbedWrap"),
  overviewEmbedTable: document.getElementById("overviewEmbedTable"),
  bomEditActions: document.getElementById("bomEditActions"),
  btnBomEdit: document.getElementById("btnBomEdit"),
  btnBomAdd: document.getElementById("btnBomAdd"),
  btnBomSave: document.getElementById("btnBomSave"),
  btnBomCancel: document.getElementById("btnBomCancel"),
  bomCorrectionWorkspace: document.getElementById("bomCorrectionWorkspace"),
  bcwSalesFiles: document.getElementById("bcwSalesFiles"),
  bcwAdminCorrectionFile: document.getElementById("bcwAdminCorrectionFile"),
  bcwAdminCalculatedFile: document.getElementById("bcwAdminCalculatedFile"),
  bcwCorrectionSheetInput: document.getElementById("bcwCorrectionSheetInput"),
  bcwCalculatedSheetInput: document.getElementById("bcwCalculatedSheetInput"),
  btnUploadCorrectionSheet: document.getElementById("btnUploadCorrectionSheet"),
  btnUploadCalculatedSheet: document.getElementById("btnUploadCalculatedSheet"),
  bcwUploadHint: document.getElementById("bcwUploadHint"),
  bcwCalculatedUploadHint: document.getElementById("bcwCalculatedUploadHint"),
  adminCorrectionNoteInput: document.getElementById("adminCorrectionNoteInput"),
  adminSavedCorrectionStatus: document.getElementById("adminSavedCorrectionStatus"),
  adminFeedbackMeta: document.getElementById("adminFeedbackMeta"),
  adminSalesViewStatus: document.getElementById("adminSalesViewStatus"),
  adminCorrectionProblemTypes: document.getElementById("adminCorrectionProblemTypes"),
  btnSaveAdminFeedback: document.getElementById("btnSaveAdminFeedback"),
  adminFeedbackSaveHint: document.getElementById("adminFeedbackSaveHint"),
  adminToast: document.getElementById("adminToast"),
  chkOverviewDetailValidation: document.getElementById("chkOverviewDetailValidation"),
  overviewNoticeWrap: document.getElementById("overviewNoticeWrap"),
  overviewNoticeToggle: document.getElementById("overviewNoticeToggle"),
  overviewNoticeFull: document.getElementById("overviewNoticeFull"),
  btnOverviewExpand: document.getElementById("btnOverviewExpand"),
  panelOverview: document.getElementById("panelOverview"),
  detailRowsBody: document.getElementById("detailRowsBody"),
  detailMarkerWrap: document.getElementById("detailMarkerWrap"),
  detailSimpleWrap: document.getElementById("detailSimpleWrap"),
  markerRoomBody: document.getElementById("markerRoomBody"),
  btnDetailViewMarker: document.getElementById("btnDetailViewMarker"),
  btnDetailViewSimple: document.getElementById("btnDetailViewSimple"),
  calcAccordion: document.getElementById("calcAccordion"),
  versionBar: document.getElementById("versionBar"),
  versionSelect: document.getElementById("versionSelect"),
  detailFiles: document.getElementById("detailFiles"),
  versionsTableBody: document.getElementById("versionsTableBody"),
  diffSection: document.getElementById("diffSection"),
  diffBody: document.getElementById("diffBody"),
};

const TAB_IDS = {
  overview: document.getElementById("panelOverview"),
  detail: document.getElementById("panelDetail"),
  calc: document.getElementById("panelCalc"),
  files: document.getElementById("panelFiles"),
};

let page = 1;
const pageSize = 30;
let total = 0;
let selectedQuoteId = null;
let selectedRowEl = null;
let lastBundle = null;
let firstSheetUrl = "";
let detailSort = { key: "line", dir: "asc" };
let searchTimer = null;
const SIMPLE_MODE_KEY = "admin_quote_detail_simple";
const DETAIL_VIEW_MODE_KEY = "admin_detail_view_mode";
const OV_VALIDATION_KEY_PREFIX = "admin_ov_val_";
const OV_CALC_LINES_KEY_PREFIX = "admin_ov_calc_lines_";
let overviewExpanded = false;
let lastOverviewPairs = [];
let bomEditMode = false;
let bomEditSnapshot = null;
let bomEditDraft = null;
let bomEditFieldErrors = {};
let bomEditSaving = false;
let adminFeedbackSaving = false;
let adminToastTimer = null;

const CORRECTION_SHEET_SUFFIXES = [".xlsx", ".xls", ".csv"];
const ADMIN_CALCULATED_ATTACHMENT_SUFFIXES = [
  ".xlsx", ".xls", ".csv", ".pdf", ".doc", ".docx", ".png", ".jpg", ".jpeg", ".zip", ".rar",
];
const ADMIN_ATTACHMENT_BLOCKED_SUFFIXES = [
  ".exe", ".bat", ".cmd", ".ps1", ".js", ".vbs", ".msi", ".scr", ".dll", ".com", ".jar", ".sh",
];
const ADMIN_ATTACHMENT_MAX_BYTES = 100 * 1024 * 1024;
const CORRECTION_PROBLEM_TYPE_OPTIONS = [
  { key: "missing_fields", label: "业务员原表缺字段" },
  { key: "unclear_usage", label: "用量不清楚" },
  { key: "bad_unit_price", label: "单价不合理" },
  { key: "bad_material_name", label: "材料名称不规范" },
  { key: "unclear_tier_qty", label: "数量/阶梯价不明确" },
  { key: "incomplete_structure", label: "结构描述不完整" },
  { key: "agent_recognition_error", label: "agent 识别错误" },
  { key: "agent_cost_bias", label: "agent 成本计算偏差" },
  { key: "other", label: "其他" },
];
const ADMIN_SHEET_KIND_CORRECTED = "admin_corrected";
const ADMIN_SHEET_KIND_CALCULATED = "admin_calculated";
const ADMIN_SHEET_UI = {
  [ADMIN_SHEET_KIND_CORRECTED]: {
    apiPath: "correction-sheet",
    roles: ["admin_corrected", "admin_correction"],
    metaId: "admin_correction_file_id",
    metaAt: "admin_correction_at",
    metaBy: "admin_correction_by",
    fileMount: () => els.bcwAdminCorrectionFile,
    hintMount: () => els.bcwUploadHint,
    emptyText: "未上传（可选）",
    replaceConfirm: "已存在管理员修正版表格附件，确定要替换吗？",
    deleteConfirm: "确定删除当前修正版表格附件吗？",
    uploadToast: (name) => `修正版表格已上传：${name}`,
    deleteToast: "修正版表格已删除",
    chipClass: "bcw-file-chip-admin",
    versionTitle: "管理员修正版表格",
    versionSuffix: "（修正版）",
  },
  [ADMIN_SHEET_KIND_CALCULATED]: {
    apiPath: "calculated-sheet",
    roles: ["admin_calculated"],
    metaId: "admin_calculated_file_id",
    metaAt: "admin_calculated_at",
    metaBy: "admin_calculated_by",
    fileMount: () => els.bcwAdminCalculatedFile,
    hintMount: () => els.bcwCalculatedUploadHint,
    emptyText: "未上传（可选）",
    replaceConfirm: "已存在管理员自算表格附件，确定要替换吗？",
    deleteConfirm: "确定删除当前自算表格附件吗？",
    uploadToast: (name) => `自算表格已上传：${name}`,
    deleteToast: "自算表格已删除",
    chipClass: "bcw-file-chip-calculated",
    versionTitle: "管理员自算表格",
    versionSuffix: "（自算）",
  },
};
const BOM_MEASURE_RE = /^\s*([+-])?((?:\d+\.\d+|\d+|\.\d+))(.*)?\s*$/;
const BOM_KNOWN_LATIN_UNIT_TOKENS = new Set([
  "m", "cm", "mm", "kg", "g", "mg", "pcs", "pc", "pair", "yd", "yd2", "m2",
]);
const BOM_COUNT_BASED_UNIT_TOKENS = new Set([
  "个", "只", "件", "套", "条", "对", "pcs", "pc", "piece", "pair",
]);

function isEmptyBomUsage(raw) {
  const s = String(raw || "").trim();
  return !s || s === "-" || s === "—";
}

function unitTextCandidates(unit, unitPrice) {
  const out = [];
  for (const raw of [unit, unitPrice]) {
    const s = String(raw || "").trim();
    if (!s || s === "-" || s === "—") continue;
    out.push(s);
    const m = s.match(BOM_MEASURE_RE);
    if (m && m[3]) out.push(String(m[3]).trim());
    if (s.includes("/")) out.push(s.split("/").pop().trim());
    if (s.includes("／")) out.push(s.split("／").pop().trim());
    const cleaned = s.replace(/^[元￥$€]+\/?/, "").trim();
    if (cleaned) out.push(cleaned);
  }
  return out;
}

function isCountBasedUnit(unit, unitPrice) {
  for (const cand of unitTextCandidates(unit, unitPrice)) {
    const lower = cand.toLowerCase();
    for (const tok of BOM_COUNT_BASED_UNIT_TOKENS) {
      if (lower.includes(tok)) return true;
    }
  }
  return false;
}

function defaultCountUsage(unit, unitPrice) {
  const cn = ["个", "只", "件", "套", "条", "对"];
  if (!isCountBasedUnit(unit, unitPrice)) return "1";
  for (const tok of cn) {
    for (const cand of unitTextCandidates(unit, unitPrice)) {
      if (cand.includes(tok)) return `1${tok}`;
    }
  }
  return "1";
}

function validateBomMeasureText(raw, { emptyMsg, invalidMsg }) {
  const s = String(raw || "").trim();
  if (!s || s === "-" || s === "—") return emptyMsg;
  const m = s.match(BOM_MEASURE_RE);
  if (!m) return invalidMsg;
  const sign = m[1] || "";
  const numStr = m[2] || "";
  const unit = String(m[3] || "");
  if (numStr.includes("..") || (numStr.match(/\./g) || []).length > 1) return invalidMsg;
  const val = Number(`${sign}${numStr}`);
  if (!Number.isFinite(val)) return invalidMsg;
  if (/\d/.test(unit)) return invalidMsg;
  const lettersOnly = unit.replace(/[\s.\-/²°%￥$€]/g, "");
  if (lettersOnly && /^[a-zA-Z]+$/.test(lettersOnly)) {
    if (!BOM_KNOWN_LATIN_UNIT_TOKENS.has(lettersOnly.toLowerCase())) return invalidMsg;
  }
  return "";
}

function parseBomMeasureValue(raw) {
  const err = validateBomMeasureText(raw, { emptyMsg: "x", invalidMsg: "x" });
  if (err) return NaN;
  const s = String(raw || "").trim();
  const m = s.match(BOM_MEASURE_RE);
  if (!m) return NaN;
  const sign = m[1] || "";
  const numStr = m[2] || "";
  return Number(`${sign}${numStr}`);
}

const LIST_POLL_VISIBLE_MS = 5000;
const LIST_POLL_HIDDEN_MS = 25000;
const PENDING_WATCH_STORAGE_KEY = "admin_pending_quote_watch_v1";
const SEEN_WATCH_STORAGE_KEY = "admin_seen_quote_watch_v1";
const PENDING_WATCH_COLLAPSED_KEY = "admin_pending_watch_collapsed_v1";
let listPollTimer = null;
let lastSeenTime = "";
let pendingWatchQuotes = [];
let seenWatchQuoteIds = new Set();
let pendingWatchUnseenOnly = false;
let pendingWatchCollapsed = localStorage.getItem(PENDING_WATCH_COLLAPSED_KEY) === "1";
let listPollFailCount = 0;
let listPollLastErrLogAt = 0;

function normalizeApprovalStatusKey(raw) {
  const key = String(raw || "pending").trim().toLowerCase();
  if (key === "approved" || key === "rejected" || key === "pending") return key;
  return "pending";
}

function approvalStatusText(statusKey) {
  const key = normalizeApprovalStatusKey(statusKey);
  if (key === "approved") return "合格";
  if (key === "rejected") return "不合格";
  return "待核实";
}

function formatReviewerLabel(name) {
  const n = String(name || "").trim();
  if (!n || n.toLowerCase() === "admin" || n.toLowerCase() === "administrator") {
    return "未填写";
  }
  return n;
}

function readReviewerNameFromInput() {
  return String(els.approvalReviewerInput?.value || "").trim();
}

function reviewerNameForInput(meta = {}) {
  const saved = String(meta.approved_by || "").trim();
  return formatReviewerLabel(saved) === "未填写" ? "" : saved;
}

function approvalPillClass(statusKey) {
  const key = normalizeApprovalStatusKey(statusKey);
  return `approval-pill approval-pill-${key}`;
}

function renderApprovalPillHtml(statusKey) {
  const key = normalizeApprovalStatusKey(statusKey);
  return `<span class="${approvalPillClass(key)}">${escapeHtml(approvalStatusText(key))}</span>`;
}

function renderQuoteApprovalPanel(meta = {}) {
  if (!els.quoteApprovalPanel) return;
  els.quoteApprovalPanel.hidden = false;
  const statusKey = normalizeApprovalStatusKey(meta.approval_status);
  const versionNo = Number(meta.selected_version_no || meta.latest_version_no || 0);
  if (els.quoteApprovalStatusBadge) {
    els.quoteApprovalStatusBadge.className = `approval-status-badge ${approvalPillClass(statusKey)}`;
    els.quoteApprovalStatusBadge.textContent = approvalStatusText(statusKey);
  }
  if (els.approvalReviewerInput) {
    els.approvalReviewerInput.value = reviewerNameForInput(meta);
  }
  if (els.approvalStatusSelect) {
    els.approvalStatusSelect.value = statusKey;
  }
  if (els.approvalNoteInput) {
    els.approvalNoteInput.value = String(meta.approval_note || "");
  }
  if (els.quoteApprovalMeta) {
    const lines = [];
    lines.push(`审核人：${formatReviewerLabel(meta.approved_by)}`);
    lines.push(`审批状态：${approvalStatusText(statusKey)}`);
    const note = String(meta.approval_note || "").trim();
    lines.push(`审批备注：${note || "—"}`);
    if (versionNo > 0) {
      lines.push(`核实版本：v${versionNo}`);
    }
    const at = String(meta.approved_at || "").trim();
    if (at) lines.push(`审批时间：${at}`);
    if (statusKey === "approved" && meta.approved_version_no != null) {
      lines.push(`合格版本：v${meta.approved_version_no}`);
    }
    els.quoteApprovalMeta.textContent = lines.join(" · ") || "尚未保存审批记录";
  }
  if (els.quoteApprovalSaveHint) {
    els.quoteApprovalSaveHint.textContent =
      versionNo > 0 ? `保存后写入当前查看版本 v${versionNo}` : "保存后写入当前查看版本";
  }
}

function hideQuoteApprovalPanel() {
  if (els.quoteApprovalPanel) els.quoteApprovalPanel.hidden = true;
}

function isApprovalDraftDirty() {
  if (!lastBundle || !els.approvalNoteInput || !els.approvalStatusSelect) return false;
  const meta = lastBundle.meta || {};
  const savedNote = String(meta.approval_note || "");
  const savedStatus = normalizeApprovalStatusKey(meta.approval_status);
  const savedReviewer = reviewerNameForInput(meta);
  const curNote = String(els.approvalNoteInput.value || "");
  const curStatus = normalizeApprovalStatusKey(els.approvalStatusSelect.value);
  const curReviewer = readReviewerNameFromInput();
  return curNote !== savedNote || curStatus !== savedStatus || curReviewer !== savedReviewer;
}

function hasActiveListFilters() {
  return Boolean(
    els.filterSearch?.value.trim() ||
      els.filterDateFrom?.value ||
      els.filterDateTo?.value ||
      els.filterVerMin?.value.trim() ||
      els.filterStatus?.value.trim() ||
      els.filterSalesUser?.value.trim(),
  );
}

function maxSavedAtFromItems(items) {
  if (!Array.isArray(items) || !items.length) return "";
  return items.reduce((max, row) => {
    const s = String(row?.saved_at || "").trim();
    return s > max ? s : max;
  }, "");
}

function bumpLastSeenTime(savedAt) {
  const s = String(savedAt || "").trim();
  if (s && s > (lastSeenTime || "")) lastSeenTime = s;
}

function loadPendingWatchState() {
  try {
    const raw = localStorage.getItem(PENDING_WATCH_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    pendingWatchQuotes = Array.isArray(parsed) ? parsed : [];
  } catch {
    pendingWatchQuotes = [];
  }
  try {
    const raw = localStorage.getItem(SEEN_WATCH_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    seenWatchQuoteIds = new Set(Array.isArray(parsed) ? parsed.map(String) : []);
  } catch {
    seenWatchQuoteIds = new Set();
  }
  sortPendingWatchQuotes();
}

function savePendingWatchQuotes() {
  try {
    localStorage.setItem(PENDING_WATCH_STORAGE_KEY, JSON.stringify(pendingWatchQuotes));
  } catch {
    /* ignore quota errors */
  }
}

function saveSeenWatchQuoteIds() {
  try {
    localStorage.setItem(SEEN_WATCH_STORAGE_KEY, JSON.stringify([...seenWatchQuoteIds]));
  } catch {
    /* ignore quota errors */
  }
}

function normalizeWatchRow(row) {
  return {
    quote_id: String(row?.quote_id || ""),
    saved_at: String(row?.saved_at || ""),
    product_name: String(row?.product_name || ""),
    sheet_original_name: String(row?.sheet_original_name || ""),
    material_total: row?.material_total,
    latest_version_no: row?.latest_version_no != null ? Number(row.latest_version_no) : 1,
    approval_status: normalizeApprovalStatusKey(row?.approval_status),
  };
}

function sortPendingWatchQuotes() {
  pendingWatchQuotes.sort((a, b) =>
    String(b.saved_at || "").localeCompare(String(a.saved_at || "")),
  );
}

function mergeIncomingToPendingWatch(items) {
  if (!Array.isArray(items) || !items.length) return;
  const byId = new Map(pendingWatchQuotes.map((r) => [r.quote_id, r]));
  for (const row of items) {
    const norm = normalizeWatchRow(row);
    if (!norm.quote_id) continue;
    const existing = byId.get(norm.quote_id);
    if (existing) {
      const versionChanged = Number(norm.latest_version_no) !== Number(existing.latest_version_no);
      const timeChanged = norm.saved_at !== existing.saved_at;
      Object.assign(existing, norm);
      if (versionChanged || timeChanged) seenWatchQuoteIds.delete(norm.quote_id);
    } else {
      pendingWatchQuotes.push(norm);
      byId.set(norm.quote_id, norm);
    }
  }
  sortPendingWatchQuotes();
  savePendingWatchQuotes();
  saveSeenWatchQuoteIds();
  renderPendingWatchPanel();
  updateNewQuotesAlertUi();
}

function getUnseenWatchCount() {
  return pendingWatchQuotes.filter((r) => r.quote_id && !seenWatchQuoteIds.has(r.quote_id)).length;
}

function isQuoteWatchSeen(quoteId) {
  return seenWatchQuoteIds.has(String(quoteId || ""));
}

function markQuoteWatchSeen(quoteId) {
  const qid = String(quoteId || "");
  if (!qid) return;
  seenWatchQuoteIds.add(qid);
  saveSeenWatchQuoteIds();
  renderPendingWatchPanel();
  updateNewQuotesAlertUi();
}

function markAllWatchSeen() {
  for (const row of pendingWatchQuotes) {
    if (row.quote_id) seenWatchQuoteIds.add(row.quote_id);
  }
  saveSeenWatchQuoteIds();
  renderPendingWatchPanel();
  updateNewQuotesAlertUi();
}

function clearSeenWatchRecords() {
  pendingWatchQuotes = pendingWatchQuotes.filter((r) => !seenWatchQuoteIds.has(r.quote_id));
  seenWatchQuoteIds.clear();
  savePendingWatchQuotes();
  saveSeenWatchQuoteIds();
  renderPendingWatchPanel();
  updateNewQuotesAlertUi();
}

function removeQuoteFromWatch(quoteId) {
  const qid = String(quoteId || "");
  pendingWatchQuotes = pendingWatchQuotes.filter((r) => r.quote_id !== qid);
  seenWatchQuoteIds.delete(qid);
  savePendingWatchQuotes();
  saveSeenWatchQuoteIds();
  renderPendingWatchPanel();
  updateNewQuotesAlertUi();
}

function renderPendingWatchPanel() {
  if (!els.pendingWatchPanel) return;
  els.pendingWatchPanel.hidden = pendingWatchQuotes.length === 0;
  els.pendingWatchPanel.classList.toggle("is-collapsed", pendingWatchCollapsed);
  const unseen = getUnseenWatchCount();
  if (els.pendingWatchBadge) {
    els.pendingWatchBadge.textContent = String(unseen);
    els.pendingWatchBadge.hidden = unseen <= 0;
  }
  if (els.pendingWatchBody) els.pendingWatchBody.hidden = pendingWatchCollapsed;
  if (els.btnTogglePendingWatch) {
    els.btnTogglePendingWatch.setAttribute("aria-expanded", pendingWatchCollapsed ? "false" : "true");
  }
  if (els.btnWatchUnseenOnly) {
    els.btnWatchUnseenOnly.classList.toggle("is-active", pendingWatchUnseenOnly);
    els.btnWatchUnseenOnly.textContent = pendingWatchUnseenOnly ? "显示全部" : "只看待查看";
  }
  const rows = pendingWatchUnseenOnly
    ? pendingWatchQuotes.filter((r) => !isQuoteWatchSeen(r.quote_id))
    : pendingWatchQuotes;
  if (els.pendingWatchEmpty) els.pendingWatchEmpty.hidden = rows.length > 0;
  if (!els.pendingWatchListBody) return;
  els.pendingWatchListBody.innerHTML = "";
  for (const row of rows) {
    const qid = row.quote_id;
    const seen = isQuoteWatchSeen(qid);
    const tr = document.createElement("tr");
    tr.className = seen
      ? "pending-watch-row pending-watch-row-seen"
      : "pending-watch-row pending-watch-row-unseen";
    tr.dataset.quoteId = qid;
    tr.innerHTML = `
      <td>${escapeHtml(row.saved_at || "")}</td>
      <td>${escapeHtml(row.product_name || "")}</td>
      <td>${escapeHtml(row.sheet_original_name || "")}</td>
      <td class="col-num">${escapeHtml(formatMoney(row.material_total))}</td>
      <td class="col-num">${escapeHtml(String(row.latest_version_no ?? ""))}</td>
      <td>${renderApprovalPillHtml(row.approval_status)}</td>
      <td><span class="${seen ? "pending-watch-status-seen" : "pending-watch-status-unseen"}">${
        seen ? "已查看" : "未查看"
      }</span></td>
    `;
    tr.addEventListener("click", () => {
      openPendingWatchQuote(qid).catch(() => {});
    });
    els.pendingWatchListBody.appendChild(tr);
  }
}

async function openPendingWatchQuote(quoteId) {
  const qid = String(quoteId || "");
  if (!qid) return;
  if (isApprovalDraftDirty()) {
    showAdminToast("当前审批备注未保存，请先保存或取消后再查看新报价", "err");
    return;
  }
  const tr = [...(els.listBody?.querySelectorAll("tr") || [])].find((r) => r.dataset.quoteId === qid);
  const ok = await selectRow(qid, tr || null);
  if (ok) markQuoteWatchSeen(qid);
}

function updateNewQuotesAlertUi() {
  const n = getUnseenWatchCount();
  if (els.newQuotesAlert) els.newQuotesAlert.hidden = n <= 0;
  if (els.newQuotesAlertText) {
    els.newQuotesAlertText.textContent = n > 0 ? `有 ${n} 条待查看新报价` : "有新报价";
  }
  els.btnRefresh?.classList.toggle("btn-has-unread", n > 0);
}

function getListPollIntervalMs() {
  return document.hidden ? LIST_POLL_HIDDEN_MS : LIST_POLL_VISIBLE_MS;
}

function stopListPoll() {
  if (listPollTimer) {
    clearInterval(listPollTimer);
    listPollTimer = null;
  }
}

function startListPoll() {
  stopListPoll();
  listPollTimer = setInterval(() => {
    pollQuoteChanges().catch(() => {});
  }, getListPollIntervalMs());
}

function rescheduleListPoll() {
  if (!lastSeenTime) return;
  startListPoll();
}

function formatSalesOwnerLabel(row) {
  const name = String(row?.sales_user_name || "").trim();
  const id = String(row?.sales_user_id || "").trim();
  if (name) return name;
  if (id.startsWith("wecom:")) return id.slice(6);
  return id || "—";
}

function buildListRowElement(row, options = {}) {
  const tr = document.createElement("tr");
  const qid = String(row.quote_id || "");
  if (qid === selectedQuoteId) tr.classList.add("row-selected");
  if (options.incoming) tr.classList.add("row-new-incoming");
  tr.dataset.quoteId = qid;
  const verNo = row.latest_version_no != null ? Number(row.latest_version_no) : 1;
  tr.innerHTML = `
      <td class="col-check"><input type="checkbox" class="row-select-cb" data-quote-id="${escapeAttr(
        qid,
      )}" aria-label="选择该行" /></td>
      <td>${escapeHtml(row.saved_at || "")}</td>
      <td>${escapeHtml(formatSalesOwnerLabel(row))}</td>
      <td>${escapeHtml(row.product_name || "")}</td>
      <td>${escapeHtml(row.sheet_original_name || "")}</td>
      <td class="col-num">${escapeHtml(formatMoney(row.material_total))}</td>
      <td class="col-num">${escapeHtml(formatMoney(row.tier1_cost_before_margin))}</td>
      <td class="col-num">${escapeHtml(String(verNo))}</td>
      <td>${renderApprovalPillHtml(row.approval_status)}</td>
    `;
  tr.querySelector(".row-select-cb")?.addEventListener("click", (ev) => ev.stopPropagation());
  tr.addEventListener("click", (ev) => {
    if (ev.target.closest(".row-select-cb")) return;
    selectRow(qid, tr);
  });
  return tr;
}

function mergeIncomingQuoteRows(newItems) {
  if (!els.listBody || page !== 1 || hasActiveListFilters() || !Array.isArray(newItems)) return 0;
  const existing = new Set(
    [...els.listBody.querySelectorAll("tr")].map((r) => r.dataset.quoteId).filter(Boolean),
  );
  let merged = 0;
  const sorted = [...newItems].sort((a, b) =>
    String(b.saved_at || "").localeCompare(String(a.saved_at || "")),
  );
  // changes 接口已 DESC；逐条 insertBefore(firstChild) 须从旧到新插入，最终才最新在前
  for (let i = sorted.length - 1; i >= 0; i -= 1) {
    const row = sorted[i];
    const qid = String(row.quote_id || "");
    if (!qid || existing.has(qid)) continue;
    const tr = buildListRowElement(row, { incoming: true });
    els.listBody.insertBefore(tr, els.listBody.firstChild);
    existing.add(qid);
    merged += 1;
  }
  if (merged > 0) {
    els.listEmpty.hidden = true;
    while (els.listBody.rows.length > pageSize) {
      els.listBody.removeChild(els.listBody.lastChild);
    }
    total += merged;
    const pages = Math.max(1, Math.ceil(total / pageSize));
    els.pageLabel.textContent = `Page ${page} / ${pages} / ${total} rows`;
  }
  return merged;
}

async function pollQuoteChanges() {
  if (!lastSeenTime) return;
  const qs = new URLSearchParams({ since: lastSeenTime });
  const { ok, data } = await apiJson(`/admin-api/quotes/changes?${qs.toString()}`);
  if (!ok) {
    listPollFailCount += 1;
    const now = Date.now();
    if (now - listPollLastErrLogAt > 60000) {
      adminApiLog("poll_changes_fail", { count: listPollFailCount, data });
      listPollLastErrLogAt = now;
    }
    return;
  }
  listPollFailCount = 0;
  const items = Array.isArray(data?.items) ? data.items : [];
  const newCount = Number(data?.new_count) || 0;
  if (newCount <= 0 && !items.length) return;

  for (const row of items) {
    bumpLastSeenTime(row.saved_at);
  }
  mergeIncomingToPendingWatch(items);
  updateNewQuotesAlertUi();
  mergeIncomingQuoteRows(items);
  loadDashboardStats().catch(() => {});
}

function applyNewQuotesAlertAction() {
  pendingWatchCollapsed = false;
  try {
    localStorage.setItem(PENDING_WATCH_COLLAPSED_KEY, "0");
  } catch {
    /* ignore */
  }
  renderPendingWatchPanel();
  els.pendingWatchPanel?.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function applyApprovalMetaToBundle(meta, data) {
  if (!lastBundle || !data || typeof data !== "object") return;
  lastBundle.meta = {
    ...meta,
    approval_status: data.approval_status ?? meta.approval_status,
    approval_note:
      data.approval_note != null ? data.approval_note : meta.approval_note,
    approved_version_no:
      data.approved_version_no != null ? data.approved_version_no : meta.approved_version_no,
    approved_calc_quote_id:
      data.approved_calc_quote_id != null
        ? data.approved_calc_quote_id
        : meta.approved_calc_quote_id,
    approved_at: data.approved_at != null ? data.approved_at : meta.approved_at,
    approved_by: data.approved_by != null ? data.approved_by : meta.approved_by,
  };
}

async function saveQuoteApproval() {
  if (!selectedQuoteId || !lastBundle) return;
  const meta = lastBundle.meta || {};
  const versionNo = Number(meta.selected_version_no || meta.latest_version_no || 0);
  if (!versionNo) {
    showAdminToast("无法确定当前版本号", "err");
    return;
  }
  const statusKey = normalizeApprovalStatusKey(els.approvalStatusSelect?.value);
  const note = String(els.approvalNoteInput?.value || "").trim();
  const reviewerName = readReviewerNameFromInput();
  if (!reviewerName) {
    showAdminToast("请填写审核人姓名", "err");
    els.approvalReviewerInput?.focus();
    return;
  }
  if (els.btnSaveQuoteApproval) els.btnSaveQuoteApproval.disabled = true;
  const { ok, data } = await apiJson(
    `/admin-api/quotes/${encodeURIComponent(selectedQuoteId)}/approval`,
    {
      method: "POST",
      body: JSON.stringify({
        approval_status: statusKey,
        approval_note: note,
        reviewer_name: reviewerName,
        version_no: versionNo,
      }),
    },
  );
  if (els.btnSaveQuoteApproval) els.btnSaveQuoteApproval.disabled = false;
  if (!ok) {
    if (data?.error === "forbidden") gotoLogin();
    else showAdminToast(data?.message || data?.error || "保存审批失败", "err");
    return;
  }
  applyApprovalMetaToBundle(meta, data);
  renderQuoteApprovalPanel(lastBundle.meta);
  await loadList();
  const refreshedRow = selectedQuoteId
    ? [...els.listBody.querySelectorAll("tr")].find((tr) => tr.dataset.quoteId === selectedQuoteId)
    : null;
  if (selectedQuoteId) {
    await selectRow(selectedQuoteId, refreshedRow || null);
  }
  showAdminToast(data?.message || "审批结果已保存，业务员将收到待查看提醒");
}

function renderDetailSubtitle(meta) {
  const v = meta.selected_version_no != null ? `v${meta.selected_version_no}` : "-";
  const saved = String(meta.latest_saved_at || "").trim() || "-";
  els.detailSubtitle.textContent = `Version ${v} / saved ${saved}`;
}

function renderTechMeta(meta, quoteId) {
  const uid = String(meta.quote_uid || quoteId || "");
  const rows = [
    ["报价 UID", uid],
    ["当前版本", String(meta.selected_version_no ?? "")],
    ["最新版本号", String(meta.latest_version_no ?? "")],
    ["核算 ID（当前）", String(meta.selected_calc_quote_id || "")],
    ["最新核算 ID", String(meta.latest_calc_quote_id || "")],
    ["saved_at", String(meta.latest_saved_at || "")],
    ["sheet_name", String(meta.sheet_original_name || "")],
    ["物料合计（快照）", formatMoney(meta.material_total)],
    ["一档毛利前成本（快照）", formatMoney(meta.tier1_cost_before_margin)],
  ];
  els.detailMetaDl.innerHTML = rows
    .map(
      ([k, v]) =>
        `<div><dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v)}</dd></div>`,
    )
    .join("");
}

function estimateNoticeCount(text) {
  const t = String(text || "").trim();
  if (!t) return 1;
  const parts = t
    .split(/[。；;，?？\n\r]+/)
    .map((s) => s.trim())
    .filter((s) => s.length >= 4);
  const hit = parts.filter((p) =>
    /缺失|补齐|准确|差异|核验|提醒|注意|异常|数据|AI|口径|粗略|规格/.test(p),
  ).length;
  return Math.max(hit || 1, 1);
}

function renderOverviewNotice(text) {
  const dn = String(text || "").trim();
  if (!dn) {
    els.overviewNoticeWrap.hidden = true;
    els.overviewNoticeFull.textContent = "";
    return;
  }
  if (els.detailWorkspace.classList.contains("simple-mode")) {
    els.overviewNoticeWrap.hidden = true;
    return;
  }
  const n = estimateNoticeCount(dn);
  els.overviewNoticeWrap.hidden = false;
  els.overviewNoticeFull.textContent = dn;
  els.overviewNoticeFull.hidden = true;
  els.overviewNoticeToggle.textContent = `数据提醒 · 共 ${n} 条相关说明，点击展开`;
  els.overviewNoticeToggle.setAttribute("aria-expanded", "false");
}

function resetOverviewUi() {
  overviewExpanded = false;
  if (els.panelOverview) els.panelOverview.classList.remove("overview-expanded");
  if (els.btnOverviewExpand) els.btnOverviewExpand.textContent = "展开成本拆解";
  if (els.overviewNoticeFull) {
    els.overviewNoticeFull.hidden = true;
    els.overviewNoticeFull.textContent = "";
  }
  if (els.overviewNoticeToggle) {
    els.overviewNoticeToggle.setAttribute("aria-expanded", "false");
    els.overviewNoticeToggle.textContent = "";
  }
  if (els.btnToggleTech) {
    els.btnToggleTech.setAttribute("aria-expanded", "false");
    els.btnToggleTech.textContent = "Tech info";
  }
  if (els.detailTechPanel) els.detailTechPanel.hidden = true;
}

function syncSimpleModeClass() {
  els.detailWorkspace.classList.toggle("simple-mode", els.chkSimpleMode.checked);
  try {
    localStorage.setItem(SIMPLE_MODE_KEY, els.chkSimpleMode.checked ? "1" : "0");
  } catch {
    /* ignore */
  }
}

function loadSimpleModeCheckbox() {
  try {
    els.chkSimpleMode.checked = localStorage.getItem(SIMPLE_MODE_KEY) === "1";
  } catch {
    els.chkSimpleMode.checked = false;
  }
}

function refreshNoticeVisibility() {
  if (!lastBundle) return;
  renderOverviewNotice(String(lastBundle.quote?.data_notice || "").trim());
}

async function guardAdminRoleOrRedirect() {
  const { ok, data } = await apiJson("/admin-api/session");
  if (!ok || !data.authenticated || data.role !== "admin") {
    gotoLogin();
    return false;
  }
  return true;
}

function formatMoney(n) {
  const x = Number(n);
  if (Number.isFinite(x)) return x.toFixed(2);
  return String(n ?? "-");
}

function formatPct(ratio) {
  const x = Number(ratio);
  if (!Number.isFinite(x)) return "-";
  return `${(x * 100).toFixed(1)}%`;
}

function quoteIsExwCostVatMode(quote) {
  return !!(quote && quote.include_fob === false);
}

function taxedUnitPriceAdmin(tier) {
  const direct = Number(tier.taxed_price);
  if (Number.isFinite(direct)) return direct;
  const cbm = Number(tier.cost_before_margin ?? tier.total_cost);
  return Number.isFinite(cbm) ? Math.round(cbm * 1.13 * 100) / 100 : NaN;
}

function parseAmountNum(row) {
  const raw = row?.amount;
  const x = Number(raw);
  if (Number.isFinite(x)) return x;
  const t = String(row?.amount_text || "").replace(/,/g, "");
  const m = t.match(/-?[\d.]+/);
  if (m) {
    const y = Number(m[0]);
    if (Number.isFinite(y)) return y;
  }
  return NaN;
}

function csvEscapeCell(value) {
  const s = String(value ?? "")
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .replace(/\n+/g, " ")
    .trim();
  if (/[",\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function csvRow(cells) {
  return cells.map(csvEscapeCell).join(",");
}

function csvBlankLine() {
  return "";
}

function csvSectionBanner(title, width = 8) {
  const cells = [`【${title}】`, ...Array(Math.max(0, width - 1)).fill("")];
  return csvRow(cells);
}

function bomPairSource(pair) {
  const r = pair.row || {};
  const db = pair.db || {};
  const origin = cleanBomText(r.data_origin_label || db.data_origin_label, "");
  const source = cleanBomText(db.source || r.source, "system");
  if (origin && source && origin !== source) return `${origin} / ${source}`;
  return origin || source || "system";
}

function bomPairCheckStatus(pair) {
  const badges = classifyAnomalies(pair)
    .map((b) => b.text)
    .filter((t) => t && t !== "正常");
  return badges.length ? badges.join("；") : "正常";
}

function inferBomMaterialType(name) {
  const n = String(name || "");
  if (/^外料|主料|^面料/.test(n) || (/布|尼龙|涤纶|牛津|帆布|塔丝隆|记忆布/.test(n) && !/里/.test(n))) return "外料";
  if (/里料|里布|内衬|210D里/.test(n)) return "里料";
  if (/拉链/.test(n) && !/拉头/.test(n)) return "拉链";
  if (/拉头|拉片|拉链头/.test(n)) return "拉头";
  if (/扣|D扣|插扣|扣具|日字扣|勾扣/.test(n)) return "扣具";
  if (/织带|包边|背带|肩带|提手/.test(n)) return "织带/包边";
  if (/LOGO|织唛|唛头|商标/.test(n)) return "织唛/LOGO";
  if (/OPP|纸箱|外箱|包装|贴纸/.test(n)) return "包装";
  if (/填充|海绵|棉|珍珠棉/.test(n)) return "填充";
  if (/内袋|插袋|分隔|辅料/.test(n)) return "辅料";
  if (/工艺|车缝|印刷|刺绣/.test(n)) return "工艺";
  return "";
}

function bomPairMaterialType(pair) {
  const r = pair.row || {};
  const db = pair.db || {};
  return cleanBomText(
    firstBomValue(r.category_label, r.category, db.category_label, db.category, inferBomMaterialType(r.name)),
    "其他",
  );
}

function bomMeasureUnit(row) {
  const direct = cleanBomText(row?.unit, "");
  if (direct) return direct;
  const up = String(row?.unit_price || "");
  const mUp = up.match(/元\s*\/\s*([^\s/]+)/);
  if (mUp) return mUp[1];
  const usage = String(row?.usage || "");
  const mUsage = usage.match(/(?:^|[\d.]+\s*)(㎡|m²|m2|平米|码|个|套|米|PCS|pcs|SET|YD|yd|cm|英寸|英尺)/i);
  if (mUsage) return mUsage[1];
  return "";
}

function bomAmountNumeric(row) {
  const n = parseAmountNum(row);
  return Number.isFinite(n) ? formatMoney(n) : "";
}

function isExportableBomPair(pair) {
  const r = pair.row || {};
  const name = String(r.name || "-").trim();
  const spec = String(r.spec || "").trim();
  const usage = String(r.usage || "").trim();
  const up = String(r.unit_price || "").trim();
  if (name !== "-" || spec || usage || up) return true;
  return Number.isFinite(parseAmountNum(r));
}

function buildBomCostSummaryRows(quote) {
  const tiers = Array.isArray(quote?.tiers) ? quote.tiers : [];
  const t0 = tiers[0] || {};
  const cb = quote?.cost_bridge || {};
  const rows = [];
  const mt = Number(quote?.material_total);
  if (Number.isFinite(mt)) rows.push(["物料合计", formatMoney(mt), "BOM 明细金额汇总"]);
  const cbm = Number(t0.cost_before_margin ?? t0.total_cost);
  if (Number.isFinite(cbm)) rows.push(["单包系统成本（一档·毛利前）", formatMoney(cbm), "含加工/模具/杂费分摊"]);
  const proc = Number(t0.processing_fee ?? cb.processing_fee_per_pc);
  if (Number.isFinite(proc) && proc > 0) rows.push(["加工费（单包）", formatMoney(proc), ""]);
  const mold = Number(t0.mold_share ?? cb.mold_share_per_pc);
  if (Number.isFinite(mold) && mold > 0) rows.push(["模具分摊（单包）", formatMoney(mold), ""]);
  const oh = Number(cb.system_overhead_per_pc);
  if (Number.isFinite(oh) && oh > 0) rows.push(["系统杂费（单包）", formatMoney(oh), ""]);
  return rows;
}

function buildMaterialBomCsv(bundle) {
  const quote = bundle?.quote || {};
  const meta = bundle?.meta || {};
  const pairs = sortedPairs(pairDetailRows(quote, Array.isArray(bundle?.items) ? bundle.items : [])).filter(
    isExportableBomPair,
  );
  const lines = [];
  const productName = String(meta.product_name || quote.product_name || "").trim();
  const sourceFile = String(meta.source_filename || meta.original_filename || meta.sheet_original_name || "").trim();
  const versionNo = meta.selected_version_no ?? "";
  const savedAt = String(meta.saved_at || meta.created_at || "").trim();
  const exportTime = new Date().toLocaleString("zh-CN", { hour12: false });

  lines.push(csvRow(["材料 BOM 明细表"]));
  lines.push(csvRow(["产品", productName || "-"]));
  if (meta.quote_uid) lines.push(csvRow(["报价 UID", meta.quote_uid]));
  if (versionNo !== "") lines.push(csvRow(["版本", `v${versionNo}`]));
  if (sourceFile) lines.push(csvRow(["源文件", sourceFile]));
  if (savedAt) lines.push(csvRow(["归档时间", savedAt]));
  lines.push(csvRow(["导出时间", exportTime]));
  lines.push(csvBlankLine());

  lines.push(csvSectionBanner("一、产品基本信息"));
  lines.push(csvRow(["项目", "内容"]));
  for (const [k, v] of buildBomProductRows(quote, meta)) {
    lines.push(csvRow([k, v]));
  }
  lines.push(csvBlankLine());

  lines.push(csvSectionBanner("二、物料单价确认"));
  lines.push(csvRow(["序号", "物料名称", "单价", "计价单位", "数据来源"]));
  pairs.forEach((pair) => {
    const r = pair.row || {};
    lines.push(
      csvRow([
        pair.lineNo,
        cleanBomText(r.name, "-"),
        cleanBomText(r.unit_price, "-"),
        bomMeasureUnit(r) || "-",
        bomPairSource(pair),
      ]),
    );
  });
  lines.push(csvBlankLine());

  const fabricPairs = pairs.filter(likelyFabricPair);
  lines.push(csvSectionBanner("三、裁片面积核算"));
  const pieceCalc = resolvePieceAreaCalc(quote, pairs);
  lines.push(csvRow(["裁片", "尺寸（cm）", "数量", "单面积（cm²）", "总面积（cm²）"]));
  if (pieceCalc) {
    pieceCalc.rows.forEach((r) => {
      if (r?.is_total) {
        lines.push(csvRow([r.piece || "合计", "", "", "", String(r.total_area_cm2 ?? "")]));
        return;
      }
      lines.push(
        csvRow([
          cleanBomText(r.piece, "-"),
          cleanBomText(r.size_text, "-"),
          cleanBomText(r.qty_text, "-"),
          r.unit_area_cm2 != null && r.unit_area_cm2 !== "" ? String(r.unit_area_cm2) : "-",
          r.total_area_cm2 != null && r.total_area_cm2 !== "" ? String(r.total_area_cm2) : "-",
        ]),
      );
    });
    (pieceCalc.notes || []).forEach((n) => {
      if (n) lines.push(csvRow(["说明", cleanBomText(n)]));
    });
  } else {
    lines.push(csvRow(["", "当前归档未识别到裁片面积核算表", "", "", ""]));
  }
  lines.push(csvBlankLine());

  const markerTable = quote?.marker_room_bom_table;
  lines.push(csvSectionBanner("三B、板房排刀用量明细"));
  lines.push(
    csvRow([
      "物料名称",
      "幅宽",
      "排刀幅宽",
      "部位名称",
      "长度",
      "宽度",
      "占用长度",
      "占用宽度",
      "件数",
      "单件排刀用量",
      "损耗%",
      "物料排刀总用量",
      "单位",
      "物料单价",
      "物料金额",
      "异常/待核",
    ]),
  );
  if (markerTable && Array.isArray(markerTable.rows) && markerTable.rows.length) {
    markerTable.rows.forEach((r) => {
      lines.push(
        csvRow([
          cleanBomText(r.material_name, ""),
          cleanBomText(r.roll_width, ""),
          cleanBomText(r.marker_width, ""),
          cleanBomText(r.piece_name, ""),
          cleanBomText(r.length, ""),
          cleanBomText(r.width, ""),
          cleanBomText(r.occupied_length, ""),
          cleanBomText(r.occupied_width, ""),
          cleanBomText(r.qty, ""),
          cleanBomText(r.single_marker_usage, ""),
          cleanBomText(r.loss_pct, ""),
          cleanBomText(r.total_marker_usage, ""),
          cleanBomText(r.unit, ""),
          cleanBomText(r.unit_price, ""),
          cleanBomText(r.amount, ""),
          Array.isArray(r.badges) ? r.badges.join("；") : "",
        ]),
      );
    });
  } else {
    lines.push(csvRow(["", "无板房用量明细数据", "", "", "", "", "", "", "", "", "", "", "", "", "", ""]));
  }
  lines.push(csvBlankLine());

  lines.push(csvSectionBanner("四、面料/裁片用量核算"));
  lines.push(csvRow(["序号", "裁片/物料", "尺寸/规格", "用量", "计算方式", "小计(元)", "核验状态"]));
  if (fabricPairs.length) {
    fabricPairs.forEach((pair) => {
      const r = pair.row || {};
      lines.push(
        csvRow([
          pair.lineNo,
          cleanBomText(r.name, "-"),
          cleanBomText(r.spec, "-"),
          cleanBomText(r.usage, "-"),
          cleanBomText(pair.mergedCalcNote || r.calc_method || r.calc_note, "-"),
          bomAmountNumeric(r) || bomAmountText(r),
          bomPairCheckStatus(pair),
        ]),
      );
    });
  } else {
    lines.push(csvRow(["", "当前归档未识别到面料用量表", "", "", "", "", ""]));
  }
  lines.push(csvBlankLine());

  lines.push(csvSectionBanner("五、各物料成本明细（全量）"));
  lines.push(
    csvRow(["序号", "类型", "物料名称", "规格", "用量", "单价", "金额(元)", "计算方式", "数据来源", "核验状态"]),
  );
  pairs.forEach((pair) => {
    const r = pair.row || {};
    lines.push(
      csvRow([
        pair.lineNo,
        bomPairMaterialType(pair),
        cleanBomText(r.name, "-"),
        cleanBomText(r.spec, "-"),
        cleanBomText(r.usage, "-"),
        cleanBomText(r.unit_price, "-"),
        bomAmountNumeric(r) || bomAmountText(r),
        cleanBomText(pair.mergedCalcNote || r.calc_note, "-"),
        bomPairSource(pair),
        bomPairCheckStatus(pair),
      ]),
    );
  });
  const materialTotal = Number(quote.material_total);
  if (Number.isFinite(materialTotal)) {
    lines.push(csvRow(["", "合计", "", "", "", "", formatMoney(materialTotal), "", "", ""]));
  }
  lines.push(csvBlankLine());

  const summaryRows = buildBomCostSummaryRows(quote);
  if (summaryRows.length) {
    lines.push(csvSectionBanner("五、成本汇总"));
    lines.push(csvRow(["项目", "金额(元)", "说明"]));
    summaryRows.forEach(([k, v, note]) => lines.push(csvRow([k, v, note || ""])));
  }

  return `\ufeff${lines.join("\r\n")}`;
}

function downloadMaterialBomCsv(bundle) {
  const uid = String(bundle.meta?.quote_uid || "quote");
  const ver = bundle.meta?.selected_version_no ?? "";
  const verSuffix = ver !== "" ? `_v${ver}` : "";
  const csv = buildMaterialBomCsv(bundle);
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${uid}${verSuffix}_材料BOM.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

function usageSortKey(usage) {
  const s = String(usage || "");
  const m = s.match(/([\d.]+)/);
  if (m) return Number(m[1]);
  return s;
}

/** 裁片展示名：片数规则，禁止「组」（仅展示，不改面积核算 qty_text） */
function pieceNameForDisplay(pieceRaw, qtyText) {
  let piece = String(pieceRaw || "")
    .trim()
    .replace(/[（(]\s*推理待核\s*[)）]/g, "");
  piece = piece.replace(/[（(]\s*(?:1\s*组|一组)\s*[)）]/g, "").trim();
  if (!piece) return "";
  if (/[（(]\s*\d+\s*片\s*[)）]/.test(piece)) return piece;
  const qty = String(qtyText || "").trim();
  if (/组/.test(qty)) {
    if (/侧片|左右片|双侧/.test(piece) && !/[（(]/.test(piece)) return `${piece}（2片）`;
    const m = qty.match(/(\d+)\s*片/);
    if (m && parseInt(m[1], 10) > 1) return `${piece}（${m[1]}片）`;
    return piece;
  }
  const mQty = qty.match(/(\d+)\s*片/);
  if (mQty && parseInt(mQty[1], 10) > 1 && !/[（(]\s*\d+\s*片/.test(piece)) {
    return `${piece}（${mQty[1]}片）`;
  }
  if (/侧片|左右片|双侧/.test(piece) && !/[（(]/.test(piece)) return `${piece}（2片）`;
  return piece;
}

function formatPieceRowLabel(row) {
  const name = pieceNameForDisplay(row.piece, row.qty_text);
  if (!name) return "";
  let size = String(row.size_text || "").trim();
  if (!size || size === "-" || size === "—") size = row.inferred ? "估算" : "待核";
  const hasDim = size.includes("×");
  if (hasDim || size === "估算" || size === "待核") {
    const joiner = name.endsWith("）") || name.endsWith(")") ? "" : " ";
    return `${name}${joiner}${size}`;
  }
  const m = name.match(/[（(]\s*(\d+)\s*片\s*[)）]/);
  if (m) return `${name.slice(0, m.index).trim()} ${m[1]}片`;
  return `${name} 1片`;
}

function looksLikePieceManifestText(text) {
  const s = String(text || "").trim();
  if (!s) return false;
  const markers = ["前片", "后片", "底片", "侧片", "拉链弧形盖"];
  let hits = 0;
  for (const m of markers) {
    if (s.includes(m)) hits += 1;
  }
  if (hits >= 2) return true;
  if (hits >= 1 && /[；;]/.test(s) && /\d+\s*[×xX*]\s*\d+/.test(s)) return true;
  return false;
}

function isMainFabricMaterialName(name) {
  const n = String(name || "");
  if (!n) return false;
  if (/拉链|拉头|扣|垫|提手|工艺|包装|纸箱|胶袋|外箱|挂钩|织标|魔术贴|缝纫线/.test(n)) return false;
  return /牛津|涤纶|里布|无纺|帆布|色丁|塔夫|提花|主布|面料|尼龙布|网布|斜纹|平纹|色织/.test(n);
}

function piecePartNamesOnlyFromArea(quote) {
  const pac = quote && typeof quote === "object" ? quote.piece_area_calculation : null;
  const rows = pac && Array.isArray(pac.rows) ? pac.rows : [];
  const labels = rows
    .filter((r) => r && !r.is_total)
    .map((r) => pieceNameForDisplay(r.piece, r.qty_text))
    .filter(Boolean);
  return labels.length ? labels.join("；") : "";
}

/** 裁片/部位：仅主料显示裁片清单；辅料用本行 piece_part，禁止裁片清单污染规格列 */
function formatDetailPiecePart(piecePart, quote, materialName) {
  let raw = String(piecePart || "").trim();
  if (!raw || raw === "-" || raw === "—") raw = "";
  raw = raw
    .replace(/[（(]\s*(?:1\s*组|一组)\s*[)）]/g, "")
    .replace(/[（(]\s*推理待核\s*[)）]/g, "")
    .replace(/；\s*；/g, "；")
    .trim();

  if (!isMainFabricMaterialName(materialName)) {
    if (raw && !looksLikePieceManifestText(raw)) return raw;
    const n = String(materialName || "").trim();
    if (/背垫/.test(n)) return "背垫";
    if (/提手/.test(n)) return "提手";
    if (/隔层|夹层/.test(n)) return "隔层";
    if (/工艺|加工|车缝/.test(n)) return "工艺费";
    if (/包装|纸箱|胶袋/.test(n)) return "包装";
    if (/侧袋/.test(n)) return "侧袋";
    return raw || "待核";
  }

  if (raw && !looksLikePieceManifestText(raw)) return raw;
  const fromArea = piecePartNamesOnlyFromArea(quote);
  return fromArea || raw || "待核";
}

function pairDetailRows(quote, items) {
  const dr = Array.isArray(quote.detail_rows) ? quote.detail_rows : [];
  const imap = new Map();
  for (const it of items || []) {
    const ln = Number(it.line_no);
    if (!Number.isNaN(ln) && ln > 0) imap.set(ln, it);
  }
  let maxLine = dr.length;
  for (const k of imap.keys()) maxLine = Math.max(maxLine, k);

  const pairs = [];
  for (let lineNo = 1; lineNo <= maxLine; lineNo++) {
    const r = dr[lineNo - 1];
    const db = imap.get(lineNo);

    let rowObj;
    if (r && typeof r === "object") {
      rowObj = { ...r };
      if (db && typeof db === "object") {
        const fillIfEmpty = (key) => {
          const v = rowObj[key];
          const empty = v == null || (typeof v === "string" && v.trim() === "");
          const dv = db[key];
          if (empty && dv != null && String(dv).trim() !== "") rowObj[key] = dv;
        };
        fillIfEmpty("name");
        fillIfEmpty("spec");
        fillIfEmpty("usage");
        fillIfEmpty("unit_price");
        fillIfEmpty("amount_text");
        fillIfEmpty("source");
        if ((rowObj.amount == null || rowObj.amount === "") && db.amount != null) rowObj.amount = db.amount;
      }
    } else if (db && typeof db === "object") {
      rowObj = {
        name: db.name || "-",
        spec: db.spec || "",
        usage: db.usage || "",
        unit_price: db.unit_price || "",
        amount: db.amount != null ? db.amount : null,
        amount_text: db.amount_text || "",
        source: db.source || "",
        calc_note: db.calc_note || "",
        accuracy_hints: [],
      };
    } else {
      rowObj = {
        name: "-",
        spec: "",
        usage: "",
        unit_price: "",
        amount: null,
        amount_text: "",
        source: "",
        calc_note: "",
        accuracy_hints: [],
      };
    }

    const mergedCalcNote = firstPresentValue([
      db && db.calc_note != null ? String(db.calc_note).trim() : "",
      rowObj.calc_note != null ? String(rowObj.calc_note).trim() : "",
      rowObj.calc_method != null ? String(rowObj.calc_method).trim() : "",
      db && db.calc_method != null ? String(db.calc_method).trim() : "",
    ]);

    pairs.push({ row: rowObj, db: db || {}, lineNo, mergedCalcNote });
  }
  return pairs;
}

function classifyAnomalies(pair) {
  const r = pair.row;
  const hints = Array.isArray(r.accuracy_hints) ? r.accuracy_hints : [];
  const badges = [];
  const push = (cls, text) => {
    if (!badges.some((b) => b.text === text)) badges.push({ cls, text });
  };

  for (const h of hints) {
    const t = String(h);
    if (/用量|单价|口径|语义/.test(t)) push("badge-warn", "单位/口径待核");
    if (/核验|首行|档位/.test(t)) push("badge-risk", "用量可疑");
  }

  const cn = String(pair.mergedCalcNote || "").trim();
  if (!cn) push("badge-warn", "计算方式缺失");

  const usage = String(r.usage || "");
  const up = String(r.unit_price || "");
  if (usage && up && /\d/.test(usage) && /\d/.test(up)) {
    const unitTokens = /m²|m\^?2|M2|平米|PCS|pcs|SET|套|YD|码|英寸|英尺|cm\b/i;
    if (!unitTokens.test(usage) && usage.length <= 6 && /^[\d.]+\s*$/.test(usage.trim())) {
      push("badge-warn", "usage unit unclear");
    }
  }

  if (!badges.length) push("badge-ok", "正常");
  return badges;
}

function escapeAttr(s) {
  return escapeHtml(s).replace(/"/g, "&quot;");
}

async function loadDashboardStats() {
  const { ok, status, data } = await apiJson("/admin-api/stats");
  if (!ok) {
    if (data?.error === "forbidden") {
      gotoLogin();
      return;
    }
    showAdminToast(data?.message || `统计加载失败（HTTP ${status}）`, "err");
    return;
  }
  els.statTotal.textContent = String(data.total_quotes ?? 0);
  els.statToday.textContent = String(data.today_new ?? 0);
  els.statLatest.textContent = data.latest_saved_at ? String(data.latest_saved_at) : "—";
}

function buildListUrl() {
  const qs = new URLSearchParams();
  qs.set("page", String(page));
  qs.set("page_size", String(pageSize));
  const q = els.filterSearch.value.trim();
  if (q) qs.set("q", q);
  const df = els.filterDateFrom.value;
  const dt = els.filterDateTo.value;
  if (df) qs.set("from", df);
  if (dt) qs.set("to", dt);
  const vm = els.filterVerMin.value.trim();
  if (vm) qs.set("version_min", vm);
  const st = els.filterStatus.value.trim();
  if (st) qs.set("status", st);
  const su = els.filterSalesUser?.value.trim();
  if (su) qs.set("sales_user_q", su);
  return `/admin-api/quotes?${qs.toString()}`;
}

/** 与列表 GET 同源筛选字段，用于「按筛选全部删除」。 */
function buildListFilterPayload() {
  const vmRaw = els.filterVerMin.value.trim();
  let version_min;
  if (vmRaw !== "") {
    const n = parseInt(vmRaw, 10);
    if (!Number.isNaN(n)) version_min = n;
  }
  const st = els.filterStatus.value.trim();
  /** @type {Record<string, string | number>} */
  const o = {};
  const q = els.filterSearch.value.trim();
  const df = els.filterDateFrom.value;
  const dt = els.filterDateTo.value;
  if (q) o.q = q;
  if (df) o.from = df;
  if (dt) o.to = dt;
  if (st) o.status = st;
  if (version_min != null) o.version_min = version_min;
  const su = els.filterSalesUser?.value.trim();
  if (su) o.sales_user_q = su;
  return o;
}

function syncBatchToolbar() {
  if (!els.listBody || !els.btnBatchDelete || !els.batchSelectHint) return;
  const cbs = els.listBody.querySelectorAll(".row-select-cb");
  const checked = els.listBody.querySelectorAll(".row-select-cb:checked");
  const n = checked.length;
  els.batchSelectHint.textContent = n ? `已选 ${n} 条` : "";
  els.btnBatchDelete.disabled = n === 0;
  if (els.chkSelectPage && cbs.length) {
    els.chkSelectPage.checked = n === cbs.length && n > 0;
    els.chkSelectPage.indeterminate = n > 0 && n < cbs.length;
  }
}

function collapseDetailIfSelectionMissing() {
  if (!selectedQuoteId) return;
  const hit = [...els.listBody.querySelectorAll("tr")].some(
    (r) => r.dataset.quoteId === selectedQuoteId,
  );
  if (hit) return;
  selectedQuoteId = null;
  selectedRowEl = null;
  lastBundle = null;
  hideQuoteApprovalPanel();
  els.detailPlaceholder.hidden = false;
  els.detailWorkspace.hidden = true;
  if (els.tierCompareMount) els.tierCompareMount.innerHTML = "";
  if (els.overviewHeroMount) els.overviewHeroMount.innerHTML = "";
  if (els.overviewCostMix) els.overviewCostMix.innerHTML = "";
  if (els.overviewEmbeddedDetailBody) els.overviewEmbeddedDetailBody.innerHTML = "";
  if (els.overviewSuggestions) els.overviewSuggestions.innerHTML = "";
  if (els.overviewCredibility) els.overviewCredibility.innerHTML = "";
}

async function loadList() {
  const listUrl = buildListUrl();
  const { ok, status, data } = await apiJson(listUrl);
  if (!ok) {
    if (data?.error === "forbidden") {
      gotoLogin();
      return;
    }
    els.listBody.innerHTML = "";
    els.listEmpty.hidden = false;
    els.listEmpty.textContent = data?.message || `列表加载失败（HTTP ${status}）`;
    showAdminToast(data?.message || `列表加载失败（HTTP ${status}）`, "err");
    return;
  }
  total = Number(data.total) || 0;
  const items = Array.isArray(data.items) ? data.items : [];
  els.listBody.innerHTML = "";
  els.listEmpty.hidden = items.length > 0;
  if (!items.length) els.listEmpty.textContent = LIST_EMPTY_DEFAULT;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  els.pageLabel.textContent = `Page ${page} / ${pages} / ${total} rows`;
  els.btnPrev.disabled = page <= 1;
  els.btnNext.disabled = page >= pages;

  for (const row of items) {
    els.listBody.appendChild(buildListRowElement(row));
  }
  if (page === 1 && !hasActiveListFilters()) {
    const mx = maxSavedAtFromItems(items);
    if (mx) {
      bumpLastSeenTime(mx);
    } else if (!lastSeenTime) {
      lastSeenTime = new Date().toISOString().slice(0, 19) + "Z";
    }
  }
  if (els.chkSelectPage) {
    els.chkSelectPage.checked = false;
    els.chkSelectPage.indeterminate = false;
  }
  syncBatchToolbar();
}

function setActiveTab(name) {
  document.querySelectorAll(".tab").forEach((btn) => {
    const tabName = btn.dataset.tab || "";
    const on = tabName === name && name !== "files";
    btn.classList.toggle("tab-active", on);
    btn.setAttribute("aria-selected", on ? "true" : "false");
  });
  Object.entries(TAB_IDS).forEach(([k, panel]) => {
    if (!panel) return;
    const on = k === name;
    panel.hidden = !on;
    panel.classList.toggle("tab-panel-active", on);
  });
}

document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => setActiveTab(btn.dataset.tab || "overview"));
});

const PKG_KW_RE =
  /包装|OPP|胶带|自封袋|纸箱|纸盒|标牌|贴纸|吊牌|封箱|包装箱|拷贝|胶袋/i;

function tierQtyNum(t) {
  const q = Number(t?.quantity);
  if (Number.isFinite(q)) return q;
  const m = String(t?.quantity_text || "").match(/(\d+)/);
  return m ? Number(m[1]) : NaN;
}

function tierNumericSnapshot(t) {
  const cbm = Number(t?.cost_before_margin);
  const exw = Number(t?.exw_price);
  return {
    qty: tierQtyNum(t),
    cbm: Number.isFinite(cbm) ? cbm : NaN,
    exw: Number.isFinite(exw) ? exw : NaN,
    marginText: String(t?.margin_rate_text || "-"),
  };
}

function computeRowOriginStats(rows) {
  const list = Array.isArray(rows) ? rows : [];
  let kb = 0;
  let ai = 0;
  let manual = 0;
  let other = 0;
  let counted = 0;
  for (const r of list) {
    if (!r || typeof r !== "object") continue;
    const name = String(r.name || "").trim();
    if (!name) continue;
    counted++;
    const o = String(r.data_origin_label || "");
    if (o.includes("KB")) kb++;
    else if (o.includes("AI")) ai++;
    else if (o.includes("浜哄伐")) manual++;
    else other++;
  }
  return { kb, ai, manual, other, counted };
}

function computeValidationFallback(rows) {
  const list = Array.isArray(rows) ? rows : [];
  let unitConflict = 0;
  let incomplete = 0;
  let highRisk = 0;
  for (const r of list) {
    const st = String(r?.validation_status || "OK").trim();
    if (st === "UNIT_CONFLICT") unitConflict++;
    else if (st === "INCOMPLETE") incomplete++;
    else if (st === "HIGH_RISK") highRisk++;
  }
  return { unitConflict, incomplete, highRisk };
}

function derivePackagingFromRows(rows, cbm) {
  const list = Array.isArray(rows) ? rows : [];
  let sum = 0;
  let kbPart = 0;
  let matched = 0;
  for (const r of list) {
    const name = String(r?.name || "");
    if (!PKG_KW_RE.test(name)) continue;
    const a = parseAmountNum(r);
    if (!Number.isFinite(a)) continue;
    sum += a;
    matched++;
    if (String(r.data_origin_label || "").includes("KB")) kbPart += a;
  }
  const pct = Number.isFinite(cbm) && cbm > 0 ? sum / cbm : NaN;
  let sourceHint = "";
  if (matched === 0) {
    sourceHint =
      "No packaging row matched; consider checking box/bag cost by dimensions.";
  } else if (sum > 0 && kbPart >= sum * 0.55) {
    sourceHint = "Packaging amount is mostly from KB rows.";
  } else {
    sourceHint = "Packaging rows are mostly sheet-derived or estimated.";
  }
  return { sum, pct, matched, sourceHint };
}

function highlightTierIndex(tiers) {
  const arr = Array.isArray(tiers) ? tiers : [];
  const idx500 = arr.findIndex((t) => tierQtyNum(t) === 500);
  if (idx500 >= 0) return idx500;
  if (arr.length >= 2) return 1;
  return 0;
}

function fmtDeltaMoney(prevVal, curVal) {
  if (!Number.isFinite(prevVal) || !Number.isFinite(curVal)) return "-";
  const d = Math.round((curVal - prevVal) * 100) / 100;
  const sign = d > 0 ? "+" : "";
  const cls = d < 0 ? "delta-good" : d > 0 ? "delta-warn" : "delta-flat";
  const arr =
    d < 0 ? '<span class="delta-arrow">↓</span> ' : d > 0 ? '<span class="delta-arrow delta-up">↑</span> ' : "";
  return `<span class="${cls}">${arr}${sign}${formatMoney(d)} 元</span>`;
}

function renderHeroDualAndBridge(quote) {
  if (!els.overviewHeroMount) return;
  const tiers = Array.isArray(quote.tiers) ? quote.tiers : [];
  const t0 = tiers[0];
  const mt = Number(quote.material_total);
  let cbm = t0 ? Number(t0.cost_before_margin ?? t0.total_cost) : NaN;
  const cb = quote.cost_bridge || {};

  const mold = Number(t0?.mold_share ?? cb.mold_share_per_pc);
  const proc = Number(t0?.processing_fee ?? cb.processing_fee_per_pc);
  const oh = Number(cb.system_overhead_per_pc);
  const moldOk = Number.isFinite(mold);
  const procOk = Number.isFinite(proc);
  const ohOk = Number.isFinite(oh);

  if (!Number.isFinite(mt) || !Number.isFinite(cbm) || cbm <= 0) {
    els.overviewHeroMount.innerHTML =
      '<div class="ov-hero-fallback muted">补全档位与物料汇总后，将在此对比物料合计与单包毛利前成本。</div>';
    return;
  }

  const previewNote = quote._bomEditPreview
    ? '<p class="ov-hero-preview-note muted">编辑预览金额，保存后将按完整规则重算。</p>'
    : "";
  els.overviewHeroMount.innerHTML = `
    <div class="ov-dual-grid">
      <article class="ov-hero-card">
        <span class="ov-hero-label">物料合计</span>
        <strong class="ov-hero-num">${escapeHtml(formatMoney(mt))}<span class="ov-hero-unit">元</span></strong>
      </article>
      <article class="ov-hero-card ov-hero-card-accent">
        <span class="ov-hero-label">单包系统成本（一档 · 毛利前）</span>
        <strong class="ov-hero-num">${escapeHtml(formatMoney(cbm))}<span class="ov-hero-unit">元</span></strong>
      </article>
    </div>${previewNote}`;
}

function renderHealthCard() {
  if (!els.overviewHealth) return;
  els.overviewHealth.innerHTML = "";
}

function renderCostMixCards(quote) {
  if (!els.overviewCostMix) return;
  const tiers = Array.isArray(quote.tiers) ? quote.tiers : [];
  const t0 = tiers[0];
  const cb = quote.cost_bridge || {};
  const mt = Number(quote.material_total);
  let cbm = t0 ? Number(t0.cost_before_margin ?? t0.total_cost) : NaN;
  if (!Number.isFinite(cbm)) cbm = NaN;

  const pkg = derivePackagingFromRows(quote.detail_rows, cbm);

  if (!Number.isFinite(mt) || !Number.isFinite(cbm) || cbm <= 0) {
    els.overviewCostMix.innerHTML =
      '<div class="ratio-card ratio-card-slim"><span class="ratio-caption">成本结构需档位与物料汇总完整后才能计算。</span></div>';
    return;
  }

  const mold = Number(t0?.mold_share ?? cb.mold_share_per_pc);
  const proc = Number(t0?.processing_fee ?? cb.processing_fee_per_pc);
  const oh = Number(cb.system_overhead_per_pc);
  const moldOk = Number.isFinite(mold);
  const procOk = Number.isFinite(proc);
  const ohOk = Number.isFinite(oh);

  const moldPct = moldOk ? mold / cbm : NaN;
  const addonPct = procOk && ohOk ? (proc + oh) / cbm : NaN;
  const matPct = mt / cbm;
  const pkgPct = Number.isFinite(pkg.pct) ? pkg.pct : NaN;

  const cards = [
    {
      title: "物料成本",
      pct: formatPct(matPct),
      amt: `${formatMoney(mt)}`,
      cap: "物料合计 ÷ 一档毛利前成本",
    },
    {
      title: "加工与杂费",
      pct: formatPct(addonPct),
      amt:
        procOk && ohOk
          ? `${formatMoney(proc + oh)}（加工 ${formatMoney(proc)} + 杂费 ${formatMoney(oh)}）`
          : "-",
      cap: "（加工费 + 体系杂费）÷ 一档毛利前成本",
    },
    {
      title: "模具摊销",
      pct: formatPct(moldPct),
      amt: moldOk ? `${formatMoney(mold)}` : "-",
      cap: "一档模具均摊 ÷ 一档毛利前成本",
    },
    {
      title: "packaging material",
      pct: formatPct(pkgPct),
      amt: `${formatMoney(pkg.sum)} / ${pkg.matched} rows`,
      cap: pkg.sourceHint,
    },
  ];

  els.overviewCostMix.innerHTML = cards
    .map(
      (c) => `
      <div class="ratio-card ratio-card-slim">
        <div class="ratio-card-main">
          <span class="ratio-title">${escapeHtml(c.title)}</span>
          <span class="ratio-value">${escapeHtml(c.pct)}</span>
        </div>
        <div class="ratio-amount">${escapeHtml(c.amt)}</div>
        <p class="ratio-caption ratio-card-extra muted">${escapeHtml(c.cap)}</p>
      </div>`,
    )
    .join("");
}

function renderTierComparison(quote) {
  if (!els.tierCompareMount || !els.tierSummaryTitle) return;
  const tiers = Array.isArray(quote.tiers) ? quote.tiers : [];
  els.tierSummaryTitle.textContent = tiers.length
    ? `三档报价对比（${tiers.length} 档）`
    : "三档报价对比";

  if (!tiers.length) {
    els.tierCompareMount.innerHTML = '<p class="muted">暂无档位数据。</p>';
    return;
  }

  const hi = highlightTierIndex(tiers);
  const exwVat = quoteIsExwCostVatMode(quote);
  const taxTh = exwVat
    ? '<th class="col-num tier-col-tax tier-col-tax-num">含税（13%）</th>'
    : '<th class="tier-col-tax tier-col-tax-desc muted">含税说明</th>';
  const body = tiers
    .map((t, i) => {
      const sn = tierNumericSnapshot(t);
      const prev = i > 0 ? tierNumericSnapshot(tiers[i - 1]) : null;
      const dCbm = prev ? fmtDeltaMoney(prev.cbm, sn.cbm) : "-";
      const dExw = prev ? fmtDeltaMoney(prev.exw, sn.exw) : "-";
      const qtyLabel = escapeHtml(String(t.quantity_text || t.quantity || "-"));
      const rowCls = i === hi ? ' class="tier-row-highlight"' : "";
      const tp = taxedUnitPriceAdmin(t);
      const taxCell = exwVat
        ? `<td class="col-num tier-col-tax tier-col-tax-num"><strong>${escapeHtml(formatMoney(tp))}</strong></td>`
        : `<td class="tier-col-tax tier-col-tax-desc muted">${escapeHtml(String(t.taxed_price_text || "FOB口径：不加税"))}</td>`;
      return `
        <tr${rowCls}>
          <td>${qtyLabel}</td>
          <td class="col-num">${escapeHtml(formatMoney(sn.cbm))}</td>
          ${taxCell}
          <td class="col-num"><strong>${escapeHtml(formatMoney(sn.exw))}</strong></td>
          <td class="col-num">${escapeHtml(sn.marginText)}</td>
          <td class="col-num tier-delta">${dCbm}</td>
          <td class="col-num tier-delta">${dExw}</td>
        </tr>`;
    })
    .join("");

  els.tierCompareMount.innerHTML = `
    <table class="data-table tier-compare-table tier-compare-v2">
      <colgroup>
        <col class="tier-col-qty" />
        <col class="tier-col-cbm" />
        <col class="tier-col-tax" />
        <col class="tier-col-exw" />
        <col class="tier-col-gp" />
        <col class="tier-col-dcbm" />
        <col class="tier-col-dexw" />
      </colgroup>
      <thead>
        <tr>
          <th>数量</th>
          <th class="col-num">毛利前成本</th>
          ${taxTh}
          <th class="col-num">EXW</th>
          <th class="col-num">毛利率</th>
          <th class="col-num">Δ 成本</th>
          <th class="col-num">Δ EXW</th>
        </tr>
      </thead>
      <tbody>${body}</tbody>
    </table>
    <p class="tier-compare-note muted">Highlighted tier is the common business reference.${exwVat ? " Taxed column is a 13% reference." : ""}</p>`;
}

function buildOverviewSuggestions(quote, pkg, vf) {
  const out = [];
  const pg = quote.pricing_gate || {};
  const cb = quote.cost_bridge || {};

  if (
    pg &&
    Object.keys(pg).length > 0 &&
    (pg.final_price_allowed === false || pg.pricing_output_mode === "estimated")
  ) {
    out.push("Current quote is still estimated or not fully released.");
  }

  const ucRaw = pg.unit_conflict_rows != null ? Number(pg.unit_conflict_rows) : NaN;
  const uc = Number.isFinite(ucRaw) ? Math.max(ucRaw, vf.unitConflict) : vf.unitConflict;
  if (uc > 0) {
    out.push(`${uc} rows may have unit / 鍙ｅ緞 conflicts; review usage and unit price.`);
  }

  const aiN = Array.isArray(pg.ai_filled_fields) ? pg.ai_filled_fields.length : 0;
  const origin = computeRowOriginStats(quote.detail_rows);
  const aiRatio = origin.counted > 0 ? origin.ai / origin.counted : 0;
  if (aiN >= 4) {
    out.push(`${aiN} fields were AI-filled; review key material usage and prices.`);
  } else if (aiRatio >= 0.42 && origin.counted >= 4) {
    out.push("AI-sourced detail rows are relatively high; review key materials.");
  }

  if (vf.incomplete >= 3) {
    out.push(`${vf.incomplete} rows are incomplete; complete usage or price before sending.`);
  }

  if (pkg.matched > 0 && pkg.sum > 0 && pkg.sourceHint.includes("sheet-derived")) {
    out.push("Packaging rows are mostly estimated; consider adding fixed packaging rules.");
  }

  const gnum = Number(cb.sheet_anchor_vs_computed_material_gap);
  if (Number.isFinite(gnum) && Math.abs(gnum) >= 8) {
    out.push(
      `Sheet anchor differs from computed material total by ${formatMoney(gnum)}.`,
    );
  }

  if (pg.risk_level === "MEDIUM" && String(pg.hint_cn || "").trim()) {
    out.push(String(pg.hint_cn).trim());
  }

  const dedup = [];
  const seen = new Set();
  for (const s of out) {
    const k = s.slice(0, 48);
    if (seen.has(k)) continue;
    seen.add(k);
    dedup.push(s);
  }
  return dedup.slice(0, 3);
}

function renderSuggestions(quote) {
  if (!els.overviewSuggestions) return;
  const vf = computeValidationFallback(quote.detail_rows);
  const tiers = Array.isArray(quote.tiers) ? quote.tiers : [];
  const t0 = tiers[0];
  let cbm = t0 ? Number(t0.cost_before_margin ?? t0.total_cost) : NaN;
  const pkg = derivePackagingFromRows(quote.detail_rows, cbm);
  const items = buildOverviewSuggestions(quote, pkg, vf);
  if (!items.length) {
    els.overviewSuggestions.innerHTML =
      '<li class="muted">暂无额外建议（快照信号较少）。仍建议抽查明细或与导出 PDF 核对。</li>';
    return;
  }
  const limit = 108;
  els.overviewSuggestions.innerHTML = items
    .map((s, ix) => {
      if (s.length <= limit) {
        return `<li class="ov-sug-item"><p class="ov-sug-text">${escapeHtml(s)}</p></li>`;
      }
      return `<li class="ov-sug-item" data-ov-sug="${ix}">
        <p class="ov-sug-text ov-sug-lead">${escapeHtml(s.slice(0, limit))}...</p>
        <p class="ov-sug-text ov-sug-rest" hidden>${escapeHtml(s)}</p>
        <button type="button" class="ov-sug-expand" data-ov-sug-exp="${ix}">More</button>
      </li>`;
    })
    .join("");
}

function renderCredibilityStrip(quote) {
  if (!els.overviewCredibility) return;
  const pg = quote.pricing_gate || {};
  const rows = quote.detail_rows;
  const st = computeRowOriginStats(rows);
  const denom = st.counted || 0;
  const kbPct = denom ? `${((st.kb / denom) * 100).toFixed(1)}%` : "-";
  const aiLinePct = denom ? `${((st.ai / denom) * 100).toFixed(1)}%` : "-";

  const aiFilledN = Array.isArray(pg.ai_filled_fields) ? pg.ai_filled_fields.length : 0;
  let aiFillLabel = "-";
  if (denom > 0 && aiFilledN > 0) {
    aiFillLabel = `${Math.min(100, Math.round((aiFilledN / denom) * 100))}%`;
  } else if (aiFilledN > 0) {
    aiFillLabel = `${aiFilledN} fields`;
  }

  const hasPg = pg && typeof pg === "object" && Object.keys(pg).length > 0;
  let manualState = "No manual gate snapshot";
  if (hasPg) {
    if (pg.manual_confirmed_applied && pg.final_price_allowed !== false) {
      manualState = "Manual confirmed";
    } else if (pg.confirm_required) {
      manualState = "Manual confirmation required";
    } else if (pg.final_price_allowed !== false) {
      manualState = "Auto released";
    } else {
      manualState = "Not finally released";
    }
  }

  const confChip =
    pg.ai_confidence != null
      ? `<span class="cred-chip">聚合置信 ${escapeHtml(String(pg.ai_confidence))}</span>`
      : "";

  els.overviewCredibility.innerHTML = `
    <div class="cred-grid">
      <div class="cred-item"><span class="cred-k">KB 命中率（按行）</span><strong>${escapeHtml(kbPct)}</strong></div>
      <div class="cred-item"><span class="cred-k">AI 来源占比（按行）</span><strong>${escapeHtml(aiLinePct)}</strong></div>
      <div class="cred-item"><span class="cred-k">AI 补全强度</span><strong>${escapeHtml(aiFillLabel)}</strong></div>
      <div class="cred-item cred-span">
        <span class="cred-k">人工确认状态</span>
        <strong>${escapeHtml(manualState)}</strong>${confChip}
      </div>
    </div>`;
}

function renderOverviewDashboard(quote) {
  renderHealthCard();
  renderHeroDualAndBridge(quote);
  renderCostMixCards(quote);
  renderTierComparison(quote);
  renderSuggestions(quote);
  renderCredibilityStrip(quote);
}

function readOverviewCalcExpandedSet(qid) {
  try {
    const raw = sessionStorage.getItem(`${OV_CALC_LINES_KEY_PREFIX}${encodeURIComponent(qid)}`);
    const arr = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(arr) ? arr.map(Number).filter(Number.isFinite) : []);
  } catch {
    return new Set();
  }
}

function writeOverviewCalcExpandedSet(qid, set) {
  try {
    sessionStorage.setItem(
      `${OV_CALC_LINES_KEY_PREFIX}${encodeURIComponent(qid)}`,
      JSON.stringify([...set]),
    );
  } catch {
    /* ignore */
  }
}

function syncOverviewEmbedValidationUi() {
  const on = !!(els.chkOverviewDetailValidation && els.chkOverviewDetailValidation.checked);
  if (els.overviewEmbedWrap) {
    els.overviewEmbedWrap.classList.toggle("ov-show-validate", on);
  }
}

function loadOverviewEmbedValidationFromSession(qid) {
  if (!els.chkOverviewDetailValidation) return;
  try {
    const v = sessionStorage.getItem(`${OV_VALIDATION_KEY_PREFIX}${encodeURIComponent(qid)}`);
    els.chkOverviewDetailValidation.checked = v === "1";
  } catch {
    els.chkOverviewDetailValidation.checked = false;
  }
  syncOverviewEmbedValidationUi();
}

function persistOverviewValidation(qid) {
  if (!els.chkOverviewDetailValidation) return;
  try {
    sessionStorage.setItem(
      `${OV_VALIDATION_KEY_PREFIX}${encodeURIComponent(qid)}`,
      els.chkOverviewDetailValidation.checked ? "1" : "0",
    );
  } catch {
    /* ignore */
  }
}

function cleanBomText(value, fallback = "-") {
  const s = String(value ?? "").replace(/\s+/g, " ").trim();
  return s || fallback;
}

function firstBomValue(...values) {
  for (const v of values) {
    if (v == null) continue;
    if (Array.isArray(v) && v.length) return v;
    if (typeof v === "object" && Object.keys(v).length) return v;
    const s = String(v).trim();
    if (s) return v;
  }
  return "";
}

function bomAmountText(row) {
  if (row?.amount_text != null && String(row.amount_text).trim() !== "") return String(row.amount_text);
  const n = parseAmountNum(row);
  return Number.isFinite(n) ? `${formatMoney(n)}元` : "-";
}

function formatBomSize(size) {
  if (!size || typeof size !== "object") return "";
  const l = firstBomValue(size.LCM, size.lcm, size.length_cm, size.length, size.long, size.l);
  const w = firstBomValue(size.WCM, size.wcm, size.width_cm, size.width, size.wide, size.w);
  const h = firstBomValue(size.HCM, size.hcm, size.height_cm, size.height, size.high, size.h);
  const unit = cleanBomText(size.unit || "cm", "cm");
  const parts = [l, w, h].map((v) => String(v || "").trim()).filter(Boolean);
  if (parts.length >= 3) return `${parts[0]}×${parts[1]}×${parts[2]}cm`;
  if (parts.length) return `${parts.join(" x ")}${unit}`;
  return "";
}

function isCompletePieceAreaCalc(calc) {
  if (!calc || typeof calc !== "object" || !Array.isArray(calc.rows) || !calc.rows.length) return false;
  const names = calc.rows.filter((r) => !r?.is_total).map((r) => String(r.piece || ""));
  const has = (sub) => names.some((n) => n.includes(sub));
  return has("前片") && has("后片") && has("底片") && has("侧片");
}

function resolvePieceAreaCalc(quote, pairs) {
  const pac = quote?.piece_area_calculation;
  const inferred = inferPieceAreaCalcFromPairs(quote, pairs);
  if (isCompletePieceAreaCalc(pac)) return pac;
  if (isCompletePieceAreaCalc(inferred)) return inferred;
  if (pac && Array.isArray(pac.rows) && pac.rows.length) return pac;
  return inferred;
}

function parseLwhFromText(text) {
  const blob = String(text || "");
  if (!blob.trim()) return null;
  const m = blob.match(
    /(?:成品|尺寸|规格|约)?[\s：:（(]*(\d+(?:\.\d+)?)\s*[×xX*]\s*(\d+(?:\.\d+)?)\s*[×xX*]\s*(\d+(?:\.\d+)?)\s*(?:cm|CM|厘米|mm|MM|毫米)?/i,
  );
  if (m) {
    let l = Number(m[1]);
    let w = Number(m[2]);
    let h = Number(m[3]);
    if ([l, w, h].every((n) => Number.isFinite(n) && n > 0)) {
      if (/mm|毫米/i.test(blob)) {
        l /= 10;
        w /= 10;
        h /= 10;
      }
      return { l, w, h };
    }
  }
  const labeled = {};
  const patterns = [
    [/长度\s*[：:]\s*(\d+(?:\.\d+)?)/i, "l"],
    [/宽度\s*[：:]\s*(\d+(?:\.\d+)?)/i, "w"],
    [/高度\s*[：:]\s*(\d+(?:\.\d+)?)/i, "h"],
  ];
  for (const [rx, key] of patterns) {
    const hit = blob.match(rx);
    if (hit) labeled[key] = Number(hit[1]);
  }
  if (labeled.l > 0 && labeled.w > 0 && labeled.h > 0) {
    return { l: labeled.l, w: labeled.w, h: labeled.h };
  }
  return null;
}

function collectBomContextText(quote, pairs) {
  const chunks = [];
  for (const key of [
    "structure_text_snapshot",
    "structure_text",
    "structure",
    "product_structure",
    "product_size_text",
    "size_text",
    "product_type",
    "product_name",
  ]) {
    const val = String(quote?.[key] || "").trim();
    if (val) chunks.push(val);
  }
  const sizeObj = firstBomValue(quote?.product_size, quote?.size, quote?.dimensions);
  if (sizeObj && typeof sizeObj === "object") {
    const l = firstBomValue(sizeObj.LCM, sizeObj.lcm, sizeObj.length_cm, sizeObj.length);
    const w = firstBomValue(sizeObj.WCM, sizeObj.wcm, sizeObj.width_cm, sizeObj.width);
    const h = firstBomValue(sizeObj.HCM, sizeObj.hcm, sizeObj.height_cm, sizeObj.height);
    if (l && w && h) chunks.push(`${l}×${w}×${h}cm`);
  }
  for (const pair of pairs || []) {
    const r = pair?.row || {};
    chunks.push(
      [pair?.mergedCalcNote, r.calc_note, r.calc_method, r.spec, r.usage, r.name]
        .map((v) => String(v || "").trim())
        .filter(Boolean)
        .join(" "),
    );
  }
  return chunks.join("\n");
}

function parseLossPctFromText(text) {
  const blob = String(text || "");
  const m1 = blob.match(/(?:加?\s*)?(?:损耗|耗损)\s*(\d+(?:\.\d+)?)\s*(?:％|%)/i);
  if (m1) return Number(m1[1]);
  const m2 = blob.match(/(\d+(?:\.\d+)?)\s*(?:％|%)\\s*(?:损耗|耗损)/i);
  if (m2) return Number(m2[1]);
  return null;
}

function inferRollWidthCm(quote, pairs) {
  const blob = collectBomContextText(quote, pairs);
  const m = blob.match(/(?:幅宽|门幅|宽幅)\s*[：:]?\s*(\d{2,3})\s*(?:CM|厘米|cm)?/i);
  if (m) return Number(m[1]);
  for (const pair of pairs || []) {
    const spec = String(pair?.row?.spec || "");
    const sm = spec.match(/(\d{2,3})\s*[*×xX]\s*\d+/);
    if (sm) return Number(sm[1]);
  }
  return null;
}

function fmtPieceDim(n) {
  const v = Number(n);
  if (!Number.isFinite(v)) return "";
  return Math.abs(v - Math.round(v)) < 1e-6 ? String(Math.round(v)) : String(v);
}

function buildPieceAreaNotes(totalCm2, quote, pairs, lossPct, rollCm, reviewHint) {
  const notes = [];
  if (reviewHint) notes.push(reviewHint);
  if (!Number.isFinite(totalCm2) || totalCm2 <= 0) return notes;
  const loss = Number.isFinite(lossPct) && lossPct > 0 ? lossPct : 15;
  const withLoss = Math.round(totalCm2 * (1 + loss / 100) * 100) / 100;
  const m2 = Math.round((withLoss / 10000) * 10000) / 10000;
  notes.push(`加损耗${loss}%：${totalCm2} × ${(1 + loss / 100).toFixed(4)} = ${withLoss} cm² = ${m2} m²`);
  if (rollCm && rollCm > 0) {
    const lenM = Math.round((m2 / (rollCm / 100)) * 10000) / 10000;
    const yards = Math.round(lenM * 1.0936 * 10000) / 10000;
    notes.push(`门幅${rollCm}cm → 所需长度 = ${m2} ÷ ${rollCm / 100} = ${lenM} m`);
    notes.push(`换算码：${lenM} × 1.0936 = ${yards} 码`);
  }
  return notes;
}

function inferPieceAreaCalcFromPairs(quote, pairs) {
  const context = collectBomContextText(quote, pairs);
  let dims = parseLwhFromText(context);
  if (!dims) {
    const sizeObj = firstBomValue(quote?.product_size, quote?.size, quote?.dimensions);
    if (sizeObj && typeof sizeObj === "object") {
      const l = Number(firstBomValue(sizeObj.LCM, sizeObj.lcm, sizeObj.length_cm, sizeObj.length));
      const w = Number(firstBomValue(sizeObj.WCM, sizeObj.wcm, sizeObj.width_cm, sizeObj.width));
      const h = Number(firstBomValue(sizeObj.HCM, sizeObj.hcm, sizeObj.height_cm, sizeObj.height));
      if (l > 0 && w > 0 && h > 0) dims = { l, w, h };
    }
  }
  if (!dims) return null;

  const { l, w, h } = dims;
  const rows = [
    { piece: "前片", size_text: `${fmtPieceDim(w)}×${fmtPieceDim(h)}`, qty_text: "1", unit_area_cm2: Math.round(w * h), total_area_cm2: Math.round(w * h), inferred: true },
    { piece: "后片", size_text: `${fmtPieceDim(w)}×${fmtPieceDim(h)}`, qty_text: "1", unit_area_cm2: Math.round(w * h), total_area_cm2: Math.round(w * h), inferred: true },
    { piece: "底片", size_text: `${fmtPieceDim(l)}×${fmtPieceDim(w)}`, qty_text: "1", unit_area_cm2: Math.round(l * w), total_area_cm2: Math.round(l * w), inferred: true },
    { piece: "侧片（2片）", size_text: `${fmtPieceDim(h)}×${fmtPieceDim(w)}×2`, qty_text: "1组", unit_area_cm2: Math.round(h * w * 2), total_area_cm2: Math.round(h * w * 2), inferred: true },
  ];
  const blobLower = context.toLowerCase();
  const hasZipper = /拉链|zip/i.test(blobLower) || (pairs || []).some((p) => /拉链|zip/i.test(String(p?.row?.name || "")));
  const isBag = /包|袋|backpack|bag/i.test(blobLower) || hasZipper;
  if (hasZipper || isBag) {
    const est = Math.max(l, w, h) <= 35 ? 200 : Math.round(Math.max(120, Math.min(420, 0.45 * (l + w) * h)));
    rows.push({
      piece: "拉链弧形盖（推理待核）",
      size_text: "估算",
      qty_text: "1",
      unit_area_cm2: est,
      total_area_cm2: est,
      inferred: true,
    });
  }
  const total = rows.reduce((sum, r) => sum + Number(r.total_area_cm2 || 0), 0);
  rows.push({ piece: "合计", size_text: "", qty_text: "", unit_area_cm2: "", total_area_cm2: total, is_total: true });
  const lossPct = parseLossPctFromText(context);
  const rollCm = inferRollWidthCm(quote, pairs);
  return {
    version: 1,
    source: "client_inferred",
    inferred: true,
    product_size_label: `${fmtPieceDim(l)}×${fmtPieceDim(w)}×${fmtPieceDim(h)}cm`,
    rows,
    total_area_cm2: total,
    loss_rate_pct: lossPct,
    roll_width_cm: rollCm,
    notes: buildPieceAreaNotes(
      total,
      quote,
      pairs,
      lossPct,
      rollCm,
      "部分裁片由结构说明/面料核算/尺寸推断生成，推理待核，请对照纸样复核。",
    ),
  };
}

function pieceAreaSectionTitle(calc) {
  const size = String(calc?.product_size_label || "").trim();
  return size ? `三、裁片面积核算（${size}）` : "三、裁片面积核算";
}

function renderPieceAreaSectionHtml(calc) {
  const columns = ["裁片", "尺寸（cm）", "数量", "单面积（cm²）", "总面积（cm²）"];
  const tableOpts = { numCols: [3, 4], tableClass: "bom-piece-area-table" };
  if (!calc) {
    return `<section class="bom-section bom-section-piece-area">
      <h3>三、裁片面积核算</h3>
      ${renderBomRowsTable(columns, [], {
        ...tableOpts,
        emptyText: "当前归档未识别到裁片面积核算表",
      })}
    </section>`;
  }
  const rows = calc.rows.map((r) => {
    if (r?.is_total) {
      return [r.piece || "合计", "", "", "", String(r.total_area_cm2 ?? "")];
    }
    return [
      r.piece || "-",
      r.size_text || "-",
      r.qty_text || "-",
      r.unit_area_cm2 != null && r.unit_area_cm2 !== "" ? String(r.unit_area_cm2) : "-",
      r.total_area_cm2 != null && r.total_area_cm2 !== "" ? String(r.total_area_cm2) : "-",
    ];
  });
  const notes = Array.isArray(calc.notes) ? calc.notes.filter(Boolean) : [];
  const notesHtml = notes.length
    ? `<ul class="bom-piece-area-notes">${notes
        .map((n) => `<li>${escapeHtml(cleanBomText(n))}</li>`)
        .join("")}</ul>`
    : "";
  return `<section class="bom-section bom-section-piece-area">
    <h3>${escapeHtml(pieceAreaSectionTitle(calc))}</h3>
    ${renderBomRowsTable(columns, rows, tableOpts)}
    ${notesHtml}
  </section>`;
}

function bomQuantitiesText(quote) {
  const tiers = Array.isArray(quote?.tiers) ? quote.tiers : [];
  const qtys = tiers
    .map((t) => tierQtyNum(t))
    .filter((n) => Number.isFinite(n) && n > 0)
    .map((n) => `${Math.round(n)}个`);
  return qtys.length ? qtys.join(" / ") : "";
}

function bomMarginText(quote) {
  const tiers = Array.isArray(quote?.tiers) ? quote.tiers : [];
  const labels = tiers.map((t) => String(t?.margin_rate_text || "").trim()).filter(Boolean);
  if (labels.length) return [...new Set(labels)].join(" / ");
  const raw = firstBomValue(quote?.gross_margin_rate, quote?.expected_margin_rate);
  const n = Number(raw);
  if (Number.isFinite(n)) return n <= 1 ? `${Math.round(n * 100)}%` : `${n}%`;
  return "";
}

function bomStructureText(quote) {
  const raw = firstBomValue(
    quote?.structure_text_snapshot,
    quote?.structure_text,
    quote?.structure,
    quote?.product_structure,
  );
  return cleanBomText(raw, "-");
}

function firstPresentValue(candidates) {
  for (const value of candidates) {
    const text = String(value == null ? "" : value).trim();
    if (text) return text;
  }
  return "";
}

function pickQuoteParamValue(quoteParams, sectionKeys, fieldKeys) {
  if (!quoteParams || typeof quoteParams !== "object") return "";
  const sections = sectionKeys
    .map((k) => quoteParams[k])
    .filter((obj) => obj && typeof obj === "object");
  for (const sec of sections) {
    for (const fk of fieldKeys) {
      const got = firstPresentValue([sec[fk]]);
      if (got) return got;
    }
  }
  return "";
}

function formatSalesDisplay(code, name) {
  const c = String(code || "").trim();
  const n = String(name || "").trim();
  if (!c && !n) return "-";
  if (c && n) {
    if (c === n) return c;
    if (n.includes(c) || /[-\s/|，,、]/.test(c)) return c;
    return `${c}-${n}`;
  }
  return c || n;
}

function pickQuoteParamValueFuzzy(quoteParams, sectionKeys, fieldKeys) {
  if (!quoteParams || typeof quoteParams !== "object") return "";
  const sections = sectionKeys
    .map((k) => quoteParams[k])
    .filter((obj) => obj && typeof obj === "object");
  for (const sec of sections) {
    for (const fk of fieldKeys) {
      const got = firstPresentValue([sec[fk]]);
      if (got) return got;
    }
    for (const fk of fieldKeys) {
      const needle = String(fk).replace(/\s+/g, "").toLowerCase();
      for (const [k, v] of Object.entries(sec)) {
        const hay = String(k).replace(/\s+/g, "").toLowerCase();
        const val = String(v == null ? "" : v).trim();
        if (!val || val === "-") continue;
        if (hay.includes(needle) || needle.includes(hay)) return val;
      }
    }
  }
  return "";
}

function extractSalesMeta(quote, meta) {
  const qp = quote?.quote_params && typeof quote.quote_params === "object"
    ? quote.quote_params
    : (meta?.quote_params && typeof meta.quote_params === "object" ? meta.quote_params : {});

  const salesCode = firstPresentValue([
    quote?.sales_code,
    meta?.sales_code,
    pickQuoteParamValueFuzzy(qp, ["A", "a"], [
      "业务员编号", "编号", "sales_code", "salesperson_id", "sales_id", "seller_id", "staff_id",
    ]),
    quote?.salesperson_id,
    quote?.sales_id,
    meta?.salesperson_id,
    meta?.sales_id,
  ]);
  const salesName = firstPresentValue([
    quote?.sales_name,
    meta?.sales_name,
    pickQuoteParamValueFuzzy(qp, ["A", "a"], [
      "业务员姓名", "业务员", "销售姓名", "sales_name", "salesperson", "salesperson_name", "seller_name", "staff_name",
    ]),
    quote?.salesperson_name,
    quote?.sales_name,
    meta?.salesperson_name,
    meta?.sales_name,
  ]);
  const salesDisplay = firstPresentValue([
    quote?.sales_display,
    meta?.sales_display,
    formatSalesDisplay(salesCode, salesName),
  ]);
  return { salesCode, salesName, salesDisplay };
}

function extractQuoteSheetSampleMeta(quote) {
  const block =
    quote?.quote_sheet_meta && typeof quote.quote_sheet_meta === "object"
      ? quote.quote_sheet_meta
      : {};
  const clean = (raw) => {
    const text = String(raw ?? "").trim();
    if (!text || /^(null|undefined|nan)$/i.test(text)) return "";
    return text;
  };
  return {
    required: clean(block.sample_required ?? quote?.quote_sheet_sample_required ?? quote?.sample_required),
    fee: clean(block.sample_fee ?? quote?.quote_sheet_sample_fee ?? quote?.sample_fee),
    lead: clean(block.sample_lead_time ?? quote?.quote_sheet_sample_lead_time ?? quote?.sample_lead_time),
  };
}

function formatSampleRequiredAdminLabel(value) {
  const text = String(value ?? "").trim().toLowerCase();
  if (text === "yes") return "需要打样";
  if (text === "no") return "不需要打样";
  if (text === "pending") return "待确认";
  return "待确认";
}

function buildBomProductRows(quote, meta) {
  const productSize = firstBomValue(quote?.product_size, quote?.size, quote?.dimensions);
  const salesMeta = extractSalesMeta(quote, meta);
  const sampleMeta = extractQuoteSheetSampleMeta(quote);
  const sizeDisplay = firstBomValue(formatBomSize(productSize), quote?.product_size_text, quote?.size_text);
  const multiSizeNote =
    Array.isArray(quote?.size_variants) && quote.size_variants.length > 1
      ? `多尺寸（${quote.size_variants.length} 档，见下方分尺寸结果）`
      : "";
  const rows = [
    ["产品名称", firstBomValue(meta?.product_name, quote?.product_name, els.detailTitle?.textContent)],
    ["产品型号", firstBomValue(quote?.product_model, quote?.model, quote?.sku, meta?.sheet_original_name)],
    ["业务员（上传表）", salesMeta.salesDisplay || "-"],
    ["是否需要打样", formatSampleRequiredAdminLabel(sampleMeta.required)],
    ["打样费", sampleMeta.fee || "-"],
    ["打样时间", sampleMeta.lead || "-"],
    ["成品尺寸", multiSizeNote || sizeDisplay],
    ["结构", bomStructureText(quote)],
    ["数量阶梯", firstBomValue(bomQuantitiesText(quote), quote?.quantity_text)],
    ["利润率", bomMarginText(quote)],
    ["含税", quote?.include_tax === true ? "是" : quote?.include_tax === false ? "否" : "-"],
    ["价格类型", quoteIsExwCostVatMode(quote) ? "EXW成本含税参考" : "FOB深圳"],
  ];
  return rows.map(([k, v]) => [k, cleanBomText(v)]);
}

const BOM_STRUCTURE_COLLAPSE_LINES = 5;

function bomStructureNeedsCollapse(text) {
  const t = String(text || "").trim();
  if (!t || t === "-") return false;
  const lines = t.split(/\r?\n/);
  if (lines.length > BOM_STRUCTURE_COLLAPSE_LINES) return true;
  return t.length > 280;
}

function renderBomStructureValueCell(rawValue) {
  const text = cleanBomText(rawValue, "-");
  const inner = escapeHtml(text);
  if (!bomStructureNeedsCollapse(text)) {
    return `<td class="bom-structure-cell">${inner}</td>`;
  }
  return `<td class="bom-structure-cell">
    <div class="bom-structure-wrap is-collapsed" data-bom-structure-wrap>
      <div class="bom-structure-text">${inner}</div>
      <button type="button" class="bom-structure-toggle" data-bom-structure-toggle aria-expanded="false">展开全部</button>
    </div>
  </td>`;
}

function renderBomKeyValueTable(rows) {
  return `<table class="bom-table bom-kv-table">
    <thead><tr><th>项目</th><th>内容</th></tr></thead>
    <tbody>
      ${rows
        .map(([k, v]) => {
          const valueCell =
            k === "结构" ? renderBomStructureValueCell(v) : `<td>${escapeHtml(v)}</td>`;
          return `<tr><th scope="row">${escapeHtml(k)}</th>${valueCell}</tr>`;
        })
        .join("")}
    </tbody>
  </table>`;
}

function renderBomRowsTable(columns, rows, options = {}) {
  const tableClass = ["bom-table", options.tableClass].filter(Boolean).join(" ");
  const emptyText = options.emptyText || "暂无可显示数据";
  const body = rows.length
    ? rows
        .map(
          (row) =>
            `<tr>${row
              .map((cell, ix) => {
                const classes = [];
                if (options.numCols?.includes(ix)) classes.push("bom-num-cell");
                if (options.clampCols?.includes(ix)) classes.push("bom-clamp-cell");
                const cls = classes.length ? ` class="${classes.join(" ")}"` : "";
                const inner = escapeHtml(cleanBomText(cell));
                if (options.clampCols?.includes(ix)) {
                  return `<td${cls}><div class="bom-clamp-text">${inner}</div></td>`;
                }
                return `<td${cls}>${inner}</td>`;
              })
              .join("")}</tr>`,
        )
        .join("")
    : `<tr><td colspan="${columns.length}" class="bom-empty-cell">${escapeHtml(emptyText)}</td></tr>`;
  return `<table class="${tableClass}">
    <thead><tr>${columns
      .map((c, ix) => {
        const cls = options.numCols?.includes(ix) ? ` class="bom-num-head"` : "";
        return `<th${cls}>${escapeHtml(c)}</th>`;
      })
      .join("")}</tr></thead>
    <tbody>${body}</tbody>
  </table>`;
}

function likelyFabricPair(pair) {
  const r = pair?.row || {};
  const text = `${r.name || ""} ${r.spec || ""} ${r.usage || ""} ${pair?.mergedCalcNote || ""}`;
  return /面料|布|尼龙|涤纶|里布|外料|里料|牛津|帆布|裁片/.test(text);
}

function formatFileSize(bytes) {
  const n = Number(bytes);
  if (!Number.isFinite(n) || n < 0) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(n < 10 * 1024 ? 1 : 0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(n < 10 * 1024 * 1024 ? 1 : 0)} MB`;
}

function parseCorrectionProblemTypes(raw) {
  if (Array.isArray(raw)) return raw.map((x) => String(x || "").trim()).filter(Boolean);
  const text = String(raw || "").trim();
  if (!text) return [];
  try {
    const parsed = JSON.parse(text);
    return Array.isArray(parsed) ? parsed.map((x) => String(x || "").trim()).filter(Boolean) : [];
  } catch {
    return [];
  }
}

function collectCorrectionProblemTypesFromDom() {
  const host = els.adminCorrectionProblemTypes;
  if (!host) return [];
  return [...host.querySelectorAll("input[type='checkbox'][data-problem-type]:checked")]
    .map((el) => String(el.getAttribute("data-problem-type") || "").trim())
    .filter(Boolean);
}

function renderCorrectionProblemTypes(meta) {
  const host = els.adminCorrectionProblemTypes;
  if (!host) return;
  const selected = new Set(parseCorrectionProblemTypes(meta?.admin_correction_problem_types));
  host.querySelectorAll("input[type='checkbox'][data-problem-type]").forEach((el) => {
    const key = String(el.getAttribute("data-problem-type") || "").trim();
    el.checked = selected.has(key);
  });
}

function showAdminToast(message, kind = "ok") {
  const el = els.adminToast;
  if (!el) return;
  el.textContent = String(message || "").trim();
  el.classList.remove("admin-toast-ok", "admin-toast-err");
  el.classList.add(kind === "err" ? "admin-toast-err" : "admin-toast-ok");
  el.hidden = false;
  if (adminToastTimer) clearTimeout(adminToastTimer);
  adminToastTimer = setTimeout(() => {
    el.hidden = true;
  }, 3200);
}

function splitUnitFromUnitPrice(unitPrice) {
  const s = String(unitPrice || "").trim();
  if (!s || s === "-") return { price: "", unit: "" };
  const m = s.match(/^([\d.,]+)\s*(.*)$/);
  if (!m) return { price: s, unit: "" };
  return { price: m[1].trim(), unit: (m[2] || "").trim() };
}

function joinUnitPrice(price, unit) {
  const p = String(price || "").trim();
  const u = String(unit || "").trim();
  if (!p) return u || "-";
  if (!u) return p;
  if (/元\/|码|米|个|条|pcs?/i.test(p)) return p;
  return `${p}${u.startsWith("元") || u.startsWith("/") ? "" : ""}${u}`;
}

function buildBomEditProductDraft(quote, meta) {
  const productSize = firstBomValue(quote?.product_size, quote?.size, quote?.dimensions);
  const includeTax = quote?.include_tax;
  return {
    product_name: String(firstBomValue(meta?.product_name, quote?.product_name) || "").trim(),
    product_model: String(firstBomValue(quote?.product_model, quote?.model, quote?.sku, meta?.sheet_original_name) || "").trim(),
    product_size_text: String(firstBomValue(formatBomSize(productSize), quote?.product_size_text, quote?.size_text) || "").trim(),
    structure_text: String(bomStructureText(quote) === "-" ? "" : bomStructureText(quote)).trim(),
    quantities_text: String(firstBomValue(bomQuantitiesText(quote), quote?.quantity_text) || "").trim(),
    margin_text: String(firstBomValue(bomMarginText(quote)) === "-" ? "" : bomMarginText(quote)).trim(),
    include_tax: includeTax === true ? "yes" : includeTax === false ? "no" : "",
    price_type: quoteIsExwCostVatMode(quote) ? "exw" : "fob",
  };
}

function buildBomEditRowsDraft(pairs) {
  return sortedPairs([...(pairs || [])]).map((pair, index) => {
    const r = pair.row || {};
    const split = splitUnitFromUnitPrice(r.unit_price);
    return {
      _key: `row-${index}-${pair.lineNo || index}`,
      line_no: pair.lineNo,
      name: String(r.name || "").trim(),
      spec: String(r.spec || "").trim(),
      usage: String(r.usage || "").trim(),
      unit: split.unit,
      unit_price: split.price || String(r.unit_price || "").trim(),
      calc_note: String(pair.mergedCalcNote || r.calc_note || r.calc_method || "").trim(),
      source: String(r.source || "").trim(),
    };
  });
}

function buildBomEditDraftFromBundle(quote, meta, pairs) {
  return {
    product: buildBomEditProductDraft(quote, meta),
    rows: buildBomEditRowsDraft(pairs),
  };
}

function createEmptyBomEditRow() {
  return {
    _key: `row-new-${Date.now()}`,
    name: "",
    spec: "",
    usage: "",
    unit: "",
    unit_price: "",
    calc_note: "",
    source: "",
  };
}

function parseNumericFromUsageText(usage) {
  const val = parseBomMeasureValue(usage);
  return Number.isFinite(val) ? val : NaN;
}

function parseNumericFromUnitPriceText(price, unit) {
  const joined = joinUnitPrice(price, unit);
  const val = parseBomMeasureValue(joined);
  return Number.isFinite(val) ? val : NaN;
}

function estimateDraftRowAmount(row) {
  const usageN = parseNumericFromUsageText(row?.usage);
  const priceN = parseNumericFromUnitPriceText(row?.unit_price, row?.unit);
  if (Number.isFinite(usageN) && Number.isFinite(priceN)) {
    return Math.round(usageN * priceN * 100) / 100;
  }
  return NaN;
}

function estimateMaterialTotalFromBomDraft(draft) {
  const rows = Array.isArray(draft?.rows) ? draft.rows : [];
  let sum = 0;
  let count = 0;
  rows.forEach((row) => {
    if (!String(row?.name || "").trim()) return;
    const amt = estimateDraftRowAmount(row);
    if (Number.isFinite(amt)) {
      sum += amt;
      count += 1;
    }
  });
  return count > 0 ? Math.round(sum * 100) / 100 : NaN;
}

function buildQuotePreviewFromBomEditDraft(baseQuote, draft) {
  if (!baseQuote || typeof baseQuote !== "object") return baseQuote;
  const mt = estimateMaterialTotalFromBomDraft(draft);
  if (!Number.isFinite(mt)) return baseQuote;
  const quote = { ...baseQuote, material_total: mt, _bomEditPreview: true };
  const tiers = Array.isArray(baseQuote.tiers) ? baseQuote.tiers.map((t) => ({ ...t })) : [];
  const t0 = tiers[0];
  const cb = baseQuote.cost_bridge || {};
  if (t0) {
    const mold = Number(t0.mold_share ?? cb.mold_share_per_pc);
    const proc = Number(t0.processing_fee ?? cb.processing_fee_per_pc);
    const oh = Number(cb.system_overhead_per_pc);
    let cbm = mt;
    if (Number.isFinite(mold)) cbm += mold;
    if (Number.isFinite(proc)) cbm += proc;
    if (Number.isFinite(oh)) cbm += oh;
    cbm = Math.round(cbm * 100) / 100;
    tiers[0] = { ...t0, cost_before_margin: cbm, total_cost: cbm };
    quote.tiers = tiers;
  }
  return quote;
}

function focusBomEditRowField(rowIndex, field = "name") {
  requestAnimationFrame(() => {
    const sel = `[data-bom-row-index="${rowIndex}"] [data-bom-row-field="${field}"]`;
    const inp = els.overviewEmbeddedDetailBody?.querySelector(sel);
    if (inp && typeof inp.focus === "function") inp.focus();
  });
}

function addBomEditRow() {
  if (!bomEditMode || !bomEditDraft) return;
  bomEditDraft = collectBomEditDraftFromDom();
  if (!Array.isArray(bomEditDraft.rows)) bomEditDraft.rows = [];
  bomEditDraft.rows.push(createEmptyBomEditRow());
  refreshBomEditView(false);
  focusBomEditRowField(bomEditDraft.rows.length - 1, "name");
}

function deleteBomEditRowAt(index) {
  if (!bomEditMode || !bomEditDraft) return;
  bomEditDraft = collectBomEditDraftFromDom();
  if (!Array.isArray(bomEditDraft.rows) || Number.isNaN(index)) return;
  const row = bomEditDraft.rows[index];
  const label = String(row?.name || "").trim() || `第 ${index + 1} 行`;
  if (!window.confirm(`确定删除物料「${label}」吗？此操作在保存前可取消恢复。`)) return;
  bomEditDraft.rows.splice(index, 1);
  refreshBomEditView(false);
}

function refreshBomEditPreviewOnly() {
  if (!bomEditMode || !bomEditDraft || !lastBundle) return;
  bomEditDraft = collectBomEditDraftFromDom();
  const quote = lastBundle.quote || {};
  const previewQuote = buildQuotePreviewFromBomEditDraft(quote, bomEditDraft);
  renderOverviewDashboard(previewQuote);
}

function refreshBomEditView(collectFromDom = true) {
  if (!bomEditMode || !bomEditDraft || !lastBundle) return;
  if (collectFromDom) bomEditDraft = collectBomEditDraftFromDom();
  const quote = lastBundle.quote || {};
  const meta = lastBundle.meta || {};
  const previewQuote = buildQuotePreviewFromBomEditDraft(quote, bomEditDraft);
  renderOverviewDashboard(previewQuote);
  renderOverviewEmbeddedDetail(lastOverviewPairs, quote, meta);
}

function bomEditFieldErrorAttr(fieldKey) {
  const msg = bomEditFieldErrors[fieldKey];
  if (!msg) return "";
  return ` data-bom-invalid="1" aria-invalid="true" title="${escapeHtml(msg)}"`;
}

function bomEditInlineErrorHtml(fieldKey) {
  const msg = bomEditFieldErrors[fieldKey];
  if (!msg) return "";
  return `<span class="bom-field-error" role="alert">${escapeHtml(msg)}</span>`;
}

function renderBomEditProductTable(product) {
  const p = product || {};
  const rows = [
    ["product_name", "产品名称", "text", true],
    ["product_model", "产品型号", "text", false],
    ["product_size_text", "成品尺寸", "text", false],
    ["structure_text", "结构", "text", false],
    ["quantities_text", "数量阶梯", "text", false],
    ["margin_text", "毛利率", "text", false],
    ["include_tax", "含税", "select", false],
    ["price_type", "价格类型", "select", false],
  ];
  const body = rows
    .map(([key, label, kind, required]) => {
      const fk = `product.${key}`;
      let control = "";
      const val = p[key] != null ? String(p[key]) : "";
      if (kind === "select" && key === "include_tax") {
        control = `<select class="bom-edit-input" data-bom-field="${escapeHtml(key)}" data-bom-product="1"${bomEditFieldErrorAttr(fk)}>
          <option value=""${val === "" ? " selected" : ""}>—</option>
          <option value="yes"${val === "yes" ? " selected" : ""}>是</option>
          <option value="no"${val === "no" ? " selected" : ""}>否</option>
        </select>`;
      } else if (kind === "select" && key === "price_type") {
        control = `<select class="bom-edit-input" data-bom-field="${escapeHtml(key)}" data-bom-product="1"${bomEditFieldErrorAttr(fk)}>
          <option value="fob"${val === "fob" ? " selected" : ""}>FOB娣卞湷</option>
          <option value="exw"${val === "exw" ? " selected" : ""}>EXW成本含税参考</option>
        </select>`;
      } else {
        control = `<input type="text" class="bom-edit-input" data-bom-field="${escapeHtml(key)}" data-bom-product="1" value="${escapeHtml(val)}"${required ? " required" : ""}${bomEditFieldErrorAttr(fk)} autocomplete="off" />`;
      }
      return `<tr>
        <th scope="row">${escapeHtml(label)}</th>
        <td><div class="bom-edit-cell">${control}${bomEditInlineErrorHtml(fk)}</div></td>
      </tr>`;
    })
    .join("");
  return `<table class="bom-table bom-kv-table bom-edit-kv"><tbody>${body}</tbody></table>`;
}

function renderBomEditMaterialTable(rows) {
  const list = Array.isArray(rows) ? rows : [];
  const head = `<thead><tr>
    <th>物料名称</th><th>规格</th><th>用量</th><th>单位</th><th>单价</th><th>备注/计算方式</th><th class="bom-edit-col-actions">操作</th>
  </tr></thead>`;
  const body = list.length
    ? list
        .map((row, i) => {
          const fkName = `items.${i}.name`;
          const fkUp = `items.${i}.unit_price`;
          const fkUsage = `items.${i}.usage`;
          return `<tr data-bom-row-index="${i}">
            <td><div class="bom-edit-cell"><input type="text" class="bom-edit-input" data-bom-row-field="name" data-bom-row-index="${i}" value="${escapeHtml(row.name || "")}"${bomEditFieldErrorAttr(fkName)} />${bomEditInlineErrorHtml(fkName)}</div></td>
            <td><input type="text" class="bom-edit-input" data-bom-row-field="spec" data-bom-row-index="${i}" value="${escapeHtml(row.spec || "")}" autocomplete="off" /></td>
            <td><div class="bom-edit-cell"><input type="text" class="bom-edit-input bom-edit-input-num" data-bom-row-field="usage" data-bom-row-index="${i}" value="${escapeHtml(row.usage || "")}"${bomEditFieldErrorAttr(fkUsage)} />${bomEditInlineErrorHtml(fkUsage)}</div></td>
            <td><input type="text" class="bom-edit-input" data-bom-row-field="unit" data-bom-row-index="${i}" value="${escapeHtml(row.unit || "")}" placeholder="元/码" autocomplete="off" /></td>
            <td><div class="bom-edit-cell"><input type="text" class="bom-edit-input bom-edit-input-num" data-bom-row-field="unit_price" data-bom-row-index="${i}" value="${escapeHtml(row.unit_price || "")}"${bomEditFieldErrorAttr(fkUp)} />${bomEditInlineErrorHtml(fkUp)}</div></td>
            <td><input type="text" class="bom-edit-input" data-bom-row-field="calc_note" data-bom-row-index="${i}" value="${escapeHtml(row.calc_note || "")}" autocomplete="off" /></td>
            <td class="bom-edit-col-actions"><button type="button" class="btn btn-danger-ghost btn-sm" data-bom-row-delete="${i}">删除</button></td>
          </tr>`;
        })
        .join("")
    : `<tr><td colspan="7" class="bom-empty-cell">暂无物料行，请点击下方「新增物料」</td></tr>`;
  return `<table class="bom-table bom-edit-material-table">${head}<tbody>${body}</tbody></table>`;
}

function buildBomEditHtml(draft) {
  const d = draft || { product: {}, rows: [] };
  return `
    <div class="bom-document bom-document-editing">
      <section class="bom-section">
        <h3>一、产品基本信息</h3>
        ${renderBomEditProductTable(d.product)}
      </section>
      <section class="bom-section bom-section-edit-materials">
        <h3>物料明细（编辑中）</h3>
        <div class="bom-edit-table-wrap">
          ${renderBomEditMaterialTable(d.rows)}
        </div>
        <div class="bom-edit-foot">
          <button type="button" class="btn btn-secondary btn-sm" data-bom-add-row>新增物料</button>
        </div>
      </section>
    </div>`;
}

function syncBomEditToolbar() {
  const hasQuote = !!(selectedQuoteId && lastBundle);
  if (els.bomEditActions) els.bomEditActions.hidden = !hasQuote;
  if (!hasQuote) {
    bomEditMode = false;
    bomEditSnapshot = null;
    bomEditDraft = null;
    bomEditFieldErrors = {};
  }
  if (els.btnBomEdit) els.btnBomEdit.hidden = !hasQuote || bomEditMode;
  if (els.btnBomAdd) {
    els.btnBomAdd.hidden = !bomEditMode;
    els.btnBomAdd.disabled = bomEditSaving;
  }
  if (els.btnBomSave) {
    els.btnBomSave.hidden = !bomEditMode;
    els.btnBomSave.disabled = bomEditSaving;
  }
  if (els.btnBomCancel) {
    els.btnBomCancel.hidden = !bomEditMode;
    els.btnBomCancel.disabled = bomEditSaving;
  }
  if (els.chkOverviewDetailValidation) {
    els.chkOverviewDetailValidation.disabled = bomEditMode;
  }
  if (els.overviewEmbedWrap) {
    els.overviewEmbedWrap.classList.toggle("bom-is-editing", bomEditMode);
  }
}

function collectBomEditDraftFromDom() {
  const host = els.overviewEmbeddedDetailBody?.querySelector(".bom-document-editing");
  if (!host || !bomEditDraft) return bomEditDraft;
  const product = { ...(bomEditDraft.product || {}) };
  host.querySelectorAll("[data-bom-product][data-bom-field]").forEach((el) => {
    const key = el.getAttribute("data-bom-field");
    if (!key) return;
    product[key] = el.value != null ? String(el.value).trim() : "";
  });
  const rows = [];
  host.querySelectorAll("tbody tr[data-bom-row-index]").forEach((tr) => {
    const idx = Number(tr.getAttribute("data-bom-row-index"));
    if (Number.isNaN(idx)) return;
    const row = { ...(bomEditDraft.rows?.[idx] || {}) };
    tr.querySelectorAll("[data-bom-row-field]").forEach((inp) => {
      const field = inp.getAttribute("data-bom-row-field");
      if (!field) return;
      row[field] = inp.value != null ? String(inp.value).trim() : "";
    });
    rows[idx] = row;
  });
  return {
    product,
    rows: rows.filter((r) => r && typeof r === "object"),
  };
}

function validateBomEditDraftClient(draft) {
  const errs = {};
  const global = [];
  const p = draft?.product || {};
  if (!String(p.product_name || "").trim()) {
    errs["product.product_name"] = "产品名称不能为空";
  }
  const rows = Array.isArray(draft?.rows) ? draft.rows : [];
  let active = 0;
  rows.forEach((row, i) => {
    if (!row || typeof row !== "object") return;
    const name = String(row.name || "").trim();
    if (!name) {
      errs[`items.${i}.name`] = "物料名称不能为空";
      return;
    }
    active += 1;
    const unit = String(row.unit || "").trim();
    const up = String(row.unit_price || "").trim();
    const usage = String(row.usage || "").trim();
    const countBased = isCountBasedUnit(unit, up);
    const upErr = validateBomMeasureText(up, {
      emptyMsg: "单价不能为空",
      invalidMsg: "单价须为有效数字或「数字+单位」",
    });
    if (upErr) errs[`items.${i}.unit_price`] = upErr;
    const usageErr =
      countBased && isEmptyBomUsage(usage)
        ? ""
        : validateBomMeasureText(usage, {
            emptyMsg: "用量不能为空",
            invalidMsg: "用量须为有效数字或「数字+单位」",
          });
    if (usageErr) errs[`items.${i}.usage`] = usageErr;
  });
  if (active === 0) global.push("至少保留一行有效物料");
  return { fieldErrors: errs, globalErrors: global, ok: !global.length && !Object.keys(errs).length };
}

function draftToSavePayload(draft) {
  const p = draft?.product || {};
  const items = (Array.isArray(draft?.rows) ? draft.rows : [])
    .map((row) => {
      const name = String(row?.name || "").trim();
      if (!name) return null;
      const unit = String(row?.unit || "").trim();
      const price = String(row?.unit_price || "").trim();
      let usage = String(row?.usage || "").trim() || "-";
      if (isCountBasedUnit(unit, price) && isEmptyBomUsage(usage)) {
        usage = defaultCountUsage(unit, price);
      }
      return {
        name,
        spec: String(row?.spec || "").trim() || "-",
        usage,
        unit_price: joinUnitPrice(price, unit),
        calc_note: String(row?.calc_note || "").trim(),
        source: String(row?.source || "").trim(),
      };
    })
    .filter(Boolean);
  const includeTax = p.include_tax === "yes" ? true : p.include_tax === "no" ? false : null;
  return {
    product: {
      product_name: String(p.product_name || "").trim(),
      product_model: String(p.product_model || "").trim(),
      product_size_text: String(p.product_size_text || "").trim(),
      structure_text: String(p.structure_text || "").trim(),
      quantities_text: String(p.quantities_text || "").trim(),
      margin_text: String(p.margin_text || "").trim(),
      include_tax: includeTax,
      price_type: p.price_type === "exw" ? "exw" : "fob",
    },
    items,
  };
}

function enterBomEditMode() {
  if (!lastBundle || bomEditMode) return;
  const quote = lastBundle.quote || {};
  const meta = lastBundle.meta || {};
  const pairs = pairDetailRows(quote, lastBundle.items || []);
  bomEditSnapshot = buildBomEditDraftFromBundle(quote, meta, pairs);
  bomEditDraft = JSON.parse(JSON.stringify(bomEditSnapshot));
  bomEditFieldErrors = {};
  bomEditMode = true;
  syncBomEditToolbar();
  refreshBomEditView();
}

function cancelBomEditMode() {
  if (!bomEditMode) return;
  bomEditDraft = bomEditSnapshot ? JSON.parse(JSON.stringify(bomEditSnapshot)) : null;
  bomEditFieldErrors = {};
  bomEditMode = false;
  syncBomEditToolbar();
  if (lastBundle) {
    const quote = lastBundle.quote || {};
    const meta = lastBundle.meta || {};
    renderOverviewDashboard(quote);
    renderOverviewEmbeddedDetail(lastOverviewPairs, quote, meta);
  }
}

async function saveBomEditMode() {
  if (!selectedQuoteId || !bomEditMode || bomEditSaving) return false;
  const note = String(els.adminCorrectionNoteInput?.value || "").trim();
  bomEditDraft = collectBomEditDraftFromDom();
  const v = validateBomEditDraftClient(bomEditDraft);
  bomEditFieldErrors = v.fieldErrors;
  if (!v.ok) {
    syncBomEditToolbar();
    refreshBomEditView();
    showAdminToast(v.globalErrors[0] || "请修正标红字段后再保存", "err");
    return false;
  }
  bomEditSaving = true;
  syncBomEditToolbar();
  const payload = draftToSavePayload(bomEditDraft);
  const { ok, data } = await apiJson(
    `/admin-api/quotes/${encodeURIComponent(selectedQuoteId)}/bom-edit`,
    { method: "POST", body: JSON.stringify(payload) },
  );
  if (!ok) {
    bomEditSaving = false;
    if (data?.field_errors && typeof data.field_errors === "object") {
      bomEditFieldErrors = data.field_errors;
    }
    syncBomEditToolbar();
    refreshBomEditView();
    showAdminToast(data?.message || data?.error || "保存失败", "err");
    return false;
  }
  lastBundle = data.bundle || lastBundle;
  bomEditMode = false;
  bomEditSnapshot = null;
  bomEditDraft = null;
  bomEditFieldErrors = {};
  syncBomEditToolbar();
  const quote = lastBundle.quote || {};
  const meta = lastBundle.meta || {};
  const items = Array.isArray(lastBundle.items) ? lastBundle.items : [];
  els.detailTitle.textContent = String(meta.product_name || quote.product_name || "报价详情");
  renderDetailSubtitle(meta);
  renderQuoteApprovalPanel(meta);
  renderTechMeta(meta, selectedQuoteId);
  renderOverviewNotice(String(quote.data_notice || "").trim());
  const fbOk = await submitAdminCorrectionFeedback(note, { toastOnSuccess: false });
  bomEditSaving = false;
  syncBomEditToolbar();
  renderBomCorrectionWorkspace(lastBundle?.meta || meta, lastBundle?.files);
  const pairs = pairDetailRows(quote, items);
  renderOverviewDashboard(quote);
  renderOverviewEmbeddedDetail(pairs, quote, meta);
  loadOverviewEmbedValidationFromSession(selectedQuoteId);
  renderDetailPanel(pairs, quote);
  renderCalcAccordion(pairs);
  await loadList();
  if (fbOk) {
    showAdminToast(data?.message || "管理员修正版已保存，已通知业务员查看");
  } else {
    showAdminToast("BOM 已保存，但通知业务员失败，请点「仅更新修正说明」重试", "err");
  }
  return fbOk;
}

function formatAdminSizeVariantTierSummary(quoteResult) {
  const tiers = Array.isArray(quoteResult?.tiers) ? quoteResult.tiers : [];
  if (!tiers.length) return "-";
  return tiers
    .map((tier) => {
      const qty = String(tier.quantity_text || tier.quantity || "-");
      const exw = String(tier.exw_price_text || "-");
      return `${qty} EXW ${exw}`;
    })
    .join(" · ");
}

function buildMultiSizeBomHtml(quote, meta) {
  const variants = Array.isArray(quote?.size_variants) ? quote.size_variants : [];
  if (variants.length < 2) return "";
  const blocks = variants
    .map((variant, idx) => {
      const qr =
        variant.quote_result && typeof variant.quote_result === "object" ? variant.quote_result : {};
      const vQuote = { ...quote, ...qr, size_variants: undefined, multi_size: false };
      const pairs = pairDetailRows(vQuote, qr.detail_rows || qr.items || []);
      const label = String(variant.label || `尺寸${idx + 1}`).trim();
      const sizeText = String(variant.size_text || "").trim();
      const title = sizeText ? `${label}（${sizeText}）` : label;
      const tierSummary = formatAdminSizeVariantTierSummary(qr);
      return `<section class="bom-size-variant">
        <header class="bom-size-variant-head">
          <h3 class="bom-size-variant-title">${escapeHtml(title)}</h3>
          <p class="muted bom-size-variant-tiers">三档报价：${escapeHtml(tierSummary)}</p>
        </header>
        ${buildBomHtml(pairs, vQuote, meta)}
      </section>`;
    })
    .join("");
  return `<div class="multi-size-bom-wrap"><p class="multi-size-bom-lead muted">本报价含 ${variants.length} 个尺寸变体；管理员 BOM 编辑仍针对默认第一档。</p>${blocks}</div>`;
}

function buildBomHtml(pairs, quote, meta) {
  const list = sortedPairs([...(pairs || [])]);
  const unitPriceRows = list.map((pair) => {
    const r = pair.row || {};
    return [r.name || "-", r.unit_price || "-"];
  });
  const usageRows = list.filter(likelyFabricPair).map((pair) => {
    const r = pair.row || {};
    return [
      r.name || "-",
      r.spec || "-",
      r.usage || "-",
      cleanBomText(pair.mergedCalcNote || r.calc_method || r.calc_note, "-"),
      bomAmountText(r),
    ];
  });
  const costRows = list.map((pair) => {
    const r = pair.row || {};
    return [r.name || "-", r.unit_price || "-", r.usage || "-", bomAmountText(r)];
  });
  const materialTotal = Number(quote?.material_total);
  if (Number.isFinite(materialTotal)) {
    costRows.push(["物料小计", "", "", `${formatMoney(materialTotal)}元`]);
  }
  const pieceAreaHtml = renderPieceAreaSectionHtml(resolvePieceAreaCalc(quote, pairs));

  return `
    <div class="bom-document">
      <section class="bom-section">
        <h3>一、产品基本信息</h3>
        ${renderBomKeyValueTable(buildBomProductRows(quote, meta))}
      </section>
      <section class="bom-section">
        <h3>二、物料单价确认</h3>
        ${renderBomRowsTable(["物料名称", "单价"], unitPriceRows)}
      </section>
      ${pieceAreaHtml}
      <section class="bom-section">
        <h3>四、面料用量核算</h3>
        ${renderBomRowsTable(["裁片/物料", "尺寸/规格", "用量", "计算方式", "小计"], usageRows, {
          numCols: [4],
          clampCols: [3],
          tableClass: "bom-usage-table",
          emptyText: "当前归档未识别到面料用量表",
        })}
      </section>
      <section class="bom-section">
        <h3>五、各物料成本计算（单个）</h3>
        ${renderBomRowsTable(["物料", "单价", "用量", "成本（元）"], costRows, {
          numCols: [3],
          tableClass: "bom-cost-table",
        })}
      </section>
    </div>`;
}

function renderOverviewEmbeddedDetail(pairs, quote = {}, meta = {}) {
  lastOverviewPairs = pairs || [];
  const body = els.overviewEmbeddedDetailBody;
  if (!body) return;
  els.overviewEmbedTable?.classList.add("ov-bom-table");
  const multiSizeBom =
    !bomEditMode && !bomEditDraft && Array.isArray(quote?.size_variants) && quote.size_variants.length > 1
      ? buildMultiSizeBomHtml(quote, meta)
      : "";
  const inner =
    bomEditMode && bomEditDraft
      ? buildBomEditHtml(bomEditDraft)
      : multiSizeBom || buildBomHtml(pairs || [], quote || {}, meta || {});
  body.innerHTML = `<tr class="bom-host-row"><td colspan="6">${inner}</td></tr>`;
  syncBomEditToolbar();
}

function renderOverviewEmbeddedDetailLegacy(pairs) {
  lastOverviewPairs = pairs || [];
  const body = els.overviewEmbeddedDetailBody;
  if (!body) return;
  const sorted = sortedPairs([...(pairs || [])]);
  const expSet = selectedQuoteId ? readOverviewCalcExpandedSet(selectedQuoteId) : new Set();

  body.innerHTML = sorted
    .map((pair) => {
      const r = pair.row;
      const note = String(pair.mergedCalcNote || "").trim();
      const badges = classifyAnomalies(pair);
      const badgeHtml = badges
        .map((b) => `<span class="badge ${b.cls}">${escapeHtml(b.text)}</span>`)
        .join("");
      const amtText =
        r.amount_text != null ? String(r.amount_text) : formatMoney(parseAmountNum(r));
      const noteTrim = String(note || "").trim();
      const needToggle = noteTrim.length > 32 || /\r|\n/.test(note);
      const isOpen = expSet.has(pair.lineNo);
      const toggleBtn = needToggle
        ? `<button type="button" class="ov-calc-toggle" data-ov-calc-line="${pair.lineNo}">${isOpen ? "鏀惰捣" : "灞曞紑"}</button>`
        : "";
      return `
        <tr data-ov-line="${pair.lineNo}">
          <td class="col-ov-val">${badgeHtml}</td>
          <td class="ov-mat-name">${escapeHtml(String(r.name || "-"))}</td>
          <td class="ov-piece-cell">${escapeHtml(formatDetailPiecePart(r.piece_part, lastBundle?.quote, r.name))}</td>
          <td class="ov-spec-cell">${escapeHtml(String(r.spec || "-"))}</td>
          <td class="ov-usage-cell">${escapeHtml(String(r.usage || "-"))}</td>
          <td class="ov-calc-cell">
            <div class="ov-calc-text ${needToggle && !isOpen ? "is-clamped" : ""}">${escapeHtml(noteTrim || "-")}</div>
            ${toggleBtn}
          </td>
          <td class="col-num ov-num-stack">
            <div class="ov-stack-line ov-price-line">${escapeHtml(String(r.unit_price || "-"))}</div>
            <div class="ov-stack-line ov-stack-gap" aria-hidden="true">&nbsp;</div>
          </td>
          <td class="col-num ov-num-stack">
            <div class="ov-stack-line ov-stack-gap" aria-hidden="true">&nbsp;</div>
            <div class="ov-stack-line ov-amount-line ov-num-strong">${escapeHtml(amtText)}</div>
          </td>
        </tr>`;
    })
    .join("");
}

function sortedPairs(pairs) {
  const arr = [...pairs];
  const dir = detailSort.dir === "desc" ? -1 : 1;
  arr.sort((a, b) => {
    if (detailSort.key === "amount_num") {
      const va = parseAmountNum(a.row);
      const vb = parseAmountNum(b.row);
      const fa = Number.isFinite(va);
      const fb = Number.isFinite(vb);
      if (fa && fb && va !== vb) return va > vb ? dir : -dir;
      if (fa !== fb) return fa ? -dir : dir;
    }
    if (detailSort.key === "usage_raw") {
      const ua = usageSortKey(a.row.usage);
      const ub = usageSortKey(b.row.usage);
      if (typeof ua === "number" && typeof ub === "number" && ua !== ub)
        return ua > ub ? dir : -dir;
      const sa = String(a.row.usage || "");
      const sb = String(b.row.usage || "");
      const c = sa.localeCompare(sb, "zh-CN");
      if (c !== 0) return c * dir;
    }
    return (a.lineNo - b.lineNo) * (detailSort.dir === "desc" ? -1 : 1);
  });
  return arr;
}

function readDetailViewMode() {
  try {
    const v = sessionStorage.getItem(DETAIL_VIEW_MODE_KEY);
    return v === "simple" ? "simple" : "marker";
  } catch {
    return "marker";
  }
}

function writeDetailViewMode(mode) {
  try {
    sessionStorage.setItem(DETAIL_VIEW_MODE_KEY, mode === "simple" ? "simple" : "marker");
  } catch {
    /* ignore */
  }
}

function syncDetailViewToolbar(mode) {
  const marker = mode !== "simple";
  els.btnDetailViewMarker?.classList.toggle("is-active", marker);
  els.btnDetailViewSimple?.classList.toggle("is-active", !marker);
  if (els.detailMarkerWrap) els.detailMarkerWrap.hidden = !marker;
  if (els.detailSimpleWrap) els.detailSimpleWrap.hidden = marker;
}

function markerBadgeClass(text) {
  const t = String(text || "");
  if (t === "待核" || t === "AI推断") return "badge-warn";
  if (t === "自动修正") return "badge-risk";
  return "badge-ok";
}

function renderMarkerRoomTable(quote) {
  const body = els.markerRoomBody;
  if (!body) return;
  const table = quote?.marker_room_bom_table;
  const rows = table && Array.isArray(table.rows) ? table.rows : [];
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="16" class="bom-empty-cell">暂无板房用量明细（可切换「简明物料表」查看原明细）</td></tr>`;
    return;
  }
  body.innerHTML = rows
    .map((r) => {
      const badges = Array.isArray(r.badges) ? r.badges : [];
      const badgeHtml = badges
        .map((b) => `<span class="badge ${markerBadgeClass(b)}">${escapeHtml(String(b))}</span>`)
        .join("");
      const matCell = r.is_group_start
        ? `<div>${escapeHtml(String(r.material_name || ""))}</div>${
            r.piece_set_label
              ? `<span class="mr-piece-set-hint">裁片：${escapeHtml(String(r.piece_set_label))}</span>`
              : ""
          }`
        : "";
      const matCls = r.is_group_start ? "" : " mr-material-empty";
      const trCls = [
        r.is_group_end ? "mr-group-end" : "",
        r.is_auxiliary ? "mr-auxiliary" : "",
      ]
        .filter(Boolean)
        .join(" ");
      return `
        <tr class="${trCls}">
          <td class="${matCls.trim()}">${matCell}</td>
          <td class="mr-num">${escapeHtml(String(r.roll_width || ""))}</td>
          <td class="mr-num">${escapeHtml(String(r.marker_width || ""))}</td>
          <td class="mr-piece-name">${escapeHtml(String(r.piece_name || ""))}</td>
          <td class="mr-num">${escapeHtml(String(r.length || ""))}</td>
          <td class="mr-num">${escapeHtml(String(r.width || ""))}</td>
          <td class="mr-num">${escapeHtml(String(r.occupied_length || ""))}</td>
          <td class="mr-num">${escapeHtml(String(r.occupied_width || ""))}</td>
          <td class="mr-num">${escapeHtml(String(r.qty || ""))}</td>
          <td class="mr-num">${escapeHtml(String(r.single_marker_usage || ""))}</td>
          <td class="mr-num">${escapeHtml(String(r.loss_pct || ""))}</td>
          <td class="mr-num">${escapeHtml(String(r.total_marker_usage || ""))}</td>
          <td>${escapeHtml(String(r.unit || ""))}</td>
          <td class="mr-num">${escapeHtml(String(r.unit_price || ""))}</td>
          <td class="mr-num">${escapeHtml(String(r.amount || ""))}</td>
          <td class="badges-cell col-anomaly">${badgeHtml}</td>
        </tr>`;
    })
    .join("");
}

function renderDetailPanel(pairs, quote) {
  const mode = readDetailViewMode();
  syncDetailViewToolbar(mode);
  if (mode === "simple") {
    renderDetailTable(pairs);
    return;
  }
  renderMarkerRoomTable(quote || lastBundle?.quote || {});
}

function renderDetailTable(pairs) {
  const sorted = sortedPairs(pairs);
  els.detailRowsBody.innerHTML = sorted
    .map((pair) => {
      const r = pair.row || {};
      const db = pair.db || {};
      const badges = classifyAnomalies(pair);
      const badgeHtml = badges
        .map((b) => `<span class="badge ${b.cls}">${escapeHtml(b.text)}</span>`)
        .join("");
      const amtText =
        r.amount_text != null ? String(r.amount_text) : formatMoney(parseAmountNum(r));
      const note = String(pair.mergedCalcNote || "").trim();
      const noteHtml = note
        ? `<div class="detail-calc-text">${escapeHtml(note)}</div>`
        : `<div class="detail-calc-text muted">No calc note</div>`;
      const piecePart = formatDetailPiecePart(r.piece_part, lastBundle?.quote, r.name);
      return `
        <tr>
          <td class="badges-cell col-anomaly">${badgeHtml}</td>
          <td>
            <div class="detail-name-line">${escapeHtml(String(r.name || "-"))}</div>
          </td>
          <td class="detail-piece-cell">${escapeHtml(piecePart)}</td>
          <td class="detail-spec-cell">${escapeHtml(String(r.spec || "-"))}</td>
          <td class="detail-usage-cell">${escapeHtml(String(r.usage || "-"))}</td>
          <td>${noteHtml}</td>
          <td class="col-num ov-num-stack">
            <div class="ov-stack-line ov-price-line">${escapeHtml(String(r.unit_price || "-"))}</div>
            <div class="ov-stack-line ov-stack-gap" aria-hidden="true">&nbsp;</div>
          </td>
          <td class="col-num ov-num-stack">
            <div class="ov-stack-line ov-stack-gap" aria-hidden="true">&nbsp;</div>
            <div class="ov-stack-line ov-amount-line detail-amount-strong">${escapeHtml(amtText)}</div>
          </td>
        </tr>`;
    })
    .join("");
}

async function ensureFirstSheetUrl() {
  if (firstSheetUrl) return firstSheetUrl;
  if (!selectedQuoteId) return "";
  const { ok, data } = await apiJson(
    `/admin-api/quotes/${encodeURIComponent(selectedQuoteId)}/files`,
  );
  const files = ok && Array.isArray(data.files) ? data.files : [];
  const { sales } = splitQuoteFilesByRole(files);
  const fid = encodeURIComponent(String(sales[0]?.file_id || ""));
  firstSheetUrl = fid ? `/admin-api/quotes/files/${fid}/download` : "";
  els.btnOpenSheet.disabled = !firstSheetUrl;
  return firstSheetUrl;
}

function normalizeQuoteFileRole(raw) {
  const role = String(raw || "sales_sheet").trim().toLowerCase();
  if (role === "admin_correction" || role === "admin_corrected") return ADMIN_SHEET_KIND_CORRECTED;
  if (role === "admin_calculated") return ADMIN_SHEET_KIND_CALCULATED;
  return "sales_sheet";
}

function categorizeQuoteFiles(files) {
  const sales = [];
  let adminCorrected = null;
  let adminCalculated = null;
  for (const f of files || []) {
    if (!f || typeof f !== "object") continue;
    const role = normalizeQuoteFileRole(f.file_role);
    if (role === ADMIN_SHEET_KIND_CORRECTED) adminCorrected = f;
    else if (role === ADMIN_SHEET_KIND_CALCULATED) adminCalculated = f;
    else sales.push(f);
  }
  return { sales, adminCorrected, adminCalculated };
}

function splitQuoteFilesByRole(files) {
  const cat = categorizeQuoteFiles(files);
  return { sales: cat.sales, adminFile: cat.adminCorrected };
}

function resolveAdminSheetRecord(kind, meta, files) {
  const cfg = ADMIN_SHEET_UI[kind];
  if (!cfg) return null;
  const cat = categorizeQuoteFiles(files);
  let rec = kind === ADMIN_SHEET_KIND_CALCULATED ? cat.adminCalculated : cat.adminCorrected;
  const fid = String((meta || {})[cfg.metaId] || "").trim();
  if (!rec && fid) {
    rec = (files || []).find((f) => String(f.file_id || "") === fid) || null;
  }
  return rec;
}

function renderAdminSheetFileRow(kind, meta, files) {
  const cfg = ADMIN_SHEET_UI[kind];
  const mount = cfg?.fileMount?.();
  if (!mount || !cfg) return;
  const m = meta || {};
  const adminRec = resolveAdminSheetRecord(kind, m, files);
  if (!adminRec) {
    mount.innerHTML = `<span class="muted">${escapeHtml(cfg.emptyText)}</span>`;
    return;
  }
  const fidl = encodeURIComponent(String(adminRec.file_id || ""));
  const name = escapeHtml(String(adminRec.original_name || "下载"));
  const upAt = escapeHtml(String(adminRec.uploaded_at || m[cfg.metaAt] || ""));
  const upBy = escapeHtml(String(adminRec.uploaded_by || m[cfg.metaBy] || ""));
  const sizeTxt = adminRec.file_size != null ? formatFileSize(adminRec.file_size) : "";
  const metaTxt = [
    upAt && `上传 ${upAt}`,
    upBy && `上传人 ${upBy}`,
    sizeTxt && `大小 ${sizeTxt}`,
  ].filter(Boolean).join(" · ");
  mount.innerHTML = `
    <span class="bcw-admin-file-line">
      <a class="bcw-file-chip ${cfg.chipClass}" href="/admin-api/quotes/files/${fidl}/download" target="_blank" rel="noopener">${name}</a>
      ${metaTxt ? `<span class="muted">${metaTxt}</span>` : ""}
      <button type="button" class="btn btn-danger btn-sm" data-bcw-delete-sheet="${escapeAttr(kind)}">删除</button>
    </span>`;
}

function renderAdminSheetHint(kind, meta, files) {
  const cfg = ADMIN_SHEET_UI[kind];
  const hint = cfg?.hintMount?.();
  if (!hint || !cfg) return;
  const adminRec = resolveAdminSheetRecord(kind, meta, files);
  hint.textContent = adminRec
    ? `重新上传将替换当前${kind === ADMIN_SHEET_KIND_CALCULATED ? "自算" : "修正版"}附件（需二次确认）`
    : kind === ADMIN_SHEET_KIND_CALCULATED
      ? "可选附件，支持 xlsx/xls/csv/pdf/doc/docx/png/jpg/jpeg/zip/rar，最大 100MB；不参与 BOM 解析"
      : "可选附件，支持 xlsx/xls/csv；不影响可视化修正结果";
}

async function submitAdminCorrectionFeedback(note, options = {}) {
  const quoteUid = resolveAdminQuoteSeriesUid();
  if (!quoteUid || adminFeedbackSaving) return false;
  const trimmed = String(note ?? "").trim();
  const problemTypes = collectCorrectionProblemTypesFromDom();
  adminFeedbackSaving = true;
  if (els.btnSaveAdminFeedback) els.btnSaveAdminFeedback.disabled = true;
  const { ok, data, status } = await apiJson(
    `/admin-api/quotes/${encodeURIComponent(quoteUid)}/feedback`,
    {
      method: "POST",
      body: JSON.stringify({ correction_note: trimmed, correction_problem_types: problemTypes }),
    },
  );
  adminFeedbackSaving = false;
  if (els.btnSaveAdminFeedback) els.btnSaveAdminFeedback.disabled = false;
  if (!ok) {
    if (options.toastOnSuccess !== false) {
      showAdminToast(formatAdminApiErrorMessage(data, status), "err");
    }
    return false;
  }
  if (lastBundle?.meta) {
    lastBundle.meta.admin_correction_note = trimmed;
    lastBundle.meta.admin_correction_problem_types = problemTypes;
    if (data.admin_feedback) {
      lastBundle.meta.admin_feedback_at = data.admin_feedback.feedback_at;
      lastBundle.meta.admin_feedback_by = data.admin_feedback.feedback_by;
      lastBundle.meta.admin_update_status = data.admin_feedback.admin_update_status || "pending_view";
      lastBundle.meta.admin_update_at = data.admin_feedback.admin_update_at || lastBundle.meta.admin_update_at;
    }
  }
  renderBomCorrectionWorkspace(lastBundle?.meta, lastBundle?.files);
  if (options.toastOnSuccess !== false) {
    showAdminToast(trimmed ? "已保存修正说明并通知业务员" : "已通知业务员查看修正版");
  }
  return true;
}

function renderAdminSavedCorrectionStatus(meta) {
  if (!els.adminSavedCorrectionStatus) return;
  const m = meta || {};
  const fbAt = String(m.admin_feedback_at || "").trim();
  const fbBy = String(m.admin_feedback_by || "").trim();
  const note = String(m.admin_correction_note || "").trim();
  const ver = Number(m.latest_version_no || 0);
  const hasSaved = Boolean(fbAt) || ver > 1;
  if (!hasSaved) {
    els.adminSavedCorrectionStatus.hidden = true;
    els.adminSavedCorrectionStatus.innerHTML = "";
    return;
  }
  const status = String(m.admin_update_status || "").trim().toLowerCase();
  const pending = status === "pending_view";
  const headParts = [
    "<strong>已保存管理员修正版</strong>",
    ver > 1 ? `版本 v${ver}` : "",
    fbAt ? `修正时间 ${escapeHtml(fbAt)}` : "",
    fbBy ? `处理人 ${escapeHtml(fbBy)}` : "",
    pending
      ? `<span class="bcw-sales-view-pending">待业务员查看</span>`
      : `<span class="bcw-sales-view-done">业务员已查看</span>`,
  ].filter(Boolean);
  const noteHtml = note
    ? `<p class="bcw-saved-note"><span class="muted">修正说明：</span>${escapeHtml(note)}</p>`
    : "";
  els.adminSavedCorrectionStatus.hidden = false;
  els.adminSavedCorrectionStatus.innerHTML = `<div class="bcw-saved-status-inner">${headParts.join(" · ")}</div>${noteHtml}`;
}

function renderSalesViewStatus(meta) {
  if (!els.adminSalesViewStatus) return;
  const m = meta || {};
  const status = String(m.admin_update_status || "").trim().toLowerCase();
  const viewedAt = String(m.admin_update_viewed_at || "").trim();
  const updateAt = String(m.admin_update_at || "").trim();
  if (status === "pending_view") {
    els.adminSalesViewStatus.innerHTML =
      `<span class="bcw-sales-view-pending">业务员待查看</span>${updateAt ? ` · 更新 ${escapeHtml(updateAt)}` : ""}`;
    return;
  }
  if (status === "handled") {
    const handledAt = String(m.admin_update_handled_at || "").trim();
    els.adminSalesViewStatus.innerHTML =
      `<span class="bcw-sales-view-done">业务员已处理</span>${handledAt ? ` · ${escapeHtml(handledAt)}` : ""}`;
    return;
  }
  if (status === "viewed" || viewedAt) {
    els.adminSalesViewStatus.innerHTML =
      `<span class="bcw-sales-view-done">业务员已查看</span>${viewedAt ? ` · ${escapeHtml(viewedAt)}` : ""}`;
    return;
  }
  els.adminSalesViewStatus.textContent = "保存管理员修正版后，业务员将收到「有新修正」提醒";
}

function renderBomCorrectionWorkspace(meta, files) {
  if (!els.bomCorrectionWorkspace) return;
  const m = meta || {};
  const allFiles = Array.isArray(files) ? files : [];
  const { sales } = categorizeQuoteFiles(allFiles);

  renderAdminSavedCorrectionStatus(m);

  if (els.bcwSalesFiles) {
    if (!sales.length) {
      els.bcwSalesFiles.innerHTML = `<span class="muted">暂无业务员原始表格</span>`;
    } else {
      els.bcwSalesFiles.innerHTML = sales
        .map((f) => {
          const fidl = encodeURIComponent(String(f.file_id || ""));
          const name = escapeHtml(String(f.original_name || "下载"));
          return `<a class="bcw-file-chip bcw-file-chip-ref" href="/admin-api/quotes/files/${fidl}/download" target="_blank" rel="noopener">${name}</a>`;
        })
        .join("");
    }
  }

  renderAdminSheetFileRow(ADMIN_SHEET_KIND_CORRECTED, m, allFiles);
  renderAdminSheetFileRow(ADMIN_SHEET_KIND_CALCULATED, m, allFiles);
  renderAdminSheetHint(ADMIN_SHEET_KIND_CORRECTED, m, allFiles);
  renderAdminSheetHint(ADMIN_SHEET_KIND_CALCULATED, m, allFiles);

  if (els.adminCorrectionNoteInput) {
    els.adminCorrectionNoteInput.value = String(m.admin_correction_note || "");
  }
  renderCorrectionProblemTypes(m);

  if (els.adminFeedbackMeta) {
    const fbAt = String(m.admin_feedback_at || "").trim();
    const fbBy = String(m.admin_feedback_by || "").trim();
    if (fbAt) {
      const parts = [`最近反馈 ${escapeHtml(fbAt)}`];
      if (fbBy) parts.push(`处理人 ${escapeHtml(fbBy)}`);
      els.adminFeedbackMeta.innerHTML = parts.join(" · ");
    } else {
      els.adminFeedbackMeta.textContent = "保存管理员修正版时将一并通知业务员";
    }
  }

  renderSalesViewStatus(m);
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const res = String(reader.result || "");
      const idx = res.indexOf(",");
      resolve(idx >= 0 ? res.slice(idx + 1) : res);
    };
    reader.onerror = () => reject(reader.error || new Error("read failed"));
    reader.readAsDataURL(file);
  });
}

function isBlockedAdminAttachmentFile(file) {
  if (!file) return false;
  const name = String(file.name || "").toLowerCase();
  return ADMIN_ATTACHMENT_BLOCKED_SUFFIXES.some((s) => name.endsWith(s));
}

function isAllowedCorrectionSheetFile(file) {
  if (!file || isBlockedAdminAttachmentFile(file)) return false;
  const name = String(file.name || "").toLowerCase();
  return CORRECTION_SHEET_SUFFIXES.some((s) => name.endsWith(s));
}

function isAllowedCalculatedAttachmentFile(file) {
  if (!file || isBlockedAdminAttachmentFile(file)) return false;
  const name = String(file.name || "").toLowerCase();
  return ADMIN_CALCULATED_ATTACHMENT_SUFFIXES.some((s) => name.endsWith(s));
}

function isAllowedAdminSheetFile(kind, file) {
  if (kind === ADMIN_SHEET_KIND_CALCULATED) {
    return isAllowedCalculatedAttachmentFile(file);
  }
  return isAllowedCorrectionSheetFile(file);
}

function resolveAdminQuoteSeriesUid() {
  return String(lastBundle?.meta?.quote_uid || selectedQuoteId || "").trim();
}

function formatAdminApiErrorMessage(data, status) {
  const msg = String(data?.message || "").trim();
  if (msg) return msg;
  const err = String(data?.error || "").trim().toLowerCase();
  if (err === "not_found" || status === 404) {
    return "当前报价不存在或已被删除，请刷新列表后重试";
  }
  if (err === "not found") {
    return "管理接口未命中后台服务，请从后台独立端口打开页面（如 :8777）后重试";
  }
  return String(data?.error || "").trim() || "操作失败";
}

function applyAdminSheetUploadToBundle(kind, data) {
  const cfg = ADMIN_SHEET_UI[kind];
  if (!lastBundle || !cfg || !data?.file) return;
  const files = Array.isArray(lastBundle.files) ? [...lastBundle.files] : [];
  const roleSet = new Set(cfg.roles);
  const withoutOld = files.filter(
    (f) => !roleSet.has(normalizeQuoteFileRole(f?.file_role))
      && String(f?.file_id) !== String(data.file.file_id),
  );
  withoutOld.push(data.file);
  lastBundle.files = withoutOld;
  if (lastBundle.meta) {
    lastBundle.meta[cfg.metaId] = data.file.file_id;
    lastBundle.meta[cfg.metaAt] = data.file.uploaded_at;
    lastBundle.meta[cfg.metaBy] = data.file.uploaded_by;
    lastBundle.meta.admin_update_status = "pending_view";
    lastBundle.meta.admin_update_at = data.file.uploaded_at;
    lastBundle.meta.admin_update_viewed_at = null;
    lastBundle.meta.admin_update_handled_at = null;
  }
}

function clearAdminSheetFromBundle(kind) {
  const cfg = ADMIN_SHEET_UI[kind];
  if (!lastBundle || !cfg) return;
  const roleSet = new Set(cfg.roles);
  const files = Array.isArray(lastBundle.files) ? lastBundle.files : [];
  lastBundle.files = files.filter((f) => !roleSet.has(normalizeQuoteFileRole(f?.file_role)));
  if (lastBundle.meta) {
    lastBundle.meta[cfg.metaId] = null;
    lastBundle.meta[cfg.metaAt] = null;
    lastBundle.meta[cfg.metaBy] = null;
  }
}

async function uploadAdminSheet(kind, file, replaceConfirmed = false) {
  const cfg = ADMIN_SHEET_UI[kind];
  if (!cfg) return false;
  const quoteUid = resolveAdminQuoteSeriesUid();
  if (!quoteUid) {
    showAdminToast("请先在列表中选择一条报价", "err");
    return false;
  }
  if (!file) return false;
  if (isBlockedAdminAttachmentFile(file)) {
    showAdminToast("不允许上传 exe、bat、cmd、ps1、js、vbs、msi、scr、dll、com、jar、sh 等危险文件", "err");
    return false;
  }
  if (!isAllowedAdminSheetFile(kind, file)) {
    showAdminToast(
      kind === ADMIN_SHEET_KIND_CALCULATED
        ? "自算附件仅支持 xlsx、xls、csv、pdf、doc、docx、png、jpg、jpeg、zip、rar"
        : "仅支持 xlsx、xls、csv 表格文件",
      "err",
    );
    return false;
  }
  if (file.size > ADMIN_ATTACHMENT_MAX_BYTES) {
    showAdminToast("文件大小不能超过 100MB", "err");
    return false;
  }
  let b64;
  try {
    b64 = await fileToBase64(file);
  } catch {
    showAdminToast("读取文件失败", "err");
    return false;
  }
  const payload = {
    uploaded_sheet: { name: file.name, content_base64: b64 },
    replace_confirmed: replaceConfirmed,
  };
  const { ok, status, data } = await apiJson(
    `/admin-api/quotes/${encodeURIComponent(quoteUid)}/${cfg.apiPath}`,
    { method: "POST", body: JSON.stringify(payload) },
  );
  if (status === 409 && data?.error === "replace_confirm_required") {
    if (window.confirm(cfg.replaceConfirm)) {
      return uploadAdminSheet(kind, file, true);
    }
    return false;
  }
  if (!ok) {
    showAdminToast(formatAdminApiErrorMessage(data, status), "err");
    return false;
  }
  applyAdminSheetUploadToBundle(kind, data);
  renderBomCorrectionWorkspace(lastBundle?.meta, lastBundle?.files);
  renderVersions(lastBundle?.files || [], lastBundle?.versions, lastBundle?.meta || {});
  showAdminToast(cfg.uploadToast(file.name));
  return true;
}

async function uploadAdminCorrectionSheet(file, replaceConfirmed = false) {
  return uploadAdminSheet(ADMIN_SHEET_KIND_CORRECTED, file, replaceConfirmed);
}

async function uploadAdminCalculatedSheet(file, replaceConfirmed = false) {
  return uploadAdminSheet(ADMIN_SHEET_KIND_CALCULATED, file, replaceConfirmed);
}

const adminSheetDeleting = {};

async function deleteAdminSheet(kind) {
  const cfg = ADMIN_SHEET_UI[kind];
  if (!cfg) return;
  const quoteUid = resolveAdminQuoteSeriesUid();
  if (!quoteUid || adminSheetDeleting[kind]) return;
  const rec = resolveAdminSheetRecord(kind, lastBundle?.meta, lastBundle?.files || []);
  if (!rec && !(lastBundle?.meta || {})[cfg.metaId]) return;
  if (!window.confirm(cfg.deleteConfirm)) return;

  adminSheetDeleting[kind] = true;
  const { ok, status, data } = await apiJson(
    `/admin-api/quotes/${encodeURIComponent(quoteUid)}/${cfg.apiPath}`,
    { method: "DELETE" },
  );
  adminSheetDeleting[kind] = false;
  if (!ok) {
    showAdminToast(formatAdminApiErrorMessage(data, status), "err");
    return;
  }
  clearAdminSheetFromBundle(kind);
  renderBomCorrectionWorkspace(lastBundle?.meta, lastBundle?.files);
  renderVersions(lastBundle?.files || [], lastBundle?.versions, lastBundle?.meta || {});
  showAdminToast(cfg.deleteToast);
}

async function deleteAdminCorrectionSheet() {
  return deleteAdminSheet(ADMIN_SHEET_KIND_CORRECTED);
}

async function deleteAdminCalculatedSheet() {
  return deleteAdminSheet(ADMIN_SHEET_KIND_CALCULATED);
}

async function saveAdminFeedbackToSales() {
  if (bomEditMode) {
    showAdminToast("请先保存或取消 BOM 编辑", "err");
    return;
  }
  const note = String(els.adminCorrectionNoteInput?.value || "").trim();
  await submitAdminCorrectionFeedback(note);
}

function renderCalcAccordion(pairs) {
  els.calcAccordion.innerHTML = pairs
    .map((pair, idx) => {
      const title = `${pair.lineNo}. ${pair.row.name || "-"}`;
      const note = String(pair.mergedCalcNote || "").trim();
      const body = note || "No calc note";
      const eid = `acc_${idx}`;
      return `
        <div class="accordion-item">
          <button type="button" class="accordion-head" aria-expanded="false" data-acc="${escapeAttr(eid)}">
            <span>${escapeHtml(title)}</span>
            <span class="muted">${note.length > 48 ? "灞曞紑" : ""}</span>
          </button>
          <div class="accordion-body" id="${escapeAttr(eid)}" hidden>${escapeHtml(body)}</div>
        </div>`;
    })
    .join("");

  els.calcAccordion.querySelectorAll(".accordion-head").forEach((head) => {
    head.addEventListener("click", () => {
      const id = head.getAttribute("data-acc");
      const body = id ? document.getElementById(id) : null;
      if (!body) return;
      const open = body.hidden;
      body.hidden = !open;
      head.setAttribute("aria-expanded", open ? "true" : "false");
    });
  });
}

function renderVersions(files, versions, meta) {
  const rows = Array.isArray(versions) ? versions : [];
  const allFiles = Array.isArray(files) ? files : [];
  const { sales, adminCorrected, adminCalculated } = categorizeQuoteFiles(allFiles);
  els.versionsTableBody.innerHTML = rows
    .map((v) => {
      return `
        <tr>
          <td>v${escapeHtml(String(v.version_no ?? ""))}</td>
          <td>${escapeHtml(String(v.saved_at || ""))}</td>
          <td>${escapeHtml(String(v.calc_quote_id || ""))}</td>
          <td>${escapeHtml(String(v.intent || ""))}</td>
        </tr>`;
    })
    .join("");

  els.versionBar.hidden = rows.length <= 1;
  els.versionSelect.innerHTML = rows
    .map((v) => {
      const lab = `v${v.version_no} 路 ${v.saved_at || ""}${v.intent ? " 路 " + String(v.intent) : ""}`;
      return `<option value="${escapeHtml(String(v.version_no))}">${escapeHtml(lab)}</option>`;
    })
    .join("");
  const selNo = meta.selected_version_no;
  if (selNo != null) els.versionSelect.value = String(selNo);

  if (!sales.length && !adminCorrected && !adminCalculated) {
    els.detailFiles.innerHTML = `<span class="muted">暂无上传的原始表文件</span>`;
    firstSheetUrl = "";
    els.btnOpenSheet.disabled = true;
  } else {
    const salesHtml = sales
      .map((f) => {
        const fid = encodeURIComponent(String(f.file_id || ""));
        const name = escapeHtml(String(f.original_name || "下载"));
        return `<a href="/admin-api/quotes/files/${fid}/download" target="_blank" rel="noopener" title="业务员原始表格">${name}</a>`;
      })
      .join("");
    const adminLinks = [ADMIN_SHEET_KIND_CORRECTED, ADMIN_SHEET_KIND_CALCULATED]
      .map((kind) => {
        const cfg = ADMIN_SHEET_UI[kind];
        const rec = resolveAdminSheetRecord(kind, meta, allFiles);
        if (!rec || !cfg) return "";
        const fid = encodeURIComponent(String(rec.file_id || ""));
        const name = escapeHtml(String(rec.original_name || "下载"));
        return `<a href="/admin-api/quotes/files/${fid}/download" target="_blank" rel="noopener" title="${escapeAttr(cfg.versionTitle)}">${name}${escapeHtml(cfg.versionSuffix)}</a>`;
      })
      .filter(Boolean);
    els.detailFiles.innerHTML = [salesHtml, ...adminLinks].filter(Boolean).join(" ")
      || `<span class="muted">暂无上传的原始表文件</span>`;
    const fid0 = encodeURIComponent(String(sales[0]?.file_id || ""));
    firstSheetUrl = fid0 ? `/admin-api/quotes/files/${fid0}/download` : "";
    els.btnOpenSheet.disabled = !firstSheetUrl;
  }
  renderBomCorrectionWorkspace(meta, allFiles);
}

function tierSnapshot(q, idx) {
  const tiers = Array.isArray(q?.tiers) ? q.tiers : [];
  const t = tiers[idx] || {};
  return {
    mt: Number(q?.material_total),
    cbm: Number(t.cost_before_margin ?? t.total_cost),
    exw: Number(t.exw_price),
  };
}

function fmtDelta(cur, prev) {
  if (!Number.isFinite(cur) || !Number.isFinite(prev)) return "-";
  const d = Math.round((cur - prev) * 100) / 100;
  if (d === 0) return "0";
  const cls = d > 0 ? "diff-pos" : "diff-neg";
  const sign = d > 0 ? "+" : "";
  return `<span class="${cls}">${sign}${formatMoney(d)}</span>`;
}

async function renderVersionDiff(quoteId, meta, quote) {
  els.diffSection.hidden = true;
  els.diffBody.innerHTML = "";
  const sel = Number(meta.selected_version_no);
  if (!Number.isFinite(sel) || sel <= 1) return;

  const { ok, data } = await apiJson(
    `/admin-api/quotes/${encodeURIComponent(quoteId)}?version=${encodeURIComponent(String(sel - 1))}`,
  );
  if (!ok || !data.quote) return;

  const prevQ = data.quote;
  const a = tierSnapshot(quote, 0);
  const b = tierSnapshot(prevQ, 0);

  els.diffBody.innerHTML = `
    <div>物料合计：${escapeHtml(formatMoney(b.mt))} → ${escapeHtml(formatMoney(a.mt))} （${fmtDelta(a.mt, b.mt)}）</div>
    <div>一档毛利前成本：${escapeHtml(formatMoney(b.cbm))} → ${escapeHtml(formatMoney(a.cbm))} （${fmtDelta(a.cbm, b.cbm)}）</div>
    <div>一档 EXW：${escapeHtml(formatMoney(b.exw))} → ${escapeHtml(formatMoney(a.exw))} （${fmtDelta(a.exw, b.exw)}）</div>
  `;
  els.diffSection.hidden = false;
}

async function selectRow(quoteId, trEl, explicitVersion) {
  selectedQuoteId = quoteId;
  if (trEl) {
    selectedRowEl = trEl;
    els.listBody.querySelectorAll("tr").forEach((r) =>
      r.classList.toggle("row-selected", r === trEl),
    );
  } else if (els.listBody) {
    const tr = [...els.listBody.querySelectorAll("tr")].find((r) => r.dataset.quoteId === quoteId);
    if (tr) {
      selectedRowEl = tr;
      els.listBody.querySelectorAll("tr").forEach((r) =>
        r.classList.toggle("row-selected", r === tr),
      );
    } else {
      selectedRowEl = null;
      els.listBody.querySelectorAll("tr").forEach((r) => r.classList.remove("row-selected"));
    }
  }

  let qs = "";
  if (
    explicitVersion != null &&
    explicitVersion !== "" &&
    !Number.isNaN(Number(explicitVersion))
  ) {
    qs = `?version=${encodeURIComponent(String(explicitVersion))}`;
  }

  els.detailWorkspace.classList.add("detail-dim");
  const { ok, status, data } = await apiJson(`/admin-api/quotes/${encodeURIComponent(quoteId)}${qs}`);
  els.detailWorkspace.classList.remove("detail-dim");

  if (!ok) {
    hideQuoteApprovalPanel();
    els.detailPlaceholder.hidden = false;
    els.detailWorkspace.hidden = true;
    lastBundle = null;
    if (els.tierSummaryTitle) els.tierSummaryTitle.textContent = "三档报价对比";
    if (els.tierCompareMount) els.tierCompareMount.innerHTML = "";
    if (els.overviewHealth) els.overviewHealth.innerHTML = "";
    if (els.overviewHeroMount) els.overviewHeroMount.innerHTML = "";
    if (els.overviewCostMix) els.overviewCostMix.innerHTML = "";
    if (els.overviewEmbeddedDetailBody) els.overviewEmbeddedDetailBody.innerHTML = "";
    if (els.overviewSuggestions) els.overviewSuggestions.innerHTML = "";
    if (els.overviewCredibility) els.overviewCredibility.innerHTML = "";
    if (status === 404 || data?.error === "not_found") {
      showAdminToast("该报价已不存在", "err");
      removeQuoteFromWatch(quoteId);
    }
    return false;
  }

  lastBundle = data;
  els.detailPlaceholder.hidden = true;
  els.detailWorkspace.hidden = false;

  resetOverviewUi();
  loadSimpleModeCheckbox();
  syncSimpleModeClass();

  const meta = data.meta || {};
  const quote = data.quote || {};
  const items = Array.isArray(data.items) ? data.items : [];

  els.detailTitle.textContent = String(meta.product_name || quote.product_name || "报价详情");
  renderDetailSubtitle(meta);
  renderQuoteApprovalPanel(meta);
  renderTechMeta(meta, quoteId);

  renderOverviewNotice(String(quote.data_notice || "").trim());

  renderVersions(Array.isArray(data.files) ? data.files : [], data.versions, meta);

  bomEditMode = false;
  bomEditSnapshot = null;
  bomEditDraft = null;
  bomEditFieldErrors = {};

  const pairs = pairDetailRows(quote, items);
  renderOverviewDashboard(quote);
  renderOverviewEmbeddedDetail(pairs, quote, meta);
  loadOverviewEmbedValidationFromSession(quoteId);
  renderDetailPanel(pairs, quote);

  renderCalcAccordion(pairs);

  setActiveTab("overview");

  renderVersionDiff(quoteId, meta, quote).catch(() => {});
  return true;
}

if (els.btnSaveQuoteApproval) {
  els.btnSaveQuoteApproval.addEventListener("click", () => saveQuoteApproval());
}

els.chkSimpleMode.addEventListener("change", () => {
  syncSimpleModeClass();
  refreshNoticeVisibility();
});

els.btnToggleTech.addEventListener("click", () => {
  const open = els.detailTechPanel.hidden;
  els.detailTechPanel.hidden = !open;
  els.btnToggleTech.setAttribute("aria-expanded", open ? "true" : "false");
  els.btnToggleTech.textContent = open ? "Hide tech info" : "Tech info";
});

if (els.btnOpenVersionsFiles) {
  els.btnOpenVersionsFiles.addEventListener("click", () => setActiveTab("files"));
}

els.btnOverviewExpand.addEventListener("click", () => {
  overviewExpanded = !overviewExpanded;
  if (els.panelOverview) els.panelOverview.classList.toggle("overview-expanded", overviewExpanded);
  els.btnOverviewExpand.textContent = overviewExpanded ? "收起成本拆解" : "展开成本拆解";
});

if (els.chkOverviewDetailValidation) {
  els.chkOverviewDetailValidation.addEventListener("change", () => {
    if (selectedQuoteId) persistOverviewValidation(selectedQuoteId);
    syncOverviewEmbedValidationUi();
  });
}

if (els.btnBomEdit) els.btnBomEdit.addEventListener("click", () => enterBomEditMode());
if (els.btnBomAdd) els.btnBomAdd.addEventListener("click", () => addBomEditRow());
if (els.btnBomCancel) els.btnBomCancel.addEventListener("click", () => cancelBomEditMode());
if (els.btnBomSave) els.btnBomSave.addEventListener("click", () => saveBomEditMode());
if (els.btnUploadCorrectionSheet && els.bcwCorrectionSheetInput) {
  els.btnUploadCorrectionSheet.addEventListener("click", () => {
    els.bcwCorrectionSheetInput.click();
  });
  els.bcwCorrectionSheetInput.addEventListener("change", async () => {
    const file = els.bcwCorrectionSheetInput.files?.[0];
    els.bcwCorrectionSheetInput.value = "";
    if (file) await uploadAdminCorrectionSheet(file);
  });
}
if (els.btnUploadCalculatedSheet && els.bcwCalculatedSheetInput) {
  els.btnUploadCalculatedSheet.addEventListener("click", () => {
    els.bcwCalculatedSheetInput.click();
  });
  els.bcwCalculatedSheetInput.addEventListener("change", async () => {
    const file = els.bcwCalculatedSheetInput.files?.[0];
    els.bcwCalculatedSheetInput.value = "";
    if (file) await uploadAdminCalculatedSheet(file);
  });
}
if (els.btnSaveAdminFeedback) {
  els.btnSaveAdminFeedback.addEventListener("click", () => saveAdminFeedbackToSales());
}

if (els.panelOverview) {
  const onBomEditFieldInput = (ev) => {
    if (!bomEditMode) return;
    if (!ev.target.closest(".bom-edit-input")) return;
    refreshBomEditPreviewOnly();
  };
  els.panelOverview.addEventListener("input", onBomEditFieldInput);
  els.panelOverview.addEventListener("change", onBomEditFieldInput);

  els.panelOverview.addEventListener("click", (ev) => {
    const bcwDel = ev.target.closest("[data-bcw-delete-sheet]");
    if (bcwDel) {
      ev.preventDefault();
      const kind = String(bcwDel.getAttribute("data-bcw-delete-sheet") || "").trim();
      if (kind === ADMIN_SHEET_KIND_CALCULATED) deleteAdminCalculatedSheet();
      else if (kind === ADMIN_SHEET_KIND_CORRECTED) deleteAdminCorrectionSheet();
      return;
    }
    const addBtn = ev.target.closest("[data-bom-add-row]");
    if (addBtn && bomEditMode && bomEditDraft) {
      ev.preventDefault();
      addBomEditRow();
      return;
    }
    const delBtn = ev.target.closest("[data-bom-row-delete]");
    if (delBtn && bomEditMode && bomEditDraft) {
      ev.preventDefault();
      const idx = Number(delBtn.getAttribute("data-bom-row-delete"));
      deleteBomEditRowAt(idx);
      return;
    }

    const act = ev.target.closest("[data-ov-action]");
    if (act && act.tagName === "BUTTON") {
      const action = act.getAttribute("data-ov-action");
      if (action === "detail") {
        ev.preventDefault();
        setActiveTab("detail");
        return;
      }
      if (action === "export") {
        ev.preventDefault();
        els.btnExportJson?.click();
        return;
      }
      if (action === "sheet") {
        ev.preventDefault();
        if (!act.disabled) els.btnOpenSheet?.click();
        return;
      }
    }

    const structToggle = ev.target.closest("[data-bom-structure-toggle]");
    if (structToggle && structToggle.tagName === "BUTTON") {
      ev.preventDefault();
      const wrap = structToggle.closest("[data-bom-structure-wrap]");
      if (!wrap) return;
      const expanded = wrap.classList.toggle("is-expanded");
      wrap.classList.toggle("is-collapsed", !expanded);
      structToggle.setAttribute("aria-expanded", expanded ? "true" : "false");
      structToggle.textContent = expanded ? "收起" : "展开全部";
      return;
    }

    const calcBt = ev.target.closest("[data-ov-calc-line]");
    if (calcBt && calcBt.tagName === "BUTTON" && selectedQuoteId) {
      ev.preventDefault();
      const ln = Number(calcBt.getAttribute("data-ov-calc-line"));
      if (!Number.isFinite(ln)) return;
      const set = readOverviewCalcExpandedSet(selectedQuoteId);
      if (set.has(ln)) set.delete(ln);
      else set.add(ln);
      writeOverviewCalcExpandedSet(selectedQuoteId, set);
      renderOverviewEmbeddedDetail(lastOverviewPairs, lastBundle?.quote || {}, lastBundle?.meta || {});
      return;
    }

    const sug = ev.target.closest("[data-ov-sug-exp]");
    if (sug && sug.tagName === "BUTTON") {
      ev.preventDefault();
      const li = sug.closest(".ov-sug-item");
      if (!li) return;
      const rest = li.querySelector(".ov-sug-rest");
      const lead = li.querySelector(".ov-sug-lead");
      const opening = !!(rest && rest.hidden);
      if (rest) rest.hidden = !opening;
      if (lead) lead.hidden = opening;
      sug.textContent = opening ? "收起" : "展开更多";
    }
  });
}

els.overviewNoticeToggle.addEventListener("click", () => {
  const open = els.overviewNoticeFull.hidden;
  els.overviewNoticeFull.hidden = !open;
  els.overviewNoticeToggle.setAttribute("aria-expanded", open ? "true" : "false");
});

els.versionSelect.addEventListener("change", async () => {
  const v = parseInt(els.versionSelect.value, 10);
  if (!selectedQuoteId || Number.isNaN(v)) return;
  await selectRow(selectedQuoteId, selectedRowEl || null, v);
});

document.querySelectorAll(".sortable").forEach((th) => {
  th.addEventListener("click", () => {
    const key = th.dataset.sort;
    if (!key) return;
    if (detailSort.key === key) detailSort.dir = detailSort.dir === "asc" ? "desc" : "asc";
    else {
      detailSort.key = key;
      detailSort.dir = key === "amount_num" ? "desc" : "asc";
    }
    if (!lastBundle) return;
    const pairs = pairDetailRows(lastBundle.quote || {}, lastBundle.items || []);
    renderDetailPanel(pairs, lastBundle.quote || {});
    renderOverviewEmbeddedDetail(pairs, lastBundle.quote || {}, lastBundle.meta || {});
  });
});

if (els.btnDetailViewMarker) {
  els.btnDetailViewMarker.addEventListener("click", () => {
    writeDetailViewMode("marker");
    if (!lastBundle) return;
    const pairs = pairDetailRows(lastBundle.quote || {}, lastBundle.items || []);
    renderDetailPanel(pairs, lastBundle.quote || {});
  });
}
if (els.btnDetailViewSimple) {
  els.btnDetailViewSimple.addEventListener("click", () => {
    writeDetailViewMode("simple");
    if (!lastBundle) return;
    const pairs = pairDetailRows(lastBundle.quote || {}, lastBundle.items || []);
    renderDetailPanel(pairs, lastBundle.quote || {});
  });
}

els.btnLogout.addEventListener("click", async () => {
  await apiJson("/admin-api/logout", { method: "POST", body: "{}" });
  selectedQuoteId = null;
  gotoLogin();
});

function reloadListPreservingSelection() {
  const prev = selectedQuoteId;
  loadList().then(() => {
    if (!prev) return;
    const tr = [...els.listBody.querySelectorAll("tr")].find((r) => r.dataset.quoteId === prev);
    if (tr) selectRow(prev, tr);
  });
}

els.btnRefresh.addEventListener("click", () => {
  loadDashboardStats();
  reloadListPreservingSelection();
});

els.btnNewQuotesAlert?.addEventListener("click", () => {
  applyNewQuotesAlertAction();
});

els.btnTogglePendingWatch?.addEventListener("click", () => {
  pendingWatchCollapsed = !pendingWatchCollapsed;
  try {
    localStorage.setItem(PENDING_WATCH_COLLAPSED_KEY, pendingWatchCollapsed ? "1" : "0");
  } catch {
    /* ignore */
  }
  renderPendingWatchPanel();
});

els.btnWatchUnseenOnly?.addEventListener("click", () => {
  pendingWatchUnseenOnly = !pendingWatchUnseenOnly;
  renderPendingWatchPanel();
});

els.btnWatchMarkAllSeen?.addEventListener("click", () => {
  markAllWatchSeen();
});

els.btnWatchClearSeen?.addEventListener("click", () => {
  clearSeenWatchRecords();
});

document.addEventListener("visibilitychange", () => {
  rescheduleListPoll();
});

els.listBody?.addEventListener("change", (ev) => {
  const el = ev.target;
  if (!(el instanceof HTMLInputElement) || !el.classList.contains("row-select-cb")) return;
  syncBatchToolbar();
});

els.chkSelectPage?.addEventListener("change", () => {
  const on = !!els.chkSelectPage?.checked;
  els.listBody.querySelectorAll(".row-select-cb").forEach((c) => {
    c.checked = on;
  });
  syncBatchToolbar();
});

async function batchDeleteSelectedRows() {
  const ids = [...els.listBody.querySelectorAll(".row-select-cb:checked")]
    .map((c) => c.getAttribute("data-quote-id") || "")
    .filter(Boolean);
  if (!ids.length) return;
  const confirmed = window.confirm(
    `确定删除选中的 ${ids.length} 条归档吗？删除后不可恢复。`,
  );
  if (!confirmed) return;
  const wasSel = selectedQuoteId;
  const { ok, data } = await apiJson("/admin-api/quotes/batch-delete", {
    method: "POST",
    body: JSON.stringify({ quote_ids: ids }),
  });
  if (!ok) {
    if (data?.error === "forbidden") gotoLogin();
    else window.alert(data?.message || data?.error || "删除失败");
    return;
  }
  const fd = Number(data.failed?.length ?? 0);
  if (fd)
    window.alert(`已删除 ${data.deleted ?? ids.length - fd} 条；${fd} 条未找到或删除失败。`);
  if (wasSel && ids.includes(wasSel)) {
    selectedQuoteId = null;
    selectedRowEl = null;
    lastBundle = null;
    hideQuoteApprovalPanel();
    els.detailPlaceholder.hidden = false;
    els.detailWorkspace.hidden = true;
  }
  for (const id of ids) removeQuoteFromWatch(id);
  await loadDashboardStats();
  await loadList();
  collapseDetailIfSelectionMissing();
}

els.btnBatchDelete?.addEventListener("click", () => {
  batchDeleteSelectedRows();
});

els.btnDeleteFilteredAll?.addEventListener("click", async () => {
  const n = Number(total) || 0;
  if (n <= 0) {
    window.alert("当前筛选下没有记录。");
    return;
  }
  if (
    !window.confirm(
      `将删除当前筛选条件下的全部归档（约 ${n} 条）。\n此操作不可恢复。确定要继续吗？`,
    )
  )
    return;
  if (!window.confirm("再次确认：真的要全部删除吗？")) return;
  const { ok, data } = await apiJson("/admin-api/quotes/batch-delete", {
    method: "POST",
    body: JSON.stringify({
      ...buildListFilterPayload(),
      mode: "filtered_all",
      confirm: "DELETE",
    }),
  });
  if (!ok) {
    if (data?.error === "forbidden") gotoLogin();
    else window.alert(data?.message || data?.error || "批量删除失败");
    return;
  }
  window.alert(
    `已删除 ${data.deleted ?? 0} 条。${
      data.failed_count ? `（${data.failed_count} 条未能删除）` : ""
    }`,
  );
  selectedQuoteId = null;
  selectedRowEl = null;
  lastBundle = null;
  hideQuoteApprovalPanel();
  els.detailPlaceholder.hidden = false;
  els.detailWorkspace.hidden = true;
  page = 1;
  await loadDashboardStats();
  await loadList();
});

els.btnApplyFilters.addEventListener("click", () => {
  page = 1;
  loadList();
});

els.btnClearFilters.addEventListener("click", () => {
  els.filterSearch.value = "";
  els.filterDateFrom.value = "";
  els.filterDateTo.value = "";
  els.filterVerMin.value = "";
  els.filterStatus.value = "";
  if (els.filterSalesUser) els.filterSalesUser.value = "";
  page = 1;
  loadList();
});

els.filterSearch.addEventListener("keydown", (ev) => {
  if (ev.key === "Enter") {
    ev.preventDefault();
    page = 1;
    loadList();
  }
});

els.filterSearch.addEventListener("input", () => {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => {
    page = 1;
    loadList();
  }, 380);
});

els.btnPrev.addEventListener("click", () => {
  if (page > 1) {
    page -= 1;
    loadList();
  }
});

els.btnNext.addEventListener("click", () => {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (page < pages) {
    page += 1;
    loadList();
  }
});

els.btnCopyUid.addEventListener("click", async () => {
  const uid = String(lastBundle?.meta?.quote_uid || selectedQuoteId || "");
  if (!uid) return;
  try {
    await navigator.clipboard.writeText(uid);
  } catch {
    window.prompt("Copy quote UID", uid);
  }
});

els.btnExportJson.addEventListener("click", () => {
  if (!lastBundle) {
    showAdminToast("请先选择一条归档记录", "err");
    return;
  }
  downloadMaterialBomCsv(lastBundle);
});

els.btnOpenSheet.addEventListener("click", async () => {
  const url = await ensureFirstSheetUrl();
  if (url) {
    window.open(url, "_blank", "noopener");
    return;
  }
  window.alert("No downloadable original sheet found for this quote.");
});

els.btnDeleteQuote.addEventListener("click", async (ev) => {
  ev.stopPropagation();
  const uid = selectedQuoteId;
  if (!uid) return;
  const title = els.detailTitle.textContent || uid;
  const confirmed = window.confirm(
    `Delete archived quote ${title}?\nQuote UID: ${uid}\nThis cannot be undone.`,
  );
  if (!confirmed) return;
  const delRes = await apiJson(`/admin-api/quotes/${encodeURIComponent(uid)}`, { method: "DELETE" });
  if (!delRes.ok) {
    if (delRes.data?.error === "forbidden") gotoLogin();
    else window.alert(delRes.data?.message || "删除失败");
    return;
  }
  selectedQuoteId = null;
  selectedRowEl = null;
  lastBundle = null;
  hideQuoteApprovalPanel();
  els.detailWorkspace.hidden = true;
  els.detailPlaceholder.hidden = false;
  removeQuoteFromWatch(uid);
  await loadDashboardStats();
  await loadList();
});

loadSimpleModeCheckbox();
syncSimpleModeClass();

syncBomEditToolbar();

(async () => {
  const ok = await guardAdminRoleOrRedirect();
  if (!ok) return;
  loadPendingWatchState();
  renderPendingWatchPanel();
  updateNewQuotesAlertUi();
  await loadDashboardStats();
  await loadList();
  if (lastSeenTime) startListPoll();
})();

