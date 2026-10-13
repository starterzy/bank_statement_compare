// 前端逻辑：公司/账户/月份选择、流水查询展示、对账表单提交。
const companySelect = document.getElementById("company");
const accountSelect = document.getElementById("account");
const yearSelect = document.getElementById("year");
const monthSelect = document.getElementById("month");
const queryBtn = document.getElementById("query_btn");
const queryResult = document.getElementById("query_result");
const form = document.getElementById("form");
const bankInput = document.getElementById("bank");
const dbInput = document.getElementById("db");
const dbUploadLabel = document.getElementById("db_upload_label");
const statusEl = document.getElementById("status");
const summaryEl = document.getElementById("summary");
const downloadEl = document.getElementById("download");
const thinkingEl = document.getElementById("thinking");
const thinkingBodyEl = document.getElementById("thinking_body");
const mappingEl = document.getElementById("mapping");

// 公司列表（含 org/book/accasoa），按 org 索引。
let companies = [];

function selectedCompany() {
  return companies.find((c) => c.org === companySelect.value);
}

async function loadCompanies() {
  companySelect.innerHTML = "";
  const opt = document.createElement("option");
  opt.value = "";
  opt.textContent = "— 请选择公司 —";
  companySelect.appendChild(opt);
  try {
    const resp = await fetch("/api/companies");
    const data = await resp.json();
    if (data.error) {
      queryResult.textContent = "错误：" + data.error;
      return;
    }
    companies = data.companies || [];
    for (const c of companies) {
      const o = document.createElement("option");
      o.value = c.org;
      o.textContent = c.name;
      companySelect.appendChild(o);
    }
  } catch (e) {
    queryResult.textContent = "错误：" + e;
  }
}

async function loadAccounts() {
  accountSelect.innerHTML = "";
  const def = document.createElement("option");
  def.value = "";
  def.textContent = "不选择 · 对照所有账户";
  accountSelect.appendChild(def);
  const c = selectedCompany();
  if (!c) return;
  try {
    const resp = await fetch("/api/bank_accounts?org=" + encodeURIComponent(c.org));
    const data = await resp.json();
    if (data.error) {
      queryResult.textContent = "错误：" + data.error;
      return;
    }
    for (const a of data.accounts || []) {
      const o = document.createElement("option");
      o.value = a.f11;
      o.textContent = a.name + "（" + a.code + "）";
      accountSelect.appendChild(o);
    }
  } catch (e) {
    queryResult.textContent = "错误：" + e;
  }
}

async function loadYears() {
  yearSelect.innerHTML = "";
  const c = selectedCompany();
  if (!c) return;
  try {
    const resp = await fetch("/api/years?book=" + encodeURIComponent(c.book) +
      "&accasoa=" + encodeURIComponent(c.accasoa));
    const data = await resp.json();
    if (data.error) return;
    for (const y of data.years || []) {
      const o = document.createElement("option");
      o.value = y;
      o.textContent = y + " 年";
      yearSelect.appendChild(o);
    }
  } catch (e) {}
}

function onCompanyChange() {
  loadAccounts();
  loadYears();
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
  }[ch]));
}

function stat(k, v) {
  return '<div class="stat"><span class="k">' + esc(k) + '</span><span class="v">' + esc(v) + "</span></div>";
}

function renderStatement(d) {
  const overview =
    '<div class="overview">' +
    stat("期初余额", d.opening) +
    stat("借方(收)合计", d.total_debit) +
    stat("贷方(付)合计", d.total_credit) +
    stat("期末余额", d.closing) +
    stat("笔数", d.count) +
    "</div>";

  let monthly =
    "<h3>月度发生额</h3><table><thead><tr><th>月份</th><th>借方(收)</th><th>贷方(付)</th><th>笔数</th><th>期末余额</th></tr></thead><tbody>";
  for (const m of d.monthly || []) {
    const hl = d.selected_month && m.month === d.selected_month ? ' class="hl"' : "";
    monthly +=
      "<tr" + hl + "><td>" + esc(m.month) + "</td>" +
      '<td class="num">' + esc(m.debit) + "</td>" +
      '<td class="num">' + esc(m.credit) + "</td>" +
      '<td class="num">' + esc(m.count) + "</td>" +
      '<td class="num">' + esc(m.balance) + "</td></tr>";
  }
  monthly += "</tbody></table>";

  let txs =
    "<h3>每笔流水（" + esc(d.count) + " 笔）</h3>" +
    "<table><thead><tr><th>日期</th><th>凭证号</th><th>序号</th><th>摘要</th><th>借方(收)</th><th>贷方(付)</th></tr></thead><tbody>";
  for (const t of d.transactions || []) {
    txs +=
      "<tr><td>" + esc(t.date) + "</td>" +
      "<td>" + esc(t.voucher_no) + "</td>" +
      '<td class="num">' + esc(t.detail_index) + "</td>" +
      "<td>" + esc(t.summary) + "</td>" +
      '<td class="num">' + esc(t.debit) + "</td>" +
      '<td class="num">' + esc(t.credit) + "</td></tr>";
  }
  txs += "</tbody></table>";

  queryResult.innerHTML = overview + monthly + txs;
}

async function queryStatement() {
  const c = selectedCompany();
  if (!c) {
    queryResult.textContent = "请先选择公司";
    return;
  }
  queryResult.textContent = "查询中…";
  const params = new URLSearchParams({
    book: c.book,
    accasoa: c.accasoa,
    f11: accountSelect.value,
    year: yearSelect.value,
    month: monthSelect.value,
  });
  try {
    const resp = await fetch("/api/statement?" + params.toString());
    const data = await resp.json();
    if (data.error) {
      queryResult.textContent = "错误：" + data.error;
      return;
    }
    renderStatement(data);
  } catch (e) {
    queryResult.textContent = "错误：" + e;
  }
}

function toggleDbUpload() {
  const dbSource = form.querySelector('input[name="db_source"]:checked').value;
  dbUploadLabel.style.display = dbSource === "upload" ? "" : "none";
}

function formatSummary(s) {
  if (!s) return "";
  const lines = [];
  lines.push('<div class="sum-head">' + esc(s.message || "") + "</div>");
  lines.push('<ul class="sum-list">');
  lines.push("<li>匹配成功 <b>" + s.matched_count + "</b> 笔；银行未匹配 <b>" +
    (s.unmatched_bank_count || 0) + "</b> 笔；数据库未匹配 <b>" +
    (s.unmatched_db_count || 0) + "</b> 笔；合并记账 <b>" + (s.merged_count || 0) + "</b> 组</li>");
  if (s.swap_warning) lines.push('<li class="warn">⚠ 疑似借贷方向颠倒</li>');
  if (s.monthly_mismatches && s.monthly_mismatches.length) {
    const ms = s.monthly_mismatches.map((m) =>
      m.month + "（借差 " + m.debit_diff + "，贷差 " + m.credit_diff + "）").join("、");
    lines.push('<li class="warn">月度总额不一致：' + esc(ms) + "</li>");
  }
  if (s.single_sided_months && s.single_sided_months.length) {
    lines.push("<li>单边月份：" + esc(s.single_sided_months.map((m) => m.month).join("、")) + "</li>");
  }
  lines.push("</ul>");

  if (s.unmatched_bank && s.unmatched_bank.length) {
    lines.push('<p class="sum-sub">银行未匹配项（前 20）：</p><ul class="sum-list">');
    for (const t of s.unmatched_bank.slice(0, 20)) {
      lines.push("<li>" + esc(t.date) + "  " + esc(t.amount || "") + "  " + esc(t.summary || "") + "</li>");
    }
    lines.push("</ul>");
  }
  if (s.unmatched_db && s.unmatched_db.length) {
    lines.push('<p class="sum-sub">数据库未匹配项（前 20）：</p><ul class="sum-list">');
    for (const t of s.unmatched_db.slice(0, 20)) {
      lines.push("<li>" + esc(t.date) + "  " + esc(t.amount || "") + "  " + esc(t.summary || "") + "</li>");
    }
    lines.push("</ul>");
  }
  if (s.merged && s.merged.length) {
    lines.push('<p class="sum-sub">合并记账（前 20）：</p><ul class="sum-list">');
    for (const g of s.merged.slice(0, 20)) {
      const parts = (g.parts || []).map((p) => p.amount + " " + (p.summary || "")).join(" + ");
      lines.push("<li>" + esc(g.kind || "") + "：" + esc(g.target_amount || "") + " " +
        esc(g.target_summary || "") + " = " + esc(parts) + "</li>");
    }
    lines.push("</ul>");
  }
  return lines.join("");
}

function showMapping(mapping) {
  const rows = [];
  for (const [field, col] of Object.entries(mapping)) {
    if (col) rows.push("<tr><td>" + esc(field) + "</td><td>" + esc(col) + "</td></tr>");
  }
  mappingEl.innerHTML =
    '<div class="mapping-head">字段识别结果</div><table><thead><tr><th>标准字段</th><th>对账单列</th></tr></thead><tbody>' +
    rows.join("") + "</tbody></table>";
  mappingEl.style.display = "";
}

function handleEvent(ev) {
  if (ev.type === "stage") {
    statusEl.textContent = "处理中 · " + ev.text;
    statusEl.className = "status";
  } else if (ev.type === "thinking") {
    thinkingEl.style.display = "";
    thinkingBodyEl.textContent += ev.text;
    thinkingBodyEl.scrollTop = thinkingBodyEl.scrollHeight;
  } else if (ev.type === "mapping") {
    showMapping(ev.mapping);
  } else if (ev.type === "done") {
    statusEl.textContent = "完成";
    statusEl.className = "status ok";
    summaryEl.innerHTML = formatSummary(ev.summary);
    if (ev.id) {
      downloadEl.href = "/api/result/" + ev.id + "/excel";
      downloadEl.style.display = "";
    }
  } else if (ev.type === "error") {
    statusEl.textContent = "错误：" + ev.message;
    statusEl.className = "status err";
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const dbSource = form.querySelector('input[name="db_source"]:checked').value;
  if (dbSource === "upload" && !dbInput.files.length) {
    statusEl.textContent = "请选择数据库流水文件";
    statusEl.className = "status err";
    return;
  }
  statusEl.textContent = "处理中…";
  statusEl.className = "status";
  summaryEl.innerHTML = "";
  downloadEl.style.display = "none";
  thinkingEl.style.display = "none";
  thinkingBodyEl.textContent = "";
  mappingEl.style.display = "none";

  const fd = new FormData();
  fd.append("bank", bankInput.files[0]);
  fd.append("db_source", dbSource);
  fd.append("year", yearSelect.value);
  fd.append("month", monthSelect.value);
  if (dbSource === "upload") {
    fd.append("db", dbInput.files[0]);
  } else {
    fd.append("account", accountSelect.value);
    const c = selectedCompany();
    if (c) {
      fd.append("book", c.book);
      fd.append("accasoa", c.accasoa);
    }
  }

  try {
    const resp = await fetch("/api/compare/stream", { method: "POST", body: fd });
    const ct = resp.headers.get("content-type") || "";
    if (!ct.includes("ndjson")) {
      const data = await resp.json().catch(() => ({}));
      throw new Error(data.error || ("HTTP " + resp.status));
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, idx).trim();
        buf = buf.slice(idx + 1);
        if (!line) continue;
        handleEvent(JSON.parse(line));
      }
    }
  } catch (err) {
    statusEl.textContent = "错误：" + err.message;
    statusEl.className = "status err";
  }
});

companySelect.addEventListener("change", onCompanyChange);
queryBtn.addEventListener("click", queryStatement);
form.querySelectorAll('input[name="db_source"]').forEach((r) =>
  r.addEventListener("change", toggleDbUpload));

loadCompanies();
