/* StreamDown v1.3 — Frontend Application Logic */

(function () {
  "use strict";

  // ── DOM References ─────────────────────────────────────────────────────
  const $ = (sel) => document.querySelector(sel);
  const inputUrl = $("#input-url");
  const inputSeason = $("#input-season");
  const inputEpisode = $("#input-episode");
  const inputFilename = $("#input-filename");
  const tvFields = $("#tv-fields");
  const btnInspect = $("#btn-inspect");
  const btnDownload = $("#btn-download");
  const btnDownloadText = $("#btn-download-text");
  const btnSelectAllSubs = $("#btn-select-all-subs");
  const errorBox = $("#error-box");
  const errorText = $("#error-text");
  const loadingBox = $("#loading-box");
  const resultsSection = $("#results-section");

  // Tab Navigation
  const tabBtnDownloader = $("#tab-btn-downloader");
  const tabBtnSaved = $("#tab-btn-saved");
  const tabDownloader = $("#tab-downloader");
  const tabSavedFiles = $("#tab-saved-files");
  const navDownloadsCount = $("#nav-downloads-count");

  // Episodes & Sources
  const episodeSelectorCard = $("#episode-selector-card");
  const seasonsContainer = $("#seasons-container");
  const seasonsBar = $("#seasons-bar");
  const episodesGrid = $("#episodes-grid");
  const episodeCountBadge = $("#episode-count-badge");
  const sourcesList = $("#sources-list");
  const sourcesLoading = $("#sources-loading");
  const sourcesEmptyHint = $("#sources-empty-hint");
  const activeProvidersCount = $("#active-providers-count");

  // Active Downloads (Non-blocking queue)
  const activeDownloadsCard = $("#active-downloads-card");
  const activeTasksList = $("#active-tasks-list");
  const activeTasksCount = $("#active-tasks-count");

  // Saved Files Tab
  const btnRefreshSavedTab = $("#btn-refresh-saved-tab");
  const searchSavedFiles = $("#search-saved-files");
  const savedSummary = $("#saved-summary");
  const downloadsList = $("#downloads-list");

  // Floating Subtitle Progress Banner
  const subActiveBanner = $("#sub-active-banner");
  const subActiveTitle = $("#sub-active-title");
  const subActivePct = $("#sub-active-pct");
  const subActiveMsg = $("#sub-active-msg");
  const subActiveBar = $("#sub-active-bar");

  // Global Subtitle Jobs Map: jobId -> { ...jobData, intervalId }
  const activeSubJobsMap = new Map();

  function trackSubJob(jobId, filename, type) {
    const jobInfo = {
      job_id: jobId,
      source_file: filename,
      type: type,
      status: "processing",
      percent: 0,
      message: "Memulai proses..."
    };
    activeSubJobsMap.set(jobId, jobInfo);
    updateSubBanner();

    const intervalId = setInterval(async () => {
      try {
        const jRes = await fetch(`/api/subtitles/jobs/${jobId}`);
        if (!jRes.ok) return;
        const job = await jRes.json();
        
        jobInfo.percent = job.percent || 0;
        jobInfo.message = job.message || "";
        jobInfo.status = job.status || "processing";
        jobInfo.target_file = job.target_file;
        updateSubBanner();

        // Update button text if on saved tab
        const cleanId = filename.replace(/[^a-zA-Z0-9]/g, '_');
        const btnAudio = $(`#btn-sub-audio-${cleanId}`);
        const btnTrans = $(`#btn-sub-trans-${cleanId}`);
        const targetBtn = type === "transcribe" ? btnAudio : btnTrans;
        if (targetBtn) {
          targetBtn.disabled = true;
          targetBtn.innerHTML = `<span>⌛ ${job.percent}%</span>`;
        }

        if (job.status === "completed") {
          clearInterval(intervalId);
          activeSubJobsMap.delete(jobId);
          updateSubBanner();
          showToast(`✔ Subtitle Indonesia selesai: ${job.target_file}`);
          loadDownloads();
        } else if (job.status === "failed") {
          clearInterval(intervalId);
          activeSubJobsMap.delete(jobId);
          updateSubBanner();
          showToast(`Gagal: ${job.message}`);
          loadDownloads();
        }
      } catch (e) {
        console.warn("Poll sub error:", e);
      }
    }, 2000);

    jobInfo.intervalId = intervalId;
  }

  function updateSubBanner() {
    if (!subActiveBanner) return;
    if (activeSubJobsMap.size === 0) {
      subActiveBanner.classList.add("hidden");
      return;
    }

    subActiveBanner.classList.remove("hidden");
    // Show the latest or highest progress job
    const jobs = Array.from(activeSubJobsMap.values());
    const current = jobs[jobs.length - 1];

    subActiveTitle.textContent = current.type === "transcribe"
      ? `🎙️ AI Transkripsi Suara: ${current.source_file}`
      : `🌐 AI Menerjemahkan: ${current.source_file}`;
    subActivePct.textContent = `${current.percent}%`;
    subActiveMsg.textContent = current.message || "Sedang memproses...";
    subActiveBar.style.transform = `scaleX(${(current.percent || 0) / 100})`;
  }

  // Restore any active subtitle jobs on page reload / initial load
  async function syncActiveSubJobs() {
    try {
      const res = await fetch("/api/subtitles/jobs");
      if (!res.ok) return;
      const allJobs = await res.json();
      for (const [jid, j] of Object.entries(allJobs)) {
        if (j.status === "processing" || j.status === "pending") {
          if (!activeSubJobsMap.has(jid)) {
            trackSubJob(jid, j.source_file || j.target_file, j.type);
          }
        }
      }
    } catch (e) {
      console.warn("Sync sub jobs failed:", e);
    }
  }


  // Settings Tab (Modular AI Subtitle Studio)
  const tabBtnSettings = $("#tab-btn-settings");
  const tabSettings = $("#tab-settings");
  const btnSaveAiSettings = $("#btn-save-ai-settings");

  // Toast
  const toast = $("#toast");
  const toastText = $("#toast-text");

  // State
  let currentTab = "downloader";
  let inspectData = null;
  let currentBaseTitle = "";
  let selectedSeason = null;
  let selectedEpisode = null;
  let allSubsSelected = false;
  let toastTimer = null;
  let activeEventSources = new Map(); // taskId -> EventSource
  let cachedSavedFiles = [];

  // ── Tab Navigation ─────────────────────────────────────────────────────
  function switchTab(tab) {
    currentTab = tab;
    tabDownloader.classList.add("hidden");
    tabSavedFiles.classList.add("hidden");
    if (tabSettings) tabSettings.classList.add("hidden");

    tabBtnDownloader.classList.remove("is-active");
    tabBtnSaved.classList.remove("is-active");
    if (tabBtnSettings) tabBtnSettings.classList.remove("is-active");

    if (tab === "downloader") {
      tabDownloader.classList.remove("hidden");
      tabBtnDownloader.classList.add("is-active");
    } else if (tab === "saved") {
      tabSavedFiles.classList.remove("hidden");
      tabBtnSaved.classList.add("is-active");
      loadDownloads();
    } else if (tab === "settings") {
      if (tabSettings) tabSettings.classList.remove("hidden");
      if (tabBtnSettings) tabBtnSettings.classList.add("is-active");
      loadAiSettings();
    }
  }

  tabBtnDownloader.addEventListener("click", () => switchTab("downloader"));
  tabBtnSaved.addEventListener("click", () => switchTab("saved"));
  if (tabBtnSettings) tabBtnSettings.addEventListener("click", () => switchTab("settings"));
  btnRefreshSavedTab.addEventListener("click", () => {
    loadDownloads();
    showToast("Daftar file diperbarui");
  });

  // ── Toast Notification ─────────────────────────────────────────────────
  function showToast(message) {
    if (toastTimer) clearTimeout(toastTimer);
    toastText.textContent = message;
    toast.classList.remove("hidden");
    toastTimer = setTimeout(() => {
      toast.classList.add("hidden");
    }, 3200);
  }

  // ── Utilities ──────────────────────────────────────────────────────────
  function showError(msg) {
    errorText.textContent = msg;
    errorBox.classList.remove("hidden");
    setTimeout(() => errorBox.classList.add("hidden"), 8000);
  }

  function formatBytes(bytes) {
    if (!bytes || bytes <= 0) return "0 B";
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    if (bytes < 1024 * 1024 * 1024)
      return (bytes / (1024 * 1024)).toFixed(1) + " MB";
    return (bytes / (1024 * 1024 * 1024)).toFixed(2) + " GB";
  }

  function formatSpeed(bps) {
    if (bps <= 0) return "—";
    return formatBytes(bps) + "/s";
  }

  function formatETA(seconds) {
    if (seconds <= 0 || !isFinite(seconds)) return "—";
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
  }

  function formatDate(epochSec) {
    const d = new Date(epochSec * 1000);
    const now = new Date();
    const diff = Math.floor((now - d) / 1000);
    if (diff < 60) return "baru saja";
    if (diff < 3600) return `${Math.floor(diff / 60)}m lalu`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}j lalu`;
    return d.toLocaleDateString("id-ID", {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  }

  function cleanQualityString(raw) {
    if (!raw) return "video";
    const match = raw.match(/(\d{3,4}p|4k|auto)/i);
    if (match) return match[1].toLowerCase();
    return raw.split("|")[0].trim().replace(/\s+/g, "_");
  }

  const statusLabels = {
    pending: "Menunggu...",
    fetching_playlist: "Mengambil playlist...",
    downloading: "Mengunduh segmen...",
    merging: "Menggabungkan ke MP4...",
    downloading_subtitles: "Mengunduh subtitle...",
    completed: "Selesai",
    failed: "Gagal",
    cancelled: "Dibatalkan",
  };

  // ── Inspect ────────────────────────────────────────────────────────────
  btnInspect.addEventListener("click", async () => {
    const url = inputUrl.value.trim();
    if (!url) {
      showError("Masukkan link FrameX atau TMDB/AniList ID.");
      inputUrl.focus();
      return;
    }

    errorBox.classList.add("hidden");
    loadingBox.classList.remove("hidden");
    btnInspect.disabled = true;
    btnInspect.textContent = "Memproses...";

    const body = { url };

    try {
      const resp = await fetch("/api/inspect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await resp.json();

      loadingBox.classList.add("hidden");
      btnInspect.disabled = false;
      btnInspect.textContent = "Cek Link";

      if (!data.success) {
        showError(data.error || "Gagal mengambil informasi stream.");
        return;
      }

      inspectData = data;
      renderResults(data);
    } catch (err) {
      loadingBox.classList.add("hidden");
      btnInspect.disabled = false;
      btnInspect.textContent = "Cek Link";
      showError("Network error: " + err.message);
    }
  });

  inputUrl.addEventListener("keydown", (e) => {
    if (e.key === "Enter") btnInspect.click();
  });

  // ── Render Results ─────────────────────────────────────────────────────
  function renderResults(data) {
    resultsSection.classList.remove("hidden");

    // 1. Poster & Details
    const details = data.details || {};
    const title = details.title || data.default_title || `Media ${data.tmdb_id}`;
    currentBaseTitle = data.default_title || title;
    selectedEpisode = data.selected_episode || null;

    $("#media-title").textContent = title;

    // Type badge
    const typeMap = { movie: "Film", tv: "Serial TV", anime: "Anime" };
    $("#badge-media-type").textContent =
      typeMap[data.media_type] || data.media_type;

    // Year
    const year = details.year;
    const badgeYear = $("#badge-year");
    if (year) {
      badgeYear.textContent = year;
      badgeYear.classList.remove("hidden");
    } else {
      badgeYear.classList.add("hidden");
    }

    // Rating
    const badgeRating = $("#badge-rating");
    if (details.rating && parseFloat(details.rating) > 0) {
      $("#text-rating").textContent = parseFloat(details.rating).toFixed(1);
      badgeRating.classList.remove("hidden");
    } else {
      badgeRating.classList.add("hidden");
    }

    // Provider / Category
    $("#badge-provider").textContent = `kategori: ${data.media_type}`;

    // Poster
    const posterImg = $("#media-poster");
    const placeholder = $("#media-poster-placeholder");
    if (details.poster) {
      posterImg.src = details.poster;
      posterImg.classList.remove("hidden");
      placeholder.classList.add("hidden");
      posterImg.onerror = () => {
        posterImg.classList.add("hidden");
        placeholder.classList.remove("hidden");
      };
    } else {
      posterImg.classList.add("hidden");
      placeholder.classList.remove("hidden");
    }

    // Genres
    const genresContainer = $("#media-genres");
    genresContainer.innerHTML = "";
    if (details.genres && details.genres.length > 0) {
      details.genres.slice(0, 4).forEach((g) => {
        const span = document.createElement("span");
        span.className =
          "text-[10px] bg-zinc-800 text-zinc-300 px-2 py-0.5 rounded-full";
        span.textContent = g;
        genresContainer.appendChild(span);
      });
    }

    // Overview
    const overviewEl = $("#media-overview");
    if (details.overview) {
      overviewEl.textContent = details.overview;
      overviewEl.classList.remove("hidden");
    } else {
      overviewEl.classList.add("hidden");
    }

    // 2. Episode & Season Selector
    selectedSeason = data.selected_season || (details.seasons?.[0]?.season_number ?? 1);
    selectedEpisode = data.selected_episode || null;

    const seasons = (data.media_type === "tv" && details.seasons) ? details.seasons : [];
    const isTV = data.media_type === "tv";

    // Handle Season selector if TV has seasons
    if (isTV && seasons.length > 0) {
      seasonsContainer.classList.remove("hidden");
      renderSeasonsBar(seasons, selectedSeason);
    } else {
      seasonsContainer.classList.add("hidden");
    }

    // Determine total episodes for the active season
    let activeSeasonEpCount = data.total_episodes || 1;
    if (isTV && seasons.length > 0) {
      const curSeasonObj = seasons.find((s) => s.season_number === selectedSeason);
      if (curSeasonObj) {
        activeSeasonEpCount = curSeasonObj.episode_count;
      }
    }

    const isMultiEpisode = activeSeasonEpCount > 1 || seasons.length > 1;
    if (isMultiEpisode) {
      episodeSelectorCard.classList.remove("hidden");
      episodeCountBadge.textContent = isTV
        ? `Season ${selectedSeason}: ${activeSeasonEpCount} Episode`
        : `Total ${activeSeasonEpCount} Episode`;
      renderEpisodeGrid(activeSeasonEpCount, selectedEpisode);
    } else {
      episodeSelectorCard.classList.add("hidden");
    }

    // 3. Render Sources & Subtitles
    if (data.needs_episode_selection && (!data.sources || data.sources.length === 0)) {
      sourcesEmptyHint.textContent = isTV
        ? `Pilih nomor episode Season ${selectedSeason} di atas untuk memuat daftar server stream.`
        : "Pilih nomor episode di atas untuk memuat daftar server stream.";
      sourcesEmptyHint.classList.remove("hidden");
      sourcesList.innerHTML = "";
      activeProvidersCount.textContent = "Pilih episode";
      btnDownload.disabled = true;
      btnDownload.classList.add("opacity-50", "pointer-events-none");
      $("#subtitles-section").classList.add("hidden");
    } else {
      sourcesEmptyHint.classList.add("hidden");
      btnDownload.disabled = false;
      btnDownload.classList.remove("opacity-50", "pointer-events-none");
      renderSourcesAndSubtitles(data);
    }
  }

  // ── Render Seasons Bar ─────────────────────────────────────────────────
  function renderSeasonsBar(seasons, curSeason) {
    seasonsBar.innerHTML = "";
    seasons.forEach((s) => {
      const isCur = s.season_number === curSeason;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = isCur
        ? "px-3 py-1.5 rounded-lg text-xs font-mono font-bold bg-indigo-600 text-white shadow-sm shadow-indigo-600/30 transition-all cursor-pointer whitespace-nowrap"
        : "px-3 py-1.5 rounded-lg text-xs font-mono bg-zinc-900 hover:bg-zinc-800 text-zinc-400 border border-zinc-800 hover:text-white transition-all cursor-pointer whitespace-nowrap";
      btn.textContent = `${s.name} (${s.episode_count} Ep)`;
      btn.addEventListener("click", () => switchSeason(s.season_number, s.episode_count));
      seasonsBar.appendChild(btn);
    });
  }

  // ── Switch Season ──────────────────────────────────────────────────────
  function switchSeason(seasonNum, epCount) {
    selectedSeason = seasonNum;
    selectedEpisode = null;

    if (inspectData && inspectData.details && inspectData.details.seasons) {
      renderSeasonsBar(inspectData.details.seasons, selectedSeason);
    }

    episodeCountBadge.textContent = `Season ${selectedSeason}: ${epCount} Episode`;
    renderEpisodeGrid(epCount, null);

    sourcesEmptyHint.textContent = `Pilih nomor episode Season ${selectedSeason} di atas untuk memuat daftar server stream.`;
    sourcesEmptyHint.classList.remove("hidden");
    sourcesList.innerHTML = "";
    activeProvidersCount.textContent = "Pilih episode";
    btnDownload.disabled = true;
    btnDownload.classList.add("opacity-50", "pointer-events-none");
    $("#subtitles-section").classList.add("hidden");
  }

  // ── Render Episode Grid ────────────────────────────────────────────────
  function renderEpisodeGrid(total, activeEp) {
    episodesGrid.innerHTML = "";
    for (let i = 1; i <= total; i++) {
      const isCur = activeEp === i;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.dataset.ep = i;
      btn.className = `ep-btn ${isCur ? 'is-selected' : ''}`;
      btn.textContent = `EP ${i}`;
      btn.addEventListener("click", () => selectEpisode(i));
      episodesGrid.appendChild(btn);
    }
  }

  // ── Select Episode Event (NON-BLOCKING: keeps downloads running) ───────
  async function selectEpisode(epNum) {
    if (!inspectData) return;
    selectedEpisode = epNum;

    // Highlight button
    document.querySelectorAll(".ep-btn").forEach((btn) => {
      const isCurrent = parseInt(btn.dataset.ep, 10) === epNum;
      if (isCurrent) {
        btn.classList.add("is-selected");
      } else {
        btn.classList.remove("is-selected");
      }
    });

    sourcesLoading.classList.remove("hidden");
    sourcesEmptyHint.classList.add("hidden");
    sourcesList.innerHTML = "";
    activeProvidersCount.textContent = "Memeriksa...";
    btnDownload.disabled = true;
    btnDownload.classList.add("opacity-50", "pointer-events-none");

    try {
      const body = {
        url: inputUrl.value.trim(),
        episode: epNum,
      };
      if (inspectData.media_type === "tv" && selectedSeason !== null) {
        body.season = selectedSeason;
      }
      const resp = await fetch("/api/inspect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await resp.json();

      sourcesLoading.classList.add("hidden");

      if (!data.success) {
        showError(data.error || `Gagal mengambil stream untuk Episode ${epNum}.`);
        return;
      }

      inspectData.sources = data.sources;
      inspectData.subtitles = data.subtitles;
      inspectData.default_title = data.default_title;
      currentBaseTitle = data.default_title;

      btnDownload.disabled = false;
      btnDownload.classList.remove("opacity-50", "pointer-events-none");

      renderSourcesAndSubtitles(data);
      const epLabel = (inspectData.media_type === "tv" && selectedSeason !== null)
        ? `Season ${selectedSeason} Episode ${epNum}`
        : `Episode ${epNum}`;
      showToast(`${epLabel} dimuat: ${data.sources.length} server aktif.`);
    } catch (err) {
      sourcesLoading.classList.add("hidden");
      showError("Network error: " + err.message);
    }
  }

  // ── Render Sources & Subtitles ─────────────────────────────────────────
  function renderSourcesAndSubtitles(data) {
    sourcesList.innerHTML = "";
    activeProvidersCount.textContent = `${data.sources.length} server aktif`;

    function updateFilenameForSource(src) {
      const cleanQ = cleanQualityString(src.quality);
      inputFilename.value = `${currentBaseTitle} [${cleanQ}]`;
    }

    data.sources.forEach((src, i) => {
      const id = `source-${i}`;
      const div = document.createElement("div");
      div.className = "file-row";
      div.style.cursor = "pointer";

      const audioBadge = src.audio
        ? `<span class="badge-tag ${src.audio === 'dub' ? 'badge-tag--accent' : 'badge-tag--success'}">${src.audio.toUpperCase()}</span>`
        : "";

      div.innerHTML = `
        <div style="display: flex; align-items: center; gap: var(--space-sm);">
          <input type="radio" name="source" id="${id}" value="${i}" style="accent-color: var(--color-accent);" ${i === 0 ? "checked" : ""}>
          <label for="${id}" style="cursor: pointer; display: flex; align-items: center; gap: var(--space-xs);">
            <span style="font-size: var(--text-xs); font-weight: 500;">${src.quality}</span>
            <span class="file-meta">${src.server}</span>
            ${audioBadge}
          </label>
        </div>
        <span class="badge-tag">${src.type.toUpperCase()}</span>
      `;

      div.addEventListener("click", () => {
        const radio = div.querySelector("input");
        radio.checked = true;
        updateFilenameForSource(src);
      });

      sourcesList.appendChild(div);
    });

    if (data.sources.length > 0) {
      updateFilenameForSource(data.sources[0]);
    } else {
      inputFilename.value = currentBaseTitle;
    }

    // Subtitles
    const subsList = $("#subtitles-list");
    subsList.innerHTML = "";
    const subsSection = $("#subtitles-section");
    if (!data.subtitles || data.subtitles.length === 0) {
      subsSection.classList.add("hidden");
    } else {
      subsSection.classList.remove("hidden");
      data.subtitles.forEach((sub, i) => {
        const id = `sub-${i}`;
        const div = document.createElement("div");
        div.className =
          "check-item flex items-center space-x-2 px-2.5 py-1.5 rounded-lg cursor-pointer border border-transparent hover:border-zinc-800";
        div.innerHTML = `
          <input type="checkbox" id="${id}" value="${i}" class="accent-indigo-500 w-3 h-3 cursor-pointer" ${sub.is_default ? "checked" : ""}>
          <label for="${id}" class="text-xs text-zinc-300 cursor-pointer truncate flex-1">${sub.label}</label>
          <span class="text-[9px] text-zinc-600 uppercase font-mono">${sub.format}</span>
        `;
        div.addEventListener("click", (e) => {
          if (e.target.tagName !== "INPUT") {
            const cb = div.querySelector("input");
            cb.checked = !cb.checked;
          }
        });
        subsList.appendChild(div);
      });
    }

    allSubsSelected = false;
  }

  // Toggle all subtitles
  btnSelectAllSubs.addEventListener("click", () => {
    allSubsSelected = !allSubsSelected;
    document
      .querySelectorAll('#subtitles-list input[type="checkbox"]')
      .forEach((cb) => (cb.checked = allSubsSelected));
  });

  // ── Start Download (NON-BLOCKING: Stays on page so user can pick next EP) ─
  btnDownload.addEventListener("click", async () => {
    if (!inspectData) return;

    const selectedSource = document.querySelector('input[name="source"]:checked');
    if (!selectedSource) {
      showError("Pilih salah satu sumber resolusi/provider.");
      return;
    }

    const checkedSubs = [
      ...document.querySelectorAll('#subtitles-list input[type="checkbox"]:checked'),
    ].map((cb) => parseInt(cb.value, 10));

    const filename = inputFilename.value.trim();

    const body = {
      url: inputUrl.value.trim(),
      source_index: parseInt(selectedSource.value, 10),
      subtitle_indices: checkedSubs,
      filename: filename,
    };

    if (selectedEpisode !== null) {
      body.episode = selectedEpisode;
    }
    if (inspectData && inspectData.media_type === "tv" && selectedSeason !== null) {
      body.season = selectedSeason;
    }

    btnDownload.disabled = true;
    btnDownloadText.textContent = "Mempersiapkan...";

    try {
      const resp = await fetch("/api/download", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || "Download request failed");
      }

      const data = await resp.json();

      // Non-blocking notification
      showToast(`Download dimulai: ${filename || "Film/Episode"}`);
      btnDownloadText.textContent = "✓ Download Dimulai!";

      // Re-enable download button after 1.5 seconds so user can immediately download next episode
      setTimeout(() => {
        btnDownload.disabled = false;
        btnDownloadText.textContent = "Mulai Download Sekarang";
      }, 1500);

      // Start task tracking widget (without hiding the page!)
      createTaskTracker(data.task_id, filename || currentBaseTitle);

    } catch (err) {
      showError("Error: " + err.message);
      btnDownload.disabled = false;
      btnDownloadText.textContent = "Mulai Download Sekarang";
    }
  });

  // ── Non-Blocking Active Task Widget ────────────────────────────────────
  function createTaskTracker(taskId, title) {
    activeDownloadsCard.classList.remove("hidden");

    const taskCard = document.createElement("div");
    taskCard.id = `task-card-${taskId}`;
    taskCard.className = "task-card";
    taskCard.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <span style="font-size: var(--text-xs); font-weight: 500; overflow-wrap: break-word; min-width: 0;">${title}</span>
        <div style="display: flex; gap: var(--space-xs); align-items: center;">
          <span class="task-status badge-tag">Memulai...</span>
          <button onclick="window.StreamDown.cancelTask('${taskId}')" class="btn btn--sm" style="color: var(--color-error);">Batal</button>
        </div>
      </div>

      <div class="progress-track">
        <div class="progress-bar task-bar"></div>
      </div>

      <div style="display: flex; justify-content: space-between; font-family: var(--font-outlier); font-size: 11px; color: var(--color-muted);">
        <span class="task-percent">0%</span>
        <span class="task-speed">--</span>
        <span class="task-eta">--</span>
        <span class="task-segments">0/0</span>
      </div>

      <div class="task-actions hidden" style="display: flex; justify-content: space-between; align-items: center; border-top: var(--rule-hair) solid var(--color-rule-2); padding-top: var(--space-xs); margin-top: var(--space-xs);">
        <span class="badge-tag badge-tag--success">Selesai diunduh!</span>
        <div style="display: flex; gap: var(--space-xs);">
          <button onclick="window.StreamDown.openSavedTab()" class="btn btn--sm">Lihat File</button>
          <a class="task-dl-btn btn btn--sm btn--primary" href="#" download>Unduh MP4</a>
        </div>
      </div>
    `;

    activeTasksList.prepend(taskCard);
    updateActiveTasksCount();

    // Start SSE stream for this task
    const es = new EventSource(`/api/progress/${taskId}`);
    activeEventSources.set(taskId, es);

    es.onmessage = (event) => {
      const d = JSON.parse(event.data);
      if (d.error && !d.status) {
        es.close();
        activeEventSources.delete(taskId);
        taskCard.querySelector(".task-status").textContent = "Gagal";
        taskCard.querySelector(".task-status").classList.add("text-red-400");
        return;
      }

      // Update UI in widget
      const statusText = statusLabels[d.status] || d.status;
      taskCard.querySelector(".task-status").textContent = statusText;
      taskCard.querySelector(".task-bar").style.transform = `scaleX(${(d.percent || 0) / 100})`;
      taskCard.querySelector(".task-percent").textContent = d.percent.toFixed(1) + "%";
      taskCard.querySelector(".task-speed").textContent = formatSpeed(d.speed_bps);
      taskCard.querySelector(".task-eta").textContent = formatETA(d.eta_seconds);
      taskCard.querySelector(".task-segments").textContent =
        d.downloaded_segments + "/" + d.total_segments;

      if (d.status === "completed") {
        es.close();
        activeEventSources.delete(taskId);
        taskCard.querySelector(".task-indicator").classList.replace("bg-indigo-400", "bg-emerald-400");
        taskCard.querySelector(".task-indicator").classList.remove("animate-pulse");
        taskCard.querySelector(".task-bar").className = "task-bar h-full bg-emerald-500 rounded-full";
        taskCard.querySelector(".task-status").textContent = "Selesai";
        taskCard.querySelector(".task-status").classList.add("text-emerald-400");
        taskCard.querySelector(".task-cancel-btn").classList.add("hidden");

        const actions = taskCard.querySelector(".task-actions");
        actions.classList.remove("hidden");
        if (d.output_file) {
          actions.querySelector(".task-dl-btn").href = `/api/files/${encodeURIComponent(d.output_file)}`;
        }

        updateActiveTasksCount();
        loadDownloads();
        showToast(`Selesai diunduh: ${d.filename || "File"}`);

      } else if (d.status === "failed") {
        es.close();
        activeEventSources.delete(taskId);
        taskCard.querySelector(".task-status").textContent = "Gagal";
        taskCard.querySelector(".task-status").classList.add("text-red-400");
        taskCard.querySelector(".task-indicator").classList.replace("bg-indigo-400", "bg-red-400");
        updateActiveTasksCount();

      } else if (d.status === "cancelled") {
        es.close();
        activeEventSources.delete(taskId);
        taskCard.querySelector(".task-status").textContent = "Dibatalkan";
        taskCard.querySelector(".task-status").classList.add("text-zinc-500");
        taskCard.querySelector(".task-indicator").classList.replace("bg-indigo-400", "bg-zinc-600");
        updateActiveTasksCount();
      }
    };

    es.onerror = () => {
      es.close();
      activeEventSources.delete(taskId);
      updateActiveTasksCount();
    };
  }

  function updateActiveTasksCount() {
    const running = activeEventSources.size;
    activeTasksCount.textContent = `${running} berjalan`;
    if (activeTasksList.children.length === 0) {
      activeDownloadsCard.classList.add("hidden");
    }
  }

  // ── Downloads Manager (List, Search & Delete) ──────────────────────────
  async function loadDownloads() {
    try {
      const resp = await fetch("/api/downloads");
      const files = await resp.json();
      cachedSavedFiles = files;

      navDownloadsCount.textContent = files.length;
      renderSavedFilesList(files);
    } catch (err) {
      console.warn("Failed to load downloads:", err);
    }
  }

  function renderSavedFilesList(files) {
    const totalBytes = files.reduce((acc, f) => acc + (f.size_bytes || 0), 0);
    savedSummary.textContent = `${files.length} file (${formatBytes(totalBytes)})`;

    if (files.length === 0) {
      downloadsList.innerHTML = `
        <div class="py-12 text-center text-zinc-500 space-y-2">
          <svg class="w-8 h-8 mx-auto opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M20.25 7.5l-.625 10.632a2.25 2.25 0 01-2.247 2.118H6.622a2.25 2.25 0 01-2.247-2.118L3.75 7.5M10 11.25h4M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125z"/></svg>
          <p class="text-xs">Belum ada file di folder downloads.</p>
        </div>
      `;
      return;
    }

    downloadsList.innerHTML = "";
    files.forEach((f) => {
      const isVideo = f.ext === "mp4" || f.ext === "mkv";
      const iconColor = isVideo ? "text-indigo-400" : "text-yellow-400";
      const icon = isVideo
        ? `<svg class="w-5 h-5 ${iconColor} shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M15.75 10.5l4.72-4.72a.75.75 0 011.28.53v11.38a.75.75 0 01-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 002.25-2.25v-9a2.25 2.25 0 00-2.25-2.25h-9A2.25 2.25 0 002.25 7.5v9a2.25 2.25 0 002.25 2.25z"/></svg>`
        : `<svg class="w-5 h-5 ${iconColor} shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"/></svg>`;

      const div = document.createElement("div");
      div.className = "file-row";

      // Check if this file has an active sub job running
      let activeJobForFile = null;
      for (const [jid, j] of activeSubJobsMap.entries()) {
        if (j.source_file === f.filename && (j.status === "processing" || j.status === "pending")) {
          activeJobForFile = j;
          break;
        }
      }

      div.innerHTML = `
        <div style="display: flex; align-items: center; gap: var(--space-sm); min-width: 0;">
          <span style="font-family: var(--font-outlier); font-size: 11px; padding: 2px 4px; border: var(--rule-hair) solid var(--color-rule);">${f.ext.toUpperCase()}</span>
          <div style="min-width: 0;">
            <div class="file-name">${f.filename}</div>
            <div class="file-meta">
              <span>${formatBytes(f.size_bytes)}</span>
              <span> &middot; </span>
              <span>${formatDate(f.modified_at)}</span>
            </div>
          </div>
        </div>
        <div style="display: flex; align-items: center; gap: var(--space-xs); flex-shrink: 0;">
          ${isVideo ? `
            <button id="btn-sub-audio-${f.filename.replace(/[^a-zA-Z0-9]/g, '_')}" onclick="window.StreamDown.makeSubFromAudio('${encodeURIComponent(f.filename)}', this)" class="btn btn--sm" ${activeJobForFile ? 'disabled' : ''} title="Buat Subtitle Indonesia dari Audio Suara Jepang">
              <span>${activeJobForFile ? `⌛ ${activeJobForFile.percent || 0}%` : '🎙️ Sub Indo'}</span>
            </button>
          ` : ''}
          ${!isVideo && !f.filename.includes('.id.') ? `
            <button id="btn-sub-trans-${f.filename.replace(/[^a-zA-Z0-9]/g, '_')}" onclick="window.StreamDown.translateSub('${encodeURIComponent(f.filename)}', this)" class="btn btn--sm" ${activeJobForFile ? 'disabled' : ''} title="Terjemahkan Subtitle ke Bahasa Indonesia">
              <span>${activeJobForFile ? `⌛ ${activeJobForFile.percent || 0}%` : '🌐 Terjemahkan'}</span>
            </button>
          ` : ''}
          ${f.filename.includes('.id.') ? `
            <span class="badge-tag badge-tag--success">SUB INDO</span>
            <button onclick="window.StreamDown.shiftTimingPrompt('${encodeURIComponent(f.filename)}')" class="btn btn--sm" title="Geser sinkronisasi waktu subtitle (delay / majukan detik)">
              <span>⏱️ ±detik</span>
            </button>
          ` : ''}
          <a href="${f.url}" download class="btn btn--sm btn--primary">
            <span>Unduh</span>
          </a>
          <button onclick="window.StreamDown.copyLink('${f.url}')" class="btn btn--sm">
            <span>Salin</span>
          </button>
          <button onclick="window.StreamDown.deleteFile('${encodeURIComponent(f.filename)}')" class="btn btn--sm" style="color: var(--color-error);" title="Hapus file">
            <span>Hapus</span>
          </button>
        </div>
      `;
      downloadsList.appendChild(div);
    });
  }

  // Filter search
  searchSavedFiles.addEventListener("input", (e) => {
    const q = e.target.value.toLowerCase().trim();
    if (!q) {
      renderSavedFilesList(cachedSavedFiles);
      return;
    }
    const filtered = cachedSavedFiles.filter((f) =>
      f.filename.toLowerCase().includes(q)
    );
    renderSavedFilesList(filtered);
  });

  // Global namespace for inline onclick handlers
  window.StreamDown = {
    openSavedTab: () => {
      switchTab("saved");
    },

    cancelTask: async (taskId) => {
      try {
        await fetch(`/api/cancel/${taskId}`, { method: "POST" });
        const es = activeEventSources.get(taskId);
        if (es) {
          es.close();
          activeEventSources.delete(taskId);
        }
        updateActiveTasksCount();
        showToast("Unduhan dibatalkan.");
      } catch (err) {
        console.warn("Cancel task failed:", err);
      }
    },

    copyLink: (relativeUrl) => {
      const fullUrl = window.location.origin + relativeUrl;
      navigator.clipboard.writeText(fullUrl).then(() => {
        showToast("Link unduhan berhasil disalin!");
      });
    },

    deleteFile: async (encodedFilename) => {
      const filename = decodeURIComponent(encodedFilename);
      if (!confirm(`Hapus permanen file ini?\n\n${filename}`)) {
        return;
      }
      try {
        const resp = await fetch(`/api/files/${encodedFilename}`, {
          method: "DELETE",
        });
        if (resp.ok) {
          showToast(`File ${filename} berhasil dihapus.`);
          loadDownloads();
        } else {
          const err = await resp.json();
          showError("Gagal menghapus file: " + (err.detail || "Unknown error"));
        }
      } catch (err) {
        showError("Network error saat menghapus file: " + err.message);
      }
    },

    // ── AI Subtitle Studio Handlers ──
    makeSubFromAudio: async (encodedFilename, btnEl) => {
      const filename = decodeURIComponent(encodedFilename);
      if (btnEl) {
        btnEl.disabled = true;
        btnEl.innerHTML = `<span>⌛ Mulai...</span>`;
      }
      showToast(`Mengekstrak audio & memproses subtitle AI: ${filename}`);

      try {
        const res = await fetch("/api/subtitles/transcribe-audio", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ filename: filename, chunk_minutes: 4.0 })
        });
        const d = await res.json();
        if (!res.ok) throw new Error(d.detail || "Gagal memulai transkripsi audio");

        showToast("Transkripsi suara audio Jepang dimulai! ✨");
        trackSubJob(d.job_id, filename, "transcribe");
      } catch (err) {
        showToast("Error: " + err.message);
        if (btnEl) {
          btnEl.disabled = false;
          btnEl.innerHTML = `<span>🎙️ Sub Indo</span>`;
        }
      }
    },

    translateSub: async (encodedFilename, btnEl) => {
      const filename = decodeURIComponent(encodedFilename);
      if (btnEl) {
        btnEl.disabled = true;
        btnEl.innerHTML = `<span>⌛ Mulai...</span>`;
      }
      showToast(`Menerjemahkan subtitle: ${filename}`);

      try {
        const res = await fetch("/api/subtitles/translate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ filename: filename, source_lang: "auto" })
        });
        const d = await res.json();
        if (!res.ok) throw new Error(d.detail || "Gagal memulai terjemahan subtitle");

        showToast("Penerjemahan subtitle dimulai!");
        trackSubJob(d.job_id, filename, "translate");
      } catch (err) {
        showToast("Error: " + err.message);
        if (btnEl) {
          btnEl.disabled = false;
          btnEl.innerHTML = `<span>🌐 Terjemahkan</span>`;
        }
      }
    },

    shiftTimingPrompt: async (encodedFilename) => {
      const filename = decodeURIComponent(encodedFilename);
      const val = prompt(`Geser waktu sinkronisasi untuk ${filename} (detik):\nContoh: 1.4 untuk memundurkan 1.4 detik, atau -1.0 untuk memajukan 1 detik:`, "1.4");
      if (!val) return;
      const offset = parseFloat(val);
      if (isNaN(offset)) return alert("Masukkan angka detik yang valid!");

      try {
        const res = await fetch("/api/subtitles/shift-timing", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ filename: filename, offset_seconds: offset })
        });
        const d = await res.json();
        if (res.ok) {
          showToast(d.message);
          loadDownloads();
        } else {
          showToast("Gagal: " + (d.detail || "Error"), "error");
        }
      } catch (e) {
        showToast("Error: " + e.message, "error");
      }
    }
  };

  // ── AI Settings Handlers ──
  async function loadAiSettings() {
    try {
      const res = await fetch("/api/subtitles/config");
      if (res.ok) {
        const cfg = await res.json();
        $("#cfg-provider").value = cfg.provider || "google";
        $("#cfg-model").value = cfg.openai_model || "";
        $("#cfg-base-url").value = cfg.openai_base_url || "";
        $("#cfg-api-key").value = cfg.openai_api_key || "";
      }
    } catch (e) {}
  }

  if (btnSaveAiSettings) {
    btnSaveAiSettings.addEventListener("click", async () => {
      const payload = {
        provider: $("#cfg-provider").value,
        openai_model: $("#cfg-model").value,
        openai_base_url: $("#cfg-base-url").value,
        openai_api_key: $("#cfg-api-key").value,
      };
      try {
        const res = await fetch("/api/subtitles/config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        if (res.ok) showToast("Pengaturan AI berhasil disimpan! ✨");
      } catch (e) {
        showToast("Gagal menyimpan pengaturan: " + e.message);
      }
    });
  }

  // Initial load
  loadDownloads();
  syncActiveSubJobs();
})();
