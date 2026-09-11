const form = document.querySelector("#downloadForm");
const urlInput = document.querySelector("#url");
const audioOnlyInput = document.querySelector("#audioOnly");
const previewButton = document.querySelector("#previewButton");
const downloadButton = document.querySelector("#downloadButton");
const preview = document.querySelector("#preview");
const statusText = document.querySelector("#statusText");
const percentText = document.querySelector("#percentText");
const progressFill = document.querySelector("#progressFill");
const resultLink = document.querySelector("#resultLink");
const files = document.querySelector("#files");
const refreshFiles = document.querySelector("#refreshFiles");

function setStatus(message, percent = null) {
  statusText.textContent = message;
  if (percent !== null) {
    const safePercent = Math.max(0, Math.min(100, Number(percent) || 0));
    percentText.textContent = `${safePercent.toFixed(safePercent % 1 ? 1 : 0)}%`;
    progressFill.style.width = `${safePercent}%`;
  }
}

function formatDuration(seconds) {
  if (!seconds) return "";
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60).toString().padStart(2, "0");
  return `${mins}:${secs}`;
}

function formatBytes(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let size = bytes;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(unit ? 1 : 0)} ${units[unit]}`;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "処理に失敗しました。");
  return data;
}

async function loadFiles() {
  const data = await api("/api/files");
  files.innerHTML = "";
  if (!data.files.length) {
    files.innerHTML = '<p class="file-size">まだファイルはありません。</p>';
    return;
  }
  for (const file of data.files) {
    const item = document.createElement("div");
    item.className = "file-item";
    item.innerHTML = `
      <a href="${file.url}">${file.name}</a>
      <span class="file-size">${formatBytes(file.size)}</span>
    `;
    files.appendChild(item);
  }
}

previewButton.addEventListener("click", async () => {
  const url = urlInput.value.trim();
  if (!url) return;
  previewButton.disabled = true;
  setStatus("動画情報を取得中", 0);
  try {
    const info = await api("/api/info", {
      method: "POST",
      body: JSON.stringify({ url }),
    });
    preview.classList.remove("hidden");
    preview.innerHTML = `
      ${info.thumbnail ? `<img src="${info.thumbnail}" alt="">` : ""}
      <div>
        <h3>${info.title || "タイトルなし"}</h3>
        <p>${[info.uploader, formatDuration(info.duration)].filter(Boolean).join(" / ")}</p>
      </div>
    `;
    setStatus("確認完了", 0);
  } catch (error) {
    setStatus(error.message, 0);
  } finally {
    previewButton.disabled = false;
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const url = urlInput.value.trim();
  if (!url) return;

  resultLink.classList.add("hidden");
  downloadButton.disabled = true;
  setStatus("開始中", 0);

  try {
    const { jobId } = await api("/api/download", {
      method: "POST",
      body: JSON.stringify({ url, audioOnly: audioOnlyInput.checked }),
    });

    const timer = window.setInterval(async () => {
      try {
        const job = await api(`/api/jobs/${jobId}`);
        if (job.status === "downloading") {
          setStatus("ダウンロード中", job.percent ?? 0);
        } else if (job.status === "processing") {
          setStatus("ファイルを処理中", 100);
        } else if (job.status === "done") {
          window.clearInterval(timer);
          setStatus("完了", 100);
          resultLink.href = job.file.url;
          resultLink.textContent = `${job.file.name} を保存`;
          resultLink.classList.remove("hidden");
          downloadButton.disabled = false;
          loadFiles();
        } else if (job.status === "error") {
          window.clearInterval(timer);
          setStatus(job.error || "エラーが発生しました。", 0);
          downloadButton.disabled = false;
        } else {
          setStatus("待機中", job.percent ?? 0);
        }
      } catch (error) {
        window.clearInterval(timer);
        setStatus(error.message, 0);
        downloadButton.disabled = false;
      }
    }, 1000);
  } catch (error) {
    setStatus(error.message, 0);
    downloadButton.disabled = false;
  }
});

refreshFiles.addEventListener("click", loadFiles);
loadFiles();
