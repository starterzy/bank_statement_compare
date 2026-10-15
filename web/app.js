// 前端逻辑：登录、公司/账户/月份选择、流水查询展示、对账表单提交、用户管理。
let me = null; // 当前登录用户

const companySelect = document.getElementById("company");
const accountSelect = document.getElementById("account");
const yearSelect = document.getElementById("year");
const monthSelect = document.getElementById("month");
const monthToSelect = document.getElementById("month_to");
const modelSelect = document.getElementById("model");
const queryBtn = document.getElementById("query_btn");
const queryResult = document.getElementById("query_result");
const form = document.getElementById("form");
const bankInput = document.getElementById("bank");
const bankFilesEl = document.getElementById("bank_files");
const dbInput = document.getElementById("db");
const dbUploadLabel = document.getElementById("db_upload_label");
const statusEl = document.getElementById("status");
const summaryEl = document.getElementById("summary");
const detailEl = document.getElementById("detail");
const downloadEl = document.getElementById("download");
const thinkingEl = document.getElementById("thinking");
const thinkingBodyEl = document.getElementById("thinking_body");
const mappingEl = document.getElementById("mapping");
const accountPickerEl = document.getElementById("account_picker");

const loginCard = document.getElementById("login_card");
const loginUser = document.getElementById("login_user");
const loginPass = document.getElementById("login_pass");
const loginBtn = document.getElementById("login_btn");
const loginMsg = document.getElementById("login_msg");
const userbar = document.getElementById("userbar");
const whoEl = document.getElementById("who");
const logoutBtn = document.getElementById("logout_btn");
const appEl = document.getElementById("app");

const userMgmtCard = document.getElementById("user_mgmt_card");
const userTableBody = document.querySelector("#user_table tbody");
const userNewBtn = document.getElementById("user_new_btn");
const userForm = document.getElementById("user_form");
const userFormTitle = document.getElementById("user_form_title");
const uUsername = document.getElementById("u_username");
const uPassword = document.getElementById("u_password");
const uDisplayName = document.getElementById("u_display_name");
const uAdmin = document.getElementById("u_admin");
const uTree = document.getElementById("u_tree");
const uSave = document.getElementById("u_save");
const uCancel = document.getElementById("u_cancel");

// ---- 鉴权 ----
function token() { return localStorage.getItem("token") || ""; }
function authHeaders() { return { "Authorization": "Bearer " + token() }; }

async function api(path, opts) {
  const o = Object.assign({}, opts);
  o.headers = Object.assign({}, authHeaders(), opts && opts.headers);
  const resp = await fetch(path, o);
  if (resp.status === 401) { showLogin(); throw new Error("未登录"); }
  return resp;
}

function showLogin() {
  localStorage.removeItem("token");
  me = null;
  loginCard.style.display = "";
  appEl.style.display = "none";
  userbar.style.display = "none";
}

function showApp() {
  loginCard.style.display = "none";
  appEl.style.display = "";
  userbar.style.display = "";
  whoEl.textContent = me.display_name ? (me.display_name + "（" + me.username + "）") : me.username;
  accountSelect.innerHTML = '<option value="">不选择 · 对照所有账户</option>';
  yearSelect.innerHTML = "";
  queryResult.innerHTML = "";
  if (me.is_admin) {
    userMgmtCard.style.display = "";
    loadUsers();
    if (!orgTreeData) loadOrgTree();
  } else {
    userMgmtCard.style.display = "none";
  }
  loadCompanies();
  loadModels();
}

async function boot() {
  if (!token()) { showLogin(); return; }
  try {
    const resp = await fetch("/api/me", { headers: authHeaders() });
    if (resp.status === 401) { showLogin(); return; }
    const data = await resp.json();
    me = data.user;
    showApp();
  } catch (e) {
    showLogin();
  }
}

loginBtn.addEventListener("click", doLogin);
loginPass.addEventListener("keydown", (e) => { if (e.key === "Enter") doLogin(); });
loginUser.addEventListener("keydown", (e) => { if (e.key === "Enter") doLogin(); });

async function doLogin() {
  loginMsg.textContent = "";
  loginMsg.className = "status";
  try {
    const resp = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: loginUser.value.trim(), password: loginPass.value }),
    });
    const data = await resp.json();
    if (data.error) { loginMsg.textContent = data.error; loginMsg.className = "status err"; return; }
    localStorage.setItem("token", data.token);
    me = data.user;
    showApp();
  } catch (e) {
    loginMsg.textContent = "登录失败：" + e;
    loginMsg.className = "status err";
  }
}

logoutBtn.addEventListener("click", async () => {
  try { await fetch("/api/logout", { method: "POST", headers: authHeaders() }); } catch (e) {}
  showLogin();
});

// ---- 用户管理 ----
let orgTreeData = null;
let editingUser = null; // null = 新增

async function loadUsers() {
  const resp = await api("/api/users");
  const data = await resp.json();
  userTableBody.innerHTML = "";
  for (const u of data.users || []) {
    const tr = document.createElement("tr");
    const role = u.is_admin ? "管理员" : "用户";
    const scope = u.is_admin ? "全部" : (u.org_roots.length + " 个子树");
    tr.innerHTML = "<td>" + esc(u.username) + "</td><td>" + esc(u.display_name) + "</td>" +
      "<td>" + role + "</td><td>" + esc(scope) + "</td>" +
      '<td><button class="btn" data-act="edit">编辑</button> <button class="btn" data-act="del">删除</button></td>';
    tr.querySelector('[data-act="edit"]').addEventListener("click", () => startEdit(u));
    tr.querySelector('[data-act="del"]').addEventListener("click", () => delUser(u));
    userTableBody.appendChild(tr);
  }
}

async function loadOrgTree() {
  const resp = await api("/api/org_tree");
  const data = await resp.json();
  if (data.error) { uTree.textContent = "错误：" + data.error; return; }
  orgTreeData = data;
  renderOrgTree([]);
}

function renderOrgTree(checked) {
  if (!orgTreeData) { uTree.innerHTML = ""; return; }
  const checkedSet = new Set(checked || []);
  // 子树内是否含已勾选项：编辑用户时据此展开到所选节点
  function hasCheckedInSubtree(n) {
    if (checkedSet.has(n.pk_org)) return true;
    return (n.children || []).some(hasCheckedInSubtree);
  }
  function walk(nodes, depth) {
    let html = "";
    for (const n of nodes) {
      const kids = n.children || [];
      const hasKids = kids.length > 0;
      const expanded = hasKids && (depth === 0 || hasCheckedInSubtree(n));
      const arrow = hasKids
        ? '<span class="tree-toggle" role="button" tabindex="0">' + (expanded ? "▾" : "▸") + "</span>"
        : '<span class="tree-toggle empty"></span>';
      const c = checkedSet.has(n.pk_org) ? " checked" : "";
      html += '<div class="tree-node">' +
        '<div class="tree-row" style="padding-left:' + (depth * 16) + 'px">' +
        arrow +
        '<label class="inline"><input type="checkbox" class="tree-check" value="' + esc(n.pk_org) + '"' + c + ">" +
        esc(n.name) + ' <span class="muted">' + esc(n.code || "") + "</span></label>" +
        "</div>";
      if (hasKids) {
        html += '<div class="tree-children"' + (expanded ? "" : ' style="display:none"') + ">" +
          walk(kids, depth + 1) + "</div>";
      }
      html += "</div>";
    }
    return html;
  }
  uTree.innerHTML = walk([orgTreeData], 0);
}

function resetForm() {
  editingUser = null;
  userFormTitle.textContent = "新增用户";
  uUsername.value = "";
  uUsername.disabled = false;
  uPassword.value = "";
  uDisplayName.value = "";
  uAdmin.checked = false;
  renderOrgTree([]);
  userForm.style.display = "none";
}

function startEdit(u) {
  editingUser = u.username;
  userFormTitle.textContent = "编辑用户：" + u.username;
  uUsername.value = u.username;
  uUsername.disabled = true;
  uPassword.value = "";
  uDisplayName.value = u.display_name || "";
  uAdmin.checked = !!u.is_admin;
  renderOrgTree(u.org_roots || []);
  userForm.style.display = "";
}

function collectChecked() {
  return Array.from(uTree.querySelectorAll(".tree-check:checked")).map((c) => c.value);
}

async function saveUser() {
  const username = uUsername.value.trim();
  if (!username) { alert("请填写用户名"); return; }
  const isNew = editingUser == null;
  if (isNew && !uPassword.value) { alert("新增用户请设置密码"); return; }
  const body = {
    username: username,
    password: uPassword.value,
    display_name: uDisplayName.value.trim(),
    is_admin: uAdmin.checked,
    org_roots: collectChecked(),
  };
  const resp = await api(isNew ? "/api/users" : ("/api/users/" + encodeURIComponent(editingUser)), {
    method: isNew ? "POST" : "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await resp.json();
  if (data.error) { alert(data.error); return; }
  resetForm();
  loadUsers();
}

async function delUser(u) {
  if (!confirm("确认删除用户 " + u.username + "？")) return;
  const resp = await api("/api/users/" + encodeURIComponent(u.username), { method: "DELETE" });
  const data = await resp.json();
  if (data.error) { alert(data.error); return; }
  loadUsers();
}

userNewBtn.addEventListener("click", () => { resetForm(); userForm.style.display = ""; });
uCancel.addEventListener("click", resetForm);
uSave.addEventListener("click", saveUser);

// 组织树点击展开/收起（事件委托，避免重渲染后重新绑定）
uTree.addEventListener("click", (e) => {
  const t = e.target.closest(".tree-toggle");
  if (!t || t.classList.contains("empty")) return;
  const node = t.closest(".tree-node");
  const children = node && node.querySelector(":scope > .tree-children");
  if (!children) return;
  const hidden = children.style.display === "none";
  children.style.display = hidden ? "" : "none";
  t.textContent = hidden ? "▾" : "▸";
});

// ---- 公司/账户/年份 ----
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
    const resp = await api("/api/companies");
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
    const resp = await api("/api/bank_accounts?org=" + encodeURIComponent(c.org));
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

async function loadModels() {
  modelSelect.innerHTML = "";
  try {
    const resp = await api("/api/models");
    const data = await resp.json();
    if (data.error) return;
    for (const m of data.models || []) {
      const o = document.createElement("option");
      o.value = m.id;
      o.textContent = m.label;
      if (m.id === data.default) o.selected = true;
      modelSelect.appendChild(o);
    }
  } catch (e) {}
}

async function loadYears() {
  yearSelect.innerHTML = "";
  const c = selectedCompany();
  if (!c) return;
  try {
    const resp = await api("/api/years?book=" + encodeURIComponent(c.book) +
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
    "<h3>月度发生额</h3><table><thead><tr><th>月份</th><th>期初余额</th><th>借方(收)</th><th>贷方(付)</th><th>笔数</th><th>期末余额</th></tr></thead><tbody>";
  for (const m of d.monthly || []) {
    const hl = d.selected_month && m.month === d.selected_month ? ' class="hl"' : "";
    monthly +=
      "<tr" + hl + "><td>" + esc(m.month) + "</td>" +
      '<td class="num">' + esc(m.opening) + "</td>" +
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
    month_to: monthToSelect.value,
  });
  try {
    const resp = await api("/api/statement?" + params.toString());
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

function dbSourceValue() {
  return form.querySelector('input[name="db_source"]:checked').value;
}

function toggleDbUpload() {
  dbUploadLabel.style.display = dbSourceValue() === "upload" ? "" : "none";
}

bankInput.addEventListener("change", () => {
  const names = Array.from(bankInput.files).map((f) => f.name);
  bankFilesEl.textContent = names.length
    ? "已选 " + names.length + " 个（按此顺序识别）：" + names.join("、")
    : "";
});

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
  if (s.balance_mismatches && s.balance_mismatches.length) {
    const ms = s.balance_mismatches.map((m) =>
      m.month + "（期初差 " + (m.opening_diff ?? "—") + "，期末差 " + (m.closing_diff ?? "—") + "）").join("、");
    lines.push('<li class="warn">月度期初/期末余额不一致：' + esc(ms) + "</li>");
  }
  if (s.single_sided_months && s.single_sided_months.length) {
    lines.push("<li>单边月份：" + esc(s.single_sided_months.map((m) => m.month).join("、")) + "</li>");
  }
  if (s.amount_suspects && s.amount_suspects.length) {
    lines.push('<li class="warn">⚠ 未匹配项金额疑似识别错误（' + s.amount_suspects.length + " 笔，见下方核对）</li>");
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
  if (s.amount_suspects && s.amount_suspects.length) {
    lines.push('<p class="sum-sub">未匹配项金额疑似识别错误（上下行余额核对）：</p><ul class="sum-list">');
    for (const a of s.amount_suspects.slice(0, 20)) {
      const ctx = [];
      if (a.prev) ctx.push("上行 " + esc(a.prev.date) + " " + esc(a.prev.amount || "") +
        "（余额 " + esc(a.prev.balance ?? "—") + "）");
      if (a.next) ctx.push("下行 " + esc(a.next.date) + " " + esc(a.next.amount || "") +
        "（余额 " + esc(a.next.balance ?? "—") + "）");
      lines.push("<li>" + esc(a.date) + " 识别 " + esc(a.amount || "") +
        "（余额 " + esc(a.balance ?? "—") + "），按余额链应为 " + esc(a.expected_amount || "") +
        "  " + esc(a.summary || "") + "　[" + ctx.join("；") + "]</li>");
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

function statusClass(status) {
  if (status === "已匹配") return "st-matched";
  if (status === "合并记账") return "st-merged";
  if (status === "└ 拆分") return "st-split";
  if (status === "仅银行有") return "st-bank-only";
  if (status === "仅数据库有") return "st-db-only";
  return "";
}

function renderDetail(rows) {
  if (!rows || !rows.length) {
    detailEl.innerHTML = "";
    return;
  }
  let html =
    "<h3>逐笔匹配明细（" + rows.length + " 行）</h3>" +
    "<table><thead><tr><th>状态</th><th>月份</th><th>方向</th><th>金额</th>" +
    "<th>银行日期</th><th>银行对方</th><th>银行摘要</th>" +
    "<th>数据库日期</th><th>数据库摘要</th><th>凭证号</th><th>明细序号</th>" +
    "</tr></thead><tbody>";
  for (const r of rows) {
    const b = r.bank || {};
    const d = r.db || {};
    const cls = statusClass(r.status);
    html +=
      '<tr class="' + cls + '"><td><span class="tag ' + cls + '">' + esc(r.status) + "</span></td>" +
      '<td class="num">' + esc(b.month || d.month) + "</td>" +
      '<td class="num">' + esc(b.direction || d.direction) + "</td>" +
      '<td class="num">' + esc(b.amount || d.amount) + "</td>" +
      "<td>" + esc(b.date) + "</td>" +
      "<td>" + esc(b.counterparty) + "</td>" +
      "<td>" + esc(b.summary) + "</td>" +
      "<td>" + esc(d.date) + "</td>" +
      "<td>" + esc(d.summary) + "</td>" +
      '<td class="num">' + esc(d.voucher_no) + "</td>" +
      '<td class="num">' + esc(d.detail_index) + "</td></tr>";
  }
  html += "</tbody></table>";
  detailEl.innerHTML = html;
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
    renderDetail(ev.detail);
    if (ev.id) {
      fetch("/api/result/" + ev.id + "/excel", { headers: authHeaders() })
        .then((r) => r.blob())
        .then((blob) => {
          const url = URL.createObjectURL(blob);
          downloadEl.href = url;
          downloadEl.download = "对账结果.xlsx";
          downloadEl.style.display = "";
        });
    }
  } else if (ev.type === "choose_account") {
    statusEl.textContent = "识别到多个候选账户，请选择";
    statusEl.className = "status";
    renderAccountPicker(ev);
  } else if (ev.type === "account_resolved") {
    applyAutoAccount(ev);
  } else if (ev.type === "error") {
    statusEl.textContent = "错误：" + ev.message;
    statusEl.className = "status err";
  }
}

async function runStream(fd) {
  statusEl.textContent = "处理中…";
  statusEl.className = "status";
  summaryEl.innerHTML = "";
  detailEl.innerHTML = "";
  accountPickerEl.innerHTML = "";
  downloadEl.style.display = "none";
  thinkingEl.style.display = "none";
  thinkingBodyEl.textContent = "";
  mappingEl.style.display = "none";

  try {
    const resp = await api("/api/compare/stream", { method: "POST", body: fd });
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
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const dbSource = dbSourceValue();
  if (dbSource === "upload" && !dbInput.files.length) {
    statusEl.textContent = "请选择数据库流水文件";
    statusEl.className = "status err";
    return;
  }

  const fd = new FormData();
  for (const f of bankInput.files) fd.append("banks", f);
  fd.append("model", modelSelect.value);
  if (dbSource === "upload") {
    fd.append("db_source", "upload");
    fd.append("db", dbInput.files[0]);
  } else if (dbSource === "auto") {
    // 不传 account/book/accasoa/year/month，触发后端自动反查账户与月份
    fd.append("db_source", "database");
  } else {
    fd.append("db_source", "database");
    fd.append("account", accountSelect.value);
    fd.append("year", yearSelect.value);
    fd.append("month", monthSelect.value);
    fd.append("month_to", monthToSelect.value);
    const c = selectedCompany();
    if (c) {
      fd.append("book", c.book);
      fd.append("accasoa", c.accasoa);
    }
  }
  runStream(fd);
});

function renderAccountPicker(ev) {
  const cands = ev.candidates || [];
  let html = '<div class="mapping-head">识别到账号 ' + esc(ev.account_no || "") +
    (ev.account_name ? "（" + esc(ev.account_name) + "）" : "") +
    " 命中 " + cands.length + ' 个账户，请选择：</div><ul class="sum-list">';
  cands.forEach((cand, i) => {
    html += '<li><button class="btn" data-pick="' + i + '">' + esc(cand.org_name) +
      " / " + esc(cand.name) + "（" + esc(cand.code) + "）</button></li>";
  });
  html += "</ul>";
  accountPickerEl.innerHTML = html;
  accountPickerEl.querySelectorAll("[data-pick]").forEach((b) =>
    b.addEventListener("click", () => pickAccount(cands[+b.dataset.pick], ev.months || [])));
}

function pickAccount(cand, months) {
  const year = (months[0] || "").slice(0, 4);
  const month = months.length === 1 ? months[0].slice(5, 7) : "";
  const month_to = months.length > 1 ? months[months.length - 1].slice(5, 7) : "";
  const fd = new FormData();
  for (const f of bankInput.files) fd.append("banks", f);
  fd.append("db_source", "database");
  fd.append("model", modelSelect.value);
  fd.append("account", cand.f11);
  fd.append("book", cand.book);
  fd.append("accasoa", cand.accasoa);
  fd.append("year", year);
  fd.append("month", month);
  fd.append("month_to", month_to);
  runStream(fd);
}

async function applyAutoAccount(ev) {
  // 把识别出的公司/账户/年月回填到上方搜索栏，并查询流水。
  if (ev.org && companies.some((c) => c.org === ev.org)) {
    companySelect.value = ev.org;
    await loadAccounts();
    await loadYears();
  }
  accountSelect.value = ev.f11 || "";
  yearSelect.value = ev.year || "";
  monthSelect.value = ev.month || "";
  monthToSelect.value = ev.month_to || "";
  queryStatement();
}

companySelect.addEventListener("change", onCompanyChange);
queryBtn.addEventListener("click", queryStatement);
form.querySelectorAll('input[name="db_source"]').forEach((r) =>
  r.addEventListener("change", toggleDbUpload));

boot();
