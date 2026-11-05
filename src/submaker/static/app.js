// Submaker Studio Frontend Logic

let currentMediaInfo = null;
let currentLink = "";

// Tab Switching
function switchTab(tab) {
  ['download', 'files', 'settings'].forEach(t => {
    document.getElementById(`tab-${t}`).classList.add('hidden');
    document.getElementById(`tab-btn-${t}`).classList.remove('bg-indigo-600', 'text-white');
    document.getElementById(`tab-btn-${t}`).classList.add('text-zinc-400');
  });

  document.getElementById(`tab-${tab}`).classList.remove('hidden');
  const activeBtn = document.getElementById(`tab-btn-${tab}`);
  activeBtn.classList.add('bg-indigo-600', 'text-white');
  activeBtn.classList.remove('text-zinc-400');

  if (tab === 'files') {
    refreshFilesList();
  } else if (tab === 'settings') {
    loadSettings();
  }
}

// Inspect Link
async function inspectLink(customUrl = null) {
  const url = customUrl || document.getElementById('input-url').value.trim();
  if (!url) return alert('Silakan masukkan link terlebih dahulu!');
  currentLink = url;

  const btnText = document.getElementById('btn-inspect-text');
  const btnSpinner = document.getElementById('btn-inspect-spinner');
  btnText.textContent = 'Memeriksa...';
  btnSpinner.classList.remove('hidden');

  try {
    const res = await fetch('/api/inspect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url })
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Gagal memeriksa media.');
    }

    const data = await res.json();
    currentMediaInfo = data;
    renderMediaInfo(data);
  } catch (err) {
    alert('Error: ' + err.message);
  } finally {
    btnText.textContent = 'Periksa Link';
    btnSpinner.classList.add('hidden');
  }
}

function renderMediaInfo(data) {
  const card = document.getElementById('preview-card');
  card.classList.remove('hidden');

  const details = data.details || {};
  document.getElementById('meta-title').textContent = details.title || 'Untitled';
  document.getElementById('meta-poster').src = details.poster || 'https://via.placeholder.com/300x450?text=No+Poster';
  document.getElementById('meta-overview').textContent = details.overview || 'Tidak ada deskripsi.';
  document.getElementById('meta-rating').textContent = `★ ${details.rating || 'N/A'}`;
  document.getElementById('meta-year').textContent = details.year || '';
  document.getElementById('meta-type').textContent = details.format || (details.is_movie ? 'FILM' : 'SERIAL');

  // Handle Episode Grid if needed
  const epPicker = document.getElementById('episode-picker');
  const epGrid = document.getElementById('episode-grid');
  epGrid.innerHTML = '';

  if (data.total_episodes && data.total_episodes > 1) {
    epPicker.classList.remove('hidden');
    for (let ep = 1; ep <= data.total_episodes; ep++) {
      const btn = document.createElement('button');
      const isSelected = data.selected_episode === ep;
      btn.className = `px-3 py-1.5 text-xs font-mono font-semibold rounded-lg transition-all ${
        isSelected ? 'bg-indigo-600 text-white' : 'bg-zinc-800 hover:bg-zinc-700 text-zinc-300'
      }`;
      btn.textContent = `EP ${ep}`;
      btn.onclick = () => {
        let newUrl = currentLink.replace(/\/(\d+)$/, `/${ep}`);
        if (!newUrl.endsWith(`/${ep}`)) newUrl += `/${ep}`;
        inspectLink(newUrl);
      };
      epGrid.appendChild(btn);
    }
  } else {
    epPicker.classList.add('hidden');
  }

  // Populate Sources
  const selSource = document.getElementById('select-source');
  selSource.innerHTML = '';
  (data.sources || []).forEach((src, idx) => {
    const opt = document.createElement('option');
    opt.value = idx;
    opt.textContent = `${src.label || src.server} (${src.quality}) [${src.stream_type.toUpperCase()}]`;
    selSource.appendChild(opt);
  });

  // Calculate default filename
  let filename = `${details.title || 'Anime'}`;
  if (data.selected_episode) {
    filename += ` S01E${String(data.selected_episode).padStart(2, '0')}`;
  }
  filename += ` [1080p].mp4`;
  document.getElementById('input-filename').value = filename.replace(/[/\\?%*:|"<>]/g, '');
}

// Start Download Process
async function startDownloadProcess() {
  if (!currentMediaInfo || !currentMediaInfo.sources || currentMediaInfo.sources.length === 0) {
    return alert('Tidak ada sumber video stream yang aktif!');
  }

  const selIdx = parseInt(document.getElementById('select-source').value || '0');
  const selectedSource = currentMediaInfo.sources[selIdx];
  const filename = document.getElementById('input-filename').value.trim();
  const autoSub = document.getElementById('chk-auto-sub').checked;

  const subtitleUrls = (currentMediaInfo.subtitles || []).map(s => s.url);

  try {
    const res = await fetch('/api/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source_url: selectedSource.url,
        output_filename: filename,
        stream_type: selectedSource.stream_type,
        headers: selectedSource.headers || {},
        skip_proxy: selectedSource.skip_proxy || false,
        subtitle_urls: subtitleUrls,
        auto_translate_id: autoSub
      })
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Gagal memulai unduhan');

    createTaskProgressCard(data.task_id, data.filename);
  } catch (err) {
    alert('Error: ' + err.message);
  }
}

function createTaskProgressCard(taskId, filename) {
  const container = document.getElementById('tasks-container');

  const card = document.createElement('div');
  card.id = `task-${taskId}`;
  card.className = 'glass p-4 rounded-xl space-y-2 border border-zinc-800';
  card.innerHTML = `
    <div class="flex items-center justify-between text-xs">
      <span class="font-bold text-white truncate max-w-sm">${filename}</span>
      <span id="task-status-${taskId}" class="px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-300 font-mono text-[10px]">Memulai...</span>
    </div>
    <div class="w-full bg-zinc-800 rounded-full h-2 overflow-hidden">
      <div id="task-bar-${taskId}" class="progress-bar bg-indigo-500 h-2 rounded-full w-0"></div>
    </div>
    <div class="flex items-center justify-between text-[11px] text-zinc-400 font-mono">
      <span id="task-info-${taskId}">0%</span>
      <span id="task-speed-${taskId}">-- KB/s</span>
      <span id="task-eta-${taskId}">ETA: --</span>
    </div>
  `;
  container.prepend(card);

  // Connect SSE
  const evSource = new EventSource(`/api/progress/${taskId}`);
  evSource.onmessage = (e) => {
    const prog = JSON.parse(e.data);
    const bar = document.getElementById(`task-bar-${taskId}`);
    const status = document.getElementById(`task-status-${taskId}`);
    const info = document.getElementById(`task-info-${taskId}`);
    const speed = document.getElementById(`task-speed-${taskId}`);
    const eta = document.getElementById(`task-eta-${taskId}`);

    if (!bar) {
      evSource.close();
      return;
    }

    if (prog.error) {
      status.textContent = prog.error;
      status.className = 'px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-400 font-mono text-[10px]';
      evSource.close();
      return;
    }

    const statusLabels = {
      pending: "Menyiapkan...",
      fetching_playlist: "Mengambil Playlist HLS...",
      downloading: "Mengunduh Segmen Video...",
      merging: "Menggabungkan MP4 (FFmpeg)...",
      downloading_subtitles: "Mengunduh Subtitle...",
      completed: "✔ Selesai!",
      failed: "Gagal",
      cancelled: "Dibatalkan"
    };

    bar.style.width = `${prog.percent || 0}%`;
    info.textContent = `${prog.percent || 0}% (${prog.downloaded_segments || 0}/${prog.total_segments || 0} segmen)`;
    speed.textContent = prog.speed || '-- KB/s';
    eta.textContent = `ETA: ${prog.eta || '--'}`;

    if (prog.status === 'completed') {
      status.textContent = '✔ Selesai!';
      status.className = 'px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 font-mono text-[10px] font-bold';
      bar.className = 'progress-bar bg-emerald-500 h-2 rounded-full';
      evSource.close();
      updateFilesBadge();
    } else if (prog.status === 'failed' || prog.status === 'cancelled') {
      status.textContent = prog.error || 'Gagal';
      status.className = 'px-2 py-0.5 rounded-full bg-red-500/20 text-red-400 font-mono text-[10px] font-bold';
      evSource.close();
    } else {
      status.textContent = statusLabels[prog.status] || prog.status;
    }
  };
}

// Refresh Files List
async function refreshFilesList() {
  const listEl = document.getElementById('files-list');
  try {
    const res = await fetch('/api/files');
    const files = await res.json();
    document.getElementById('files-badge').textContent = files.length;

    if (files.length === 0) {
      listEl.innerHTML = '<p class="text-xs text-zinc-500 italic p-4 text-center">Belum ada file yang diunduh.</p>';
      return;
    }

    listEl.innerHTML = '';
    files.forEach(f => {
      const item = document.createElement('div');
      item.className = 'glass p-3 rounded-xl flex items-center justify-between gap-3 text-xs';
      
      const icon = f.is_video ? '🎬' : (f.is_id_sub ? '🇮🇩' : '📝');
      const badge = f.is_id_sub ? '<span class="text-[9px] bg-red-500/20 text-red-300 px-1.5 py-0.5 rounded font-bold ml-1.5">SUB INDO</span>' : '';

      item.innerHTML = `
        <div class="flex items-center space-x-2 truncate">
          <span class="text-base">${icon}</span>
          <div class="truncate">
            <div class="font-medium text-zinc-200 truncate flex items-center">${f.name} ${badge}</div>
            <div class="text-[10px] text-zinc-500 font-mono">${f.size_mb} MB</div>
          </div>
        </div>
        <div class="flex items-center space-x-2 shrink-0">
          ${f.is_video ? `
            <button onclick="triggerWhisperRaw('${f.name}', this)" class="px-2.5 py-1 bg-purple-600/30 hover:bg-purple-600/50 text-purple-300 border border-purple-500/30 rounded-lg text-[11px] font-semibold transition-all flex items-center">
              🎙️ Buat Sub Indo (Whisper)
            </button>
          ` : ''}
          ${f.is_sub && !f.is_id_sub ? `
            <button onclick="triggerTranslateSub('${f.name}', this)" class="px-2.5 py-1 bg-indigo-600/30 hover:bg-indigo-600/50 text-indigo-300 border border-indigo-500/30 rounded-lg text-[11px] font-semibold transition-all flex items-center">
              🌐 Terjemahkan ke Indo
            </button>
          ` : ''}
          <a href="/api/files/${encodeURIComponent(f.name)}" download class="px-2.5 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 rounded-lg text-[11px] font-medium transition-all">
            ⬇️ Unduh
          </a>
          <button onclick="deleteFile('${f.name}')" class="p-1 text-zinc-500 hover:text-red-400 transition-colors">
            ✕
          </button>
        </div>
      `;
      listEl.appendChild(item);
    });
  } catch (err) {
    listEl.innerHTML = `<p class="text-xs text-red-400">Gagal memuat file: ${err.message}</p>`;
  }
}

async function updateFilesBadge() {
  try {
    const res = await fetch('/api/files');
    const files = await res.json();
    document.getElementById('files-badge').textContent = files.length;
  } catch (e) {}
}

async function deleteFile(filename) {
  if (!confirm(`Hapus file ${filename}?`)) return;
  await fetch(`/api/files/${encodeURIComponent(filename)}`, { method: 'DELETE' });
  refreshFilesList();
}

// Simple in-memory tracker for client buttons
const activeJobs = new Set();

function showToast(msg, type = "info") {
  let toast = document.getElementById("toast-msg");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "toast-msg";
    toast.className = "fixed bottom-5 right-5 z-50 px-4 py-2.5 rounded-xl text-xs font-semibold shadow-xl transition-all flex items-center space-x-2";
    document.body.appendChild(toast);
  }
  toast.className = `fixed bottom-5 right-5 z-50 px-4 py-2.5 rounded-xl text-xs font-semibold shadow-xl transition-all flex items-center space-x-2 ${
    type === "success" ? "bg-emerald-600 text-white" : (type === "error" ? "bg-red-600 text-white" : "bg-indigo-600 text-white")
  }`;
  toast.innerHTML = `<span>${type === "success" ? "✔" : "ℹ"}</span><span>${msg}</span>`;
  toast.style.display = "flex";
  setTimeout(() => {
    toast.style.display = "none";
  }, 4000);
}

async function triggerWhisperRaw(filename, btnEl = null) {
  if (btnEl) {
    btnEl.disabled = true;
    btnEl.innerHTML = `<span class="inline-block animate-spin mr-1">⌛</span> Transkripsi Audio...`;
  }
  showToast(`Mengekstrak audio & memotong segmen hening: ${filename}`, "info");

  try {
    const res = await fetch('/api/subtitles/transcribe-audio', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename: filename, chunk_minutes: 4.0 })
    });
    const d = await res.json();
    if (!res.ok) throw new Error(d.detail || 'Gagal memulai transkripsi audio');

    const jobId = d.job_id;
    showToast(`Transkripsi audio suara Jepang dimulai! ✨`, "success");

    // Track job status live
    const pollInterval = setInterval(async () => {
      try {
        const jRes = await fetch(`/api/subtitles/jobs/${jobId}`);
        const job = await jRes.json();

        if (btnEl) {
          btnEl.innerHTML = `<span class="inline-block animate-spin mr-1">⌛</span> ${job.percent}%`;
        }

        if (job.status === 'completed') {
          clearInterval(pollInterval);
          showToast(`✔ Subtitle Indonesia berhasil dibuat: ${job.target_file}`, "success");
          if (btnEl) {
            btnEl.disabled = false;
            btnEl.innerHTML = `🎙️ Buat Sub Indo (Audio)`;
          }
          refreshFilesList();
        } else if (job.status === 'failed') {
          clearInterval(pollInterval);
          showToast(`Gagal: ${job.message}`, "error");
          if (btnEl) {
            btnEl.disabled = false;
            btnEl.innerHTML = `🎙️ Buat Sub Indo (Audio)`;
          }
        }
      } catch (e) {}
    }, 3000);

  } catch (err) {
    showToast('Error: ' + err.message, "error");
    if (btnEl) {
      btnEl.disabled = false;
      btnEl.innerHTML = `🎙️ Buat Sub Indo (Audio)`;
    }
  }
}

async function triggerTranslateSub(filename, btnEl = null) {
  if (btnEl) {
    btnEl.disabled = true;
    btnEl.innerHTML = `<span class="inline-block animate-spin mr-1">⌛</span> Menerjemahkan...`;
  }
  showToast(`Menerjemahkan subtitle ke Bahasa Indonesia: ${filename}`, "info");

  try {
    const res = await fetch('/api/subtitles/translate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename: filename, source_lang: "auto" })
    });
    const d = await res.json();
    if (!res.ok) throw new Error(d.detail || 'Gagal memulai terjemahan subtitle');

    const jobId = d.job_id;
    showToast(`Penerjemahan subtitle dimulai!`, "success");

    // Poll live job progress
    const pollInterval = setInterval(async () => {
      try {
        const jRes = await fetch(`/api/subtitles/jobs/${jobId}`);
        const job = await jRes.json();

        if (btnEl) {
          btnEl.innerHTML = `<span class="inline-block animate-spin mr-1">⌛</span> ${job.percent}%`;
        }

        if (job.status === 'completed') {
          clearInterval(pollInterval);
          showToast(`✔ Terjemahan selesai: ${job.target_file}`, "success");
          if (btnEl) {
            btnEl.disabled = false;
            btnEl.innerHTML = `🌐 Terjemahkan ke Indo`;
          }
          refreshFilesList();
        } else if (job.status === 'failed') {
          clearInterval(pollInterval);
          showToast(`Gagal: ${job.message}`, "error");
          if (btnEl) {
            btnEl.disabled = false;
            btnEl.innerHTML = `🌐 Terjemahkan ke Indo`;
          }
        }
      } catch (e) {}
    }, 2500);

  } catch (err) {
    showToast('Error: ' + err.message, "error");
    if (btnEl) {
      btnEl.disabled = false;
      btnEl.innerHTML = `🌐 Terjemahkan ke Indo`;
    }
  }
}

// Settings
async function loadSettings() {
  try {
    const res = await fetch('/api/config');
    const cfg = await res.json();
    document.getElementById('cfg-provider').value = cfg.provider || 'google';
    document.getElementById('cfg-whisper-model').value = cfg.whisper_model || 'medium';
    document.getElementById('cfg-api-key').value = cfg.openai_api_key || '';
    document.getElementById('cfg-base-url').value = cfg.openai_base_url || '';
    document.getElementById('cfg-model').value = cfg.openai_model || '';
    document.getElementById('cfg-groq-key').value = cfg.groq_api_key || '';
  } catch (e) {}
}

async function saveSettings() {
  const payload = {
    provider: document.getElementById('cfg-provider').value,
    whisper_model: document.getElementById('cfg-whisper-model').value,
    openai_api_key: document.getElementById('cfg-api-key').value,
    openai_base_url: document.getElementById('cfg-base-url').value,
    openai_model: document.getElementById('cfg-model').value,
    groq_api_key: document.getElementById('cfg-groq-key').value
  };

  try {
    const res = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (res.ok) alert('Konfigurasi berhasil disimpan! ✨');
  } catch (err) {
    alert('Gagal menyimpan konfigurasi: ' + err.message);
  }
}

// Initialize on load
document.addEventListener('DOMContentLoaded', () => {
  updateFilesBadge();
});
