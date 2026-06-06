/** 业务员/客户可见数字：最多 1 位小数，整数不带 .0 */
const DISPLAY_MAX_DECIMALS = 1;

function roundDisplayNumber(value, maxDecimals = DISPLAY_MAX_DECIMALS) {
  const x = Number(value);
  if (!Number.isFinite(x)) return NaN;
  const factor = 10 ** maxDecimals;
  return Math.round(x * factor) / factor;
}

function formatDisplayNumber(value, maxDecimals = DISPLAY_MAX_DECIMALS) {
  const x = roundDisplayNumber(value, maxDecimals);
  if (!Number.isFinite(x)) return "";
  if (Math.abs(x - Math.round(x)) < 1e-9) return String(Math.round(x));
  const text = x.toFixed(maxDecimals);
  return text.replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
}

function formatDisplayMoneyCny(value, maxDecimals = DISPLAY_MAX_DECIMALS) {
  const n = formatDisplayNumber(value, maxDecimals);
  return n ? `${n}元` : "-";
}

function formatNumbersInDisplayText(raw, maxDecimals = DISPLAY_MAX_DECIMALS) {
  if (raw == null || raw === "" || raw === "-") return raw;
  return String(raw).replace(/\d+\.\d+/g, (match) => {
    const x = Number.parseFloat(match);
    return Number.isFinite(x) ? formatDisplayNumber(x, maxDecimals) : match;
  });
}
