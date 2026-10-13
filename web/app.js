// 前端逻辑：公司/账户选择、流水查询展示、对账表单提交。
const companySelect = document.getElementById("company");
const accountSelect = document.getElementById("account");
const queryBtn = document.getElementById("query_btn");
const queryResult = document.getElementById("query_result");
const form = document.getElementById("form");
const bankInput = document.getElementById("bank");
const dbInput = document.getElementById("db");
const apiKeyInput = document.getElementById("api_key");
const dbUploadLabel = document.getElementById("db_upload_label");
const statusEl = document.getElementById("status");
const summaryEl = document.getElementById("summary");
const downloadEl = document.getElementById("download");

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

function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
  }[ch]));
}

function renderStatement(d) {
  const head =
    "<p>" +
    "期初余额 <b>" + esc(d.opening) + "</b> ｜ " +
    "本年借方(收) <b>" + esc(d.total_debit) + "</b> ｜ " +
    "本年贷方(付) <b>" + esc(d.total_credit) + "</b> ｜ " +
    "期末余额 <b>" + esc(d.closing) + "</b> ｜ " +
    "笔数 <b>" + esc(d.count) + "</b>" +
    "</p>";

  let monthly =
    "<h3>月度发生额</h3><table><tr><th>月份</th><th>借方(收)</th><th>贷方(付)</th><th>笔数</th><th>期末余额</th></tr>";
  for (const m of d.monthly || []) {
    monthly +=
      "<tr><td>" + esc(m.month) + "</td>" +
      '<td class="num">' + esc(m.debit) + "</td>" +
      '<td class="num">' + esc(m.credit) + "</td>" +
      "<td>" + esc(m.count) + "</td>" +
      '<td class="num">' + esc(m.balance) + "</td></tr>";
  }
  monthly += "</table>";

  let txs =
    "<h3>每笔流水（" + esc(d.count) + " 笔）</h3>" +
    "<table><tr><th>日期</th><th>凭证号</th><th>序号</th><th>摘要</th><th>借方(收)</th><th>贷方(付)</th></tr>";
  for (const t of d.transactions || []) {
    txs +=
      "<tr><td>" + esc(t.date) + "</td>" +
      "<td>" + esc(t.voucher_no) + "</td>" +
      "<td>" + esc(t.detail_index) + "</td>" +
      "<td>" + esc(t.summary) + "</td>" +
      '<td class="num">' + esc(t.debit) + "</td>" +
      '<td class="num">' + esc(t.credit) + "</td></tr>";
  }
  txs += "</table>";

  queryResult.innerHTML = head + monthly + txs;
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

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const dbSource = form.querySelector('input[name="db_source"]:checked').value;
  if (dbSource === "upload" && !dbInput.files.length) {
    statusEl.textContent = "请选择数据库流水文件";
    return;
  }
  statusEl.textContent = "处理中…";
  summaryEl.textContent = "";
  downloadEl.style.display = "none";

  const fd = new FormData();
  fd.append("bank", bankInput.files[0]);
  fd.append("api_key", apiKeyInput.value);
  fd.append("db_source", dbSource);
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
    const resp = await fetch("/api/compare", { method: "POST", body: fd });
    const data = await resp.json();
    if (data.error) {
      statusEl.textContent = "错误：" + data.error;
      return;
    }
    statusEl.textContent = "完成";
    summaryEl.textContent = data.summary || "";
    if (data.id) {
      downloadEl.href = "/api/result/" + data.id + "/excel";
      downloadEl.style.display = "";
    }
  } catch (err) {
    statusEl.textContent = "错误：" + err;
  }
});

companySelect.addEventListener("change", loadAccounts);
queryBtn.addEventListener("click", queryStatement);
form.querySelectorAll('input[name="db_source"]').forEach((r) =>
  r.addEventListener("change", toggleDbUpload));

loadCompanies();
