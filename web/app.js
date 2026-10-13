const form = document.getElementById("form");
const statusEl = document.getElementById("status");
const summaryEl = document.getElementById("summary");
const downloadEl = document.getElementById("download");
const dbUploadLabel = document.getElementById("db_upload_label");
const dbFileInput = document.getElementById("db");
const bankInput = document.getElementById("bank");
const accountLabel = document.getElementById("account_label");
const accountSelect = document.getElementById("account");

function currentDbSource() {
  const checked = document.querySelector('input[name="db_source"]:checked');
  return checked ? checked.value : "database";
}

function syncVisibility() {
  const isDb = currentDbSource() === "database";
  accountLabel.style.display = isDb ? "" : "none";
  dbUploadLabel.style.display = isDb ? "none" : "";
}

document.querySelectorAll('input[name="db_source"]').forEach((radio) => {
  radio.addEventListener("change", syncVisibility);
});

async function loadAccounts() {
  try {
    const resp = await fetch("/api/bank_accounts");
    const data = await resp.json();
    if (data.error || !data.accounts) return;
    for (const a of data.accounts) {
      const opt = document.createElement("option");
      opt.value = a.f11;
      opt.textContent = `${a.name}（${a.code}）`;
      accountSelect.appendChild(opt);
    }
  } catch (e) {
    // 拉取失败时保留「对照所有账户」一个选项，仍可对账
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  statusEl.textContent = "对比中…";
  const dbSource = currentDbSource();
  const fd = new FormData();
  if (!bankInput.files.length) { statusEl.textContent = "请选择银行对账单"; return; }
  fd.append("bank", bankInput.files[0]);
  fd.append("db_source", dbSource);
  if (dbSource === "upload") {
    if (!dbFileInput.files.length) { statusEl.textContent = "请选择数据库流水文件"; return; }
    fd.append("db", dbFileInput.files[0]);
  } else {
    fd.append("account", accountSelect.value);
  }
  fd.append("api_key", document.getElementById("api_key").value);
  const resp = await fetch("/api/compare", { method: "POST", body: fd });
  const data = await resp.json();
  if (data.error) { statusEl.textContent = "错误：" + data.error; return; }
  statusEl.textContent = "完成";
  summaryEl.textContent = JSON.stringify(data.summary, null, 2);
  downloadEl.href = "/api/result/" + data.id + "/excel";
  downloadEl.style.display = "inline";
});

syncVisibility();
loadAccounts();
