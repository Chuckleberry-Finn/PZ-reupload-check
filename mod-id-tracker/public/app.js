const LS_MODS = "tracked_mods_v2";
const LS_COLLAPSED = "collapsed_groups_v2";
const LS_DMCA_MANAGER = "dmca_manager_v1";
const LS_SEARCH_RESULTS = "search_results_v1";
const LS_PROFILES = "profiles_v1";
const LS_ACTIVE_PROFILE = "active_profile_v1";
const LS_LEGAL_NOTICE_COLLAPSED = "legal_notice_collapsed_v1";
const DEFAULT_PROFILE_NAME = "Default Profile";

const trackedListEl = document.getElementById("trackedList");
const statsBarEl = document.getElementById("statsBar");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");

const addModBtn = document.getElementById("addModBtn");
const runBtn = document.getElementById("runSearchBtn");
const exportBtn = document.getElementById("exportBtn");
const importBtn = document.getElementById("importBtn");
const importProfileBtn = document.getElementById("importProfileBtn");
const deleteAllBtn = document.getElementById("deleteAllBtn");
const clearResultsBtn = document.getElementById("clearResultsBtn");
const filterUnapprovedCheckbox = document.getElementById("filterUnapproved");
const sortResultsSelect = document.getElementById("sortResults");
const hideZeroResultsCheckbox = document.getElementById("hideZeroResults");

const dmcaManagerList = document.getElementById("dmcaManagerList");
const dmcaPendingCount = document.getElementById("dmcaPendingCount");
const dmcaFiledCount = document.getElementById("dmcaFiledCount");
const dmcaTakenDownCount = document.getElementById("dmcaTakenDownCount");
const dmcaTotalCount = document.getElementById("dmcaTotalCount");
const dmcaVerifiedCount = document.getElementById("dmcaVerifiedCount");
const exportDmcaBtn = document.getElementById("exportDmcaBtn");
const importDmcaBtn = document.getElementById("importDmcaBtn");
const clearDmcaBtn = document.getElementById("clearDmcaBtn");
const recheckFiledBtn = document.getElementById("recheckFiledBtn");
const showPendingOnlyCheckbox = document.getElementById("showPendingOnly");
const showFiledOnlyCheckbox = document.getElementById("showFiledOnly");
const showTakenDownOnlyCheckbox = document.getElementById("showTakenDownOnly");

const profileSelect = document.getElementById("profileSelect");
const newProfileBtn = document.getElementById("newProfileBtn");
const renameProfileBtn = document.getElementById("renameProfileBtn");
const deleteProfileBtn = document.getElementById("deleteProfileBtn");
const profileMenuBtn = document.getElementById("profileMenuBtn");
const profileDropdown = document.getElementById("profileDropdown");

let trackedMods = [];
let collapsedGroups = new Set();
let searchResults = {};
let filterUnapproved = false;
let sortOrder = "default";
let hideZeroResults = false;
let dmcaEntries = [];
let profiles = {};
let activeProfileId = null;
let showPendingOnly = false;
let showFiledOnly = false;
let showTakenDownOnly = false;

const SINGLE_DELETE_HOLD_TIME = 330;
const DELETE_ALL_HOLD_TIME = 1000;

// ============================================================================
// STEAM RATE LIMITER
// Enforces delays between requests and handles rate limit retries
// ============================================================================
const SteamRateLimiter = {
  REQUEST_DELAY: 3500,        // 3.5 seconds between consecutive requests
  INITIAL_RETRY_DELAY: 6000,  // 6 seconds on first rate limit
  SUBSEQUENT_RETRY_DELAY: 15000, // 15 seconds for subsequent retries
  MAX_RETRIES: 5,             // Maximum retry attempts
  
  lastRequestTime: 0,
  requestQueue: [],
  isProcessing: false,
  
  // Wait for the required delay between requests
  async waitForNextSlot() {
    const now = Date.now();
    const timeSinceLastRequest = now - this.lastRequestTime;
    
    if (timeSinceLastRequest < this.REQUEST_DELAY) {
      const waitTime = this.REQUEST_DELAY - timeSinceLastRequest;
      await new Promise(resolve => setTimeout(resolve, waitTime));
    }
    
    this.lastRequestTime = Date.now();
  },
  
  // Execute a fetch with rate limit handling and retries
  async fetchWithRateLimit(url, options = {}) {
    await this.waitForNextSlot();
    
    let retryCount = 0;
    let lastError = null;
    
    while (retryCount <= this.MAX_RETRIES) {
      try {
        const resp = await fetch(url, options);
        
        // Check for rate limiting
        if (resp.status === 429 || resp.status === 403) {
          retryCount++;
          
          if (retryCount > this.MAX_RETRIES) {
            const errorMsg = `Steam rate limit: Max retries (${this.MAX_RETRIES}) exceeded. Please wait a few minutes and try again.`;
            setStatus(`${errorMsg}`);
            throw new Error(errorMsg);
          }
          
          // Calculate retry delay
          const retryDelay = retryCount === 1 ? this.INITIAL_RETRY_DELAY : this.SUBSEQUENT_RETRY_DELAY;
          const retrySeconds = retryDelay / 1000;
          
          setStatus(`Rate limited by Steam. Retry ${retryCount}/${this.MAX_RETRIES} in ${retrySeconds}s...`);
          console.warn(`[RateLimiter] Rate limited (${resp.status}). Retry ${retryCount}/${this.MAX_RETRIES} in ${retrySeconds}s`);
          
          await new Promise(resolve => setTimeout(resolve, retryDelay));
          this.lastRequestTime = Date.now(); // Reset timing after wait
          continue;
        }
        
        return resp;
        
      } catch (error) {
        // Network errors - not rate limiting
        if (error.message && error.message.includes('rate limit')) {
          throw error; // Re-throw rate limit errors
        }
        
        retryCount++;
        lastError = error;
        
        if (retryCount > this.MAX_RETRIES) {
          const errorMsg = `Request failed after ${this.MAX_RETRIES} retries: ${error.message}`;
          setStatus(`${errorMsg}`);
          throw new Error(errorMsg);
        }
        
        const retryDelay = retryCount === 1 ? this.INITIAL_RETRY_DELAY : this.SUBSEQUENT_RETRY_DELAY;
        const retrySeconds = retryDelay / 1000;
        
        setStatus(`Request error. Retry ${retryCount}/${this.MAX_RETRIES} in ${retrySeconds}s...`);
        console.warn(`[RateLimiter] Error: ${error.message}. Retry ${retryCount}/${this.MAX_RETRIES} in ${retrySeconds}s`);
        
        await new Promise(resolve => setTimeout(resolve, retryDelay));
        this.lastRequestTime = Date.now();
      }
    }
    
    throw lastError || new Error('Request failed after max retries');
  },
  
  // Reset the rate limiter state (e.g., when starting a new batch)
  reset() {
    this.lastRequestTime = 0;
  }
};

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function generateDmcaMessage(entry, trackedMods) {
  const originalModUrls = [];

  // Build list of original mod URLs from containsModIds
  if (entry.containsModIds && entry.containsModIds.length > 0) {
    entry.containsModIds.forEach(modId => {
      const trackedMod = trackedMods.find(m => m.modId === modId);
      if (trackedMod && trackedMod.workshopId) {
        originalModUrls.push(`https://steamcommunity.com/sharedfiles/filedetails/?id=${trackedMod.workshopId}`);
      }
    });
  }

  if (originalModUrls.length === 0) {
    return "The infringing content contains unauthorized copies of my original work.";
  }

  const urlList = originalModUrls.map(url => `- ${url}`).join('\n');

  return `The infringing content contains unauthorized copies and redistribution of my original copyrighted work.
The following original items that I created can be found bundled within the infringing upload:

${urlList}

This upload violates my copyright by redistributing my work without permission.`;
}

function generateId() {
  return `mod_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
}

function formatDate(dateStr) {
  if (!dateStr) return "";
  const date = new Date(dateStr);
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function loadData() {
  // Load profiles
  try {
    const stored = localStorage.getItem(LS_PROFILES);
    if (stored) {
      profiles = JSON.parse(stored);
    } else {
      // Create default profile
      const defaultId = generateId();
      profiles[defaultId] = {
        name: DEFAULT_PROFILE_NAME,
        mods: [],
        dmca: [],
        searchResults: {},
        collapsed: []
      };
    }
  } catch (e) {
    console.error("Failed to load profiles:", e);
    const defaultId = generateId();
    profiles[defaultId] = {
      name: DEFAULT_PROFILE_NAME,
      mods: [],
      dmca: [],
      searchResults: {},
      collapsed: []
    };
  }

  // Load active profile
  try {
    const stored = localStorage.getItem(LS_ACTIVE_PROFILE);
    if (stored && profiles[stored]) {
      activeProfileId = stored;
    } else {
      activeProfileId = Object.keys(profiles)[0];
    }
  } catch (e) {
    console.error("Failed to load active profile:", e);
    activeProfileId = Object.keys(profiles)[0];
  }

  // Load data from active profile
  loadActiveProfile();
}

function loadActiveProfile() {
  if (!activeProfileId || !profiles[activeProfileId]) {
    activeProfileId = Object.keys(profiles)[0];
  }

  const profile = profiles[activeProfileId];
  trackedMods = profile.mods || [];
  dmcaEntries = profile.dmca || [];

  // Deduplicate DMCA entries by workshop ID (keep the most recent/complete one)
  const uniqueEntries = new Map();
  dmcaEntries.forEach(entry => {
    const existing = uniqueEntries.get(entry.workshopId);
    if (!existing || (entry.filedDate && !existing.filedDate) || (entry.takenDownDate && !existing.takenDownDate)) {
      uniqueEntries.set(entry.workshopId, entry);
    }
  });
  dmcaEntries = Array.from(uniqueEntries.values());

  // Migrate old DMCA entries to include containsModIds and takenDownDate
  dmcaEntries = dmcaEntries.map(entry => {
    if (!entry.containsModIds) {
      entry.containsModIds = entry.modId ? [entry.modId] : [];
    }
    if (entry.takenDownDate === undefined) {
      entry.takenDownDate = null;
    }
    return entry;
  });

  searchResults = profile.searchResults || {};
  collapsedGroups = new Set(profile.collapsed || []);
  filterUnapproved = profile.filterUnapproved || false;
  sortOrder = profile.sortOrder || "default";
  hideZeroResults = profile.hideZeroResults || false;
  showPendingOnly = profile.showPendingOnly || false;
  showFiledOnly = profile.showFiledOnly || false;
  showTakenDownOnly = profile.showTakenDownOnly || false;

  // Update UI elements to match loaded state
  if (filterUnapprovedCheckbox) filterUnapprovedCheckbox.checked = filterUnapproved;
  if (sortResultsSelect) sortResultsSelect.value = sortOrder;
  if (hideZeroResultsCheckbox) hideZeroResultsCheckbox.checked = hideZeroResults;
  if (showPendingOnlyCheckbox) showPendingOnlyCheckbox.checked = showPendingOnly;
  if (showFiledOnlyCheckbox) showFiledOnlyCheckbox.checked = showFiledOnly;
  if (showTakenDownOnlyCheckbox) showTakenDownOnlyCheckbox.checked = showTakenDownOnly;
}

function saveProfiles() {
  try {
    localStorage.setItem(LS_PROFILES, JSON.stringify(profiles));
    localStorage.setItem(LS_ACTIVE_PROFILE, activeProfileId);
  } catch (e) {
    console.error("Failed to save profiles:", e);
  }
}

function saveActiveProfile() {
  if (!activeProfileId || !profiles[activeProfileId]) return;

  profiles[activeProfileId].mods = trackedMods;
  profiles[activeProfileId].dmca = dmcaEntries;
  profiles[activeProfileId].searchResults = searchResults;
  profiles[activeProfileId].collapsed = [...collapsedGroups];
  profiles[activeProfileId].filterUnapproved = filterUnapproved;
  profiles[activeProfileId].sortOrder = sortOrder;
  profiles[activeProfileId].hideZeroResults = hideZeroResults;
  profiles[activeProfileId].showPendingOnly = showPendingOnly;
  profiles[activeProfileId].showFiledOnly = showFiledOnly;
  profiles[activeProfileId].showTakenDownOnly = showTakenDownOnly;

  saveProfiles();
}

function saveData() {
  saveActiveProfile();
}

function saveCollapsedState() {
  saveActiveProfile();
}

function saveSearchResults() {
  saveActiveProfile();
}

function saveDmcaEntries() {
  saveActiveProfile();
}

function renderProfileSelect() {
  profileSelect.innerHTML = "";

  Object.entries(profiles).forEach(([id, profile]) => {
    const option = document.createElement("option");
    option.value = id;
    option.textContent = profile.name;
    option.selected = id === activeProfileId;
    profileSelect.appendChild(option);
  });
}

function switchProfile(profileId) {
  if (!profiles[profileId]) return;

  activeProfileId = profileId;
  loadActiveProfile();
  saveProfiles();

  renderProfileSelect();
  renderTrackedList();
  renderSavedResults();
  renderDmcaManager();
  updateStats();
  updateDmcaCounts();

  setStatus(`Switched to profile: ${profiles[profileId].name}`);
}

function createNewProfile() {
  const name = prompt("Enter a name for the new profile:");
  if (!name || !name.trim()) return;

  const newId = generateId();
  profiles[newId] = {
    name: name.trim(),
    mods: [],
    dmca: [],
    searchResults: {},
    collapsed: []
  };

  saveProfiles();
  switchProfile(newId);
  setStatus(`Created new profile: ${name.trim()}`);
}

function renameProfile() {
  if (!activeProfileId || !profiles[activeProfileId]) return;

  const currentName = profiles[activeProfileId].name;
  const newName = prompt(`Rename profile "${currentName}" to:`, currentName);

  if (!newName || !newName.trim() || newName.trim() === currentName) return;

  profiles[activeProfileId].name = newName.trim();
  saveProfiles();
  renderProfileSelect();

  setStatus(`Profile renamed to: ${newName.trim()}`);
}

function deleteProfile() {
  if (!activeProfileId || !profiles[activeProfileId]) return;

  const profileCount = Object.keys(profiles).length;
  if (profileCount === 1) {
    alert("Cannot delete the last profile. Create a new profile first.");
    return;
  }

  const profileName = profiles[activeProfileId].name;
  const confirm = window.confirm(`Are you sure you want to delete the profile "${profileName}"?\n\nThis will permanently delete all tracked mods, search results, and DMCA entries in this profile.`);

  if (!confirm) return;

  delete profiles[activeProfileId];

  // Switch to first available profile
  activeProfileId = Object.keys(profiles)[0];
  loadActiveProfile();
  saveProfiles();

  renderProfileSelect();
  renderTrackedList();
  renderSavedResults();
  renderDmcaManager();
  updateStats();
  updateDmcaCounts();

  setStatus(`Deleted profile: ${profileName}`);
}

function toggleProfileDropdown() {
  profileDropdown.classList.toggle("show");
}

function addMod() {
  const mod = {
    id: generateId(),
    modId: "",
    workshopId: "",
    approved: "",
    lastSearch: null
  };
  trackedMods.push(mod);
  saveData();
  renderTrackedList();
  updateStats();
}

function deleteMod(id) {
  trackedMods = trackedMods.filter(m => m.id !== id);
  delete searchResults[id];
  saveData();
  saveSearchResults();
  renderTrackedList();
  renderSavedResults();
  updateStats();
}

function updateMod(id, field, value) {
  const mod = trackedMods.find(m => m.id === id);
  if (mod) {
    mod[field] = value;
    saveData();
    updateStats();
  }
}

function renderTrackedList() {
  trackedListEl.innerHTML = "";

  trackedMods.forEach(mod => {
    const item = document.createElement("div");
    item.className = "tracked-item";

    const lastSearchText = mod.lastSearch
      ? `<span class="last-search">Last searched: ${new Date(mod.lastSearch).toLocaleString()}</span>`
      : '';

    item.innerHTML = `
      <div class="tracked-item-row tracked-item-labels">
        <div class="tracked-item-label-group" style="flex: 2;">
          <span class="tracked-item-label">Mod ID</span>
          ${lastSearchText}
        </div>
        <span class="tracked-item-label" style="flex: 1;">Workshop ID</span>
      </div>
      <div class="tracked-item-row">
        <input type="text" class="modid-input" data-id="${mod.id}" value="${escapeHtml(mod.modId)}" placeholder="e.g., SkillRecoveryJournal" style="flex: 2;" />
        <input type="text" class="workshopid-input" data-id="${mod.id}" value="${escapeHtml(mod.workshopId)}" placeholder="Optional" style="flex: 1;" />
      </div>
      <div class="tracked-item-row tracked-item-labels">
        <span class="tracked-item-label">Approved Exceptions (Workshop IDs, comma-separated)</span>
        <div class="tracked-item-actions-top">
          <button class="search-single-btn" data-id="${mod.id}" title="Search only this mod">Search</button>
          <button class="delete-btn" data-id="${mod.id}" style="padding: 3px 8px; font-size: 10px;" title="Hold to delete">Delete</button>
        </div>
      </div>
      <div class="tracked-item-row">
        <input type="text" class="approved-input" data-id="${mod.id}" value="${escapeHtml(mod.approved)}" placeholder="e.g., 1234567890, 9876543210" style="flex: 1;" />
      </div>
    `;

    trackedListEl.appendChild(item);
  });

  document.querySelectorAll(".modid-input").forEach(input => {
    input.addEventListener("input", (e) => updateMod(e.target.dataset.id, "modId", e.target.value));
  });

  document.querySelectorAll(".workshopid-input").forEach(input => {
    input.addEventListener("input", (e) => updateMod(e.target.dataset.id, "workshopId", e.target.value));
  });

  document.querySelectorAll(".approved-input").forEach(input => {
    input.addEventListener("input", (e) => updateMod(e.target.dataset.id, "approved", e.target.value));
  });

  document.querySelectorAll(".search-single-btn").forEach(btn => {
    btn.addEventListener("click", (e) => {
      const mod = trackedMods.find(m => m.id === e.target.dataset.id);
      if (mod && mod.modId.trim()) searchSingleMod(mod);
    });
  });

  document.querySelectorAll(".tracked-item .delete-btn").forEach(btn => {
    let holdTimer = null;
    let activePointerId = null;
    const holdDuration = SINGLE_DELETE_HOLD_TIME;

    const action = () => deleteMod(btn.dataset.id);

    const cleanup = () => {
      if (holdTimer) clearTimeout(holdTimer);
      holdTimer = null;
      btn.classList.remove("holding");
      btn.textContent = "Delete";

      try {
        if (activePointerId !== null) {
          btn.releasePointerCapture(activePointerId);
          activePointerId = null;
        }
      } catch {}
    };

    const startHold = (e) => {
      e.preventDefault();
      e.stopPropagation();

      activePointerId = e.pointerId;
      try {
        btn.setPointerCapture(activePointerId);
      } catch {}

      btn.style.setProperty('--hold-duration', `${holdDuration}ms`);
      btn.classList.add("holding");
      btn.textContent = "Hold...";

      holdTimer = setTimeout(() => {
        action();
        cleanup();
      }, holdDuration);
    };

    const endHold = (e) => {
      e.preventDefault();
      cleanup();
    };

    btn.addEventListener("pointerdown", startHold);
    btn.addEventListener("pointerup", endHold);
    btn.addEventListener("pointerleave", endHold);
    btn.addEventListener("pointercancel", endHold);
  });
}

function setStatus(msg) {
  statusEl.textContent = msg || "";
}

async function fetchAllForModId(modId, maxPages) {
  const resp = await SteamRateLimiter.fetchWithRateLimit(
    `/api/modid-search-all?modId=${encodeURIComponent(modId)}&maxPages=${encodeURIComponent(maxPages)}`
  );
  const text = await resp.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch (e) {
    throw new Error(`Server returned invalid JSON. This might be a Steam rate limit or error page.`);
  }
  if (!resp.ok) throw new Error(data?.error || "Request failed");
  return data;
}

function getApprovedSet(mod) {
  const approved = new Set();
  if (mod.approved && mod.approved.trim()) {
    mod.approved.split(",").forEach(id => {
      const clean = id.trim().replace(/[^\d]/g, "");
      if (clean) approved.add(clean);
    });
  }
  return approved;
}

function isOriginal(mod, workshopId) {
  return mod.workshopId && mod.workshopId.trim() === workshopId.trim();
}

function isInDmcaManager(workshopId) {
  return dmcaEntries.some(entry => entry.workshopId === workshopId);
}

function isDmcaFiled(workshopId) {
  const entry = dmcaEntries.find(e => e.workshopId === workshopId);
  return entry && entry.filedDate !== null && !entry.takenDownDate;
}

function isDmcaTakenDown(workshopId) {
  const entry = dmcaEntries.find(e => e.workshopId === workshopId);
  return entry && entry.takenDownDate !== null && entry.takenDownDate !== undefined;
}

async function checkDepotDownloaderConfig() {
  try {
    const resp = await fetch('/api/config/depot-path');
    const data = await resp.json();
    return data;
  } catch (err) {
    console.error('Failed to check DepotDownloader config:', err);
    return { configured: false, path: null };
  }
}

async function promptDepotDownloaderPath() {
  const path = prompt(
    "DepotDownloader not configured!\n\n" +
    "Please enter the path to DepotDownloader.exe:\n" +
    "(Download from: https://github.com/SteamRE/DepotDownloader/releases)\n\n" +
    "Example: C:\\DepotDownloader\\DepotDownloader.exe"
  );

  if (!path || !path.trim()) {
    return false;
  }

  try {
    const resp = await fetch('/api/config/depot-path', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: path.trim() })
    });

    const data = await resp.json();

    if (resp.ok) {
      alert(`✓ DepotDownloader configured successfully!\n\nPath: ${data.path}`);
      return true;
    } else {
      alert(`✗ Failed to configure DepotDownloader:\n\n${data.error}\n\nPath: ${path}`);
      return false;
    }
  } catch (err) {
    alert(`✗ Error configuring DepotDownloader:\n\n${err.message}`);
    return false;
  }
}

function updateStats() {
  const totalMods = trackedMods.length;
  const activeMods = trackedMods.filter(m => m.modId.trim()).length;
  const workshopStatus = new Map();

  Object.values(searchResults).forEach(result => {
    if (result && result.items) {
      result.items.forEach(item => {
        const wid = String(item.workshopId || "").trim();
        if (!wid) return;
        
        const currentStatus = workshopStatus.get(wid);
        
        if (isOriginal(result.mod, wid)) {
          // Original is highest priority
          workshopStatus.set(wid, 'original');
        } else if (getApprovedSet(result.mod).has(wid)) {
          // Approved only if not already original
          if (currentStatus !== 'original') {
            workshopStatus.set(wid, 'approved');
          }
        } else {
          // Unapproved only if no status yet
          if (!currentStatus) {
            workshopStatus.set(wid, 'unapproved');
          }
        }
      });
    }
  });

  // Count unique items by status
  let totalResults = workshopStatus.size;
  let totalOriginal = 0, totalApproved = 0, totalUnapproved = 0;
  
  workshopStatus.forEach(status => {
    if (status === 'original') totalOriginal++;
    else if (status === 'approved') totalApproved++;
    else totalUnapproved++;
  });

  statsBarEl.innerHTML = `
    <div class="stat-item"><div class="stat-label">Tracked Mods</div><div class="stat-value">${activeMods}/${totalMods}</div></div>
    <div class="stat-item"><div class="stat-label">Total Results</div><div class="stat-value">${totalResults}</div></div>
    <div class="stat-item"><div class="stat-label">Original</div><div class="stat-value" style="color: #daa520;">${totalOriginal}</div></div>
    <div class="stat-item"><div class="stat-label">Approved</div><div class="stat-value" style="color: var(--success);">${totalApproved}</div></div>
    <div class="stat-item"><div class="stat-label">Unapproved</div><div class="stat-value highlight">${totalUnapproved}</div></div>
  `;
}

function exportMods() {
  const data = { version: 2, exportDate: new Date().toISOString(), mods: trackedMods };
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `pz-mod-tracker-${new Date().toISOString().split('T')[0]}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

function importMods() {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'application/json';
  input.onchange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const data = JSON.parse(event.target.result);
        if (!data.mods || !Array.isArray(data.mods)) {
          setStatus('Invalid file format - import cancelled');
          return;
        }
        trackedMods = data.mods;
        saveData();
        renderTrackedList();
        updateStats();
        setStatus(`Imported ${data.mods.length} mod(s) successfully`);
      } catch (err) {
        setStatus('Failed to parse file: ' + err.message);
      }
    };
    reader.readAsText(file);
  };
  input.click();
}

function clearResults() {
  resultsEl.innerHTML = '';
  searchResults = {};
  saveSearchResults();
  updateStats();
  setStatus('Results cleared');
}

function copyToClipboard(text) {
  navigator.clipboard.writeText(text).then(() => showCopyFeedback()).catch(err => console.error('Failed to copy:', err));
}

function showCopyFeedback() {
  const feedback = document.createElement('div');
  feedback.className = 'copy-feedback';
  feedback.textContent = '✓ Copied to clipboard';
  document.body.appendChild(feedback);
  setTimeout(() => feedback.remove(), 1500);
}

function toggleApproval(modId, workshopId) {
  const mod = trackedMods.find(m => m.modId.trim() === modId);
  if (!mod) return;
  const approved = getApprovedSet(mod);
  const cleanId = workshopId.trim();

  if (approved.has(cleanId)) {
    const ids = mod.approved.split(",").map(id => id.trim().replace(/[^\d]/g, "")).filter(id => id && id !== cleanId);
    mod.approved = ids.join(", ");
  } else {
    const current = mod.approved.trim();
    mod.approved = current ? `${current}, ${cleanId}` : cleanId;
  }

  saveData();
  renderTrackedList();

  // Re-render all groups to update button states and visual styling
  Object.values(searchResults).forEach(result => {
    if (result && result.mod) {
      const group = document.querySelector(`.group[data-modid="${result.mod.modId}"]`);
      if (group) {
        renderModGroup(group, result.mod, result);
      }
    }
  });

  applyResultsFilters();
  updateStats();
}

async function searchSingleMod(mod) {
  const modId = mod.modId.trim();
  setStatus(`Searching "${modId}"...`);

  try {
    const data = await fetchAllForModId(modId, 50);
    const searchDate = new Date().toISOString();
    mod.lastSearch = searchDate;
    searchResults[mod.id] = { ...data, mod, searchDate };
    saveData();
    saveSearchResults();
    renderTrackedList();

    let group = document.querySelector(`.group[data-modid="${modId}"]`);
    if (!group) {
      group = document.createElement("div");
      group.className = collapsedGroups.has(modId) ? "group collapsed" : "group";
      group.dataset.modid = modId;
      group.innerHTML = `<div class="group-header"><span class="collapse-icon">▼</span><h3></h3></div><div class="group-content"></div>`;
      resultsEl.appendChild(group);
      group.querySelector(".group-header").addEventListener("click", () => toggleCollapse(modId));
    }

    renderModGroup(group, mod, searchResults[mod.id]);
    updateStats();
    updateDmcaCounts();
    setStatus(`Found ${data.count} result(s) for "${modId}"`);
  } catch (err) {
    setStatus(`Error searching "${modId}": ${err.message}`);
  }
}

function renderModGroup(group, mod, data) {
  const modId = mod.modId;
  const approved = getApprovedSet(mod);
  const nonOriginalItems = (data.items || []).filter(it => !isOriginal(mod, String(it.workshopId || "").trim()));
  const nonOriginalCount = nonOriginalItems.length;
  
  // Calculate visible count (items that pass the current filter)
  const visibleCount = filterUnapproved 
    ? nonOriginalItems.filter(it => !approved.has(String(it.workshopId || "").trim())).length
    : nonOriginalCount;
  
  const searchDateStr = data.searchDate ? `<span class="search-date">Searched: ${formatDate(data.searchDate)}</span>` : '';
  
  // Show fraction if filtering reduces the visible count
  const badgeText = (filterUnapproved && visibleCount !== nonOriginalCount) 
    ? `${visibleCount}/${nonOriginalCount} Found`
    : `${nonOriginalCount} Found`;

  group.querySelector(".group-header h3").innerHTML = `<code>${escapeHtml(modId)}</code><span class="badge">${badgeText}</span>${searchDateStr}`;

  const content = group.querySelector(".group-content");
  const itemsHtml = (data.items || []).map(it => {
    const wid = String(it.workshopId || "").trim();
    const isOrig = isOriginal(mod, wid);
    const isAppr = approved.has(wid);
    const isFiled = isDmcaFiled(wid);
    const isTakenDown = isDmcaTakenDown(wid);
    const inDmca = isInDmcaManager(wid);

    let cls = "resultItem", statusBadge = "", buttonHtml = "", displayStyle = "";
    if (filterUnapproved && (isOrig || isAppr)) displayStyle = ' style="display: none;"';

    if (isOrig) {
      cls = "resultItem original";
      statusBadge = '<span class="badge status-badge" style="background: #daa520; color: #fff; border-color: #daa520;">ORIGINAL</span>';
    } else if (isAppr) {
      cls = "resultItem approved";
      statusBadge = '<span class="badge status-badge" style="background: var(--success); color: #fff; border-color: var(--success);">APPROVED</span>';
      buttonHtml = `<button class="approve-toggle-btn remove" data-modid="${escapeHtml(modId)}" data-workshopid="${escapeHtml(wid)}">Remove</button>`;
    } else {
      buttonHtml = `<button class="approve-toggle-btn add" data-modid="${escapeHtml(modId)}" data-workshopid="${escapeHtml(wid)}"${inDmca ? ' disabled title="Remove from DMCA list first"' : ''}>+ Approve</button>`;
    }

    if (!isOrig) {
      if (isTakenDown) {
        cls += " taken-down";
        statusBadge += '<span class="badge status-badge" style="background: #6a5fa8; color: #fff; margin-left: 4px;">TAKEN DOWN</span>';
      } else if (isFiled) {
        cls += " filed";
        statusBadge += '<span class="badge status-badge" style="background: #7b68ee; color: #fff; margin-left: 4px;">FILED</span>';
      } else if (inDmca) {
        cls += " in-dmca";
        buttonHtml += `<button class="dmca-toggle-btn remove" data-workshopid="${escapeHtml(wid)}" data-title="${escapeHtml(it.title)}" data-modid="${escapeHtml(modId)}">- DMCA</button>`;
      } else {
        buttonHtml += `<button class="dmca-toggle-btn add" data-workshopid="${escapeHtml(wid)}" data-title="${escapeHtml(it.title)}" data-modid="${escapeHtml(modId)}">+ DMCA</button>`;
      }
    }

    return `<div class="${cls}" data-workshopid="${escapeHtml(wid)}"${displayStyle}>
      <div class="resultItem-content">
        <a target="_blank" rel="noreferrer" href="${escapeHtml(it.url)}"><strong class="copy-id" data-id="${escapeHtml(wid)}">${escapeHtml(it.title || "(No title found)")}</strong></a>
        <span class="badge">ID ${escapeHtml(wid)}</span>${statusBadge}
      </div>${buttonHtml}
    </div>`;
  }).join("");

  content.innerHTML = itemsHtml || `<div class="meta">No Workshop items found for this Mod ID.</div>`;

  content.querySelectorAll(".approve-toggle-btn").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggleApproval(btn.dataset.modid, btn.dataset.workshopid);
    });
  });

  content.querySelectorAll(".dmca-toggle-btn").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggleDmcaEntry(btn.dataset.workshopid, btn.dataset.title, btn.dataset.modid);
    });
  });

  content.querySelectorAll(".copy-id").forEach(el => {
    el.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); copyToClipboard(el.dataset.id); });
  });
}

async function renderResults() {
  const activeMods = trackedMods.filter(m => m.modId.trim());
  resultsEl.innerHTML = "";

  if (activeMods.length === 0) {
    setStatus("No mods to search. Add a Mod ID to start.");
    return;
  }

  setStatus(`Searching ${activeMods.length} mod(s)...`);
  SteamRateLimiter.reset(); // Reset rate limiter for fresh batch
  
  let completedCount = 0;
  let errorCount = 0;

  for (let i = 0; i < activeMods.length; i++) {
    const mod = activeMods[i];
    const modId = mod.modId.trim();

    const group = document.createElement("div");
    group.className = collapsedGroups.has(modId) ? "group collapsed" : "group";
    group.dataset.modid = modId;
    group.innerHTML = `<div class="group-header"><span class="collapse-icon">▼</span><h3><code>${escapeHtml(modId)}</code><span class="badge">Loading...</span></h3></div><div class="group-content"></div>`;
    resultsEl.appendChild(group);
    group.querySelector(".group-header").addEventListener("click", () => toggleCollapse(modId));

    try {
      setStatus(`Searching ${i + 1}/${activeMods.length}: "${modId}"...`);
      const data = await fetchAllForModId(modId, 50);
      const searchDate = new Date().toISOString();
      mod.lastSearch = searchDate;
      searchResults[mod.id] = { ...data, mod, searchDate };
      saveData();
      renderModGroup(group, mod, searchResults[mod.id]);
      completedCount++;
    } catch (err) {
      group.querySelector(".group-header h3").innerHTML = `<code>${escapeHtml(modId)}</code><span class="badge">Error</span>`;
      group.querySelector(".group-content").innerHTML = `<div class="meta">${escapeHtml(err.message || String(err))}</div>`;
      errorCount++;
      
      // If it's a rate limit error that exceeded retries, stop the batch
      if (err.message && err.message.includes('rate limit')) {
        setStatus(`Stopped due to rate limiting. Searched ${completedCount}/${activeMods.length} mod(s).`);
        break;
      }
    }
  }

  saveSearchResults();
  
  if (errorCount === 0) {
    setStatus(`Done. Searched ${activeMods.length} mod(s).`);
  } else {
    setStatus(`Done. Searched ${completedCount}/${activeMods.length} mod(s). ${errorCount} error(s).`);
  }
  
  renderTrackedList();
  updateStats();
  applyResultsFilters();
}

function toggleCollapse(modId) {
  if (collapsedGroups.has(modId)) collapsedGroups.delete(modId);
  else collapsedGroups.add(modId);
  saveCollapsedState();
  const group = document.querySelector(`.group[data-modid="${escapeHtml(modId)}"]`);
  if (group) group.classList.toggle("collapsed");
}

function applyResultsFilters() {
  const groups = document.querySelectorAll(".group");

  document.querySelectorAll(".resultItem").forEach(item => {
    if (filterUnapproved) {
      if (item.classList.contains("approved") || item.classList.contains("original")) item.style.display = "none";
      else item.style.display = "flex";
    } else {
      item.style.display = "flex";
    }
  });

  groups.forEach(group => {
    if (hideZeroResults) {
      const badge = group.querySelector(".group-header .badge");
      if (badge) {
        const match = badge.textContent.match(/(\d+)/);
        group.style.display = (match && parseInt(match[1]) === 0) ? "none" : "";
      }
    } else {
      group.style.display = "";
    }
  });

  if (sortOrder !== "default") {
    const groupsArray = Array.from(groups);
    const parent = groupsArray[0]?.parentNode;
    if (!parent) return;

    groupsArray.sort((a, b) => {
      const modIdA = a.dataset.modid || "";
      const modIdB = b.dataset.modid || "";
      const badgeA = a.querySelector(".group-header .badge");
      const badgeB = b.querySelector(".group-header .badge");
      const countA = badgeA ? parseInt(badgeA.textContent.match(/(\d+)/)?.[1] || 0) : 0;
      const countB = badgeB ? parseInt(badgeB.textContent.match(/(\d+)/)?.[1] || 0) : 0;

      switch (sortOrder) {
        case "found-desc": return countB - countA;
        case "found-asc": return countA - countB;
        case "modid-asc": return modIdA.localeCompare(modIdB);
        case "modid-desc": return modIdB.localeCompare(modIdA);
        default: return 0;
      }
    });

    groupsArray.forEach(group => parent.appendChild(group));
  }
}

// DMCA Manager Functions
function toggleDmcaEntry(workshopId, title, modId) {
  const existingIndex = dmcaEntries.findIndex(e => e.workshopId === workshopId);

  if (existingIndex >= 0) {
    dmcaEntries.splice(existingIndex, 1);
  } else {
    // Find all tracked mods that this workshop item appears in
    const containsModIds = [];

    // Search through all search results to find which mods contain this workshop ID
    Object.values(searchResults).forEach(result => {
      if (result && result.mod && result.items) {
        const found = result.items.find(item => String(item.workshopId || "").trim() === workshopId);
        if (found) {
          const trackedModId = result.mod.modId.trim();
          if (!containsModIds.includes(trackedModId)) {
            containsModIds.push(trackedModId);
          }
        }
      }
    });

    // Fallback to the triggering mod ID if none found
    if (containsModIds.length === 0) {
      containsModIds.push(modId);
    }

    dmcaEntries.push({
      workshopId,
      title,
      modId,
      containsModIds, // Array of tracked mod IDs found in this workshop item
      addedDate: new Date().toISOString(),
      filedDate: null,
      takenDownDate: null
    });
  }

  saveDmcaEntries();
  renderDmcaManager();
  updateDmcaCounts();
  refreshResultsBadges();
}

function removeDmcaEntry(workshopId) {
  dmcaEntries = dmcaEntries.filter(e => e.workshopId !== workshopId);
  saveDmcaEntries();
  renderDmcaManager();
  updateDmcaCounts();
  refreshResultsBadges();
}

function openDmcaForm(workshopId) {
  window.open(`https://steamcommunity.com/dmca/create/${workshopId}`, '_blank');
}

function markAsFiled(workshopId) {
  const entry = dmcaEntries.find(e => e.workshopId === workshopId);
  if (entry) {
    entry.filedDate = entry.filedDate ? null : new Date().toISOString();
    saveDmcaEntries();
    renderDmcaManager();
    updateDmcaCounts();
    refreshResultsBadges();
    updateStats();
  }
}

function refreshResultsBadges() {
  Object.values(searchResults).forEach(result => {
    if (result && result.mod) {
      const group = document.querySelector(`.group[data-modid="${result.mod.modId}"]`);
      if (group) renderModGroup(group, result.mod, result);
    }
  });
}

// Enhanced rendering for DMCA items with per-mod breakdown
function renderDmcaManager() {
  const showPendingOnlyValue = showPendingOnly;
  const showFiledOnlyValue = showFiledOnly;
  const showTakenDownOnlyValue = showTakenDownOnly;

  let filteredEntries = dmcaEntries;
  
  // If any filter is active, use OR logic to show matching entries
  const anyFilterActive = showPendingOnlyValue || showFiledOnlyValue || showTakenDownOnlyValue;
  if (anyFilterActive) {
    filteredEntries = dmcaEntries.filter(e => {
      const isPending = !e.filedDate && !e.takenDownDate;
      const isFiled = e.filedDate && !e.takenDownDate;
      const isTakenDown = !!e.takenDownDate;
      
      return (showPendingOnlyValue && isPending) || 
             (showFiledOnlyValue && isFiled) || 
             (showTakenDownOnlyValue && isTakenDown);
    });
  }

  filteredEntries = [...filteredEntries].sort((a, b) => {
    return new Date(b.addedDate) - new Date(a.addedDate);
  });

  dmcaManagerList.innerHTML = "";

  if (filteredEntries.length === 0) {
    const msg = dmcaEntries.length === 0
      ? "No DMCA entries. Click '+ DMCA' on search results to add items."
      : "No entries match the current filter.";
    dmcaManagerList.innerHTML = `<div style="color: var(--text-muted); text-align: center; padding: 40px 20px; font-style: italic;">${msg}</div>`;
    return;
  }

  filteredEntries.forEach(entry => {
    const isFiled = entry.filedDate && !entry.takenDownDate;
    const isTakenDown = !!entry.takenDownDate;
    const item = document.createElement("div");
    item.className = `dmca-item${isFiled ? ' filed' : ''}${isTakenDown ? ' taken-down' : ''}`;

    let statusDateHtml = '';
    if (isTakenDown) {
      statusDateHtml = `<div class="dmca-filed-date" style="color: #6a5fa8;">Taken Down: ${formatDate(entry.takenDownDate)}</div>`;
    } else if (isFiled) {
      statusDateHtml = `<div class="dmca-filed-date">Filed: ${formatDate(entry.filedDate)}</div>`;
    }

    // Build verification badge
    let verificationBadgeHtml = '';
    if (entry.verification) {
      const v = entry.verification;
      if (v.error) {
        verificationBadgeHtml = `<span class="verification-badge error" title="Verification error: ${escapeHtml(v.error)}">ERROR</span>`;
      } else if (v.takenDown) {
        verificationBadgeHtml = `<span class="verification-badge high" title="Item was taken down during verification">GONE ✓</span>`;
      } else if (v.verified) {
        const pct = v.matchPercentage || 0;
        let badgeClass = 'none';
        let badgeText = `${pct}%`;
        if (pct >= 75) {
          badgeClass = 'high';
          badgeText = `${pct}% HIGH`;
        } else if (pct >= 50) {
          badgeClass = 'medium';
          badgeText = `${pct}% MED`;
        } else if (pct >= 25) {
          badgeClass = 'low';
          badgeText = `${pct}% LOW`;
        }
        const filesInfo = v.totalFiles > 0 ? `${v.matchedFiles}/${v.totalFiles} files matched` : '';
        verificationBadgeHtml = `<span class="verification-badge ${badgeClass}" title="${filesInfo}">${badgeText}</span>`;
      }
    }

    // Build tracked mod IDs section with per-mod stats
    let trackedModsHtml = '';
    if (entry.containsModIds && entry.containsModIds.length > 0) {
      const modIdsList = entry.containsModIds.map(id => {
        const v = entry.verification;
        const r = v && v.modResults ? v.modResults[id] : null;

        let badgeHtml = '';
        let detailsHtml = '';

        if (v && v.verified) {
          if (v.takenDown) {
            badgeHtml = `<span class="verification-badge none" title="Item taken down during verification">GONE ✓</span>`;
          } else if (v.error) {
            badgeHtml = `<span class="verification-badge error" title="Verification error: ${escapeHtml(v.error)}">ERROR</span>`;
          } else if (r) {
            const pct = typeof r.matchPercentage === 'number' ? r.matchPercentage : 0;
            const matched = r.matchedFiles ?? 0;
            const total = r.totalFiles ?? 0;

            let cls = 'none';
            if (pct >= 75) cls = 'high';
            else if (pct >= 50) cls = 'medium';
            else if (pct >= 25) cls = 'low';

            badgeHtml = `<span class="verification-badge ${cls}" title="${matched}/${total} files matched for this mod">${pct}%</span>`;

            detailsHtml = `<div class="mod-match-details">${matched}/${total} files</div>`;
          } else {
            badgeHtml = `<span class="verification-badge none" title="No per-mod data returned">N/A</span>`;
          }
        }

        return `<div class="tracked-mod-row">
          <span class="tracked-mod-id">${escapeHtml(id)}</span>
          ${badgeHtml}
          ${detailsHtml}
        </div>`;
      }).join('');

      trackedModsHtml = `
        <div class="dmca-tracked-mods collapsed" data-workshopid="${escapeHtml(entry.workshopId)}">
          <div class="tracked-mods-toggle">
            <span class="toggle-icon">▶</span>
            <span class="toggle-label">Contains ${entry.containsModIds.length} tracked mod${entry.containsModIds.length > 1 ? 's' : ''}</span>
          </div>
          <div class="tracked-mods-list">
            ${modIdsList}
          </div>
        </div>
      `;
    }

    let actionsHtml = '';
    if (isTakenDown) {
      actionsHtml = `
        <button class="dmca-copy-msg-btn" data-workshopid="${escapeHtml(entry.workshopId)}" title="Copy DMCA message to clipboard">Copy DMCA Message</button>
        <button class="dmca-remove-btn" data-workshopid="${escapeHtml(entry.workshopId)}" title="Remove from DMCA list">×</button>
      `;
    } else {
      actionsHtml = `
        <button class="dmca-copy-msg-btn" data-workshopid="${escapeHtml(entry.workshopId)}" title="Copy DMCA message to clipboard">Copy DMCA Message</button>
        <button class="dmca-file-btn" data-workshopid="${escapeHtml(entry.workshopId)}" title="Open Steam DMCA form">File</button>
        <button class="dmca-filed-btn${isFiled ? ' is-filed' : ''}" data-workshopid="${escapeHtml(entry.workshopId)}" title="${isFiled ? 'Click to unmark as filed' : 'Mark as filed'}">${isFiled ? '✓ Filed' : 'Mark Filed'}</button>
        <button class="dmca-remove-btn" data-workshopid="${escapeHtml(entry.workshopId)}" title="Remove from DMCA list">×</button>
      `;
    }

    item.innerHTML = `
      <div class="dmca-item-header">
        <div class="dmca-item-info">
          <div class="dmca-item-title-row">
            <div class="dmca-item-title">
              <a href="https://steamcommunity.com/sharedfiles/filedetails/?id=${escapeHtml(entry.workshopId)}" target="_blank" rel="noreferrer">${escapeHtml(entry.title)}</a>
              ${isTakenDown ? '<span class="taken-down-badge">TAKEN DOWN</span>' : ''}
              ${verificationBadgeHtml}
            </div>
          </div>
          <div class="dmca-item-meta">
            <span>Workshop ID: ${escapeHtml(entry.workshopId)}</span>
            <span>Added: ${formatDate(entry.addedDate)}</span>
          </div>
          <div class="dmca-item-actions">
            ${actionsHtml}
          </div>
          ${trackedModsHtml}
          ${statusDateHtml}
        </div>
      </div>
    `;

    dmcaManagerList.appendChild(item);
  });

  // Add event listeners
  dmcaManagerList.querySelectorAll(".dmca-copy-msg-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const workshopId = btn.dataset.workshopid;
      const entry = dmcaEntries.find(e => e.workshopId === workshopId);
      if (entry) {
        const message = generateDmcaMessage(entry, trackedMods);
        copyToClipboard(message);
        setStatus("DMCA message copied to clipboard");
      }
    });
  });

  dmcaManagerList.querySelectorAll(".dmca-file-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      // Show temporary "File..." state
      const originalText = btn.textContent;
      btn.textContent = "File...";
      btn.classList.add("filing");
      
      // Open the form
      openDmcaForm(btn.dataset.workshopid);
      
    });
  });

  dmcaManagerList.querySelectorAll(".dmca-filed-btn").forEach(btn => {
    btn.addEventListener("click", () => markAsFiled(btn.dataset.workshopid));
  });

  dmcaManagerList.querySelectorAll(".dmca-remove-btn").forEach(btn => {
    btn.addEventListener("click", () => removeDmcaEntry(btn.dataset.workshopid));
  });

  dmcaManagerList.querySelectorAll(".tracked-mods-toggle").forEach(toggle => {
    toggle.addEventListener("click", (e) => {
      e.stopPropagation();
      const container = toggle.closest('.dmca-tracked-mods');
      container.classList.toggle('collapsed');
    });
  });
}

function updateDmcaCounts() {
  // Get unique workshop IDs for each status
  const uniquePending = new Set(dmcaEntries.filter(e => !e.filedDate && !e.takenDownDate).map(e => e.workshopId));
  const uniqueFiled = new Set(dmcaEntries.filter(e => e.filedDate && !e.takenDownDate).map(e => e.workshopId));
  const uniqueTakenDown = new Set(dmcaEntries.filter(e => e.takenDownDate).map(e => e.workshopId));
  const uniqueVerified = new Set(dmcaEntries.filter(e => e.verification && e.verification.verified).map(e => e.workshopId));
  const uniqueTotal = new Set(dmcaEntries.map(e => e.workshopId));

  dmcaPendingCount.textContent = uniquePending.size;
  dmcaFiledCount.textContent = uniqueFiled.size;
  dmcaTakenDownCount.textContent = uniqueTakenDown.size;
  if (dmcaVerifiedCount) dmcaVerifiedCount.textContent = uniqueVerified.size;
  dmcaTotalCount.textContent = uniqueTotal.size;
}

function exportDmcaList() {
  // Enhance entries with original workshop IDs
  const enhancedEntries = dmcaEntries.map(entry => {
    const originalWorkshopIds = [];

    if (entry.containsModIds && entry.containsModIds.length > 0) {
      entry.containsModIds.forEach(modId => {
        const trackedMod = trackedMods.find(m => m.modId === modId);
        if (trackedMod && trackedMod.workshopId) {
          originalWorkshopIds.push({
            modId: modId,
            workshopId: trackedMod.workshopId,
            url: `https://steamcommunity.com/sharedfiles/filedetails/?id=${trackedMod.workshopId}`
          });
        }
      });
    }

    return {
      ...entry,
      originalMods: originalWorkshopIds
    };
  });

  const data = {
    version: 2,
    exportDate: new Date().toISOString(),
    entries: enhancedEntries,
    trackedMods: trackedMods.map(m => ({
      modId: m.modId,
      workshopId: m.workshopId || ''
    }))
  };

  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `pz-dmca-list-${new Date().toISOString().split('T')[0]}.json`;
  a.click();
  URL.revokeObjectURL(url);
  setStatus(`Exported ${enhancedEntries.length} DMCA entries — Run verify_dmca.exe on this file`);
}

function importDmcaList() {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'application/json';
  input.onchange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const data = JSON.parse(event.target.result);
        if (!data.entries || !Array.isArray(data.entries)) {
          setStatus('Invalid DMCA file format - import cancelled');
          return;
        }

        let imported = 0, updated = 0, skipped = 0;

        data.entries.forEach(entry => {
          const existingIndex = dmcaEntries.findIndex(e => e.workshopId === entry.workshopId);

          if (existingIndex >= 0) {
            // OVERWRITE: Replace existing entry with imported one
            dmcaEntries[existingIndex] = entry;
            updated++;
          } else {
            // NEW: Add new entry
            dmcaEntries.push(entry);
            imported++;
          }
        });

        saveDmcaEntries();
        renderDmcaManager();
        updateDmcaCounts();
        refreshResultsBadges();

        setStatus(`DMCA import complete: ${imported} new, ${updated} updated`);
      } catch (err) {
        setStatus('Failed to parse DMCA file: ' + err.message);
      }
    };
    reader.readAsText(file);
  };
  input.click();
}

function clearDmcaList() {
  dmcaEntries = [];
  saveDmcaEntries();
  renderDmcaManager();
  updateDmcaCounts();
  refreshResultsBadges();
  setStatus("DMCA list cleared");
}

function clearVerificationData() {
  let clearedCount = 0;

  dmcaEntries.forEach(entry => {
    if (entry.verification) {
      delete entry.verification;
      clearedCount++;
    }
  });

  saveDmcaEntries();
  renderDmcaManager();
  updateDmcaCounts();

  setStatus(`Cleared verification data from ${clearedCount} entries`);
}

async function recheckFiledItems() {
  const filedEntries = dmcaEntries.filter(e => e.filedDate && !e.takenDownDate);

  if (filedEntries.length === 0) {
    setStatus("No filed items to re-check.");
    return;
  }

  setStatus(`Re-checking ${filedEntries.length} filed item(s)...`);
  SteamRateLimiter.reset(); // Reset rate limiter for fresh batch

  let checkedCount = 0;
  let takenDownCount = 0;
  let stillActiveCount = 0;
  let errorCount = 0;

  for (let i = 0; i < filedEntries.length; i++) {
    const entry = filedEntries[i];
    setStatus(`Checking ${i + 1}/${filedEntries.length}: ${entry.title}...`);

    try {
      const resp = await SteamRateLimiter.fetchWithRateLimit(
        `/api/check-workshop-exists?workshopId=${entry.workshopId}`
      );

      const data = await resp.json();

      if (data.exists === false) {
        entry.takenDownDate = new Date().toISOString();
        takenDownCount++;
      } else if (data.exists === true) {
        stillActiveCount++;
      } else {
        errorCount++;
      }

      checkedCount++;

    } catch (err) {
      console.error(`Error checking ${entry.workshopId}:`, err);
      errorCount++;
      
      // If it's a rate limit error that exceeded retries, stop the batch
      if (err.message && err.message.includes('rate limit')) {
        setStatus(`Stopped due to rate limiting. Checked ${checkedCount} items before stopping.`);
        break;
      }
    }
  }

  saveDmcaEntries();
  renderDmcaManager();
  updateDmcaCounts();
  refreshResultsBadges();

  let statusMsg = `Re-check complete: ${checkedCount} checked`;
  if (takenDownCount > 0) statusMsg += `, ${takenDownCount} taken down`;
  if (stillActiveCount > 0) statusMsg += `, ${stillActiveCount} still active`;
  if (errorCount > 0) statusMsg += `, ${errorCount} errors`;
  setStatus(statusMsg);
}

// ============================================================================
// VERIFICATION FUNCTIONS
// ============================================================================

function buildVerificationExport() {
  // Build the export data needed for verification
  const enhancedEntries = dmcaEntries.map(entry => {
    const originalWorkshopIds = [];
    if (entry.containsModIds && entry.containsModIds.length > 0) {
      entry.containsModIds.forEach(modId => {
        const trackedMod = trackedMods.find(m => m.modId === modId);
        if (trackedMod && trackedMod.workshopId) {
          originalWorkshopIds.push({
            modId: trackedMod.modId,
            workshopId: trackedMod.workshopId,
            url: `https://steamcommunity.com/sharedfiles/filedetails/?id=${trackedMod.workshopId}`
          });
        }
      });
    }
    return {
      ...entry,
      originalMods: originalWorkshopIds
    };
  });

  return {
    version: 2,
    exportDate: new Date().toISOString(),
    entries: enhancedEntries,
    trackedMods: trackedMods.map(m => ({
      modId: m.modId,
      workshopId: m.workshopId || ''
    }))
  };
}

async function importFromProfile() {
  const profileInput = prompt("Enter Steam profile URL or profile ID:\n\nExamples:\n- https://steamcommunity.com/id/Chuckleberry_Finn\n- https://steamcommunity.com/profiles/76561198012345678\n- Chuckleberry_Finn");

  if (!profileInput || !profileInput.trim()) return;

  setStatus("Fetching workshop items from profile...");
  SteamRateLimiter.reset(); // Reset rate limiter for fresh batch

  try {
    const resp = await SteamRateLimiter.fetchWithRateLimit(
      `/api/profile-workshop?profileId=${encodeURIComponent(profileInput.trim())}&maxPages=20`
    );
    const text = await resp.text();
    let data;
    try { data = JSON.parse(text); } catch (e) { throw new Error("Server returned invalid JSON. This might be a Steam rate limit."); }
    if (!resp.ok) throw new Error(data?.error || "Request failed");
    if (!data.items || data.items.length === 0) { setStatus("No workshop items found for this profile."); return; }

    setStatus(`Found ${data.items.length} items. Extracting Mod IDs...`);

    let imported = 0, alreadyTracked = 0, skipped = 0, rateLimitHit = false;

    for (let i = 0; i < data.items.length; i++) {
      const item = data.items[i];
      setStatus(`Processing ${i + 1}/${data.items.length}: ${item.title}...`);

      if (trackedMods.some(m => m.workshopId === item.workshopId)) { alreadyTracked++; continue; }

      try {
        const detailResp = await SteamRateLimiter.fetchWithRateLimit(
          `/api/workshop-details?workshopId=${item.workshopId}`
        );
        const detailData = await detailResp.json();
        if (detailData.modId) {
          if (trackedMods.some(m => m.modId === detailData.modId)) { alreadyTracked++; }
          else {
            trackedMods.push({ id: generateId(), modId: detailData.modId, workshopId: item.workshopId, approved: "", lastSearch: null });
            imported++;
          }
        } else { skipped++; }
      } catch (err) { 
        console.error(`Failed to fetch details for ${item.workshopId}:`, err); 
        skipped++;
        
        // If it's a rate limit error that exceeded retries, stop the batch
        if (err.message && err.message.includes('rate limit')) {
          rateLimitHit = true;
          setStatus(`Stopped due to rate limiting. Processed ${i + 1}/${data.items.length} items.`);
          break;
        }
      }
    }

    saveData();
    renderTrackedList();
    updateStats();
    let statusMessage = `Import complete! Imported: ${imported} new mods, Already tracked: ${alreadyTracked}, Skipped: ${skipped}, Total: ${data.count} items`;
    if (rateLimitHit) statusMessage += ` - Stopped early due to rate limiting`;
    setStatus(statusMessage);
  } catch (err) {
    setStatus(`Error importing from profile: ${err.message}`);
  }
}

function deleteAll() {
  trackedMods = [];
  searchResults = {};
  saveData();
  saveSearchResults();
  renderTrackedList();
  resultsEl.innerHTML = '';
  updateStats();
  setStatus("All mods deleted.");
}

function setupHoldButton(btn, holdDuration, originalText, action) {
  let holdTimer = null;
  let activePointerId = null;

  const cleanup = () => {
    if (holdTimer) clearTimeout(holdTimer);
    holdTimer = null;

    btn.classList.remove("holding");
    btn.textContent = originalText;

    try {
      if (activePointerId !== null) {
        btn.releasePointerCapture(activePointerId);
        activePointerId = null;
      }
    } catch {}
  };

  const startHold = (e) => {
    e.preventDefault();
    e.stopPropagation();

    activePointerId = e.pointerId;
    try {
      btn.setPointerCapture(activePointerId);
    } catch {}

    btn.style.setProperty('--hold-duration', `${holdDuration}ms`);
    btn.classList.add("holding");
    btn.textContent = "Hold...";

    holdTimer = setTimeout(() => {
      action();
      cleanup();
    }, holdDuration);
  };

  const endHold = (e) => {
    e.preventDefault();
    cleanup();
  };

  btn.addEventListener("pointerdown", startHold);
  btn.addEventListener("pointerup", endHold);
  btn.addEventListener("pointerleave", endHold);
  btn.addEventListener("pointercancel", endHold);
}

function renderSavedResults() {
  resultsEl.innerHTML = "";

  const resultsToRender = [];

  for (const [modInternalId, result] of Object.entries(searchResults)) {
    if (result && result.items && result.mod) {
      const currentMod = trackedMods.find(m => m.id === modInternalId);
      if (currentMod) {
        result.mod = currentMod;
        resultsToRender.push({ modInternalId, result, modId: currentMod.modId });
      }
    }
  }

  if (resultsToRender.length === 0) return;

  resultsToRender.forEach(({ result, modId }) => {
    const group = document.createElement("div");
    group.className = collapsedGroups.has(modId) ? "group collapsed" : "group";
    group.dataset.modid = modId;
    group.innerHTML = `<div class="group-header"><span class="collapse-icon">▼</span><h3></h3></div><div class="group-content"></div>`;
    resultsEl.appendChild(group);
    group.querySelector(".group-header").addEventListener("click", () => toggleCollapse(modId));
    renderModGroup(group, result.mod, result);
  });

  applyResultsFilters();
}

// Event listeners
addModBtn.addEventListener("click", addMod);
runBtn.addEventListener("click", renderResults);
exportBtn.addEventListener("click", exportMods);
importBtn.addEventListener("click", importMods);
importProfileBtn.addEventListener("click", importFromProfile);
exportDmcaBtn.addEventListener("click", exportDmcaList);
importDmcaBtn.addEventListener("click", importDmcaList);
recheckFiledBtn.addEventListener("click", recheckFiledItems);

showPendingOnlyCheckbox.addEventListener("change", () => {
  showPendingOnly = showPendingOnlyCheckbox.checked;
  saveActiveProfile();
  renderDmcaManager();
});

showFiledOnlyCheckbox.addEventListener("change", () => {
  showFiledOnly = showFiledOnlyCheckbox.checked;
  saveActiveProfile();
  renderDmcaManager();
});

showTakenDownOnlyCheckbox.addEventListener("change", () => {
  showTakenDownOnly = showTakenDownOnlyCheckbox.checked;
  saveActiveProfile();
  renderDmcaManager();
});

profileSelect.addEventListener("change", (e) => {
  switchProfile(e.target.value);
});

newProfileBtn.addEventListener("click", () => {
  createNewProfile();
  profileDropdown.classList.remove("show");
});

renameProfileBtn.addEventListener("click", () => {
  renameProfile();
  profileDropdown.classList.remove("show");
});

deleteProfileBtn.addEventListener("click", () => {
  deleteProfile();
  profileDropdown.classList.remove("show");
});

profileMenuBtn.addEventListener("click", (e) => {
  e.stopPropagation();
  toggleProfileDropdown();
});

document.addEventListener("click", (e) => {
  if (!profileMenuBtn.contains(e.target) && !profileDropdown.contains(e.target)) {
    profileDropdown.classList.remove("show");
  }
});

setupHoldButton(clearResultsBtn, DELETE_ALL_HOLD_TIME, "Clear Results", clearResults);
setupHoldButton(deleteAllBtn, DELETE_ALL_HOLD_TIME, "Delete All", deleteAll);
setupHoldButton(clearDmcaBtn, DELETE_ALL_HOLD_TIME, "Clear All", clearDmcaList);

filterUnapprovedCheckbox.addEventListener("change", (e) => {
  filterUnapproved = e.target.checked;
  saveActiveProfile();
  refreshResultsBadges();
  applyResultsFilters();
});

sortResultsSelect.addEventListener("change", (e) => {
  sortOrder = e.target.value;
  saveActiveProfile();
  applyResultsFilters();
});

hideZeroResultsCheckbox.addEventListener("change", (e) => {
  hideZeroResults = e.target.checked;
  saveActiveProfile();
  applyResultsFilters();
});

const clearVerificationBtn = document.getElementById("clearVerificationBtn");

if (clearVerificationBtn) {
  setupHoldButton(clearVerificationBtn, DELETE_ALL_HOLD_TIME, "Clear Verification", clearVerificationData);
}

// Initialize
loadData();
renderProfileSelect();
renderTrackedList();
renderSavedResults();
renderDmcaManager();
updateStats();
updateDmcaCounts();


const verifyDmcaBtn = document.getElementById("verifyDmcaBtn");

function loadTrackedModsForVerify() {
  if (!activeProfileId || !profiles[activeProfileId]) {
    return [];
  }
  const profile = profiles[activeProfileId];
  return (profile.mods || []).map(m => ({
    modId: m.modId,
    workshopId: m.workshopId || ''
  }));
}

function loadDmcaEntriesForVerify() {
  if (!activeProfileId || !profiles[activeProfileId]) {
    return [];
  }
  const profile = profiles[activeProfileId];
  return profile.dmca || [];
}

function setVerifyBtnRunning(running) {
  if (!verifyDmcaBtn) return;
  if (running) {
    verifyDmcaBtn.classList.add("running");
    verifyDmcaBtn.textContent = "Verifying...";
  } else {
    verifyDmcaBtn.classList.remove("running");
    verifyDmcaBtn.textContent = "Verify";
  }
}

async function apiGet(url) {
  const res = await fetch(url);
  return res.json();
}

async function apiPost(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {})
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = data?.error || `Request failed: ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

async function pollVerifyStatus() {
  while (true) {
    const status = await apiGet("/api/verify/status");

    console.log("Poll status:", status);

    if (!status.running) {
      setVerifyBtnRunning(false);

      if (status.results && status.results.entries) {
        const verifiedEntries = status.results.entries;

        console.log("Got verified entries:", verifiedEntries.length);

        // IMPORTANT: Merge verification results back into dmcaEntries
        verifiedEntries.forEach(verifiedEntry => {
          const localEntry = dmcaEntries.find(e => e.workshopId === verifiedEntry.workshopId);
          if (localEntry && verifiedEntry.verification) {
            localEntry.verification = verifiedEntry.verification;
          }
        });

        // Save updated entries
        saveDmcaEntries();
        renderDmcaManager();
        updateDmcaCounts();

        // Show summary
        const summary = status.results.summary || {};
        alert(
          `Verification complete!\n\n` +
          `High Match (75%+): ${summary.high || 0}\n` +
          `Medium (50-74%): ${summary.medium || 0}\n` +
          `Low (25-49%): ${summary.low || 0}\n` +
          `No Match (<25%): ${summary.none || 0}\n` +
          `Taken Down: ${summary.takenDown || 0}`
        );
      } else if (status.error && status.error.message) {
        alert("Verify error: " + status.error.message);
      } else {
        console.error("No results in status:", status);
        alert("Verifier returned no results");
      }
      return;
    }

    // Handle different progress event types
    if (status.progress && status.progress.payload) {
      const p = status.progress.payload;
      const eventType = status.progress.type;

      if (eventType === "download" && p.current && p.total) {
        setStatus(`Downloading manifests: ${p.current}/${p.total} - ${p.name || ''}`);
      } else if (eventType === "read_manifest" && p.current && p.total) {
        setStatus(`Reading manifests: ${p.current}/${p.total} - ${p.name || ''}`);
      } else if (eventType === "verify_item" && p.current && p.total) {
        setStatus(`Comparing files: ${p.current}/${p.total} - ${p.title || ''}`);
      } else if (p.current && p.total) {
        setStatus(`Processing: ${p.current}/${p.total}...`);
      } else if (p.message) {
        setStatus(p.message);
      }
    }

    await new Promise(r => setTimeout(r, 500)); // ← Poll twice as fast
  }
}

if (verifyDmcaBtn) {
  verifyDmcaBtn.addEventListener("click", async () => {
    const trackedMods = loadTrackedModsForVerify();
    const entries = loadDmcaEntriesForVerify();

    if (!entries.length) {
      alert("No DMCA entries found.\n\nAdd some workshop items using \"+ DMCA\" first.");
      return;
    }

    // Check if DepotDownloader is configured
    const depotConfig = await checkDepotDownloaderConfig();
    if (!depotConfig.configured) {
      const configured = await promptDepotDownloaderPath();
      if (!configured) {
        return; // User cancelled or failed to configure
      }
    }

    try {
      setVerifyBtnRunning(true);
      setStatus("Starting verification...");

      await apiPost("/api/verify/start", {
        trackedMods,
        entries,
      });

      await pollVerifyStatus();
    } catch (e) {
      setVerifyBtnRunning(false);

      // Handle specific error codes
      if (e.message.includes("NO_DEPOT")) {
        const configured = await promptDepotDownloaderPath();
        if (configured) {
          // Retry verification
          verifyDmcaBtn.click();
        }
      } else {
        alert("Verify failed: " + (e?.message || e));
      }

      setStatus("Verification failed");
    }
  });
}

const configDepotBtn = document.getElementById("configDepotBtn");

if (configDepotBtn) {
  configDepotBtn.addEventListener("click", async () => {
    const config = await checkDepotDownloaderConfig();

    let message = "DepotDownloader Configuration\n\n";

    if (config.configured) {
      message += `Current path: ${config.path}\n\n`;
      message += "Enter a new path to update, or click Cancel to keep current configuration.";
    } else {
      message += "DepotDownloader is not configured.\n\n";
      message += "Enter the path to DepotDownloader.exe:\n";
      message += "(Download from: https://github.com/SteamRE/DepotDownloader/releases)";
    }

    const newPath = prompt(message, config.path || "");

    if (newPath && newPath.trim() && newPath !== config.path) {
      try {
        const resp = await fetch('/api/config/depot-path', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: newPath.trim() })
        });

        const data = await resp.json();

        if (resp.ok) {
          setStatus(`DepotDownloader configured: ${data.path}`);
          alert(`✓ DepotDownloader configured successfully!\n\nPath: ${data.path}`);
        } else {
          setStatus(`Failed to configure DepotDownloader: ${data.error}`);
          alert(`✗ ${data.error}`);
        }
      } catch (err) {
        setStatus(`Error: ${err.message}`);
        alert(`✗ Error: ${err.message}`);
      }
    }
  });
}

(async function initializeDepotDownloader() {
  const config = await checkDepotDownloaderConfig();
  if (!config.configured) {
    console.warn("DepotDownloader not configured - verification will not work");
    // Optionally show a non-intrusive notification
    if (verifyDmcaBtn) {
      verifyDmcaBtn.title = "DepotDownloader not configured - click to configure";
    }
  } else {
    console.log("DepotDownloader configured:", config.path);
  }
})();

// Legal Notice collapse functionality
(function initLegalNotice() {
  const legalNotice = document.getElementById("legalNotice");
  const legalNoticeToggle = document.getElementById("legalNoticeToggle");
  
  if (!legalNotice || !legalNoticeToggle) return;
  
  // Load saved state (default is expanded/not collapsed)
  const isCollapsed = localStorage.getItem(LS_LEGAL_NOTICE_COLLAPSED) === "true";
  if (isCollapsed) {
    legalNotice.classList.add("collapsed");
  }
  
  // Toggle on click
  legalNoticeToggle.addEventListener("click", () => {
    legalNotice.classList.toggle("collapsed");
    const nowCollapsed = legalNotice.classList.contains("collapsed");
    localStorage.setItem(LS_LEGAL_NOTICE_COLLAPSED, nowCollapsed);
  });
})();