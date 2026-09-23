const form = document.getElementById("form");
const statusEl = document.getElementById("status");
const summaryEl = document.getElementById("summary");
const downloadEl = document.getElementById("download");

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  statusEl.textContent = "对比中…";
  const fd = new FormData();
  fd.append("bank", document.getElementById("bank").files[0]);
  fd.append("db", document.getElementById("db").files[0]);
  fd.append("api_key", document.getElementById("api_key").value);
  const resp = await fetch("/api/compare", { method: "POST", body: fd });
  const data = await resp.json();
  if (data.error) { statusEl.textContent = "错误：" + data.error; return; }
  statusEl.textContent = "完成";
  summaryEl.textContent = JSON.stringify(data.summary, null, 2);
  downloadEl.href = "/api/result/" + data.id + "/excel";
  downloadEl.style.display = "inline";
});
