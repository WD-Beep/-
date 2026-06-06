/** 与 server.py DEFAULT_HTTP_PORT 对齐；管理后台默认 8080 */
const FRONT_HTTP_PORT = "8776";

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

async function apiJson(url, opts = {}) {
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
  return { ok: res.ok, status: res.status, data };
}

function gotoLogin() {
  window.location.replace("/admin/login");
}

function normalizeEntryStatus(item) {
  const raw = String(item?.status || "").trim().toLowerCase();
  if (raw === "pending" || raw === "待补充" || raw === "待补价" || raw === "待确认") {
    return "pending";
  }
  if (item?.is_active) {
    return "active";
  }
  return "inactive";
}

function statusBadgeHtml(item) {
  const st = normalizeEntryStatus(item);
  if (st === "pending") {
    return '<span class="badge badge-pending">待补充</span>';
  }
  if (st === "active") {
    return '<span class="badge badge-ok">启用</span>';
  }
  return '<span class="badge badge-warn">停用</span>';
}

function markerLabel(marker) {
  const m = String(marker || "").trim();
  if (m === "AUTO_QUOTE_SYNC") return "报价候选";
  if (m === "AUTO_PENDING_PRICE") return "待补价";
  if (m === "AUTO_PRICE_CONFLICT") return "价格冲突";
  return m;
}

function sourceTypeLabel(sourceType) {
  const st = String(sourceType || "").trim();
  const map = {
    missing_price: "缺价/新材料",
    ai_estimate: "AI估算",
    admin_correction: "管理员修正",
    price_conflict: "价格冲突",
    low_confidence: "低置信度",
    smart_lookup_miss: "智能查价",
  };
  return map[st] || st || "—";
}

function markerTagHtml(marker) {
  const raw = String(marker || "").trim();
  if (!raw) {
    return '<span class="muted">—</span>';
  }
  const label = markerLabel(raw);
  let cls = "marker-tag";
  if (raw === "AUTO_QUOTE_SYNC") cls += " marker-tag-auto-sync";
  else if (raw === "AUTO_PENDING_PRICE") cls += " marker-tag-auto-pending";
  else if (raw === "AUTO_PRICE_CONFLICT") cls += " marker-tag-auto-conflict";
  return `<span class="${cls}" title="${escapeHtml(raw)}">${escapeHtml(label)}</span>`;
}

function reviewHintTagHtml(hint) {
  const raw = String(hint || "").trim();
  if (raw === "fixable") {
    return '<span class="review-hint-tag hint-fixable" title="建议修正后入库">可修正</span>';
  }
  if (raw === "exclude_suggest") {
    return '<span class="review-hint-tag hint-exclude" title="建议标记排除">建议排除</span>';
  }
  return "";
}

function exceptionReasonTagHtml(reason, hint) {
  const text = String(reason || "待人工确认").trim() || "待人工确认";
  const cls =
    String(hint || "") === "exclude_suggest" ? "exception-reason-tag reason-exclude" : "exception-reason-tag";
  return `<span class="${cls}" title="${escapeHtml(text)}">${escapeHtml(text)}</span>${reviewHintTagHtml(hint)}`;
}

const els = {
  statTotal: document.getElementById("priceStatTotal"),
  statActive: document.getElementById("priceStatActive"),
  statPending: document.getElementById("priceStatPending"),
  statLatest: document.getElementById("priceStatLatest"),
  exceptionCount: document.getElementById("priceExceptionCount"),
  exceptionEntry: document.getElementById("priceExceptionEntry"),
  exceptionWorkbench: document.getElementById("priceExceptionWorkbench"),
  excStatOpen: document.getElementById("excStatOpen"),
  excStatFixable: document.getElementById("excStatFixable"),
  excStatExcludeSuggest: document.getElementById("excStatExcludeSuggest"),
  excStatAutoDropped: document.getElementById("excStatAutoDropped"),
  btnHandleExceptions: document.getElementById("btnHandleExceptions"),
  btnLeaveExceptions: document.getElementById("btnLeaveExceptions"),
  btnPriceBatchDelete: document.getElementById("btnPriceBatchDelete"),
  btnPriceBatchCancel: document.getElementById("btnPriceBatchCancel"),
  btnPriceBatchApprove: document.getElementById("btnPriceBatchApprove"),
  btnPriceBatchReject: document.getElementById("btnPriceBatchReject"),
  priceTableHeadRow: document.getElementById("priceTableHeadRow"),
  pricePaneList: document.querySelector(".price-pane-list"),
  priceSelectAll: document.getElementById("priceSelectAll"),
  priceSearch: document.getElementById("priceSearch"),
  priceStatus: document.getElementById("priceStatus"),
  btnPriceApply: document.getElementById("btnPriceApply"),
  btnPriceReset: document.getElementById("btnPriceReset"),
  btnPriceRefresh: document.getElementById("btnPriceRefresh"),
  priceImportFile: document.getElementById("priceImportFile"),
  btnPriceImport: document.getElementById("btnPriceImport"),
  btnPriceExport: document.getElementById("btnPriceExport"),
  btnPricePrev: document.getElementById("btnPricePrev"),
  btnPriceNext: document.getElementById("btnPriceNext"),
  btnPriceLogout: document.getElementById("btnPriceLogout"),
  priceListBody: document.getElementById("priceListBody"),
  priceListEmpty: document.getElementById("priceListEmpty"),
  pricePageLabel: document.getElementById("pricePageLabel"),
  priceEditorTitle: document.getElementById("priceEditorTitle"),
  btnPriceNew: document.getElementById("btnPriceNew"),
  priceForm: document.getElementById("priceForm"),
  priceRowId: document.getElementById("priceRowId"),
  priceName: document.getElementById("priceName"),
  priceSpec: document.getElementById("priceSpec"),
  priceValue: document.getElementById("priceValue"),
  priceMarker: document.getElementById("priceMarker"),
  priceFormStatus: document.getElementById("priceFormStatus"),
  priceUpdatedBy: document.getElementById("priceUpdatedBy"),
  priceNote: document.getElementById("priceNote"),
  btnPriceClear: document.getElementById("btnPriceClear"),
  btnPriceDelete: document.getElementById("btnPriceDelete"),
  btnPriceSave: document.getElementById("btnPriceSave"),
  btnPriceApprove: document.getElementById("btnPriceApprove"),
  btnPriceExclude: document.getElementById("btnPriceExclude"),
  priceSaveHint: document.getElementById("priceSaveHint"),
};

let page = 1;
const pageSize = 25;
let total = 0;
let selectedRowId = "";
let selectedIsException = false;
let exceptionMode = false;
let searchTimer = null;

function clearPriceRowChecks() {
  els.priceListBody.querySelectorAll(".price-row-check").forEach((cb) => {
    cb.checked = false;
  });
  if (els.priceSelectAll) {
    els.priceSelectAll.checked = false;
    els.priceSelectAll.indeterminate = false;
  }
  syncBatchDeleteButtonState();
}

function syncBatchDeleteButtonState() {
  const checked = els.priceListBody.querySelectorAll(".price-row-check:checked").length;
  const all = els.priceListBody.querySelectorAll(".price-row-check");
  all.forEach((cb) => {
    cb.disabled = false;
    cb.title = exceptionMode ? "选择候选" : "选择要删除的数据";
  });
  if (els.btnPriceBatchDelete) {
    els.btnPriceBatchDelete.disabled = checked <= 0;
    els.btnPriceBatchDelete.hidden = exceptionMode;
    els.btnPriceBatchDelete.textContent = checked > 0 ? `删除 (${checked})` : "删除";
  }
  if (els.btnPriceBatchApprove) {
    els.btnPriceBatchApprove.disabled = checked <= 0;
    els.btnPriceBatchApprove.textContent = checked > 0 ? `批量确认 (${checked})` : "批量确认";
  }
  if (els.btnPriceBatchReject) {
    els.btnPriceBatchReject.disabled = checked <= 0;
    els.btnPriceBatchReject.textContent = checked > 0 ? `批量驳回 (${checked})` : "批量驳回";
  }
  if (els.priceSelectAll) {
    els.priceSelectAll.disabled = false;
    els.priceSelectAll.title = "全选本页";
    els.priceSelectAll.checked = all.length > 0 && checked === all.length;
    els.priceSelectAll.indeterminate = checked > 0 && checked < all.length;
  }
}

function getCheckedRowItems() {
  const out = [];
  els.priceListBody.querySelectorAll(".price-row-check:checked").forEach((cb) => {
    const tr = cb.closest("tr");
    if (!tr || !tr._priceItem) {
      return;
    }
    out.push(tr._priceItem);
  });
  return out;
}

function enterExceptionMode() {
  exceptionMode = true;
  els.priceStatus.value = "pending";
  page = 1;
  syncExceptionModeUi();
  renderTableHead();
  return loadList(false);
}

function syncExceptionModeUi() {
  if (els.exceptionWorkbench) {
    els.exceptionWorkbench.hidden = !exceptionMode;
  }
  if (els.exceptionEntry) {
    els.exceptionEntry.hidden = exceptionMode;
  }
  if (els.pricePaneList) {
    els.pricePaneList.classList.toggle("exception-mode", exceptionMode);
  }
  if (els.btnHandleExceptions) {
    els.btnHandleExceptions.textContent = exceptionMode ? "整理台已打开" : "打开整理台";
    els.btnHandleExceptions.disabled = exceptionMode;
  }
}

async function leaveExceptionMode() {
  exceptionMode = false;
  els.priceStatus.value = "";
  page = 1;
  resetForm();
  syncExceptionModeUi();
  renderTableHead();
  await loadList(false);
}

async function guardAdminRoleOrRedirect() {
  const { ok, data } = await apiJson("/admin-api/session");
  if (!ok || !data.authenticated || data.role !== "admin") {
    gotoLogin();
    return false;
  }
  return true;
}

function syncFormActionButtons() {
  if (selectedIsException) {
    if (els.btnPriceSave) els.btnPriceSave.hidden = true;
    if (els.btnPriceApprove) {
      els.btnPriceApprove.hidden = false;
      els.btnPriceApprove.disabled = !selectedRowId;
    }
    if (els.btnPriceExclude) {
      els.btnPriceExclude.hidden = false;
      els.btnPriceExclude.disabled = !selectedRowId;
    }
    return;
  }
  if (els.btnPriceSave) els.btnPriceSave.hidden = false;
  if (els.btnPriceApprove) {
    els.btnPriceApprove.hidden = true;
    els.btnPriceApprove.disabled = true;
  }
  if (els.btnPriceExclude) {
    els.btnPriceExclude.hidden = true;
    els.btnPriceExclude.disabled = true;
  }
}

function syncDeleteButtonState() {
  if (els.btnPriceDelete) {
    els.btnPriceDelete.disabled = !selectedRowId;
  }
  syncFormActionButtons();
}

function renderTableHead() {
  if (!els.priceTableHeadRow) return;
  if (exceptionMode) {
    els.priceTableHeadRow.innerHTML = `
      <th class="col-select">
        <input type="checkbox" id="priceSelectAll" title="全选本页" aria-label="全选本页" />
      </th>
      <th>材料名称</th>
      <th>规格</th>
      <th>原价</th>
      <th>新价</th>
      <th>来源</th>
      <th class="col-reason">原因</th>
      <th>状态</th>
      <th>更新时间</th>
      <th class="col-actions col-actions-wide">操作</th>
    `;
  } else {
    els.priceTableHeadRow.innerHTML = `
      <th class="col-select">
        <input type="checkbox" id="priceSelectAll" title="全选本页" aria-label="全选本页" />
      </th>
      <th>材料名称</th>
      <th>规格</th>
      <th>单价</th>
      <th>标记</th>
      <th>状态</th>
      <th>更新时间</th>
    `;
  }
  els.priceSelectAll = document.getElementById("priceSelectAll");
  if (els.priceSelectAll) {
    els.priceSelectAll.addEventListener("change", () => {
      const checked = Boolean(els.priceSelectAll.checked);
      els.priceListBody.querySelectorAll(".price-row-check").forEach((cb) => {
        cb.checked = checked;
      });
      syncBatchDeleteButtonState();
    });
  }
}

function resetForm() {
  selectedRowId = "";
  selectedIsException = false;
  syncDeleteButtonState();
  els.priceEditorTitle.textContent = "新增价格条目";
  els.priceRowId.value = "";
  els.priceName.value = "";
  els.priceSpec.value = "";
  els.priceValue.value = "";
  els.priceMarker.value = "";
  els.priceFormStatus.value = "active";
  els.priceUpdatedBy.value = "admin";
  els.priceNote.value = "";
  els.priceSaveHint.textContent = "保存后会自动重载价格库，新报价立即使用最新价格。";
  els.priceListBody.querySelectorAll("tr").forEach((tr) => tr.classList.remove("row-selected"));
  if (els.priceSelectAll) {
    els.priceSelectAll.checked = false;
    els.priceSelectAll.indeterminate = false;
  }
  syncBatchDeleteButtonState();
}

function fillForm(item) {
  selectedRowId = String(item.exception_id || item.row_id || "");
  selectedIsException = item?.is_exception === true;
  syncDeleteButtonState();
  els.priceEditorTitle.textContent = selectedIsException ? "修正后入库" : "编辑价格条目";
  els.priceRowId.value = selectedRowId;
  els.priceName.value = String(item.material_name || item.name || "");
  els.priceSpec.value = String(item.spec || "");
  els.priceValue.value = String(item.new_price || item.price || "");
  els.priceMarker.value = String(item.marker || "");
  els.priceFormStatus.value = normalizeEntryStatus(item);
  els.priceUpdatedBy.value = String(item.updated_by || "admin");
  els.priceNote.value = String(item.note || "");
  if (selectedIsException) {
    const reason = String(item.exception_reason || "").trim();
    els.priceSaveHint.textContent = reason
      ? `异常原因：${reason}。请修正字段后点击「修正后入库」，或标记排除。`
      : "请修正材料信息后点击「修正后入库」，明显非材料可「标记排除」。";
  } else if (normalizeEntryStatus(item) === "pending") {
    els.priceSaveHint.textContent = "请补齐或修正单价，确认无误后保存。";
  } else {
    els.priceSaveHint.textContent = "保存后会自动重载价格库，新报价立即使用最新价格。";
  }
}

function buildListUrl() {
  const qs = new URLSearchParams();
  qs.set("page", String(page));
  qs.set("page_size", String(pageSize));
  const q = els.priceSearch.value.trim();
  const st = els.priceStatus.value.trim();
  if (q) qs.set("q", q);
  if (exceptionMode) {
    qs.set("status", "open");
    return `/admin-api/price-exceptions?${qs.toString()}`;
  }
  if (st) qs.set("status", st);
  return `/admin-api/prices?${qs.toString()}`;
}

function renderKbSourceBanner(data) {
  const banner = document.getElementById("priceKbSourceBanner");
  if (!banner) return;
  const official = String(data.official_kb_path || "").trim();
  const exists = Boolean(data.official_kb_exists);
  const review = String(data.review_data_dir || "").trim();
  const hidden = Number(data.hidden_test_pollution || 0);
  const sugg = Number(data.quote_sync_suggestions_pending || 0);
  const autoInserted = Number(data.auto_inserted_total || 0);
  const pendingReview = Number(data.pending_review_count ?? data.open_exceptions ?? 0);
  const ignored = Number(data.ignored_count ?? data.auto_dropped_total ?? 0);
  const parts = [];
  if (official) {
    parts.push(
      exists
        ? `正式价格库：${official}`
        : `正式价格库缺失：${official}`
    );
  }
  if (review) parts.push(`待审核缓存目录：${review}`);
  if (autoInserted > 0) parts.push(`已自动加入知识库 ${autoInserted} 条`);
  if (pendingReview > 0) parts.push(`待人工确认 ${pendingReview} 条`);
  if (ignored > 0) parts.push(`已忽略非材料数据 ${ignored} 条`);
  if (sugg > 0) parts.push(`待写入正式库建议 ${sugg} 条`);
  if (hidden > 0) parts.push(`已隐藏测试污染 ${hidden} 条（未删除，见清理清单）`);
  if (!parts.length) {
    banner.hidden = true;
    banner.textContent = "";
    return;
  }
  banner.hidden = false;
  banner.textContent = parts.join(" · ");
}

async function loadStats() {
  const { ok, data } = await apiJson("/admin-api/prices/stats");
  if (!ok) {
    if (data?.error === "forbidden") gotoLogin();
    return;
  }
  renderKbSourceBanner(data);
  els.statTotal.textContent = String(data.total_entries ?? "-");
  els.statActive.textContent = String(data.active_entries ?? "-");
  if (els.statPending) {
    els.statPending.textContent = String(data.pending_entries ?? "-");
  }
  const pendingReview = Number(data.pending_review_count ?? data.open_exceptions ?? 0);
  if (els.exceptionCount) {
    els.exceptionCount.textContent = String(pendingReview);
  }
  if (els.excStatOpen) els.excStatOpen.textContent = String(data.open_exceptions ?? "0");
  if (els.excStatFixable) els.excStatFixable.textContent = String(data.fixable_exceptions ?? "0");
  if (els.excStatExcludeSuggest) {
    els.excStatExcludeSuggest.textContent = String(data.exclude_suggest_exceptions ?? "0");
  }
  if (els.excStatAutoDropped) {
    els.excStatAutoDropped.textContent = String(data.auto_dropped_total ?? "0");
  }
  els.statLatest.textContent = data.latest_updated_at ? String(data.latest_updated_at) : "-";
}

async function loadList(preserveSelection = true) {
  const { ok, data } = await apiJson(buildListUrl());
  if (!ok) {
    if (data?.error === "forbidden") gotoLogin();
    return;
  }
  total = Number(data.total) || 0;
  const items = Array.isArray(data.items) ? data.items : [];
  els.priceListBody.innerHTML = "";
  els.priceListEmpty.hidden = items.length > 0;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  els.pricePageLabel.textContent = `Page ${page} / ${pages} / ${total} rows`;
  els.btnPricePrev.disabled = page <= 1;
  els.btnPriceNext.disabled = page >= pages;

  let matchedSelection = false;
  for (const item of items) {
    const tr = document.createElement("tr");
    tr._priceItem = item;
    const rowId = String(item.exception_id || item.row_id || "");
    const isPending = normalizeEntryStatus(item) === "pending";
    if (preserveSelection && selectedRowId && rowId === selectedRowId) {
      tr.classList.add("row-selected");
      matchedSelection = true;
    }
    if (isPending) {
      tr.classList.add("row-pending");
    }
    const reasonCell = exceptionMode
      ? `<td class="col-reason">${exceptionReasonTagHtml(item.exception_reason, item.review_hint)}</td>`
      : "";
    const displayName = String(item.material_name || item.name || "");
    const displayPrice = String(item.new_price || item.price || "—") || "—";
    const oldPrice = String(item.old_price || "—") || "—";
    const sourceCell = exceptionMode
      ? `<td title="${escapeHtml(String(item.source_type || ""))}">${escapeHtml(sourceTypeLabel(item.source_type))}</td>`
      : "";
    const actionHtml = exceptionMode
      ? `
        <button type="button" class="btn btn-primary btn-sm btn-price-row-review" data-row-id="${escapeHtml(rowId)}">处理</button>
        <button type="button" class="btn btn-ghost btn-sm btn-price-row-exclude" data-row-id="${escapeHtml(rowId)}">排除</button>
      `
      : "";
    const actionCell = exceptionMode
      ? `<td class="col-actions col-actions-wide">${actionHtml}</td>`
      : "";
    tr.innerHTML = `
      <td class="col-select">
        <input type="checkbox" class="price-row-check" data-row-id="${escapeHtml(rowId)}" aria-label="选择条目" />
      </td>
      <td>${escapeHtml(displayName)}</td>
      <td>${escapeHtml(String(item.spec || ""))}</td>
      ${exceptionMode ? `<td>${escapeHtml(oldPrice)}</td>` : ""}
      <td>${escapeHtml(displayPrice)}</td>
      ${sourceCell}
      ${reasonCell}
      ${exceptionMode ? "" : `<td>${markerTagHtml(item.marker)}</td>`}
      <td>${statusBadgeHtml(item)}</td>
      <td>${escapeHtml(String(item.updated_at || ""))}</td>
      ${actionCell}
    `;
    tr.addEventListener("click", (ev) => {
      if (
        ev.target.closest(".btn-price-row-exclude") ||
        ev.target.closest(".btn-price-row-review") ||
        ev.target.closest(".price-row-check")
      ) {
        return;
      }
      els.priceListBody.querySelectorAll("tr").forEach((x) => x.classList.remove("row-selected"));
      tr.classList.add("row-selected");
      fillForm(item);
    });
    const reviewBtn = tr.querySelector(".btn-price-row-review");
    if (reviewBtn) {
      reviewBtn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        els.priceListBody.querySelectorAll("tr").forEach((x) => x.classList.remove("row-selected"));
        tr.classList.add("row-selected");
        fillForm(item);
      });
    }
    const excludeBtn = tr.querySelector(".btn-price-row-exclude");
    if (excludeBtn) {
      excludeBtn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        els.priceListBody.querySelectorAll("tr").forEach((x) => x.classList.remove("row-selected"));
        tr.classList.add("row-selected");
        fillForm(item);
        excludeSelectedPrice();
      });
    }
    const rowCheck = tr.querySelector(".price-row-check");
    if (rowCheck) {
      rowCheck.addEventListener("click", (ev) => ev.stopPropagation());
      rowCheck.addEventListener("change", syncBatchDeleteButtonState);
    }
    els.priceListBody.appendChild(tr);
  }
  syncBatchDeleteButtonState();
  if (!matchedSelection && !preserveSelection) {
    resetForm();
  }
}

async function deleteSelectedPrice() {
  const rowId = String(selectedRowId || els.priceRowId.value || "").trim();
  if (!rowId) {
    window.alert("请先在列表中选择要删除的价格条目。");
    return;
  }
  const name = els.priceName.value.trim() || "（未命名）";
  const spec = els.priceSpec.value.trim() || "-";
  const confirmText = selectedIsException
    ? `确认删除这条异常待处理数据？\n\n材料：${name}\n规格：${spec}\n\n不会写入正式价格库。`
    : `确认从价格库删除以下条目？\n\n材料：${name}\n规格：${spec}\n\n删除后不可恢复（建议先导出备份）。`;
  const okay = window.confirm(confirmText);
  if (!okay) {
    return;
  }

  const updatedBy = els.priceUpdatedBy.value.trim() || "admin";
  const rowDeleteBtn = els.priceListBody.querySelector(`button[data-row-id="${CSS.escape(rowId)}"]`);
  const selectedTr = rowDeleteBtn ? rowDeleteBtn.closest("tr") : null;
  let optimisticRemoved = false;
  if (selectedTr) {
    selectedTr.remove();
    optimisticRemoved = true;
    const leftRows = els.priceListBody.querySelectorAll("tr").length;
    els.priceListEmpty.hidden = leftRows > 0;
  }
  selectedRowId = "";
  syncDeleteButtonState();

  if (els.btnPriceDelete) {
    els.btnPriceDelete.disabled = true;
  }
  els.priceSaveHint.textContent = "正在删除…";

  try {
    let ok;
    let data;
    if (selectedIsException) {
      ({ ok, data } = await apiJson("/admin-api/price-exceptions/delete", {
        method: "POST",
        body: JSON.stringify({
          exception_id: rowId,
          row_id: rowId,
          updated_by: updatedBy,
        }),
      }));
    } else {
      ({ ok, data } = await apiJson("/admin-api/prices/delete", {
        method: "POST",
        body: JSON.stringify({
          row_id: rowId,
          name: els.priceName.value.trim(),
          spec: els.priceSpec.value.trim() || "-",
          price: els.priceValue.value.trim(),
          updated_by: updatedBy,
        }),
      }));

      if (!ok && data?.error === "not found") {
        ({ ok, data } = await apiJson(
          `/admin-api/prices/${encodeURIComponent(rowId)}?updated_by=${encodeURIComponent(updatedBy)}`,
          { method: "DELETE" },
        ));
      }
    }

    if (!ok) {
      if (data?.error === "forbidden") {
        gotoLogin();
        return;
      }
      const hint =
        data?.error === "not found"
          ? "删除接口未生效，请重启 python server.py 后刷新本页再试。"
          : "";
      window.alert([data?.message || data?.error || "删除失败", hint].filter(Boolean).join("\n"));
      els.priceSaveHint.textContent = "删除失败。";
      if (optimisticRemoved) {
        await loadList(true);
      }
      syncDeleteButtonState();
      return;
    }

    const deletedName = String(data?.deleted?.name || name);
    els.priceSaveHint.textContent = `已删除：${deletedName}`;
    resetForm();
    page = 1;
    await Promise.all([loadStats(), loadList(false)]);
    window.alert(`已删除：${deletedName}`);
  } finally {
    syncDeleteButtonState();
  }
}

async function batchDeleteSelected() {
  const items = getCheckedRowItems();
  if (!items.length) {
    window.alert("请先勾选要删除的条目。");
    return;
  }
  const count = items.length;
  const confirmText = exceptionMode
    ? `确认删除选中的 ${count} 条异常待处理数据？\n\n不会写入正式价格库。`
    : `确认从价格库删除选中的 ${count} 条？\n\n删除后不可恢复（建议先导出备份）。`;
  if (!window.confirm(confirmText)) {
    return;
  }

  const updatedBy = els.priceUpdatedBy.value.trim() || "admin";
  if (els.btnPriceBatchDelete) {
    els.btnPriceBatchDelete.disabled = true;
  }
  els.priceSaveHint.textContent = `正在批量删除 ${count} 条…`;

  try {
    if (exceptionMode) {
      const ids = items.map((item) => String(item.exception_id || item.row_id || "")).filter(Boolean);
      const { ok, data } = await apiJson("/admin-api/price-exceptions/delete-batch", {
        method: "POST",
        body: JSON.stringify({
          exception_ids: ids,
          updated_by: updatedBy,
        }),
      });
      if (!ok) {
        if (data?.error === "forbidden") {
          gotoLogin();
          return;
        }
        window.alert(data?.message || data?.error || "批量删除失败");
        els.priceSaveHint.textContent = "批量删除失败。";
        await loadList(true);
        return;
      }
      const deletedCount = Number(data.deleted_count) || ids.length;
      els.priceSaveHint.textContent = `已批量删除 ${deletedCount} 条异常数据`;
      resetForm();
      clearPriceRowChecks();
      page = 1;
      await Promise.all([loadStats(), loadList(false)]);
      window.alert(`已删除 ${deletedCount} 条异常数据`);
      return;
    }

    let deletedCount = 0;
    const failed = [];
    for (const item of items) {
      const rowId = String(item.row_id || "").trim();
      if (!rowId) {
        continue;
      }
      const { ok, data } = await apiJson("/admin-api/prices/delete", {
        method: "POST",
        body: JSON.stringify({
          row_id: rowId,
          name: String(item.name || "").trim(),
          spec: String(item.spec || "").trim() || "-",
          price: String(item.price || "").trim(),
          updated_by: updatedBy,
        }),
      });
      if (ok) {
        deletedCount += 1;
      } else {
        failed.push(String(item.name || rowId));
      }
    }
    if (failed.length) {
      window.alert(`已删除 ${deletedCount} 条，失败 ${failed.length} 条：\n${failed.slice(0, 5).join("\n")}`);
    } else {
      window.alert(`已删除 ${deletedCount} 条价格条目`);
    }
    els.priceSaveHint.textContent = `已批量删除 ${deletedCount} 条`;
    resetForm();
    clearPriceRowChecks();
    page = 1;
    await Promise.all([loadStats(), loadList(false)]);
  } finally {
    syncBatchDeleteButtonState();
  }
}

async function batchApproveSelected() {
  const items = getCheckedRowItems();
  if (!items.length) {
    window.alert("请先勾选待学习候选。");
    return;
  }
  const missingPrice = items.filter((x) => !String(x.new_price || x.price || "").trim());
  if (missingPrice.length) {
    window.alert("所选候选中有缺少单价的条目，请先逐条补齐后再批量确认。");
    return;
  }
  if (!window.confirm(`确认将选中的 ${items.length} 条候选写入正式价格库？`)) {
    return;
  }
  const ids = items.map((x) => String(x.exception_id || x.candidate_id || x.row_id || "")).filter(Boolean);
  if (els.btnPriceBatchApprove) els.btnPriceBatchApprove.disabled = true;
  els.priceSaveHint.textContent = "正在批量确认入库…";
  const { ok, data } = await apiJson("/admin-api/price-exceptions/approve-batch", {
    method: "POST",
    body: JSON.stringify({
      exception_ids: ids,
      updated_by: els.priceUpdatedBy.value.trim() || "admin",
    }),
  });
  if (els.btnPriceBatchApprove) els.btnPriceBatchApprove.disabled = false;
  if (!ok) {
    if (data?.error === "forbidden") {
      gotoLogin();
      return;
    }
    window.alert(data?.message || data?.error || "批量确认失败");
    els.priceSaveHint.textContent = "批量确认失败。";
    await loadList(false);
    return;
  }
  const approved = Number(data.approved_count || 0);
  const errors = Array.isArray(data.errors) ? data.errors : [];
  els.priceSaveHint.textContent = `已确认入库 ${approved} 条${errors.length ? `，失败 ${errors.length} 条` : ""}`;
  resetForm();
  clearPriceRowChecks();
  await Promise.all([loadStats(), loadList(false)]);
  if (errors.length) {
    window.alert(
      `成功 ${approved} 条，失败 ${errors.length} 条：\n${errors
        .slice(0, 5)
        .map((e) => `${e.exception_id}: ${e.message}`)
        .join("\n")}`,
    );
  }
}

async function batchRejectSelected() {
  const items = getCheckedRowItems();
  if (!items.length) {
    window.alert("请先勾选待学习候选。");
    return;
  }
  const reason = window.prompt(`确认驳回选中的 ${items.length} 条候选？\n\n可填写驳回原因（可留空）：`, "批量驳回");
  if (reason === null) {
    return;
  }
  const ids = items.map((x) => String(x.exception_id || x.candidate_id || x.row_id || "")).filter(Boolean);
  if (els.btnPriceBatchReject) els.btnPriceBatchReject.disabled = true;
  els.priceSaveHint.textContent = "正在批量驳回…";
  const { ok, data } = await apiJson("/admin-api/price-exceptions/reject-batch", {
    method: "POST",
    body: JSON.stringify({
      exception_ids: ids,
      reject_reason: String(reason || "").trim(),
      updated_by: els.priceUpdatedBy.value.trim() || "admin",
    }),
  });
  if (els.btnPriceBatchReject) els.btnPriceBatchReject.disabled = false;
  if (!ok) {
    if (data?.error === "forbidden") {
      gotoLogin();
      return;
    }
    window.alert(data?.message || data?.error || "批量驳回失败");
    els.priceSaveHint.textContent = "批量驳回失败。";
    return;
  }
  els.priceSaveHint.textContent = `已驳回 ${Number(data.rejected_count || ids.length)} 条候选`;
  resetForm();
  clearPriceRowChecks();
  await Promise.all([loadStats(), loadList(false)]);
}

async function savePrice(ev) {
  ev.preventDefault();
  if (selectedIsException) {
    window.alert("当前选中的是异常待处理数据，请使用「修正后入库」。");
    return;
  }
  const payload = {
    row_id: els.priceRowId.value.trim(),
    name: els.priceName.value.trim(),
    spec: els.priceSpec.value.trim(),
    price: els.priceValue.value.trim(),
    marker: els.priceMarker.value.trim(),
    status: els.priceFormStatus.value,
    updated_by: els.priceUpdatedBy.value.trim() || "admin",
    note: els.priceNote.value.trim(),
  };
  if (!payload.name) {
    window.alert("材料名称不能为空。");
    return;
  }
  if (payload.status !== "pending" && !payload.price) {
    window.alert("单价不能为空；若暂无单价请选择「待补充」。");
    return;
  }
  els.btnPriceSave.disabled = true;
  els.priceSaveHint.textContent = "正在保存并重载价格库...";
  const { ok, data } = await apiJson("/admin-api/prices", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  els.btnPriceSave.disabled = false;
  if (!ok) {
    if (data?.error === "forbidden") {
      gotoLogin();
      return;
    }
    window.alert(data?.message || data?.error || "保存失败");
    els.priceSaveHint.textContent = "保存失败，请检查输入后重试。";
    return;
  }
  els.priceSaveHint.textContent = "保存成功，价格库已自动重载。";
  selectedRowId = String(data.entry?.row_id || payload.row_id || "");
  if (data.entry) {
    fillForm(data.entry);
  }
  await loadStats();
  await loadList(true);
}

async function approveSelectedPrice() {
  const rowId = els.priceRowId.value.trim();
  if (!rowId) {
    window.alert("请先选择一条待处理数据。");
    return;
  }
  const price = els.priceValue.value.trim();
  if (!price) {
    window.alert("修正后入库前，请先补齐单价。");
    els.priceValue.focus();
    return;
  }
  const payload = {
    exception_id: rowId,
    name: els.priceName.value.trim(),
    spec: els.priceSpec.value.trim(),
    price,
    marker: els.priceMarker.value.trim(),
    status: "active",
    updated_by: els.priceUpdatedBy.value.trim() || "admin",
    note: els.priceNote.value.trim(),
  };
  if (!payload.name) {
    window.alert("材料名称不能为空。");
    return;
  }
  const okay = window.confirm(`确认将「${payload.name}」修正为启用价格并加入报价知识库？`);
  if (!okay) return;
  els.btnPriceApprove.disabled = true;
  els.priceSaveHint.textContent = "正在入库，已先从待处理列表移除...";
  const optimisticRow = els.priceListBody.querySelector(`tr.row-selected`);
  if (optimisticRow) {
    optimisticRow.remove();
  }
  if (!els.priceListBody.children.length) {
    els.priceListEmpty.hidden = false;
  }
  const { ok, data } = await apiJson("/admin-api/price-exceptions/approve", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!ok) {
    if (data?.error === "forbidden") {
      gotoLogin();
      return;
    }
    window.alert(data?.message || data?.error || "入库失败");
    els.priceSaveHint.textContent = "入库失败，请检查单价和状态。";
    syncDeleteButtonState();
    return;
  }
  els.priceSaveHint.textContent = "已修正并启用，报价知识库已自动重载。";
  selectedRowId = "";
  selectedIsException = false;
  resetForm();
  await loadStats();
  await loadList(false);
}

async function excludeSelectedPrice() {
  const rowId = els.priceRowId.value.trim();
  if (!rowId || !selectedIsException) {
    window.alert("请先选择一条待整理数据。");
    return;
  }
  const name = els.priceName.value.trim() || "（未命名）";
  const okay = window.confirm(
    `确认将「${name}」标记为排除？\n\n不会写入正式价格库，将记入排除日志并从待整理队列移除。`,
  );
  if (!okay) return;

  const updatedBy = els.priceUpdatedBy.value.trim() || "admin";
  if (els.btnPriceExclude) els.btnPriceExclude.disabled = true;
  els.priceSaveHint.textContent = "正在标记排除…";
  const { ok, data } = await apiJson("/admin-api/price-exceptions/exclude", {
    method: "POST",
    body: JSON.stringify({
      exception_id: rowId,
      row_id: rowId,
      updated_by: updatedBy,
      note: els.priceNote.value.trim(),
    }),
  });
  if (!ok) {
    if (data?.error === "forbidden") {
      gotoLogin();
      return;
    }
    window.alert(data?.message || data?.error || "标记排除失败");
    els.priceSaveHint.textContent = "标记排除失败。";
    syncDeleteButtonState();
    return;
  }
  els.priceSaveHint.textContent = `已标记排除：${name}`;
  resetForm();
  await Promise.all([loadStats(), loadList(false)]);
}

async function logout() {
  await apiJson("/admin-api/logout", { method: "POST", body: "{}" });
  gotoLogin();
}

function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("读取文件失败"));
    reader.onload = () => {
      const raw = String(reader.result || "");
      const pos = raw.indexOf("base64,");
      resolve(pos >= 0 ? raw.slice(pos + 7) : "");
    };
    reader.readAsDataURL(file);
  });
}

function parseDownloadFilename(contentDisposition, fallback) {
  const raw = String(contentDisposition || "");
  const utf8 = raw.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8 && utf8[1]) {
    try {
      return decodeURIComponent(utf8[1]);
    } catch {
      return utf8[1];
    }
  }
  const plain = raw.match(/filename="?([^";]+)"?/i);
  if (plain && plain[1]) {
    return plain[1];
  }
  return fallback;
}

function isZipXlsxBuffer(buffer) {
  if (!buffer || buffer.byteLength < 4) {
    return false;
  }
  const u8 = new Uint8Array(buffer);
  return u8[0] === 0x50 && u8[1] === 0x4b;
}

async function exportWorkbook() {
  if (!els.btnPriceExport) {
    return;
  }
  if (!window.location.port || window.location.port === FRONT_HTTP_PORT) {
    window.alert(
      "请在管理后台端口打开本页后再导出，例如 http://127.0.0.1:8080/admin/prices（不要用前台 8776）。",
    );
    return;
  }
  els.btnPriceExport.disabled = true;
  els.priceSaveHint.textContent = "正在导出知识库 Excel…";
  try {
    const updatedBy = els.priceUpdatedBy.value.trim() || "admin";
    const res = await fetch(`/admin-api/prices/export?updated_by=${encodeURIComponent(updatedBy)}`, {
      credentials: "same-origin",
    });
    if (res.status === 403) {
      gotoLogin();
      return;
    }
    const buf = await res.arrayBuffer();
    if (!res.ok) {
      let data = {};
      try {
        data = JSON.parse(new TextDecoder().decode(buf));
      } catch {
        data = {};
      }
      window.alert(data?.message || data?.error || `导出失败（HTTP ${res.status}）`);
      els.priceSaveHint.textContent = "导出失败。";
      return;
    }
    if (!isZipXlsxBuffer(buf)) {
      const preview = new TextDecoder().decode(buf.slice(0, 120)).replace(/\s+/g, " ");
      window.alert(
        `下载到的不是 Excel 文件（可能是网页 HTML）。\n请确认：\n1. 地址为 http://127.0.0.1:8080/admin/prices\n2. 已登录管理员\n3. 点击的是「导出知识库Excel」\n\n响应开头：${preview}`,
      );
      els.priceSaveHint.textContent = "导出失败：返回内容不是 xlsx。";
      return;
    }
    const rowCount = res.headers.get("X-Price-Kb-Rows") || "";
    const blob = new Blob([buf], {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    const filename = parseDownloadFilename(
      res.headers.get("Content-Disposition"),
      `price_kb_${new Date().toISOString().slice(0, 10)}.xlsx`,
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    els.priceSaveHint.textContent = rowCount
      ? `已下载 ${filename}（${rowCount} 条材料）`
      : `已下载：${filename}`;
  } catch (err) {
    window.alert(err instanceof Error ? err.message : String(err));
    els.priceSaveHint.textContent = "导出失败。";
  } finally {
    els.btnPriceExport.disabled = false;
  }
}

async function importWorkbook() {
  const file = els.priceImportFile?.files && els.priceImportFile.files[0];
  if (!file) {
    window.alert("请先选择一个 .xlsx 文件。");
    return;
  }
  const okay = window.confirm(`确认导入「${file.name}」？这会替换当前价格库，并自动备份旧文件。`);
  if (!okay) return;
  els.btnPriceImport.disabled = true;
  els.priceSaveHint.textContent = "正在导入知识库并重载价格库...";
  try {
    const contentBase64 = await readFileAsBase64(file);
    const { ok, data } = await apiJson("/admin-api/prices/import", {
      method: "POST",
      body: JSON.stringify({
        filename: file.name,
        content_base64: contentBase64,
        updated_by: els.priceUpdatedBy.value.trim() || "admin",
      }),
    });
    if (!ok) {
      if (data?.error === "forbidden") {
        gotoLogin();
        return;
      }
      window.alert(data?.message || data?.error || "导入失败");
      els.priceSaveHint.textContent = "导入失败，请检查文件格式。";
      return;
    }
    const rows = Number(data.rows || 0);
    const backup = String(data.backup_file || "").trim();
    els.priceSaveHint.textContent = `导入成功：${rows} 条可用价格。${backup ? `备份：${backup}` : ""}`;
    page = 1;
    resetForm();
    await loadStats();
    await loadList(false);
  } finally {
    els.btnPriceImport.disabled = false;
  }
}

els.priceForm.addEventListener("submit", savePrice);
els.btnPriceClear.addEventListener("click", resetForm);
if (els.btnPriceApprove) {
  els.btnPriceApprove.addEventListener("click", approveSelectedPrice);
}
if (els.btnPriceExclude) {
  els.btnPriceExclude.addEventListener("click", excludeSelectedPrice);
}
if (els.btnPriceDelete) {
  els.btnPriceDelete.addEventListener("click", deleteSelectedPrice);
}
if (els.btnPriceBatchDelete) {
  els.btnPriceBatchDelete.addEventListener("click", batchDeleteSelected);
}
if (els.btnPriceBatchApprove) {
  els.btnPriceBatchApprove.addEventListener("click", batchApproveSelected);
}
if (els.btnPriceBatchReject) {
  els.btnPriceBatchReject.addEventListener("click", batchRejectSelected);
}
els.btnPriceNew.addEventListener("click", resetForm);
els.btnPriceRefresh.addEventListener("click", async () => {
  await loadStats();
  await loadList(true);
});
els.btnPriceImport.addEventListener("click", importWorkbook);
els.btnPriceExport.addEventListener("click", exportWorkbook);
els.btnPriceApply.addEventListener("click", async () => {
  exceptionMode = false;
  syncExceptionModeUi();
  renderTableHead();
  page = 1;
  await loadList(false);
});
if (els.btnHandleExceptions) {
  els.btnHandleExceptions.addEventListener("click", async () => {
    await enterExceptionMode();
  });
}
if (els.btnLeaveExceptions) {
  els.btnLeaveExceptions.addEventListener("click", async () => {
    await leaveExceptionMode();
  });
}
els.btnPriceReset.addEventListener("click", async () => {
  exceptionMode = false;
  syncExceptionModeUi();
  renderTableHead();
  els.priceSearch.value = "";
  els.priceStatus.value = "";
  page = 1;
  await loadList(false);
});
els.btnPricePrev.addEventListener("click", async () => {
  if (page <= 1) return;
  page -= 1;
  await loadList(false);
});
els.btnPriceNext.addEventListener("click", async () => {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (page >= pages) return;
  page += 1;
  await loadList(false);
});
els.btnPriceLogout.addEventListener("click", logout);

els.priceSearch.addEventListener("keydown", (ev) => {
  if (ev.key !== "Enter") return;
  ev.preventDefault();
  page = 1;
  loadList(false);
});
els.priceSearch.addEventListener("input", () => {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => {
    page = 1;
    loadList(false);
  }, 320);
});
els.priceFormStatus.addEventListener("change", syncDeleteButtonState);

(async () => {
  const ok = await guardAdminRoleOrRedirect();
  if (!ok) return;
  resetForm();
  syncExceptionModeUi();
  renderTableHead();
  await loadStats();
  await loadList(false);
})();
