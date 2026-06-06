/* global document, window */

(function quoteSheetBootstrap() {
  const MAX_ROWS = 10;
  const STATUS_LEVELS = {
    idle: "idle",
    busy: "busy",
    success: "success",
    warn: "warn",
    error: "error",
  };

  /** 客户 PDF 页眉/签章公司名：固定为报价出具方，不随表单公司名或收款公司变化。 */
  const QUOTE_ISSUER_COMPANY_NAME = "深圳市栢博旅游用品有限公司";

  const defaults = {
    coName: QUOTE_ISSUER_COMPANY_NAME,
    coPhone: "0755-28223791",
    coAddr: "广东省深圳市龙岗区平湖街道宝能智创谷B栋A单元6A01",
  };

  const PAYEE_NOT_FOUND_MSG = "未找到该公司的收款信息，请检查公司名或联系管理员维护账户资料";
  const PAYEE_SELECT_REQUIRED_MSG = "请选择一个收款公司";
  const PAYEE_CANDIDATE_EMPTY_MSG = "未找到匹配收款公司";
  const PAYEE_LIST_LIMIT = 30;

  const payeeState = {
    selected: null,
    searching: false,
    searchToken: 0,
    candidates: [],
    activeIndex: -1,
    dropdownOpen: false,
  };
  const exportGuard = {
    inflight: false,
    preflightDialogPromise: null,
  };
  let payeeSearchTimer = null;

  function normalizePayeeCompanyName(raw) {
    return String(raw || "")
      .trim()
      .replace(/\s+/g, "");
  }

  function buildBankNamePdfText(account) {
    if (!account || typeof account !== "object") {
      return "";
    }
    return String(account.bank_name || "").trim();
  }

  function buildBankAccountPdfText(account) {
    if (!account || typeof account !== "object") {
      return "";
    }
    return String(account.bank_account || "").trim();
  }

  function buildAlipayPdfText(account) {
    if (!account || typeof account !== "object") {
      return "";
    }
    return String(account.alipay || "").trim();
  }

  function setPayeeStatus(text, level = STATUS_LEVELS.idle) {
    const node = el("qsPayeeStatus");
    if (!node) {
      return;
    }
    node.textContent = text || "";
    node.classList.remove("is-error", "is-warn", "is-success");
    if (level === STATUS_LEVELS.error) {
      node.classList.add("is-error");
    } else if (level === STATUS_LEVELS.warn) {
      node.classList.add("is-warn");
    } else if (level === STATUS_LEVELS.success) {
      node.classList.add("is-success");
    }
  }

  function renderPayeePreview(account) {
    const wrap = el("qsPayeePreview");
    if (!wrap) {
      return;
    }
    if (!account) {
      wrap.hidden = true;
      setText("qsPayeePreviewName", "");
      setText("qsPayeePreviewBankName", "");
      setText("qsPayeePreviewBankAccount", "");
      setText("qsPayeePreviewAlipay", "");
      return;
    }
    wrap.hidden = false;
    setText("qsPayeePreviewName", account.company_name || "");
    setText("qsPayeePreviewBankName", account.bank_name || "—");
    setText("qsPayeePreviewBankAccount", account.bank_account || "—");
    setText("qsPayeePreviewAlipay", account.alipay || "—");
  }

  function formatPayeeCandidateSummary(account) {
    if (!account || typeof account !== "object") {
      return "";
    }
    const parts = [];
    const bankName = String(account.bank_name || "").trim();
    const bankAccount = String(account.bank_account || "").replace(/\s+/g, "");
    if (bankName || bankAccount) {
      const bankLabel = bankName.length > 14 ? `${bankName.slice(0, 14)}…` : bankName;
      const tail = bankAccount.length > 4 ? `尾号${bankAccount.slice(-4)}` : bankAccount;
      parts.push([bankLabel, tail].filter(Boolean).join(" "));
    }
    const alipay = String(account.alipay || "").trim();
    if (alipay) {
      parts.push(alipay.length > 22 ? `${alipay.slice(0, 20)}…` : alipay);
    }
    return parts.join(" · ") || "暂无银行/支付宝信息";
  }

  function setPayeeDropdownOpen(open) {
    const list = el("qsPayeeCandidates");
    const input = el("qsPayeeCompany");
    const combo = input?.closest(".qs-payee-combobox");
    payeeState.dropdownOpen = Boolean(open);
    if (list) {
      list.hidden = !payeeState.dropdownOpen;
    }
    if (input) {
      input.setAttribute("aria-expanded", payeeState.dropdownOpen ? "true" : "false");
    }
    if (combo) {
      combo.classList.toggle("is-open", payeeState.dropdownOpen);
    }
    if (!payeeState.dropdownOpen) {
      payeeState.activeIndex = -1;
    }
  }

  function highlightPayeeCandidate(index) {
    const list = el("qsPayeeCandidates");
    if (!list) {
      return;
    }
    const buttons = Array.from(list.querySelectorAll(".qs-payee-candidate-btn"));
    buttons.forEach((btn, idx) => {
      btn.classList.toggle("is-active", idx === index);
      if (idx === index) {
        btn.scrollIntoView({ block: "nearest" });
      }
    });
  }

  function renderPayeeCandidates(candidates, options = {}) {
    const list = el("qsPayeeCandidates");
    if (!list) {
      return;
    }
    const rows = Array.isArray(candidates) ? candidates : [];
    payeeState.candidates = rows;
    list.innerHTML = "";
    if (!rows.length) {
      if (options.showEmpty) {
        const li = document.createElement("li");
        li.className = "qs-payee-candidates-empty";
        li.textContent = PAYEE_CANDIDATE_EMPTY_MSG;
        list.appendChild(li);
        setPayeeDropdownOpen(true);
      } else {
        setPayeeDropdownOpen(false);
      }
      return;
    }
    rows.forEach((row, index) => {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "qs-payee-candidate-btn";
      btn.setAttribute("role", "option");
      btn.dataset.index = String(index);
      const nameNode = document.createElement("span");
      nameNode.className = "qs-payee-candidate-name";
      nameNode.textContent = row.company_name || "";
      const metaNode = document.createElement("span");
      metaNode.className = "qs-payee-candidate-meta";
      metaNode.textContent = formatPayeeCandidateSummary(row);
      btn.appendChild(nameNode);
      btn.appendChild(metaNode);
      btn.addEventListener("mousedown", (event) => {
        event.preventDefault();
      });
      btn.addEventListener("click", () => {
        selectPayeeAccount(row);
        setPayeeDropdownOpen(false);
      });
      li.appendChild(btn);
      list.appendChild(li);
    });
    payeeState.activeIndex = rows.length ? 0 : -1;
    setPayeeDropdownOpen(true);
    highlightPayeeCandidate(payeeState.activeIndex);
  }

  function selectPayeeCandidateByIndex(index) {
    const row = payeeState.candidates[index];
    if (!row) {
      return false;
    }
    return selectPayeeAccount(row);
  }

  function selectPayeeAccount(account, options = {}) {
    if (!account || typeof account !== "object") {
      payeeState.selected = null;
      renderPayeePreview(null);
      setPayeeStatus(PAYEE_NOT_FOUND_MSG, STATUS_LEVELS.error);
      syncAllPreview();
      return false;
    }
    payeeState.selected = {
      company_name: String(account.company_name || "").trim(),
      bank_name: String(account.bank_name || "").trim(),
      bank_account: String(account.bank_account || "").trim(),
      alipay: String(account.alipay || "").trim(),
    };
    const input = el("qsPayeeCompany");
    if (input) {
      input.value = payeeState.selected.company_name;
    }
    renderPayeePreview(payeeState.selected);
    setPayeeStatus("已匹配收款账户，导出 PDF 时将写入对应银行与支付宝信息。", STATUS_LEVELS.success);
    setPayeeDropdownOpen(false);
    markEnglishSnapshotDirty();
    syncAllPreview();
    return true;
  }

  function clearPayeeSelection() {
    payeeState.selected = null;
    renderPayeePreview(null);
    syncAllPreview();
  }

  async function fetchPayeeAccounts(query, options = {}) {
    const {
      autoSelectExact = true,
      autoSelectUnique = true,
      showDropdown = true,
      silent = false,
    } = options;
    const text = String(query || "").trim();
    const token = ++payeeState.searchToken;
    if (!text && !showDropdown) {
      clearPayeeSelection();
      renderPayeeCandidates([], { showEmpty: false });
      setPayeeStatus("");
      return null;
    }
    payeeState.searching = true;
    if (!silent) {
      setPayeeStatus(text ? "正在匹配收款公司…" : "", text ? STATUS_LEVELS.busy : STATUS_LEVELS.idle);
    }
    try {
      const limit = text ? PAYEE_LIST_LIMIT : PAYEE_LIST_LIMIT;
      const resp = await window.fetch(
        `/api/quote-sheet/payment-accounts/search?q=${encodeURIComponent(text)}&limit=${limit}`,
      );
      const payload = await resp.json().catch(() => ({}));
      if (token !== payeeState.searchToken) {
        return null;
      }
      if (!resp.ok || !payload?.ok) {
        throw new Error(payload?.message || payload?.error || "search_failed");
      }
      const exact = payload.exact && typeof payload.exact === "object" ? payload.exact : null;
      const candidates = Array.isArray(payload.candidates) ? payload.candidates : [];
      if (exact && autoSelectExact) {
        setPayeeDropdownOpen(false);
        return selectPayeeAccount(exact) ? exact : null;
      }
      if (!text) {
        renderPayeeCandidates(candidates, { showEmpty: !candidates.length });
        setPayeeStatus("");
        return null;
      }
      clearPayeeSelection();
      if (!candidates.length) {
        if (showDropdown) {
          renderPayeeCandidates([], { showEmpty: true });
        } else {
          setPayeeDropdownOpen(false);
        }
        setPayeeStatus(PAYEE_NOT_FOUND_MSG, STATUS_LEVELS.error);
        return null;
      }
      if (candidates.length === 1 && autoSelectUnique) {
        setPayeeDropdownOpen(false);
        return selectPayeeAccount(candidates[0]) ? candidates[0] : null;
      }
      if (showDropdown) {
        renderPayeeCandidates(candidates);
      }
      setPayeeStatus(PAYEE_SELECT_REQUIRED_MSG, STATUS_LEVELS.warn);
      return null;
    } catch (err) {
      if (token !== payeeState.searchToken) {
        return null;
      }
      clearPayeeSelection();
      setPayeeDropdownOpen(false);
      setPayeeStatus(`匹配失败：${err?.message || "未知错误"}`, STATUS_LEVELS.error);
      return null;
    } finally {
      if (token === payeeState.searchToken) {
        payeeState.searching = false;
      }
    }
  }

  function schedulePayeeSearch() {
    if (payeeSearchTimer) {
      window.clearTimeout(payeeSearchTimer);
    }
    payeeSearchTimer = window.setTimeout(() => {
      payeeSearchTimer = null;
      const query = el("qsPayeeCompany")?.value ?? "";
      if (!String(query).trim()) {
        clearPayeeSelection();
        setPayeeStatus("");
        setPayeeDropdownOpen(false);
        return;
      }
      void fetchPayeeAccounts(query, { autoSelectExact: true, autoSelectUnique: true, showDropdown: true });
    }, 220);
  }

  function currentPayeeAccountForPdf() {
    return payeeState.selected;
  }

  function resolveQuoteCompanyNameForPdf() {
    return QUOTE_ISSUER_COMPANY_NAME;
  }

  function resolveFooterCompanyNameForPdf() {
    return QUOTE_ISSUER_COMPANY_NAME;
  }

  function syncQuoteIssuerCompanyNameForPdf() {
    setText("pvCoTitle", QUOTE_ISSUER_COMPANY_NAME);
    setText("pvFooterCo", QUOTE_ISSUER_COMPANY_NAME);
  }

  function resolveAuthorizedPayeeCompanyForPdf() {
    const payee = currentPayeeAccountForPdf();
    const fromSelected = String(payee?.company_name || "").trim();
    if (fromSelected) {
      return fromSelected;
    }
    return String(el("qsPayeeCompany")?.value || "").trim();
  }

  const EXPORT_MISSING_FIELDS = {
    payee_company: {
      key: "payee_company",
      message: "请先选择收款公司",
      focusId: "qsPayeeCompany",
      scrollTarget: ".qs-payee-wrap",
    },
    payee_account: {
      key: "payee_account",
      message: "请确认收款账户信息已匹配",
      focusId: "qsPayeeCompany",
      scrollTarget: ".qs-payee-wrap",
    },
    sample_fee: {
      key: "sample_fee",
      message: "请填写打样费",
      focusId: "qsSampleFee",
      scrollTarget: "#qsSampleDetailFields",
    },
    sample_lead_time: {
      key: "sample_lead_time",
      message: "请填写打样时间",
      focusId: "qsSampleLeadTime",
      scrollTarget: "#qsSampleDetailFields",
    },
  };

  async function inspectPayeeForExport() {
    const input = el("qsPayeeCompany");
    const query = String(input?.value || "").trim();
    if (!query) {
      return { ok: false, missingKey: "payee_company" };
    }
    const selected = payeeState.selected;
    if (
      selected &&
      normalizePayeeCompanyName(selected.company_name) === normalizePayeeCompanyName(query)
    ) {
      return { ok: true };
    }
    const matched = await fetchPayeeAccounts(query, {
      autoSelectExact: true,
      autoSelectUnique: true,
      showDropdown: false,
      silent: true,
    });
    if (matched || payeeState.selected) {
      return { ok: true };
    }
    if (payeeState.candidates.length > 1) {
      return { ok: false, missingKey: "payee_company" };
    }
    return { ok: false, missingKey: "payee_account" };
  }

  function inspectSampleFieldsForExport() {
    const missing = [];
    if (!readSampleFeeFromForm()) {
      missing.push("sample_fee");
    }
    if (!readSampleLeadTimeFromForm()) {
      missing.push("sample_lead_time");
    }
    return missing;
  }

  async function validateBeforeExport() {
    await saveQuoteSheetMeta({ silent: true, forExport: true });
    const missingKeys = [];
    const payee = await inspectPayeeForExport();
    if (!payee.ok && payee.missingKey) {
      missingKeys.push(payee.missingKey);
    }
    inspectSampleFieldsForExport().forEach((key) => {
      if (!missingKeys.includes(key)) {
        missingKeys.push(key);
      }
    });
    const missing = missingKeys
      .map((key) => EXPORT_MISSING_FIELDS[key])
      .filter(Boolean);
    return {
      complete: missing.length === 0,
      missing,
    };
  }

  function focusFirstMissingField(item) {
    if (!item) {
      return;
    }
    const focusNode = item.focusId ? el(item.focusId) : null;
    const scrollNode =
      (item.scrollTarget && document.querySelector(item.scrollTarget)) ||
      focusNode?.closest("fieldset") ||
      focusNode;
    scrollNode?.scrollIntoView({ behavior: "smooth", block: "center" });
    const highlightNode = focusNode || scrollNode;
    if (highlightNode) {
      highlightNode.classList.add("qs-export-missing-flash");
      window.setTimeout(() => {
        highlightNode.classList.remove("qs-export-missing-flash");
      }, 2200);
    }
    if (focusNode && typeof focusNode.focus === "function") {
      focusNode.focus();
    }
  }

  function showExportPreflightDialog(missingItems) {
    if (exportGuard.preflightDialogPromise) {
      return exportGuard.preflightDialogPromise;
    }
    exportGuard.preflightDialogPromise = new Promise((resolve) => {
      const modal = el("qsExportPreflightModal");
      const list = el("qsExportPreflightList");
      const fillBtn = el("qsExportPreflightFill");
      const proceedBtn = el("qsExportPreflightProceed");
      const clearDialogPromise = () => {
        exportGuard.preflightDialogPromise = null;
      };
      if (!modal || !list || !fillBtn || !proceedBtn) {
        clearDialogPromise();
        resolve("fill");
        return;
      }
      list.innerHTML = "";
      (Array.isArray(missingItems) ? missingItems : []).forEach((item) => {
        const li = document.createElement("li");
        li.textContent = item.message || "";
        list.appendChild(li);
      });
      const finish = (action) => {
        modal.hidden = true;
        modal.setAttribute("aria-hidden", "true");
        fillBtn.removeEventListener("click", onFill);
        proceedBtn.removeEventListener("click", onProceed);
        modal.querySelectorAll("[data-export-preflight-dismiss]").forEach((node) => {
          node.removeEventListener("click", onFill);
        });
        document.removeEventListener("keydown", onKeydown);
        clearDialogPromise();
        resolve(action);
      };
      const onFill = () => finish("fill");
      const onProceed = () => finish("proceed");
      const onKeydown = (event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          onFill();
        }
      };
      fillBtn.addEventListener("click", onFill);
      proceedBtn.addEventListener("click", onProceed);
      modal.querySelectorAll("[data-export-preflight-dismiss]").forEach((node) => {
        node.addEventListener("click", onFill);
      });
      document.addEventListener("keydown", onKeydown);
      modal.hidden = false;
      modal.setAttribute("aria-hidden", "false");
      fillBtn.focus();
    });
    return exportGuard.preflightDialogPromise;
  }

  async function ensureExportPreflight() {
    const validation = await validateBeforeExport();
    if (validation.complete) {
      return true;
    }
    const action = await showExportPreflightDialog(validation.missing);
    if (action === "fill") {
      focusFirstMissingField(validation.missing[0]);
      return false;
    }
    return action === "proceed";
  }

  async function ensurePayeeAccountReadyForExport() {
    const payee = await inspectPayeeForExport();
    if (payee.ok) {
      return true;
    }
    if (payee.missingKey === "payee_company") {
      window.alert(PAYEE_SELECT_REQUIRED_MSG);
      if (payeeState.candidates.length > 1) {
        renderPayeeCandidates(payeeState.candidates);
      }
      return false;
    }
    window.alert(PAYEE_NOT_FOUND_MSG);
    return false;
  }

  function bindPayeeCompanyField() {
    const input = el("qsPayeeCompany");
    const toggle = el("qsPayeeToggle");
    const wrap = input?.closest(".qs-payee-wrap");
    if (!input) {
      return;
    }
    input.addEventListener("input", () => {
      if (
        payeeState.selected &&
        normalizePayeeCompanyName(input.value) !== normalizePayeeCompanyName(payeeState.selected.company_name)
      ) {
        clearPayeeSelection();
      }
      if (!String(input.value || "").trim()) {
        clearPayeeSelection();
        setPayeeStatus("");
        setPayeeDropdownOpen(false);
        return;
      }
      schedulePayeeSearch();
    });
    input.addEventListener("focus", () => {
      const query = String(input.value || "").trim();
      void fetchPayeeAccounts(query, {
        autoSelectExact: false,
        autoSelectUnique: false,
        showDropdown: true,
        silent: true,
      });
    });
    input.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        if (!payeeState.dropdownOpen) {
          void fetchPayeeAccounts(input.value, {
            autoSelectExact: false,
            autoSelectUnique: false,
            showDropdown: true,
            silent: true,
          });
          return;
        }
        if (!payeeState.candidates.length) {
          return;
        }
        payeeState.activeIndex = Math.min(
          payeeState.activeIndex + 1,
          payeeState.candidates.length - 1,
        );
        highlightPayeeCandidate(payeeState.activeIndex);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        if (!payeeState.dropdownOpen || !payeeState.candidates.length) {
          return;
        }
        payeeState.activeIndex = Math.max(payeeState.activeIndex - 1, 0);
        highlightPayeeCandidate(payeeState.activeIndex);
        return;
      }
      if (event.key === "Enter") {
        if (!payeeState.dropdownOpen || payeeState.activeIndex < 0) {
          return;
        }
        event.preventDefault();
        if (selectPayeeCandidateByIndex(payeeState.activeIndex)) {
          setPayeeDropdownOpen(false);
        }
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        setPayeeDropdownOpen(false);
      }
    });
    input.addEventListener("change", () => {
      void fetchPayeeAccounts(input.value, {
        autoSelectExact: true,
        autoSelectUnique: true,
        showDropdown: true,
      });
    });
    input.addEventListener("blur", () => {
      window.setTimeout(() => {
        if (wrap?.contains(document.activeElement)) {
          return;
        }
        setPayeeDropdownOpen(false);
        const query = String(input.value || "").trim();
        if (!query) {
          clearPayeeSelection();
          setPayeeStatus("");
          return;
        }
        void fetchPayeeAccounts(query, {
          autoSelectExact: true,
          autoSelectUnique: true,
          showDropdown: false,
        });
      }, 160);
    });
    toggle?.addEventListener("mousedown", (event) => {
      event.preventDefault();
    });
    toggle?.addEventListener("click", () => {
      if (payeeState.dropdownOpen) {
        setPayeeDropdownOpen(false);
        return;
      }
      input.focus();
      void fetchPayeeAccounts(input.value, {
        autoSelectExact: false,
        autoSelectUnique: false,
        showDropdown: true,
        silent: true,
      });
    });
    document.addEventListener("mousedown", (event) => {
      if (!wrap || wrap.contains(event.target)) {
        return;
      }
      setPayeeDropdownOpen(false);
    });
  }

  async function bootstrapPayeeFromCompanyName(name) {
    const text = String(name || "").trim();
    if (!text) {
      return;
    }
    const payeeInput = el("qsPayeeCompany");
    if (payeeInput && !String(payeeInput.value || "").trim()) {
      payeeInput.value = text;
    }
    await fetchPayeeAccounts(payeeInput?.value || text, {
      autoSelectExact: true,
      autoSelectUnique: true,
      showDropdown: false,
    });
  }

  const enState = {
    ready: false,
    translating: false,
    translatedAt: "",
    meta: null,
    rows: null,
    labels: null,
    fixed: null,
    untranslatedFields: [],
  };

  let currentPdfLang = "cn";

  function el(id) {
    return document.getElementById(id);
  }

  function padUrlFilenamePart(text) {
    return String(text || "")
      .trim()
      .replace(/[/\\?%*:|"<>#\s]+/g, "_")
      .slice(0, 80);
  }

  function formatQuoteDateIso(iso) {
    if (!iso) {
      return "";
    }
    const parts = iso.split("-");
    if (parts.length !== 3) {
      return iso;
    }
    const y = Number(parts[0]);
    const m = Number(parts[1]);
    const d = Number(parts[2]);
    if (!y || !m || !d) {
      return iso;
    }
    return `${y}/${m}/${d}`;
  }

  function formatQuoteDateByLang(iso, lang) {
    if (!iso) {
      return "";
    }
    if (lang === "en") {
      return iso;
    }
    return formatQuoteDateIso(iso);
  }

  function todayIsoDate() {
    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, "0");
    const d = String(now.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
  }

  function formatMoneyByLang(n, lang) {
    const x = Number(n);
    if (!Number.isFinite(x)) {
      return "0";
    }
    const rounded =
      typeof formatDisplayNumber === "function"
        ? formatDisplayNumber(x)
        : String(Math.round(x * 10) / 10).replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
    if (lang === "en") {
      return rounded;
    }
    return rounded;
  }

  function lineTotal(qtyStr, priceStr) {
    const qty = Number(String(qtyStr || "").trim());
    const price = Number(String(priceStr || "").trim());
    if (!Number.isFinite(qty) || !Number.isFinite(price)) {
      return 0;
    }
    return qty * price;
  }

  function sanitizeRate(raw) {
    const n = Number(String(raw ?? "").trim().replace(/,/g, ""));
    return Number.isFinite(n) && n > 1e-6 ? n : 7.15;
  }

  function sanitizeFobYuanPerPc(raw) {
    const n = Number(String(raw ?? "").trim().replace(/,/g, ""));
    return Number.isFinite(n) && n >= 0 ? n : 4;
  }

  function escapeHtml(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /** 客户报价单描述：去掉解析/嵌入图说明等内部文案（与后端 quote_sheet_content 规则一致）。 */
  function sanitizeQuoteSheetDescription(text) {
    const blockMarkers = [
      "【工作簿嵌入图片】",
      "【工作簿内超链接",
      "【附图说明】",
    ];
    let raw = String(text || "").replace(/\r\n/g, "\n").trim();
    for (const marker of blockMarkers) {
      let start = raw.indexOf(marker);
      while (start >= 0) {
        let end = raw.indexOf("\n\n【", start + marker.length);
        if (end < 0) {
          end = raw.length;
        } else {
          const next = raw.indexOf("【", start + 1);
          if (next >= 0 && next < end) {
            end = next;
          }
        }
        raw = `${raw.slice(0, start)}${raw.slice(end)}`.trim();
        start = raw.indexOf(marker);
      }
    }
    const lineDrop =
      /^(问题[一二三四五六七八九十\d]+描述(?:[：:\s]|$).*|问题[一二三四五六七八九十\d]+[：:\s].*|背景指向.*|图片说明(?:[：:\s]|$).*|.*工作簿嵌入.*|.*未向模型附带图像.*|.*体积超限或未启用视觉.*)$/i;
    const lines = raw
      .split("\n")
      .map((line) => line.trim())
      .filter(
        (line) =>
          line &&
          !lineDrop.test(line) &&
          !/^问题[一二三四五六七八九十\d]+描述/i.test(line) &&
          !/^(null|undefined|nan|-)$/i.test(line),
      );
    return lines.join("\n").trim();
  }

  const PDF_DESC_MAX_LINES = 14;
  const PDF_DESC_MAX_CHARS = 1400;
  const PDF_DESC_OMISSION = "（其余结构说明已从报价单正文省略，详见确认版技术资料。）";
  const PDF_DESC_MATERIAL_PREFIX_RE =
    /^(?:主料|里布|面料|外料|辅料|main\s*material|lining|fabric)[：:\s]+/i;
  const PDF_DESC_WIDTH_LABEL_RE = /宽幅[：:]?\s*/gi;
  const PDF_DESC_WIDTH_TOKEN_RE =
    /\d+(?:\.\d+)?\s*(?:cm|厘米|mm|毫米|''|"|″|inch|in)\b/gi;
  const PDF_DESC_SEGMENT_SPLIT_RE = /[，,、/\r\n]+/;

  const PDF_BRIEF_DESC_BANNED =
    /裁片|系统估算|AI估算|系统推断|计算方式|内部推断|本地兜底|问题[一二三四五六七八九十\d]+描述|背景指向|图片说明|工作簿嵌入|推断|待核/i;

  function normalizeQuoteNoForPdf(raw) {
    let s = String(raw ?? "").trim();
    if (!s) {
      return "";
    }
    if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(s)) {
      return "";
    }
    const hashStyle = /^BJ-(\d{8})-([0-9a-f]{8})$/i.exec(s);
    if (hashStyle) {
      const seq = (parseInt(hashStyle[2].slice(0, 6), 16) % 999) + 1;
      return `BJ-${hashStyle[1]}-${String(seq).padStart(3, "0")}`;
    }
    return s;
  }

  function stripProductPrefixFromDesc(descText, name) {
    let d = String(descText ?? "").trim();
    const n = String(name ?? "").trim();
    if (!d || !n || !d.startsWith(n)) {
      return d;
    }
    return d.slice(n.length).replace(/^[，,\s]+/, "").trim();
  }

  function stripDescPunctuation(text) {
    let s = String(text ?? "").trim();
    while (s && /[。.!！?？;；,，]$/.test(s)) {
      s = s.slice(0, -1).trimEnd();
    }
    return s;
  }

  function buildBriefDescForPdf(name, descText, lang = "cn") {
    let cleaned = stripProductPrefixFromDesc(String(descText ?? "").trim(), name);
    cleaned = stripDescPunctuation(cleaned);
    if (cleaned && !PDF_BRIEF_DESC_BANNED.test(cleaned)) {
      return cleaned.length > 100 ? `${cleaned.slice(0, 99).trim()}…` : cleaned;
    }
    return lang === "en" ? "Main material TBD" : "主料待确认";
  }

  function stripMaterialPrefixAndWidth(text) {
    let p = String(text || "").trim();
    if (!p) {
      return "";
    }
    p = p.replace(PDF_DESC_MATERIAL_PREFIX_RE, "");
    p = p.replace(PDF_DESC_WIDTH_LABEL_RE, "");
    p = p.replace(PDF_DESC_WIDTH_TOKEN_RE, "");
    return p.replace(/\s{2,}/g, " ").trim();
  }

  function normalizePdfDescSegmentKey(text) {
    return String(text ?? "").trim().replace(/\s+/g, " ");
  }

  function joinPdfDescSegments(segments, lang = "cn") {
    const sep = lang === "en" ? ", " : "、";
    return segments.join(sep);
  }

  /** 按分隔符拆分描述段，去重后拼接（保留首次出现顺序）。 */
  function dedupePdfDescSegments(raw, lang = "cn") {
    const source = String(raw ?? "").trim();
    if (!source) {
      return "";
    }
    const seen = new Set();
    const kept = [];
    for (const part of source.split(PDF_DESC_SEGMENT_SPLIT_RE)) {
      const cleaned = normalizePdfDescSegmentKey(stripMaterialPrefixAndWidth(part));
      if (!cleaned || seen.has(cleaned)) {
        continue;
      }
      seen.add(cleaned);
      kept.push(cleaned);
    }
    return joinPdfDescSegments(kept, lang);
  }

  /** 客户 PDF 描述列：去掉材料前缀与宽幅，去重后仅保留材质名/业务描述。 */
  function sanitizeCustomerDescForPdf(raw, lang = "cn", rawFallback = "") {
    const original = String(raw ?? "").trim();
    const fallbackRaw = String(rawFallback ?? "").trim();
    if (!original && !fallbackRaw) {
      return "-";
    }
    const source = original || fallbackRaw;
    let s = dedupePdfDescSegments(source, lang);
    if (!s || PDF_BRIEF_DESC_BANNED.test(s)) {
      const plain = dedupePdfDescSegments(fallbackRaw || source, lang);
      if (plain && !PDF_BRIEF_DESC_BANNED.test(plain)) {
        s = plain;
      }
    }
    if (!s) {
      return "-";
    }
    if (s.length > 72) {
      return `${s.slice(0, 71).trim()}…`;
    }
    return s;
  }

  function resolvePdfDescValue(translatedRow, descEl, nameEl, lang) {
    const nameVal = translatedRow?.name ?? nameEl?.value ?? "";
    const fromEn =
      lang === "en" && translatedRow && String(translatedRow.desc ?? "").trim()
        ? String(translatedRow.desc).trim()
        : "";
    const fromForm = String(descEl?.value ?? "").trim();
    const rawSource = fromEn || fromForm;
    const brief = buildBriefDescForPdf(nameVal, rawSource, lang);
    return sanitizeCustomerDescForPdf(brief, lang, rawSource);
  }

  function resolvePdfNoteColumnValue({
    forFobUsdExport,
    lang,
    row,
    translatedRow,
    priceEl,
    rate,
    fobYuanPc,
  }) {
    if (forFobUsdExport && rate) {
      let unitUsd = rowFobUsdUnit(row, rate);
      if (!Number.isFinite(unitUsd)) {
        const trUsd = parseMoneyNumber(translatedRow?.fob_price_usd);
        if (Number.isFinite(trUsd)) {
          unitUsd = trUsd;
        }
      }
      if (!Number.isFinite(unitUsd)) {
        const priceNum = Number(String(priceEl?.value ?? "").trim());
        const addon = Number.isFinite(fobYuanPc) ? fobYuanPc : sanitizeFobYuanPerPc(null);
        if (Number.isFinite(priceNum)) {
          unitUsd = (priceNum + addon) / rate;
        }
      }
      if (!Number.isFinite(unitUsd)) {
        const fobRmb = rowFobRmbUnit(row);
        if (Number.isFinite(fobRmb)) {
          unitUsd = fobRmb / rate;
        }
      }
      return Number.isFinite(unitUsd) ? formatMoneyByLang(unitUsd, lang) : "-";
    }
    const taxedCandidates = [
      translatedRow?.taxed_price,
      translatedRow?.taxed_price_text,
      row.dataset.taxedPrice,
      row.dataset.taxedPriceText,
    ];
    for (const item of taxedCandidates) {
      const text = String(item ?? "").trim();
      if (text && !/^(null|undefined|nan|-)$/i.test(text)) {
        return text;
      }
    }
    const unitPrice = String(priceEl?.value ?? "").trim();
    if (unitPrice) {
      return unitPrice;
    }
    return "-";
  }

  /** 报价单/PDF 描述：清洗后按行友好摘要，超长时明示省略（非静默裁切）。 */
  function customerDescriptionForQuoteSheet(text) {
    const cleaned = sanitizeQuoteSheetDescription(text);
    if (!cleaned) {
      return "";
    }
    const lines = cleaned.split("\n").filter((ln) => ln.trim());
    const kept = [];
    let charCount = 0;
    let truncated = false;
    for (const ln of lines) {
      const add = ln.length + (kept.length ? 1 : 0);
      if (charCount + add > PDF_DESC_MAX_CHARS || kept.length >= PDF_DESC_MAX_LINES) {
        truncated = true;
        break;
      }
      kept.push(ln);
      charCount += add;
    }
    if (truncated && !kept.includes(PDF_DESC_OMISSION)) {
      kept.push(PDF_DESC_OMISSION);
    }
    return kept.join("\n");
  }

  function looksLikeBagProductPhoto(w, h) {
    if (looksLikeDocumentScreenshot(w, h)) {
      return false;
    }
    const short = Math.min(w, h);
    const long = Math.max(w, h);
    const ratio = long / Math.max(short, 1);
    if (ratio > 2.75 || ratio < 0.42) {
      return false;
    }
    const area = w * h;
    if (area > 480000 && ratio > 1.55) {
      return false;
    }
    return true;
  }

  function looksLikeDocumentScreenshot(w, h) {
    const short = Math.min(w, h);
    const long = Math.max(w, h);
    const ratio = long / Math.max(short, 1);
    const area = w * h;
    if (long >= 680 && short <= 450 && ratio >= 1.55) {
      return true;
    }
    if (long >= 520 && short <= 300 && ratio >= 1.95) {
      return true;
    }
    if (area >= 280000 && ratio >= 1.75) {
      return true;
    }
    if (long >= 900 && short <= 520) {
      return true;
    }
    return false;
  }

  function isAcceptableProductImageDataUrl(dataUrl, done, options = {}) {
    if (options.userUploaded) {
      done(true);
      return;
    }
    const url = String(dataUrl || "").trim();
    if (!url.startsWith("data:")) {
      done(false);
      return;
    }
    const img = new Image();
    img.onload = () => {
      const w = img.naturalWidth || 0;
      const h = img.naturalHeight || 0;
      const short = Math.min(w, h);
      const long = Math.max(w, h);
      const ok =
        short >= 72 &&
        w * h >= 6400 &&
        long / Math.max(short, 1) <= 3.8 &&
        !(long <= 110 && url.length < 28000) &&
        !looksLikeDocumentScreenshot(w, h) &&
        looksLikeBagProductPhoto(w, h);
      done(ok);
    };
    img.onerror = () => done(false);
    img.src = url;
  }

  function setText(pvId, value) {
    const node = document.getElementById(pvId);
    if (node) {
      node.textContent = value ?? "";
    }
  }

  function displayMetaPdfValue(raw) {
    const text = String(raw ?? "").trim();
    if (!text || /^(null|undefined|nan)$/i.test(text)) {
      return "-";
    }
    return text;
  }

  const SAMPLE_REQUIRED_VALUES = new Set(["yes", "no", "pending"]);

  function trimMetaText(raw) {
    const text = String(raw ?? "").trim();
    if (!text || /^(null|undefined|nan)$/i.test(text)) {
      return "";
    }
    return text;
  }

  function normalizeSampleRequired(raw) {
    const text = String(raw ?? "").trim().toLowerCase();
    if (SAMPLE_REQUIRED_VALUES.has(text)) {
      return text;
    }
    const alias = {
      需要打样: "yes",
      不需要打样: "no",
      待确认: "pending",
    };
    return alias[text] || "";
  }

  function readSampleRequiredFromForm() {
    return "";
  }

  function readSampleFeeFromForm() {
    return trimMetaText(el("qsSampleFee")?.value ?? "");
  }

  function readSampleLeadTimeFromForm() {
    return trimMetaText(el("qsSampleLeadTime")?.value ?? "");
  }

  function updateSampleFieldsUi() {
    const wrap = el("qsSampleDetailFields");
    const feeEl = el("qsSampleFee");
    const leadEl = el("qsSampleLeadTime");
    if (!wrap) {
      return;
    }
    wrap.hidden = false;
    wrap.classList.remove("is-disabled");
    if (feeEl) {
      feeEl.disabled = false;
    }
    if (leadEl) {
      leadEl.disabled = false;
    }
  }

  function sampleStatusLabel(required, lang) {
    if (required === "no") {
      return lang === "en"
        ? enState.labels?.lbl_sample_status_no || "Not required"
        : "不需要";
    }
    if (required === "pending") {
      return lang === "en"
        ? enState.labels?.lbl_sample_status_pending || "To be confirmed"
        : "待确认";
    }
    return "";
  }

  function resolveSamplePdfValues(lang) {
    const metaEn = lang === "en" && enState.meta ? enState.meta : null;
    const fee = trimMetaText(metaEn?.sample_fee ?? readSampleFeeFromForm());
    const lead = trimMetaText(metaEn?.sample_lead_time ?? readSampleLeadTimeFromForm());
    return { fee, lead };
  }

  function syncSamplePdfPreview(lang = currentPdfLang) {
    const { fee, lead } = resolveSamplePdfValues(lang);
    const statusLine = el("pvSampleStatusLine");
    const feeLine = el("pvSampleFeeLine");
    const leadLine = el("pvSampleLeadTimeLine");

    if (statusLine) {
      statusLine.hidden = true;
    }
    setText("pvSampleStatus", "");
    if (feeLine) {
      feeLine.hidden = !fee;
    }
    if (leadLine) {
      leadLine.hidden = !lead;
    }
    setText("pvSampleFee", fee);
    setText("pvSampleLeadTime", lead);
    syncAuthorizedPayeePdfPreview();
  }

  function syncAuthorizedPayeePdfPreview() {
    const name = resolveAuthorizedPayeeCompanyForPdf();
    const line = el("pvAuthorizedPayeeLine");
    if (line) {
      line.hidden = !name;
    }
    setText("pvAuthorizedPayee", name);
  }

  async function ensureSampleExportReady({ lang = "cn" } = {}) {
    const saved = await saveQuoteSheetMeta({ silent: true, forExport: true });
    syncSamplePdfPreview(lang);
    return { ok: true, saved, sample_required: readSampleRequiredFromForm() };
  }

  function formatPdfAddress(value, lang) {
    const text = String(value ?? "").replace(/\s+/g, " ").trim();
    if (lang !== "en" || text.length < 72) {
      return text;
    }
    if (/\bValley,\s+/i.test(text)) {
      return text.replace(/\b(Valley,)\s+/i, "$1\n");
    }
    const parts = text.split(/,\s+/);
    if (parts.length <= 2) {
      return text;
    }
    let line = "";
    const out = [];
    for (const part of parts) {
      const next = line ? `${line}, ${part}` : part;
      if (next.length > 68 && line) {
        out.push(line);
        line = part;
      } else {
        line = next;
      }
    }
    if (line) {
      out.push(line);
    }
    return out.join("\n");
  }

  function selFormBody() {
    return el("qsFormProductBody");
  }

  function selPdfProducts() {
    return el("quotePdfProducts");
  }

  function switchView(which) {
    const view = which === "quote" ? "quoteSheet" : "chat";
    if (typeof window.switchWorkspaceView === "function") {
      window.switchWorkspaceView(view);
      return;
    }
    const chatPane = el("workspaceChat");
    const quotePane = el("workspaceQuote");
    const navChat = document.querySelector('.session-item[data-route="chat"]');
    const navQuote = el("navQuoteSheet");
    if (!chatPane || !quotePane) {
      return;
    }
    document.querySelectorAll(".session-item").forEach((b) => b.classList.remove("active"));
    if (which === "quote") {
      chatPane.hidden = true;
      chatPane.classList.remove("workspace-pane-visible");
      quotePane.hidden = false;
      quotePane.classList.add("workspace-pane-visible");
      navQuote?.classList.add("active");
    } else {
      quotePane.hidden = true;
      quotePane.classList.remove("workspace-pane-visible");
      chatPane.hidden = false;
      chatPane.classList.add("workspace-pane-visible");
      navChat?.classList.add("active");
    }
  }

  function refreshAddDisabled() {
    const tbody = selFormBody();
    const btn = el("qsAddProductRow");
    if (!tbody || !btn) {
      return;
    }
    btn.disabled = tbody.rows.length >= MAX_ROWS;
  }

  function readUsdCnyRate() {
    const raw = el("qsUsdCnyRate")?.value;
    if (raw != null && String(raw).trim() !== "") {
      return sanitizeRate(raw);
    }
    const s = typeof window !== "undefined" && window.__quoteUsdSnapshot?.usdCnyRate;
    return sanitizeRate(s);
  }

  function readFobYuanPerPc(forExport = false) {
    const raw = el("qsFobYuanPerPc")?.value;
    if (raw != null && String(raw).trim() !== "") {
      const n = Number(String(raw).trim().replace(/,/g, ""));
      if (Number.isFinite(n) && n >= 0) {
        return n;
      }
    }
    const snap = typeof window !== "undefined" && window.__quoteUsdSnapshot?.fobYuanPerPc;
    if (snap != null && String(snap).trim() !== "") {
      const n = Number(String(snap).trim().replace(/,/g, ""));
      if (Number.isFinite(n) && n >= 0) {
        return n;
      }
    }
    return sanitizeFobYuanPerPc(snap ?? raw);
  }

  function parseMoneyNumber(raw) {
    const s = String(raw ?? "").trim().replace(/,/g, "");
    if (!s) {
      return NaN;
    }
    const m = s.match(/-?\d+(?:\.\d+)?/);
    if (!m) {
      return NaN;
    }
    const n = Number(m[0]);
    return Number.isFinite(n) ? n : NaN;
  }

  function applyRowFobDataset(tr, row) {
    if (!tr || !row || typeof row !== "object") {
      return;
    }
    const set = (key, val) => {
      const text = val != null && val !== undefined ? String(val).trim() : "";
      if (text) {
        tr.dataset[key] = text;
      } else {
        delete tr.dataset[key];
      }
    };
    set("fobPrice", row.fob_price);
    set("fobPriceText", row.fob_price_text);
    set("fobPriceUsd", row.fob_price_usd);
    set("fobPriceUsdText", row.fob_price_usd_text);
    set("fobTotal", row.fob_total);
    set("fobTotalUsd", row.fob_total_usd);
    set("taxedPrice", row.taxed_price);
    set("taxedPriceText", row.taxed_price_text);
  }

  function rowFobUsdUnit(tr, rate) {
    if (!tr) {
      return NaN;
    }
    const usdText = tr.dataset.fobPriceUsdText || "";
    let usd = parseMoneyNumber(usdText);
    if (!Number.isFinite(usd)) {
      usd = parseMoneyNumber(tr.dataset.fobPriceUsd);
    }
    if (Number.isFinite(usd)) {
      return usd;
    }
    const fobRmb = parseMoneyNumber(tr.dataset.fobPrice);
    if (Number.isFinite(fobRmb) && Number.isFinite(rate) && rate > 1e-6) {
      return fobRmb / rate;
    }
    return NaN;
  }

  function rowFobRmbUnit(tr) {
    if (!tr) {
      return NaN;
    }
    const n = parseMoneyNumber(tr.dataset.fobPrice);
    return Number.isFinite(n) ? n : NaN;
  }

  function setPdfPriceHeaders(fobUsdMode, lang = currentPdfLang) {
    const thP = el("pvThUnitPrice");
    const thT = el("pvThLineTotal");
    if (!thP || !thT) {
      return;
    }

    if (lang === "en" && enState.labels) {
      if (fobUsdMode) {
        thP.innerHTML = String(enState.labels.th_fob_unit_usd || "FOB Unit Price<br />(USD)");
        thT.innerHTML = String(enState.labels.th_fob_total_usd || "FOB Total<br />(USD)");
      } else {
        thP.innerHTML = String(enState.labels.th_unit_price_rmb || "Unit Price");
        thT.innerHTML = String(enState.labels.th_line_total_rmb || "Total EXW<br />RMB");
      }
    } else if (fobUsdMode) {
      thP.innerHTML = "FOB单价<br />(USD)";
      thT.innerHTML = "FOB总价<br />(USD)";
    } else {
      thP.textContent = "单价";
      thT.innerHTML = "出厂总价<br />RMB";
    }
    setPdfNoteColumnHeader(fobUsdMode, lang);
  }

  function setPdfNoteColumnHeader(fobUsdMode, lang = currentPdfLang) {
    const th = el("pvThNoteColumn");
    if (!th) {
      return;
    }
    if (lang === "en" && enState.labels) {
      if (fobUsdMode) {
        th.innerHTML = String(enState.labels.th_fob_price_usd || "FOB Price<br />(USD)");
      } else {
        th.textContent = String(enState.labels.th_tax_inclusive_price || "Tax-incl. Price");
      }
      return;
    }
    if (fobUsdMode) {
      th.innerHTML = "FOB价格<br />USD";
    } else {
      th.textContent = "含税价";
    }
  }

  const PDF_VALIDITY_REMARK_STRIP_RE =
    /[*＊]?\s*以上报价\s*20\s*天内有效[，,]?\s*具体价格以实际打样核算为准[。.]?/gi;

  function stripValidityRemarkFromPdfNote(text) {
    return String(text ?? "")
      .replace(PDF_VALIDITY_REMARK_STRIP_RE, "")
      .replace(/\s{2,}/g, " ")
      .trim();
  }

  function readPdfRemarkFromForm() {
    return stripValidityRemarkFromPdfNote(el("qsPdfRemark")?.value ?? "");
  }

  /** 黄色条下方备注行：默认空，仅展示用户手填备注（不重复 20 天有效说明）。 */
  function syncPdfBottomRemark(lang = currentPdfLang) {
    const remarkLine = el("pvPdfRemarkLine");
    void lang;
    setText("pvPdfRemark", readPdfRemarkFromForm());
    if (remarkLine) {
      remarkLine.hidden = false;
    }
  }

  function syncPdfValidityRemark() {
    const yellowFoot = el("pvValidityYellowFoot");
    const yellowRow = el("pvValidityYellowRow");
    if (yellowFoot) {
      yellowFoot.hidden = false;
    }
    if (yellowRow) {
      yellowRow.hidden = false;
    }
  }

  /** @param forFobUsdExport PDF 预览：在人民币出厂单价上加 FOB 加价/件后再按汇率折美金（非纯 EXW 折算）。 */
  function syncProductPreview(forFobUsdExport = false, lang = currentPdfLang) {
    const body = selPdfProducts();
    const tbody = selFormBody();
    if (!body || !tbody) {
      return;
    }
    const rate = forFobUsdExport ? readUsdCnyRate() : null;
    const fobYuanPc = forFobUsdExport ? readFobYuanPerPc(true) : null;
    const fobQuoteSheet = Boolean(typeof window !== "undefined" && window.__quoteSheetFobQuote);

    body.innerHTML = "";
    Array.from(tbody.querySelectorAll("tr")).forEach((row, rowIndex) => {
      const img = row.querySelector(".qs-form-thumb");
      const imgSrc =
        img && !img.classList.contains("hidden") && img.src && img.src.startsWith("data:")
          ? img.src
          : "";
      const inputs = Array.from(row.querySelectorAll("input:not(.qs-img-file), textarea"));
      const [nameEl, sizeEl, descEl, packEl, qtyEl, priceEl, totalEl, noteEl] = inputs;
      const totalVal = lineTotal(qtyEl?.value, priceEl?.value);
      if (totalEl && totalEl.classList.contains("qs-total-readonly")) {
        totalEl.value = formatMoneyByLang(totalVal, "cn");
      }

      const tr = document.createElement("tr");

      const imgTd = document.createElement("td");
      imgTd.className = "col-img";
      if (imgSrc) {
        const im = document.createElement("img");
        im.src = imgSrc;
        im.alt = "";
        im.className = "qs-pdf-prod-img";
        imgTd.appendChild(im);
      } else {
        const ph = document.createElement("div");
        ph.className = "qs-pdf-placeholder";
        ph.innerHTML = "&nbsp;";
        imgTd.appendChild(ph);
      }
      tr.appendChild(imgTd);

      function textCell(cls, multiline, value) {
        const td = document.createElement("td");
        td.className = `${cls} qs-pdf-cn`;
        td.style.textAlign = "left";
        if (multiline) {
          td.innerHTML = escapeHtml(value || "").replaceAll("\n", "<br />");
        } else {
          td.textContent = value || "";
        }
        tr.appendChild(td);
      }

      const translatedRow = lang === "en" && Array.isArray(enState.rows) ? enState.rows[rowIndex] : null;
      textCell("col-name", false, translatedRow?.name ?? nameEl?.value ?? "");
      textCell(
        "col-size",
        true,
        sanitizeCustomerSizeText(translatedRow?.size ?? sizeEl?.value ?? ""),
      );
      const descTd = document.createElement("td");
      descTd.className = "col-desc qs-pdf-cn";
      descTd.style.textAlign = "left";
      descTd.textContent = resolvePdfDescValue(translatedRow, descEl, nameEl, lang);
      tr.appendChild(descTd);
      textCell(
        "col-pack",
        true,
        sanitizeCustomerPackText(
          lang === "en" && translatedRow && String(translatedRow.pack ?? "").trim()
            ? translatedRow.pack
            : packEl?.value ?? "",
        ),
      );

      const qtyTd = document.createElement("td");
      qtyTd.className = "col-qty qs-pdf-arial";
      qtyTd.style.textAlign = "center";
      let qtyDisp =
        translatedRow?.qty !== undefined && translatedRow?.qty !== null && translatedRow?.qty !== ""
          ? String(translatedRow.qty)
          : qtyEl?.value !== undefined && qtyEl.value !== ""
            ? String(qtyEl.value)
            : "";
      if (typeof formatNumbersInDisplayText === "function") {
        qtyDisp = formatNumbersInDisplayText(qtyDisp);
      }
      qtyTd.textContent = qtyDisp;
      tr.appendChild(qtyTd);

      const priceTd = document.createElement("td");
      priceTd.className = "col-price qs-pdf-arial";
      priceTd.style.textAlign = "center";
      const priceNum = Number(String(priceEl?.value ?? "").trim());
      const qtyNum = Number(String(qtyEl?.value ?? "").trim());
      let priceDisp;
      let totalDisp;
      if (forFobUsdExport && rate) {
        let unitUsd = rowFobUsdUnit(row, rate);
        if (!Number.isFinite(unitUsd)) {
          const trUsd = parseMoneyNumber(translatedRow?.fob_price_usd);
          if (Number.isFinite(trUsd)) {
            unitUsd = trUsd;
          }
        }
        if (!Number.isFinite(unitUsd)) {
          const exwNum = Number.isFinite(priceNum) ? priceNum : NaN;
          const addon = Number.isFinite(fobYuanPc) ? fobYuanPc : sanitizeFobYuanPerPc(null);
          if (Number.isFinite(exwNum)) {
            unitUsd = (exwNum + addon) / rate;
          }
        }
        if (!Number.isFinite(unitUsd)) {
          const fobRmb = rowFobRmbUnit(row);
          if (Number.isFinite(fobRmb)) {
            unitUsd = fobRmb / rate;
          }
        }
        priceDisp = Number.isFinite(unitUsd) ? formatMoneyByLang(unitUsd, lang) : "";
        const usdLine = Number.isFinite(unitUsd) && Number.isFinite(qtyNum) ? qtyNum * unitUsd : NaN;
        let tierUsdTotal = parseMoneyNumber(row.dataset.fobTotalUsd);
        if (!Number.isFinite(tierUsdTotal)) {
          tierUsdTotal = parseMoneyNumber(translatedRow?.fob_total_usd);
        }
        totalDisp = Number.isFinite(tierUsdTotal)
          ? formatMoneyByLang(tierUsdTotal, lang)
          : Number.isFinite(usdLine)
            ? formatMoneyByLang(usdLine, lang)
            : "";
      } else if (fobQuoteSheet && lang === "en") {
        const fobRmb = rowFobRmbUnit(row);
        priceDisp = Number.isFinite(fobRmb)
          ? formatMoneyByLang(fobRmb, lang)
          : translatedRow?.price !== undefined && translatedRow?.price !== null && translatedRow?.price !== ""
            ? String(translatedRow.price)
            : priceEl?.value !== undefined && priceEl.value !== ""
              ? String(priceEl.value)
              : "";
        const tierFobTotal = parseMoneyNumber(row.dataset.fobTotal);
        totalDisp = Number.isFinite(tierFobTotal)
          ? formatMoneyByLang(tierFobTotal, lang)
          : Number.isFinite(fobRmb) && Number.isFinite(qtyNum)
            ? formatMoneyByLang(qtyNum * fobRmb, lang)
            : formatMoneyByLang(totalVal, lang);
      } else {
        priceDisp =
          translatedRow?.price !== undefined && translatedRow?.price !== null && translatedRow?.price !== ""
            ? String(translatedRow.price)
            : priceEl?.value !== undefined && priceEl.value !== ""
              ? String(priceEl.value)
              : "";
        totalDisp = formatMoneyByLang(totalVal, lang);
      }
      if (typeof formatNumbersInDisplayText === "function") {
        priceDisp = formatNumbersInDisplayText(priceDisp);
        totalDisp = formatNumbersInDisplayText(totalDisp);
      }
      priceTd.textContent = priceDisp;
      tr.appendChild(priceTd);

      const totTd = document.createElement("td");
      totTd.className = "col-total qs-pdf-arial";
      totTd.style.textAlign = "center";
      totTd.textContent = totalDisp;
      tr.appendChild(totTd);

      const noteTd = document.createElement("td");
      noteTd.className = "col-note qs-pdf-cn qs-pdf-arial";
      noteTd.style.textAlign = "center";
      noteTd.textContent = resolvePdfNoteColumnValue({
        forFobUsdExport,
        lang,
        row,
        translatedRow,
        priceEl,
        rate,
        fobYuanPc,
      });
      tr.appendChild(noteTd);

      body.appendChild(tr);
    });

    setPdfPriceHeaders(Boolean(forFobUsdExport), lang);
    refreshAddDisabled();
  }

  function bindField(idInput, pvId, coerce) {
    const input = el(idInput);
    if (!input) {
      return;
    }
    const run = () => {
      let v = input.value;
      if (coerce) {
        v = coerce(v);
      }
      setText(pvId, v);
    };
    input.addEventListener("input", run);
    input.addEventListener("change", run);
  }

  function syncAllPreview() {
    const metaEn = currentPdfLang === "en" && enState.meta ? enState.meta : null;

    syncQuoteIssuerCompanyNameForPdf();
    setText("pvCoPhone", metaEn?.co_phone ?? el("qsCoPhone")?.value ?? "");
    setText("pvCoAddr", formatPdfAddress(metaEn?.co_addr ?? el("qsCoAddr")?.value ?? "", currentPdfLang));
    setText(
      "pvQuoteNo",
      normalizeQuoteNoForPdf(metaEn?.quote_no ?? el("qsQuoteNo")?.value ?? ""),
    );
    setText("pvSellerContact", metaEn?.seller_contact ?? el("qsSellerContact")?.value ?? "");
    setText("pvSellerEmail", metaEn?.seller_email ?? el("qsSellerEmail")?.value ?? "");
    setText("pvCustName", metaEn?.cust_name ?? el("qsCustName")?.value ?? "");
    setText("pvCustContact", metaEn?.cust_contact ?? el("qsCustContact")?.value ?? "");
    setText("pvCustPhone", metaEn?.cust_phone ?? el("qsCustPhone")?.value ?? "");
    setText("pvCustAddr", formatPdfAddress(metaEn?.cust_addr ?? el("qsCustAddr")?.value ?? "", currentPdfLang));
    const d = el("qsQuoteDate")?.value;
    setText("pvQuoteDate", formatQuoteDateByLang(metaEn?.quote_date_iso ?? (d || ""), currentPdfLang));
    syncSamplePdfPreview(currentPdfLang);
    syncPdfBottomRemark(currentPdfLang);
    syncPdfValidityRemark();

    const payeeAccount = currentPayeeAccountForPdf();
    const bankNameText = buildBankNamePdfText(payeeAccount);
    const bankAccountText = buildBankAccountPdfText(payeeAccount);
    const alipayText = buildAlipayPdfText(payeeAccount);
    setText("pvBank", bankNameText);
    setText("pvBankAccount", bankAccountText);
    const bankAccountLine = el("pvBankAccountLine");
    if (bankAccountLine) {
      bankAccountLine.hidden = !bankAccountText;
    }
    setText("pvAlipay", alipayText);

    syncProductPreview(false, currentPdfLang);
  }

  function applyDefaultsToForm() {
    if (el("qsCoName") && !el("qsCoName").value) {
      el("qsCoName").value = defaults.coName;
    }
    if (el("qsCoPhone") && !el("qsCoPhone").value) {
      el("qsCoPhone").value = defaults.coPhone;
    }
    if (el("qsCoAddr") && !el("qsCoAddr").value) {
      el("qsCoAddr").value = defaults.coAddr;
    }
    if (el("qsPayeeCompany") && !el("qsPayeeCompany").value) {
      el("qsPayeeCompany").value = defaults.coName;
    }
    if (el("qsQuoteDate") && !el("qsQuoteDate").value) {
      el("qsQuoteDate").value = todayIsoDate();
    }
  }

  function markEnglishSnapshotDirty() {
    if (enState.translating || !enState.ready) {
      return;
    }
    enState.ready = false;
    if (readExportScope() !== "cn") {
      updateTranslateStatus("中文数据已变更，请先点击“翻译成英文版”后导出。", STATUS_LEVELS.warn);
    }
  }

  function createFormProductRow() {
    const tr = document.createElement("tr");

    const imgCell = document.createElement("td");
    imgCell.className = "qs-form-td-img";
    const ph = document.createElement("div");
    ph.className = "qs-img-placeholder";
    ph.textContent = "无图";
    const imgThumb = document.createElement("img");
    imgThumb.className = "qs-form-thumb hidden";
    imgThumb.alt = "";
    const fi = document.createElement("input");
    fi.type = "file";
    fi.accept = "image/*";
    fi.className = "qs-img-file";
    fi.addEventListener("change", () => {
      const file = fi.files && fi.files[0];
      if (!file) {
        ph.classList.remove("hidden");
        imgThumb.classList.add("hidden");
        imgThumb.src = "";
        markEnglishSnapshotDirty();
        syncProductPreview();
        return;
      }
      const reader = new FileReader();
      reader.onload = () => {
        imgThumb.src = String(reader.result || "");
        imgThumb.dataset.userUploaded = "1";
        imgThumb.classList.remove("hidden");
        ph.classList.add("hidden");
        markEnglishSnapshotDirty();
        syncProductPreview();
      };
      reader.readAsDataURL(file);
    });
    imgCell.appendChild(ph);
    imgCell.appendChild(imgThumb);
    imgCell.appendChild(fi);

    function tdWith(child) {
      const td = document.createElement("td");
      td.appendChild(child);
      return td;
    }

    function miniInput(kind) {
      const node = document.createElement(kind === "textarea" ? "textarea" : "input");
      if (kind !== "textarea") {
        node.type = kind;
      }
      node.className = kind === "textarea" ? "qs-textarea-row" : "qs-input-mini";
      if (kind === "textarea") {
        node.rows = 2;
      }
      if (kind === "number") {
        node.min = "0";
        node.step = "any";
      }
      node.addEventListener("input", () => {
        markEnglishSnapshotDirty();
        syncProductPreview();
      });
      node.addEventListener("change", () => {
        markEnglishSnapshotDirty();
      });
      return node;
    }

    const name = miniInput("text");
    const size = miniInput("textarea");
    const desc = miniInput("textarea");
    const pack = miniInput("text");
    const qty = miniInput("number");
    const price = miniInput("number");

    function recalcInline() {
      const t = lineTotal(qty.value, price.value);
      total.value = formatMoneyByLang(t, "cn");
      markEnglishSnapshotDirty();
      syncProductPreview();
    }
    qty.addEventListener("input", recalcInline);
    price.addEventListener("input", recalcInline);

    const total = document.createElement("input");
    total.type = "text";
    total.className = "qs-input-mini qs-total-readonly";
    total.readOnly = true;
    total.tabIndex = -1;
    total.value = formatMoneyByLang(0, "cn");

    const note = miniInput("text");

    const delCell = document.createElement("td");
    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "qs-row-del-btn";
    delBtn.textContent = "删除";
    delBtn.addEventListener("click", () => {
      const tb = selFormBody();
      if (!tb) {
        return;
      }
      if (tb.rows.length <= 1) {
        fi.value = "";
        ph.classList.remove("hidden");
        imgThumb.classList.add("hidden");
        imgThumb.src = "";
        name.value = "";
        size.value = "";
        desc.value = "";
        pack.value = "";
        qty.value = "";
        price.value = "";
        total.value = formatMoneyByLang(0, "cn");
        note.value = "";
        markEnglishSnapshotDirty();
        syncProductPreview();
        return;
      }
      tr.remove();
      markEnglishSnapshotDirty();
      syncProductPreview();
    });
    delCell.appendChild(delBtn);

    tr.appendChild(imgCell);
    tr.appendChild(tdWith(name));
    tr.appendChild(tdWith(size));
    tr.appendChild(tdWith(desc));
    tr.appendChild(tdWith(pack));
    tr.appendChild(tdWith(qty));
    tr.appendChild(tdWith(price));
    tr.appendChild(tdWith(total));
    tr.appendChild(tdWith(note));
    tr.appendChild(delCell);
    return tr;
  }

  function bindStaticFields() {
    bindField("qsCoPhone", "pvCoPhone", (v) => v);
    bindField("qsCoAddr", "pvCoAddr", (v) => v);
    bindField("qsQuoteNo", "pvQuoteNo", (v) => normalizeQuoteNoForPdf(v));
    bindField("qsSellerContact", "pvSellerContact", (v) => v);
    bindField("qsSellerEmail", "pvSellerEmail", (v) => v);
    bindField("qsCustName", "pvCustName", (v) => v);
    bindField("qsCustContact", "pvCustContact", (v) => v);
    bindField("qsCustPhone", "pvCustPhone", (v) => v);
    bindField("qsCustAddr", "pvCustAddr", (v) => v);
    bindField("qsSampleFee", "pvSampleFee", (v) => trimMetaText(v));
    bindField("qsSampleLeadTime", "pvSampleLeadTime", (v) => trimMetaText(v));
    const dateEl = el("qsQuoteDate");
    if (dateEl) {
      const run = () => setText("pvQuoteDate", formatQuoteDateIso(dateEl.value || ""));
      dateEl.addEventListener("change", run);
      dateEl.addEventListener("input", run);
    }

    [
      "qsCoName",
      "qsCoPhone",
      "qsCoAddr",
      "qsQuoteNo",
      "qsSellerContact",
      "qsSellerEmail",
      "qsCustName",
      "qsCustContact",
      "qsCustPhone",
      "qsCustAddr",
      "qsQuoteDate",
      "qsSampleFee",
      "qsSampleLeadTime",
    ].forEach((id) => {
      const node = el(id);
      if (!node) {
        return;
      }
      const onMetaEdit = () => {
        markEnglishSnapshotDirty();
        scheduleQuoteSheetMetaSave();
      };
      node.addEventListener("input", onMetaEdit);
      node.addEventListener("change", onMetaEdit);
    });
  }

  function updateTranslateStatus(text, level = STATUS_LEVELS.idle) {
    const node = el("qsTranslateStatus");
    if (!node) {
      return;
    }
    node.textContent = text || "";
    node.classList.remove("is-busy", "is-success", "is-warn", "is-error");
    if (level === STATUS_LEVELS.busy) {
      node.classList.add("is-busy");
    } else if (level === STATUS_LEVELS.success) {
      node.classList.add("is-success");
    } else if (level === STATUS_LEVELS.warn) {
      node.classList.add("is-warn");
    } else if (level === STATUS_LEVELS.error) {
      node.classList.add("is-error");
    }
  }

  function setButtonsBusy(isBusy) {
    const translateBtn = el("qsTranslateEnBtn");
    const exportBtn = el("qsExportPdfBtn");
    const exportUsdBtn = el("qsExportPdfFobUsdBtn");
    if (translateBtn) {
      translateBtn.disabled = isBusy;
    }
    if (exportBtn) {
      exportBtn.disabled = isBusy;
    }
    if (exportUsdBtn) {
      exportUsdBtn.disabled = isBusy;
    }
  }

  function readExportScope() {
    const selected = document.querySelector('input[name="qsExportLangScope"]:checked');
    const v = selected && selected.value ? String(selected.value).trim().toLowerCase() : "cn";
    if (v === "en" || v === "both") {
      return v;
    }
    return "cn";
  }

  function buildQuoteBundleFromForm() {
    const meta = collectMetaBundle();

    const rows = [];
    const body = selFormBody();
    if (body) {
      Array.from(body.querySelectorAll("tr")).forEach((row, idx) => {
        const inputs = Array.from(row.querySelectorAll("input:not(.qs-img-file), textarea"));
        const [nameEl, sizeEl, descEl, packEl, qtyEl, priceEl, totalEl, noteEl] = inputs;
        rows.push({
          line_order: idx,
          name: nameEl?.value ?? "",
          size: sizeEl?.value ?? "",
          desc: descEl?.value ?? "",
          pack: packEl?.value ?? "",
          qty: qtyEl?.value ?? "",
          price: priceEl?.value ?? "",
          total: totalEl?.value ?? "",
          note: noteEl?.value ?? "",
          fob_price: row.dataset.fobPrice ?? "",
          fob_price_text: row.dataset.fobPriceText ?? "",
          fob_price_usd: row.dataset.fobPriceUsd ?? "",
          fob_price_usd_text: row.dataset.fobPriceUsdText ?? "",
          fob_total: row.dataset.fobTotal ?? "",
          fob_total_usd: row.dataset.fobTotalUsd ?? "",
        });
      });
    }

    return { meta, rows };
  }

  async function requestTranslateEnglish() {
    if (enState.translating) {
      return false;
    }

    enState.translating = true;
    setButtonsBusy(true);
    updateTranslateStatus("正在翻译英文内容...", STATUS_LEVELS.busy);

    try {
      const resp = await window.fetch("/api/quote-sheet/translate-en", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bundle: buildQuoteBundleFromForm() }),
      });
      const payload = await resp.json();
      if (!resp.ok || !payload || payload.ok === false) {
        throw new Error(payload?.message || payload?.error || "translate_failed");
      }

      enState.meta = payload.meta_en || {};
      enState.rows = Array.isArray(payload.rows_en) ? payload.rows_en : [];
      enState.labels = payload.labels || {};
      enState.fixed = payload.fixed || {};
      enState.untranslatedFields = Array.isArray(payload.untranslated_fields)
        ? payload.untranslated_fields
        : [];
      enState.ready = true;
      enState.translatedAt = new Date().toISOString();

      if (enState.untranslatedFields.length > 0) {
        updateTranslateStatus(
          `翻译完成，${enState.untranslatedFields.length} 个字段未翻译，已保留原文并标记 [UNTRANSLATED]。`,
          STATUS_LEVELS.warn
        );
      } else {
        updateTranslateStatus("翻译完成，可导出英文 PDF。", STATUS_LEVELS.success);
      }
      return true;
    } catch (err) {
      enState.ready = false;
      enState.meta = null;
      enState.rows = null;
      enState.labels = null;
      enState.fixed = null;
      enState.untranslatedFields = [];
      updateTranslateStatus(`翻译失败：${err?.message || "未知错误"}`, STATUS_LEVELS.error);
      return false;
    } finally {
      enState.translating = false;
      setButtonsBusy(false);
    }
  }

  async function ensureEnglishSnapshotReady() {
    if (enState.ready) {
      return true;
    }
    return requestTranslateEnglish();
  }

  function applyLabelsForLang(lang) {
    const useEn = lang === "en" && enState.labels;
    const pdfRoot = el("quotePdfRoot");
    if (pdfRoot) {
      pdfRoot.setAttribute("data-pdf-lang", lang === "en" ? "en" : "cn");
    }
    document.querySelectorAll("[data-pdf-lbl]").forEach((node) => {
      const key = node.getAttribute("data-pdf-lbl");
      if (!key) {
        return;
      }
      const zh = node.getAttribute("data-pdf-zh");
      if (!zh) {
        node.setAttribute("data-pdf-zh", node.innerHTML);
      }
      if (useEn && Object.prototype.hasOwnProperty.call(enState.labels, key)) {
        node.innerHTML = String(enState.labels[key] ?? "");
      } else {
        node.innerHTML = node.getAttribute("data-pdf-zh") || "";
      }
    });
    currentPdfLang = lang;
  }

  function resetPdfToChinese() {
    applyLabelsForLang("cn");
    syncAllPreview();
  }

  function fileStemByLang(lang) {
    const custRaw =
      lang === "en" && enState.meta?.cust_name ? String(enState.meta.cust_name) : el("qsCustName")?.value || "客户";
    const dateRaw =
      lang === "en" && enState.meta?.quote_date_iso
        ? String(enState.meta.quote_date_iso)
        : formatQuoteDateIso(el("qsQuoteDate")?.value || "") || todayIsoDate();
    const cust = padUrlFilenamePart(custRaw || (lang === "en" ? "Customer" : "客户"));
    const dateDisp = padUrlFilenamePart(dateRaw);
    return lang === "en" ? `Quotation_${cust}_${dateDisp}` : `报价单_${cust}_${dateDisp}`;
  }

  function applyProductRowImage(tr, dataUrl, options = {}) {
    if (!tr) {
      return;
    }
    const ph = tr.querySelector(".qs-img-placeholder");
    const img = tr.querySelector(".qs-form-thumb");
    if (!ph || !img) {
      return;
    }
    const url = String(dataUrl || "").trim();
    if (url.startsWith("data:")) {
      const userUploaded = options.userUploaded || img.dataset.userUploaded === "1";
      isAcceptableProductImageDataUrl(url, (ok) => {
        if (!ok) {
          img.src = "";
          img.classList.add("hidden");
          ph.classList.remove("hidden");
          return;
        }
        img.onerror = () => {
          img.onerror = null;
          img.src = "";
          img.classList.add("hidden");
          ph.classList.remove("hidden");
        };
        img.src = url;
        img.classList.remove("hidden");
        ph.classList.add("hidden");
      }, { userUploaded });
      return;
    }
    img.src = "";
    img.classList.add("hidden");
    ph.classList.remove("hidden");
  }

  /** 客户报价单：尺寸列仅保留成品尺寸，去掉裁片名称 */
  function sanitizeCustomerSizeText(raw) {
    let s = String(raw ?? "").trim();
    if (!s || s === "-" || s === "—") return "";
    const slashParts = s.split(/\s*\/\s*/);
    if (slashParts.length > 1 && /前片|后片|底片|侧片|拉链|裁片/.test(slashParts[1] || "")) {
      return slashParts[0].trim();
    }
    const lines = s
      .split(/\r?\n/)
      .map((x) => x.trim())
      .filter(Boolean);
    if (lines.length > 1) {
      const dim = lines.find(
        (ln) => /cm|×|mm/i.test(ln) && !/前片|后片|底片|侧片|拉链弧形盖/.test(ln),
      );
      if (dim) return dim;
      if (/前片|后片|底片|侧片/.test(lines[0])) return "";
    }
    if (/前片|后片|底片|侧片|拉链弧形盖/.test(s) && !/cm|×/i.test(s)) return "";
    return s;
  }

  /** 客户报价单：包装列去掉系统估算等内部口径，禁止用「1个」补位 */
  function sanitizeCustomerPackText(raw) {
    let s = String(raw ?? "")
      .replace(/\s*\[UNTRANSLATED\]\s*/gi, "")
      .trim();
    if (!s || s === "-" || s === "—" || s === "/") return "";
    const internal =
      /系统估算|系统推断|系统推算|系统近似|AI估算|AI推断|本地兜底|推断待核|推理待核/gi;
    const onlyInternal =
      /^(?:系统估算|系统推断|系统推算|系统近似|AI估算|AI推断|本地兜底|推断|估算|待核|推理待核|—|-|\/|\s*)+$/i;
    const parts = s
      .split(/\s*\/\s*/)
      .map((p) => p.trim())
      .filter(Boolean)
      .map((p) => p.replace(internal, "").trim())
      .filter((p) => p && !onlyInternal.test(p));
    if (parts.length) return parts.join(" / ");
    if (onlyInternal.test(s) || internal.test(s)) return "";
    const m = s.match(/\d+(?:\.\d+)?\s*(?:个|套|条|张|件|只|卷|米|码|㎡|m²)/i);
    if (m && !onlyInternal.test(m[0])) return m[0].trim();
    return "";
  }

  let quoteSheetExportLangDefault = "cn";
  let activeQuoteSeriesUid = "";
  let metaSaveTimer = null;
  let metaSaveInflight = null;

  function collectMetaBundle() {
    return {
      co_name: el("qsCoName")?.value ?? "",
      co_phone: el("qsCoPhone")?.value ?? "",
      co_addr: el("qsCoAddr")?.value ?? "",
      quote_no: el("qsQuoteNo")?.value ?? "",
      seller_contact: el("qsSellerContact")?.value ?? "",
      seller_email: el("qsSellerEmail")?.value ?? "",
      cust_name: el("qsCustName")?.value ?? "",
      cust_contact: el("qsCustContact")?.value ?? "",
      cust_phone: el("qsCustPhone")?.value ?? "",
      cust_addr: el("qsCustAddr")?.value ?? "",
      quote_date_iso: el("qsQuoteDate")?.value ?? "",
      sample_required: readSampleRequiredFromForm(),
      sample_fee: trimMetaText(el("qsSampleFee")?.value ?? ""),
      sample_lead_time: trimMetaText(el("qsSampleLeadTime")?.value ?? ""),
    };
  }

  function updateMetaSaveStatus(text, level = STATUS_LEVELS.idle) {
    const node = el("qsMetaSaveStatus");
    if (!node) {
      return;
    }
    node.textContent = text || "";
    node.classList.remove("is-busy", "is-success", "is-warn", "is-error");
    if (level === STATUS_LEVELS.busy) {
      node.classList.add("is-busy");
    } else if (level === STATUS_LEVELS.success) {
      node.classList.add("is-success");
    } else if (level === STATUS_LEVELS.warn) {
      node.classList.add("is-warn");
    } else if (level === STATUS_LEVELS.error) {
      node.classList.add("is-error");
    }
  }

  /** 导出前尝试保存；失败不抛错，不阻断 PDF。 */
  async function trySaveQuoteSheetMetaForExport() {
    try {
      return await saveQuoteSheetMeta({
        silent: true,
        nonBlocking: true,
        forExport: true,
      });
    } catch {
      return { ok: false, error: "save_failed", message: "save_exception" };
    }
  }

  async function saveQuoteSheetMeta(options = {}) {
    const uid = String(options.seriesUid || activeQuoteSeriesUid || "").trim();
    const nonBlocking = Boolean(options.nonBlocking || options.forExport || options.silent);
    if (!uid) {
      return { ok: false, skipped: true, reason: "no_quote_uid" };
    }
    const meta = collectMetaBundle();
    const quoteNoManual = Boolean(String(meta.quote_no || "").trim());
    if (metaSaveInflight) {
      try {
        await metaSaveInflight;
      } catch {
        /* ignore */
      }
    }
    if (!options.silent) {
      updateMetaSaveStatus("正在保存客户资料…", STATUS_LEVELS.busy);
    }
    const task = window
      .fetch(`/api/my/quotes/${encodeURIComponent(uid)}/quote-sheet-meta`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ meta, quote_no_manual: quoteNoManual }),
      })
      .then(async (resp) => {
        const payload = await resp.json().catch(() => ({}));
        if (!resp.ok || !payload?.ok) {
          const errMsg = String(payload?.message || payload?.error || `HTTP ${resp.status}`).trim();
          if (nonBlocking) {
            return { ok: false, error: payload?.error || "save_failed", message: errMsg };
          }
          throw new Error(errMsg);
        }
        if (!options.silent) {
          updateMetaSaveStatus("客户资料已保存", STATUS_LEVELS.success);
        }
        return payload;
      })
      .catch((err) => {
        const errMsg = String(err?.message || err || "save_failed").trim();
        if (nonBlocking) {
          return { ok: false, error: "save_failed", message: errMsg };
        }
        if (!options.silent) {
          updateMetaSaveStatus(`保存失败：${errMsg}`, STATUS_LEVELS.error);
        }
        throw err;
      })
      .finally(() => {
        metaSaveInflight = null;
      });
    metaSaveInflight = task;
    return task;
  }

  function scheduleQuoteSheetMetaSave() {
    if (!activeQuoteSeriesUid) {
      return;
    }
    if (metaSaveTimer) {
      window.clearTimeout(metaSaveTimer);
    }
    metaSaveTimer = window.setTimeout(() => {
      metaSaveTimer = null;
      void saveQuoteSheetMeta({ silent: true, nonBlocking: true });
    }, 700);
  }

  function setQuoteSheetExportLangDefault(prefill) {
    const lang = String(prefill?.suggested_export_lang || "cn").trim().toLowerCase();
    quoteSheetExportLangDefault = lang === "en" ? "en" : "cn";
    if (typeof window !== "undefined") {
      window.__quoteSheetExportLangDefault = quoteSheetExportLangDefault;
      window.__quoteSheetFobQuote = Boolean(prefill?.fob_quote);
    }
  }

  /** FOB 报价单默认导出英文模板；非 FOB 保持中文 */
  function resolveExportLang(scope) {
    const selected = scope || readExportScope();
    if (selected === "en" || selected === "both") {
      return selected;
    }
    if (quoteSheetExportLangDefault === "en") {
      return "en";
    }
    return "cn";
  }

  function fillProductRowFromData(tr, row) {
    if (!tr || !row || typeof row !== "object") {
      return;
    }
    const inputs = Array.from(tr.querySelectorAll("input:not(.qs-img-file), textarea"));
    const [nameEl, sizeEl, descEl, packEl, qtyEl, priceEl, totalEl, noteEl] = inputs;
    if (nameEl) nameEl.value = row.name ?? "";
    if (sizeEl) sizeEl.value = sanitizeCustomerSizeText(row.size ?? "");
    if (descEl) {
      const rowDesc = row.desc != null && row.desc !== undefined ? String(row.desc).trim() : "";
      descEl.value = buildBriefDescForPdf(row.name ?? nameEl?.value ?? "", rowDesc, "cn");
    }
    if (packEl) packEl.value = sanitizeCustomerPackText(row.pack ?? "");
    if (qtyEl) qtyEl.value = row.qty ?? "";
    if (priceEl) priceEl.value = row.price ?? "";
    if (totalEl) totalEl.value = row.total ?? formatMoneyByLang(lineTotal(row.qty, row.price), "cn");
    if (noteEl) noteEl.value = row.note ?? "";
    applyRowFobDataset(tr, row);
    applyProductRowImage(tr, row.image_data_url);
  }

  function applyPrefill(prefill) {
    if (!prefill || typeof prefill !== "object") {
      return false;
    }
    activeQuoteSeriesUid = String(prefill.quote_series_uid || "").trim();
    setQuoteSheetExportLangDefault(prefill);
    const meta = prefill.meta && typeof prefill.meta === "object" ? prefill.meta : {};
    const setVal = (id, key) => {
      const node = el(id);
      if (node && meta[key] != null) {
        node.value = String(meta[key] ?? "");
      }
    };
    setVal("qsCoName", "co_name");
    setVal("qsCoPhone", "co_phone");
    setVal("qsCoAddr", "co_addr");
    setVal("qsQuoteNo", "quote_no");
    setVal("qsSellerContact", "seller_contact");
    setVal("qsSellerEmail", "seller_email");
    setVal("qsCustName", "cust_name");
    setVal("qsCustContact", "cust_contact");
    setVal("qsCustPhone", "cust_phone");
    setVal("qsCustAddr", "cust_addr");
    setVal("qsQuoteDate", "quote_date_iso");
    setVal("qsSampleFee", "sample_fee");
    setVal("qsSampleLeadTime", "sample_lead_time");
    updateSampleFieldsUi();
    syncSamplePdfPreview(currentPdfLang);
    if (prefill.usd_cny_rate != null && el("qsUsdCnyRate")) {
      el("qsUsdCnyRate").value = String(prefill.usd_cny_rate);
    }
    if (el("qsFobYuanPerPc")) {
      if (prefill.fob_yuan_per_pc != null && String(prefill.fob_yuan_per_pc).trim() !== "") {
        el("qsFobYuanPerPc").value = String(prefill.fob_yuan_per_pc);
      } else {
        el("qsFobYuanPerPc").value = "";
      }
    }
    if (typeof window !== "undefined") {
      window.__quoteUsdSnapshot = {
        usdCnyRate: prefill.usd_cny_rate,
        fobYuanPerPc:
          prefill.fob_yuan_per_pc != null && String(prefill.fob_yuan_per_pc).trim() !== ""
            ? prefill.fob_yuan_per_pc
            : "",
      };
    }
    const tbody = selFormBody();
    if (!tbody) {
      return false;
    }
    tbody.innerHTML = "";
    const rows = Array.isArray(prefill.rows) ? prefill.rows.slice(0, MAX_ROWS) : [];
    const list = rows.length ? rows : [{}];
    list.forEach((row) => {
      const tr = createFormProductRow();
      tbody.appendChild(tr);
      fillProductRowFromData(tr, row);
    });
    enState.ready = false;
    enState.meta = null;
    enState.rows = null;
    markEnglishSnapshotDirty();
    applyLabelsForLang("cn");
    void (async () => {
      await bootstrapPayeeFromCompanyName(meta.co_name || el("qsCoName")?.value || defaults.coName);
      syncAllPreview();
    })();
    return true;
  }

  function mapQuoteRecordToQuotationForm(prefill) {
    return prefill;
  }

  function mapAdminCorrectionToQuotationForm(prefill) {
    return prefill;
  }

  async function exportPdf(
    asFobUsdPdf = false,
    lang = "cn",
    customFilenameStem = "",
    skipConfirm = false,
    exportOptions = {},
  ) {
    const isPrimaryExport = !exportOptions.preflightSkipped;
    if (isPrimaryExport) {
      if (exportGuard.inflight) {
        return;
      }
      exportGuard.inflight = true;
    }
    try {
      if (!exportOptions.preflightSkipped) {
        const preflightOk = await ensureExportPreflight();
        if (!preflightOk) {
          return;
        }
        exportOptions = { ...exportOptions, preflightSkipped: true };
      }
      await runExportPdfBody(asFobUsdPdf, lang, customFilenameStem, skipConfirm, exportOptions);
    } finally {
      if (isPrimaryExport) {
        exportGuard.inflight = false;
      }
    }
  }

  async function runExportPdfBody(
    asFobUsdPdf = false,
    lang = "cn",
    customFilenameStem = "",
    skipConfirm = false,
    exportOptions = {},
  ) {
    const sampleReady = await ensureSampleExportReady(lang);
    if (!sampleReady.ok) {
      return;
    }
    if (sampleReady.saved?.ok) {
      updateMetaSaveStatus("客户资料已保存", STATUS_LEVELS.success);
    } else {
      updateMetaSaveStatus(
        "客户资料未保存，本次将使用页面当前填写内容导出。",
        STATUS_LEVELS.warn,
      );
    }
    await inspectPayeeForExport();
    applyLabelsForLang(lang);
    syncAllPreview();
    if (asFobUsdPdf) {
      syncProductPreview(true, currentPdfLang);
    }

    const restoreLangAfterExport = () => {
      if (asFobUsdPdf) {
        syncProductPreview(false, currentPdfLang);
      }
      if (lang !== "cn") {
        resetPdfToChinese();
      }
    };

    const isEn = lang === "en";
    const kind = isEn
      ? asFobUsdPdf
        ? "FOB USD version"
        : "RMB version"
      : asFobUsdPdf
        ? "FOB·美金折算版（单价已含FOB加价）"
        : "人民币";
    const confirmMsg = isEn
      ? `Confirm downloading quotation PDF (${kind})? The browser will save it to the default downloads folder.`
      : `确认下载报价单 PDF（${kind}）？浏览器将把文件保存到默认下载目录。`;
    if (!skipConfirm && !window.confirm(confirmMsg)) {
      restoreLangAfterExport();
      return;
    }

    const stem = customFilenameStem || fileStemByLang(lang);
    const filename = asFobUsdPdf ? `${stem}_FOB_USD.pdf` : `${stem}.pdf`;
    const rootEl = el("quotePdfRoot");
    const exportBtn = el("qsExportPdfBtn");
    const exportUsdBtn = el("qsExportPdfFobUsdBtn");
    if (!rootEl) {
      restoreLangAfterExport();
      return;
    }

    const prevTitle = document.title;
    const printFallback = () => {
      document.title = filename.replace(/\.pdf$/i, "");
      window.print();
      document.title = prevTitle;
    };

    const unlock = () => {
      if (exportBtn) {
        exportBtn.disabled = false;
      }
      if (exportUsdBtn) {
        exportUsdBtn.disabled = false;
      }
    };

    if (exportBtn) {
      exportBtn.disabled = true;
    }
    if (exportUsdBtn) {
      exportUsdBtn.disabled = true;
    }

    if (typeof window.html2pdf !== "function") {
      window.alert(
        isEn
          ? 'PDF component is not loaded. The system print dialog will open; please choose "Microsoft Print to PDF".'
          : "PDF 组件未加载成功，将改用系统打印。请在打印对话框中选择「Microsoft Print to PDF」。"
      );
      printFallback();
      document.title = prevTitle;
      unlock();
      restoreLangAfterExport();
      return;
    }

    document.title = filename.replace(/\.pdf$/i, "");

    const pdfOpt = {
        margin: [0, 0, 0, 0],
        filename,
        image: { type: "jpeg", quality: 0.94 },
        html2canvas: {
          scale: 2,
          useCORS: true,
          logging: false,
          scrollY: 0,
          scrollX: 0,
          onclone: (doc) => {
            const wrap = doc.querySelector(".qs-pdf-offscreen");
            if (wrap) {
              wrap.style.setProperty("position", "static", "important");
              wrap.style.setProperty("left", "0", "important");
              wrap.style.setProperty("top", "0", "important");
              wrap.style.setProperty("width", "210mm", "important");
              wrap.style.setProperty("max-width", "210mm", "important");
              wrap.style.setProperty("overflow", "visible", "important");
              wrap.style.setProperty("z-index", "0", "important");
            }
            const rootNode = doc.getElementById("quotePdfRoot");
            if (rootNode) {
              rootNode.style.setProperty("position", "relative", "important");
              rootNode.style.setProperty("left", "0", "important");
              rootNode.style.setProperty("top", "0", "important");
              rootNode.style.setProperty("min-height", "0", "important");
              rootNode.style.setProperty("max-width", "210mm", "important");
              rootNode.style.setProperty("overflow", "visible", "important");
              rootNode.style.setProperty("box-shadow", "none", "important");
            }
            const pdfTable = doc.querySelector(".qs-pdf-table");
            if (pdfTable) {
              pdfTable.style.setProperty("width", "100%", "important");
              pdfTable.style.setProperty("table-layout", "fixed", "important");
            }
            doc.querySelectorAll(".qs-pdf-table col.col-size").forEach((col) => {
              col.style.setProperty("width", "14%", "important");
            });
            doc.querySelectorAll(".qs-pdf-table col.col-desc").forEach((col) => {
              col.style.setProperty("width", "16%", "important");
            });
            doc.querySelectorAll(".qs-pdf-table th.col-size, .qs-pdf-table th.col-desc, .qs-pdf-table th.col-pack").forEach((cell) => {
              cell.style.setProperty("white-space", "normal", "important");
              cell.style.setProperty("overflow", "visible", "important");
            });
            doc.querySelectorAll(".qs-pdf-table td.col-size, .qs-pdf-table td.col-pack").forEach((cell) => {
              cell.style.setProperty("display", "table-cell", "important");
              cell.style.setProperty("white-space", "normal", "important");
              cell.style.setProperty("overflow", "visible", "important");
              cell.style.setProperty("word-break", "normal", "important");
              cell.style.setProperty("overflow-wrap", "break-word", "important");
              cell.style.setProperty("line-height", "1.25", "important");
              cell.style.setProperty("height", "auto", "important");
              cell.style.setProperty("max-width", "none", "important");
              cell.style.setProperty("padding", "5px 3px", "important");
              cell.style.setProperty("vertical-align", "middle", "important");
              cell.style.setProperty("border", "1px solid #000", "important");
            });
            doc.querySelectorAll(".qs-pdf-table td.col-desc").forEach((cell) => {
              cell.style.setProperty("display", "table-cell", "important");
              cell.style.setProperty("white-space", "normal", "important");
              cell.style.setProperty("line-height", "1.25", "important");
              cell.style.setProperty("overflow", "hidden", "important");
              cell.style.setProperty("text-overflow", "ellipsis", "important");
              cell.style.setProperty("max-height", "3.75em", "important");
              cell.style.setProperty("word-break", "break-word", "important");
              cell.style.setProperty("height", "auto", "important");
              cell.style.setProperty("min-height", "0", "important");
              cell.style.setProperty("padding", "5px 4px", "important");
              cell.style.setProperty("vertical-align", "middle", "important");
              cell.style.setProperty("border", "1px solid #000", "important");
            });
            doc.querySelectorAll(".qs-pdf-table tbody tr:last-child > td").forEach((cell) => {
              cell.style.setProperty("border-bottom", "1px solid #000", "important");
            });
            const remarkLine = doc.getElementById("pvPdfRemarkLine");
            if (remarkLine) {
              remarkLine.hidden = false;
              remarkLine.style.setProperty("display", "block", "important");
              remarkLine.style.setProperty("visibility", "visible", "important");
            }
            const remarkText = doc.getElementById("pvPdfRemark");
            if (remarkText) {
              remarkText.style.setProperty("display", "inline-block", "important");
              remarkText.style.setProperty("visibility", "visible", "important");
              remarkText.style.setProperty("color", "#000", "important");
              remarkText.style.setProperty("max-height", "none", "important");
              remarkText.style.setProperty("overflow", "visible", "important");
            }
            const yellowFoot = doc.getElementById("pvValidityYellowFoot");
            if (yellowFoot) {
              yellowFoot.hidden = false;
              yellowFoot.style.setProperty("display", "table-footer-group", "important");
            }
            doc.querySelectorAll(".qs-pdf-yellow-cell").forEach((cell) => {
              cell.style.setProperty("display", "table-cell", "important");
              cell.style.setProperty("background", "#ffff00", "important");
              cell.style.setProperty("color", "#f00", "important");
              cell.style.setProperty("text-align", "center", "important");
              cell.style.setProperty("border", "1px solid #000", "important");
              cell.style.setProperty("-webkit-print-color-adjust", "exact", "important");
              cell.style.setProperty("print-color-adjust", "exact", "important");
            });
            doc.querySelectorAll(".qs-pdf-table tbody tr").forEach((row) => {
              row.style.setProperty("page-break-inside", "avoid", "important");
            });
            doc.querySelectorAll(".qs-pdf-meta-right-shifted").forEach((cell) => {
              cell.style.setProperty("text-align", "left", "important");
              cell.style.setProperty("padding-right", "6px", "important");
              cell.style.setProperty("padding-left", "0", "important");
              cell.style.setProperty("white-space", "nowrap", "important");
            });
            doc.querySelectorAll(".qs-pdf-meta-right-shifted .qs-pdf-meta-value").forEach((node) => {
              node.style.setProperty("display", "inline-block", "important");
              node.style.setProperty("overflow", "hidden", "important");
              node.style.setProperty("text-overflow", "ellipsis", "important");
              node.style.setProperty("line-height", "1.2", "important");
              if (node.classList.contains("qs-pdf-meta-value-quote-no")) {
                node.style.setProperty("white-space", "nowrap", "important");
                node.style.setProperty("word-break", "keep-all", "important");
                node.style.setProperty("max-height", "none", "important");
                node.style.setProperty("font-size", "9pt", "important");
              } else {
                node.style.setProperty("word-break", "break-all", "important");
                node.style.setProperty("max-height", "2.4em", "important");
              }
            });
            const metaTable = doc.querySelector(".qs-pdf-meta-table");
            if (metaTable) {
              metaTable.style.setProperty("width", "100%", "important");
              metaTable.style.setProperty("table-layout", "fixed", "important");
            }
          },
        },
        jsPDF: { unit: "mm", format: "a4", orientation: "portrait", compress: true },
        pagebreak: { mode: ["css", "legacy"] },
    };

    const worker = window.html2pdf().set(pdfOpt).from(rootEl).save();

    const finish = () => {
      document.title = prevTitle;
      unlock();
      restoreLangAfterExport();
    };

    if (worker && typeof worker.then === "function") {
      try {
        await worker;
        finish();
      } catch {
        window.alert(
          isEn
            ? 'Automatic PDF generation failed. The print dialog will open; please choose "Print to PDF".'
            : "自动生成 PDF 失败，将打开打印窗口。请选择「打印到 PDF」。"
        );
        printFallback();
        finish();
      }
      return;
    }
    finish();
  }

  async function exportByScope(asFobUsdPdf = false, skipConfirm = false) {
    const scope = readExportScope();
    const lang = resolveExportLang(scope);
    const preflightOpts = { preflightSkipped: false };
    if (lang === "cn") {
      await exportPdf(asFobUsdPdf, "cn", "", skipConfirm, preflightOpts);
      return;
    }

    const ok = await ensureEnglishSnapshotReady();
    if (!ok) {
      window.alert(
        lang === "both"
          ? "英文翻译未完成，无法执行中英双导出。"
          : "英文翻译未完成，无法导出英文版。",
      );
      return;
    }

    if (lang === "en") {
      await exportPdf(asFobUsdPdf, "en", "", skipConfirm, preflightOpts);
      return;
    }

    await exportPdf(asFobUsdPdf, "cn", "", skipConfirm, preflightOpts);
    window.setTimeout(
      () => void exportPdf(asFobUsdPdf, "en", "", skipConfirm, { preflightSkipped: true }),
      260,
    );
  }

  async function exportDirect(options = {}) {
    const opts = options && typeof options === "object" ? options : {};
    switchView("quote");
    syncAllPreview();
    await new Promise((resolve) => window.setTimeout(resolve, 150));
    const fobUsd = Boolean(opts.fobUsd);
    const langOpt = String(opts.lang || "").trim().toLowerCase();
    const lang =
      langOpt === "en" || langOpt === "cn"
        ? langOpt
        : resolveExportLang(opts.langScope || readExportScope());
    const skipConfirm = Boolean(opts.skipConfirm);
    const preflightOpts = { preflightSkipped: false };
    const preflightSkipped = { preflightSkipped: true };
    if (lang === "en" || opts.langScope === "en") {
      const ok = await ensureEnglishSnapshotReady();
      if (!ok) {
        return false;
      }
      await exportPdf(fobUsd, "en", opts.filenameStem || "", skipConfirm, preflightOpts);
      return true;
    }
    if (opts.langScope === "both") {
      const ok = await ensureEnglishSnapshotReady();
      if (!ok) {
        return false;
      }
      await exportPdf(fobUsd, "cn", opts.filenameStem || "", skipConfirm, preflightOpts);
      window.setTimeout(
        () => void exportPdf(fobUsd, "en", opts.filenameStem || "", skipConfirm, preflightSkipped),
        260,
      );
      return true;
    }
    if (lang === "en") {
      const ok = await ensureEnglishSnapshotReady();
      if (!ok) {
        return false;
      }
      await exportPdf(fobUsd, "en", opts.filenameStem || "", skipConfirm, preflightOpts);
      return true;
    }
    await exportPdf(fobUsd, "cn", opts.filenameStem || "", skipConfirm, preflightOpts);
    return true;
  }

  async function openFromQuoteRecord(seriesUid, options = {}) {
    const uid = String(seriesUid || "").trim();
    if (!uid) {
      return false;
    }
    const source = String(options.source || "record").trim() || "record";
    try {
      const resp = await window.fetch(
        `/api/my/quotes/${encodeURIComponent(uid)}/quote-sheet-prefill?source=${encodeURIComponent(source)}`,
      );
      const payload = await resp.json().catch(() => ({}));
      if (!resp.ok || !payload?.ok) {
        throw new Error(payload?.message || payload?.error || `HTTP ${resp.status}`);
      }
      switchView("quote");
      applyPrefill(mapQuoteRecordToQuotationForm(payload));
      activeQuoteSeriesUid = uid;
      if (options.exportMode === "pdf_rmb") {
        await exportDirect({ fobUsd: false, skipConfirm: true });
      } else if (options.exportMode === "pdf_fob") {
        await exportDirect({ fobUsd: true, skipConfirm: true });
      }
      return true;
    } catch (err) {
      window.alert(`加载报价单数据失败：${err?.message || err}`);
      return false;
    }
  }

  function init() {
    applyDefaultsToForm();
    applyLabelsForLang("cn");
    bindStaticFields();
    bindPayeeCompanyField();
    updateSampleFieldsUi();
    const tbody = selFormBody();
    if (tbody && tbody.rows.length === 0) {
      tbody.appendChild(createFormProductRow());
    }
    el("navQuoteSheet")?.addEventListener("click", () => {
      switchView("quote");
      syncAllPreview();
    });
    document.querySelector('.session-item[data-route="chat"]')?.addEventListener("click", () => switchView("chat"));

    el("qsAddProductRow")?.addEventListener("click", () => {
      const tb = selFormBody();
      if (!tb || tb.rows.length >= MAX_ROWS) {
        return;
      }
      tb.appendChild(createFormProductRow());
      markEnglishSnapshotDirty();
      syncProductPreview();
    });

    el("qsExportPdfBtn")?.addEventListener("click", () => exportByScope(false));
    el("qsExportPdfFobUsdBtn")?.addEventListener("click", () => exportByScope(true));
    el("qsTranslateEnBtn")?.addEventListener("click", async () => {
      const ok = await requestTranslateEnglish();
      if (!ok) {
        return;
      }
      const scope = readExportScope();
      if (scope === "both") {
        exportPdf(false, "cn", "", false, { preflightSkipped: false });
        window.setTimeout(() => exportPdf(false, "en", "", false, { preflightSkipped: true }), 260);
        return;
      }
      exportPdf(false, "en", "", false, { preflightSkipped: false });
    });

    document.querySelectorAll('input[name="qsExportLangScope"]').forEach((node) => {
      node.addEventListener("change", () => {
        if (readExportScope() !== "cn" && !enState.ready) {
          updateTranslateStatus("请选择“翻译成英文版”后再导出英文。", STATUS_LEVELS.warn);
          return;
        }
        if (readExportScope() === "cn") {
          updateTranslateStatus("", STATUS_LEVELS.idle);
        }
      });
    });

    syncAllPreview();
    void bootstrapPayeeFromCompanyName(el("qsPayeeCompany")?.value || el("qsCoName")?.value || defaults.coName);
  }

  window.QuoteSheetBridge = {
    applyPrefill,
    saveQuoteSheetMeta,
    trySaveQuoteSheetMetaForExport,
    collectMetaBundle,
    exportDirect,
    exportByScope,
    exportPdf,
    openFromQuoteRecord,
    mapQuoteRecordToQuotationForm,
    mapAdminCorrectionToQuotationForm,
    fillProductRowFromData,
    syncAllPreview,
    ensurePayeeAccountReadyForExport,
    validateBeforeExport,
    ensureExportPreflight,
    selectPayeeAccount,
    normalizeSampleRequired,
    validateSampleExportState(meta) {
      const fee = trimMetaText(meta?.sample_fee);
      const lead = trimMetaText(meta?.sample_lead_time);
      const pdfMode = fee && lead ? "fee_lead" : fee || lead ? "partial" : "empty";
      return { ok: true, sample_required: "", pdf_mode: pdfMode, status_text: "" };
    },
    resolveFooterCompanyNameForPdf,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
