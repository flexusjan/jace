const state = {
  cards: [],
  selectedId: null,
  query: "",
  sortKey: "name",
  sortDirection: "asc",
  selectedIds: new Set(),
  visibleColumns: new Set(),
  histories: new Map(),
  historyErrors: new Map(),
  historyRequests: new Map(),
  detailRenderKey: ""
};

const COLUMN_STORAGE_KEY = "jace.visibleColumns";
const DATE_FORMATTER = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short"
});
const columns = [
  {
    key: "name",
    className: "card-name",
    render: card => escapeHtml(card.name)
  },
  {
    key: "set",
    render: card => `${escapeHtml(card.set_code.toUpperCase())} #${escapeHtml(card.collector_number)}`
  },
  {
    key: "quantity",
    render: card => String(card.quantity)
  },
  {
    key: "condition",
    render: card => escapeHtml(card.condition || "NM")
  },
  {
    key: "language",
    render: card => escapeHtml(card.language || "English")
  },
  {
    key: "latest_price",
    render: card => money(card.latest_price, card.currency)
  },
  {
    key: "change",
    className: card => changeClass(card),
    render: card => signedMoney(card.change, card.currency)
  },
  {
    key: "latest_captured_at",
    render: card => formatDate(card.latest_captured_at)
  }
];

const cardsBody = document.querySelector("#cards");
const detail = document.querySelector("#detail");
const search = document.querySelector("#search");
const priceRefresh = document.querySelector("#price-refresh");
const refreshState = document.querySelector("#refresh-state");
const refreshTimes = document.querySelector("#refresh-times");
const cardCount = document.querySelector("#card-count");
const portfolioValue = document.querySelector("#portfolio-value");
const importForm = document.querySelector("#import-form");
const importSubmit = document.querySelector("#import-submit");
const importStatus = document.querySelector("#import-status");
const importResults = document.querySelector("#import-results");
const importProgress = document.querySelector("#import-progress");
const importProgressBar = document.querySelector("#import-progress-bar");
const importTabs = document.querySelectorAll("[data-import-tab]");
const importPanels = document.querySelectorAll("[data-import-panel]");
const singleCard = document.querySelector("#single-card");
const cardFile = document.querySelector("#card-file");
const moxfieldUrl = document.querySelector("#moxfield-url");
const currency = document.querySelector("#currency");
const sortButtons = document.querySelectorAll("[data-sort]");
const columnOptions = document.querySelector("#column-options");
const columnToggles = document.querySelectorAll("#column-options input[type='checkbox']");
const selectAll = document.querySelector("#select-all");
const selectionCount = document.querySelector("#selection-count");
const deleteSelected = document.querySelector("#delete-selected");
const ACTIVE_IMPORT_JOB_KEY = "jace.activeImportJobId";

initializeColumns();
priceRefresh.addEventListener("click", refreshPricesNow);
search.addEventListener("input", event => {
  state.query = event.target.value.toLowerCase();
  render();
});
importTabs.forEach(tab => {
  tab.addEventListener("click", () => setImportTab(tab.dataset.importTab));
});
importForm.addEventListener("submit", submitImport);
sortButtons.forEach(button => {
  button.addEventListener("click", () => setSort(button.dataset.sort));
});
columnOptions.addEventListener("change", updateVisibleColumns);
selectAll.addEventListener("change", toggleVisibleSelection);
deleteSelected.addEventListener("click", deleteSelectedCards);
cardsBody.addEventListener("click", event => {
  const checkbox = event.target.closest(".row-select");
  if (checkbox) {
    return;
  }
  const row = event.target.closest("tr");
  if (!row) {
    return;
  }
  state.selectedId = row.dataset.cardId;
  updateSelectedRows();
  renderDetail(state.cards.find(card => card.id === state.selectedId));
});
cardsBody.addEventListener("change", event => {
  const checkbox = event.target.closest(".row-select");
  if (!checkbox) {
    return;
  }
  setCardSelection(checkbox.value, checkbox.checked);
  updateSelectionControls(visibleSortedCards());
});

loadCards();
loadRefreshStatus();
setInterval(loadRefreshStatus, 30000);
resumeActiveImport();

async function loadCards() {
  try {
    const response = await fetch("/api/cards", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Request failed with status ${response.status}`);
    }
    const payload = await response.json();
    state.cards = payload.cards;
    state.histories.clear();
    state.historyErrors.clear();
    state.historyRequests.clear();
    state.detailRenderKey = "";
    reconcileSelection();
    if (!state.selectedId && state.cards.length > 0) {
      state.selectedId = state.cards[0].id;
    }
    render();
  } catch (error) {
    detail.innerHTML = `<h2>Could not load prices</h2><p class="muted">${escapeHtml(error.message)}</p>`;
  }
}

async function loadRefreshStatus() {
  try {
    const response = await fetch("/api/refresh-status", { cache: "no-store" });
    const status = await response.json();
    if (!response.ok) {
      throw new Error(status.error || `Request failed with status ${response.status}`);
    }
    renderRefreshStatus(status);
  } catch (error) {
    refreshState.textContent = "Refresh status unavailable";
    refreshTimes.textContent = error.message;
  }
}

async function refreshPricesNow() {
  priceRefresh.disabled = true;
  refreshState.textContent = "Starting price update...";
  try {
    const response = await fetch("/api/refresh", { method: "POST" });
    const status = await response.json();
    if (!response.ok && response.status !== 409) {
      throw new Error(status.error || `Request failed with status ${response.status}`);
    }
    renderRefreshStatus(status);
    await pollPriceRefresh();
  } catch (error) {
    refreshState.textContent = "Could not update prices";
    refreshTimes.textContent = error.message;
    priceRefresh.disabled = false;
  }
}

async function pollPriceRefresh() {
  while (true) {
    await delay(1000);
    const response = await fetch("/api/refresh-status", { cache: "no-store" });
    const status = await response.json();
    if (!response.ok) {
      throw new Error(status.error || `Request failed with status ${response.status}`);
    }
    renderRefreshStatus(status);
    if (!status.running) {
      await loadCards();
      return;
    }
  }
}

function renderRefreshStatus(status) {
  priceRefresh.disabled = Boolean(status.running);
  if (status.running) {
    refreshState.textContent = "Updating prices...";
  } else if (status.error) {
    refreshState.textContent = "Last price update failed";
  } else {
    const refreshed = Number(status.refreshed || 0);
    refreshState.textContent = status.last_finished_at ? `Last update refreshed ${refreshed} cards` : "Prices idle";
  }

  const last = status.last_finished_at ? formatDate(status.last_finished_at) : "n/a";
  const next = status.next_run_at ? formatDate(status.next_run_at) : (status.running ? "after current update" : "n/a");
  refreshTimes.textContent = `Last check ${last} · Next check ${next}`;
}

function setImportTab(name) {
  importTabs.forEach(tab => {
    tab.classList.toggle("active", tab.dataset.importTab === name);
  });
  importPanels.forEach(panel => {
    panel.classList.toggle("hidden", panel.dataset.importPanel !== name);
  });
  importStatus.textContent = "";
  importResults.innerHTML = "";
  resetProgress();
}

async function submitImport(event) {
  event.preventDefault();
  importSubmit.disabled = true;
  importStatus.className = "import-status";
  importStatus.textContent = "Preparing import...";
  importResults.innerHTML = "";
  resetProgress();

  try {
    const payload = await importPayload();
    const response = await fetch("/api/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.error || `Request failed with status ${response.status}`);
    }

    rememberActiveImport(result.id);
    await pollImport(result.id);
    clearImportInput(payload.source);
  } catch (error) {
    forgetActiveImport();
    importStatus.classList.add("error");
    importStatus.textContent = error.message;
    importResults.innerHTML = "";
  } finally {
    importSubmit.disabled = false;
  }
}

async function pollImport(jobId) {
  if (!jobId) {
    throw new Error("Import job did not return an id");
  }

  let job = null;
  while (true) {
    const response = await fetch(`/api/import-jobs/${encodeURIComponent(jobId)}`, { cache: "no-store" });
    job = await response.json();
    if (!response.ok || job.error && !job.id) {
      throw new Error(job.error || `Request failed with status ${response.status}`);
    }

    renderImportProgress(job);
    if (job.status === "done") {
      importStatus.classList.toggle("warning", Boolean(job.failed));
      renderImportResults(job);
      await loadCardsAfterImport(job);
      forgetActiveImport();
      return;
    }
    if (job.status === "error") {
      forgetActiveImport();
      throw new Error(job.error || "Import failed");
    }
    await delay(500);
  }
}

async function resumeActiveImport() {
  const jobId = localStorage.getItem(ACTIVE_IMPORT_JOB_KEY);
  if (!jobId) {
    return;
  }

  importSubmit.disabled = true;
  importStatus.className = "import-status";
  importStatus.textContent = "Resuming import progress...";
  try {
    await pollImport(jobId);
  } catch (error) {
    forgetActiveImport();
    importStatus.classList.add("error");
    importStatus.textContent = error.message;
  } finally {
    importSubmit.disabled = false;
  }
}

function rememberActiveImport(jobId) {
  if (jobId) {
    localStorage.setItem(ACTIVE_IMPORT_JOB_KEY, jobId);
  }
}

function forgetActiveImport() {
  localStorage.removeItem(ACTIVE_IMPORT_JOB_KEY);
}

async function loadCardsAfterImport(job) {
  const summary = `${job.processed}/${job.total} processed, ${job.imported} imported, ${job.failed} failed`;
  await loadCards();
  importStatus.textContent = summary;
  importStatus.classList.toggle("warning", Boolean(job.failed));
}

function renderImportProgress(job) {
  const total = Number(job.total || 0);
  const processed = Number(job.processed || 0);
  const imported = Number(job.imported || 0);
  const failed = Number(job.failed || 0);
  const percent = total > 0 ? Math.round((processed / total) * 100) : 0;

  importProgress.classList.remove("hidden");
  importProgress.setAttribute("aria-hidden", "false");
  importProgressBar.style.width = `${Math.min(percent, 100)}%`;
  const current = job.current_card && processed < total ? `, working on ${job.current_card}` : "";
  importStatus.textContent = `${processed}/${total} processed, ${imported} imported, ${failed} failed${current}`;
}

function resetProgress() {
  importProgress.classList.add("hidden");
  importProgress.setAttribute("aria-hidden", "true");
  importProgressBar.style.width = "0%";
}

async function importPayload() {
  const source = document.querySelector("[data-import-tab].active").dataset.importTab;
  if (source === "moxfield") {
    return {
      source: "moxfield",
      url: moxfieldUrl.value.trim(),
      currency: currency.value
    };
  }

  if (source === "file") {
    const file = cardFile.files[0];
    if (!file) {
      throw new Error("Choose a .txt or .csv file first");
    }
    return {
      source: file.name.toLowerCase().endsWith(".csv") ? "csv" : "text",
      text: await file.text(),
      currency: currency.value
    };
  }

  return {
    source: "text",
    text: singleCard.value.trim(),
    currency: currency.value
  };
}

function renderImportResults(result) {
  if (!result.failed) {
    importResults.innerHTML = "";
    return;
  }
  importResults.innerHTML = `
    <div class="failure-list">
      <strong>Failed cards</strong>
      <ul>
        ${result.failures.map(failure => `
          <li>
            <span>${escapeHtml(failure.name)}</span>
            <small>${escapeHtml(failure.error)}</small>
          </li>
        `).join("")}
      </ul>
    </div>
  `;
}

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function clearImportInput(source) {
  if (source === "moxfield") {
    moxfieldUrl.value = "";
    return;
  }
  singleCard.value = "";
  cardFile.value = "";
}

function render() {
  const sorted = visibleSortedCards();

  updateSortButtons();
  updateColumnVisibility();
  updateSelectionControls(sorted);
  renderRows(sorted);

  const total = state.cards.reduce((sum, card) => {
    const price = Number(card.latest_price || 0);
    return sum + price * card.quantity;
  }, 0);
  const currency = state.cards[0]?.currency || "";
  cardCount.textContent = `${state.cards.length} cards`;
  portfolioValue.textContent = `${total.toFixed(2)} ${currency}`.trim();

  const selected = state.cards.find(card => card.id === state.selectedId) || sorted[0];
  renderDetail(selected);
}

function reconcileSelection() {
  const knownIds = new Set(state.cards.map(card => card.id));
  state.selectedIds.forEach(id => {
    if (!knownIds.has(id)) {
      state.selectedIds.delete(id);
    }
  });
  if (state.selectedId && !state.cards.some(card => card.id === state.selectedId)) {
    state.selectedId = state.cards[0]?.id || null;
  }
}

function setCardSelection(id, selected) {
  if (selected) {
    state.selectedIds.add(id);
  } else {
    state.selectedIds.delete(id);
  }
}

function toggleVisibleSelection(event) {
  const visibleCards = visibleSortedCards();
  visibleCards.forEach(card => setCardSelection(card.id, event.target.checked));
  render();
}

function visibleSortedCards() {
  const filtered = state.cards.filter(card => {
    const haystack = `${card.name} ${card.set_code} ${card.collector_number}`.toLowerCase();
    return haystack.includes(state.query);
  });
  return sortCards(filtered);
}

function updateSelectionControls(visibleCards) {
  const visibleIds = visibleCards.map(card => card.id);
  const selectedVisible = visibleIds.filter(id => state.selectedIds.has(id)).length;
  selectAll.checked = visibleIds.length > 0 && selectedVisible === visibleIds.length;
  selectAll.indeterminate = selectedVisible > 0 && selectedVisible < visibleIds.length;

  const selectedCount = state.selectedIds.size;
  selectionCount.textContent = `${selectedCount} selected`;
  deleteSelected.disabled = selectedCount === 0;
}

async function deleteSelectedCards() {
  const ids = Array.from(state.selectedIds);
  if (ids.length === 0) {
    return;
  }
  const confirmed = window.confirm(`Delete ${ids.length} selected card${ids.length === 1 ? "" : "s"} and all price history?`);
  if (!confirmed) {
    return;
  }

  deleteSelected.disabled = true;
  try {
    const response = await fetch("/api/cards", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tracking_ids: ids })
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.error || `Request failed with status ${response.status}`);
    }
    state.selectedIds.clear();
    await loadCards();
  } catch (error) {
    detail.innerHTML = `<h2>Could not delete cards</h2><p class="muted">${escapeHtml(error.message)}</p>`;
    deleteSelected.disabled = false;
  }
}

function initializeColumns() {
  const saved = readSavedColumns();
  const allowed = new Set(columns.map(column => column.key));
  const initial = Array.isArray(saved) ? saved.filter(key => allowed.has(key)) : columns.map(column => column.key);
  state.visibleColumns = new Set(initial.length > 0 ? initial : columns.map(column => column.key));
  columnToggles.forEach(toggle => {
    toggle.checked = state.visibleColumns.has(toggle.value);
  });
}

function readSavedColumns() {
  try {
    return JSON.parse(localStorage.getItem(COLUMN_STORAGE_KEY) || "null");
  } catch {
    return null;
  }
}

function updateVisibleColumns() {
  const next = new Set(Array.from(columnToggles).filter(toggle => toggle.checked).map(toggle => toggle.value));
  if (next.size === 0) {
    const nameToggle = Array.from(columnToggles).find(toggle => toggle.value === "name");
    if (nameToggle) {
      nameToggle.checked = true;
      next.add("name");
    }
  }
  state.visibleColumns = next;
  localStorage.setItem(COLUMN_STORAGE_KEY, JSON.stringify(Array.from(next)));
  render();
}

function updateColumnVisibility() {
  document.querySelectorAll("[data-column]").forEach(element => {
    element.classList.toggle("column-hidden", !state.visibleColumns.has(element.dataset.column));
  });
}

function setSort(key) {
  if (state.sortKey === key) {
    state.sortDirection = state.sortDirection === "asc" ? "desc" : "asc";
  } else {
    state.sortKey = key;
    state.sortDirection = defaultSortDirection(key);
  }
  render();
}

function sortCards(cards) {
  const direction = state.sortDirection === "asc" ? 1 : -1;
  return cards.slice().sort((left, right) => {
    const comparison = compareValues(sortValue(left, state.sortKey), sortValue(right, state.sortKey));
    if (comparison !== 0) {
      return comparison * direction;
    }
    return compareValues(left.name.toLowerCase(), right.name.toLowerCase());
  });
}

function sortValue(card, key) {
  if (key === "set") {
    return `${card.set_code} ${card.collector_number}`.toLowerCase();
  }
  if (key === "condition" || key === "language") {
    return String(card[key] || "").toLowerCase();
  }
  if (key === "quantity") {
    return Number(card.quantity || 0);
  }
  if (key === "latest_price" || key === "change") {
    const value = card[key];
    return value === null || value === undefined ? Number.NEGATIVE_INFINITY : Number(value);
  }
  if (key === "latest_captured_at") {
    return new Date(card.latest_captured_at).getTime();
  }
  return String(card.name || "").toLowerCase();
}

function compareValues(left, right) {
  if (typeof left === "number" && typeof right === "number") {
    return left - right;
  }
  return String(left).localeCompare(String(right), undefined, { numeric: true, sensitivity: "base" });
}

function defaultSortDirection(key) {
  return ["quantity", "latest_price", "change", "latest_captured_at"].includes(key) ? "desc" : "asc";
}

function updateSortButtons() {
  sortButtons.forEach(button => {
    const active = button.dataset.sort === state.sortKey;
    button.classList.toggle("active", active);
    button.setAttribute("aria-sort", active ? (state.sortDirection === "asc" ? "ascending" : "descending") : "none");
    button.dataset.direction = active ? state.sortDirection : "";
  });
}

function renderRows(cards) {
  cardsBody.innerHTML = cards.map(card => rowTemplate(card)).join("");
}

function updateSelectedRows() {
  cardsBody.querySelectorAll("tr").forEach(row => {
    row.classList.toggle("selected", row.dataset.cardId === state.selectedId);
  });
}

function rowTemplate(card) {
  const selected = card.id === state.selectedId ? "selected" : "";
  const checked = state.selectedIds.has(card.id) ? "checked" : "";
  return `
    <tr class="${selected}" data-card-id="${escapeHtml(card.id)}">
      <td class="select-column">
        <input class="row-select" type="checkbox" value="${escapeHtml(card.id)}" aria-label="Select ${escapeHtml(card.name)}" ${checked}>
      </td>
      ${columns.map(column => columnTemplate(column, card)).join("")}
    </tr>
  `;
}

function columnTemplate(column, card) {
  const hidden = state.visibleColumns.has(column.key) ? "" : " column-hidden";
  const extraClass = typeof column.className === "function" ? column.className(card) : column.className || "";
  return `<td class="${extraClass}${hidden}" data-column="${column.key}">${column.render(card)}</td>`;
}

function changeClass(card) {
  const change = Number(card.change || 0);
  return change > 0 ? "gain" : change < 0 ? "loss" : "";
}

function renderDetail(card) {
  if (!card) {
    state.detailRenderKey = "empty";
    detail.innerHTML = `<h2>No cards tracked</h2><p class="muted">Run the tracker to create the first price snapshot.</p>`;
    return;
  }

  const history = state.histories.get(card.id);
  const error = state.historyErrors.get(card.id);
  const loading = state.historyRequests.has(card.id);
  const renderKey = `${card.id}:${error || (history ? history.length : loading ? "loading" : "missing")}`;
  if (state.detailRenderKey === renderKey) {
    return;
  }
  state.detailRenderKey = renderKey;

  if (!history && !loading && !error) {
    loadCardHistory(card.id);
  }

  const points = (history || []).filter(point => point.price !== null);
  detail.innerHTML = `
    ${cardImage(card)}
    <h2>${escapeHtml(card.name)}</h2>
    <p class="muted">${escapeHtml(card.set_code.toUpperCase())} #${escapeHtml(card.collector_number)} · ${card.quantity} tracked · ${escapeHtml(card.condition || "NM")} · ${escapeHtml(card.language || "English")}</p>
    ${historyStatus(history, points, card.currency, error)}
    <ul class="history-list">
      ${(history || []).slice().reverse().map(point => `
        <li>
          <span>${formatDate(point.captured_at)}</span>
          <strong>${money(point.price, point.currency)}</strong>
        </li>
      `).join("")}
    </ul>
  `;
}

async function loadCardHistory(cardId) {
  const request = fetch(`/api/cards/${encodeURIComponent(cardId)}/history`, { cache: "no-store" })
    .then(async response => {
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || `Request failed with status ${response.status}`);
      }
      state.histories.set(cardId, payload.history || []);
      state.historyErrors.delete(cardId);
    })
    .catch(error => {
      state.historyErrors.set(cardId, error.message);
    })
    .finally(() => {
      state.historyRequests.delete(cardId);
      state.detailRenderKey = "";
      if (state.selectedId === cardId) {
        renderDetail(state.cards.find(card => card.id === cardId));
      }
    });
  state.historyRequests.set(cardId, request);
}

function historyStatus(history, points, currency, error) {
  if (error) {
    return `<p class="muted">Could not load price history: ${escapeHtml(error)}</p>`;
  }
  if (!history) {
    return `<p class="muted">Loading price history...</p>`;
  }
  return chartSvg(points, currency);
}

function cardImage(card) {
  if (!card.has_image_url && !card.has_cached_image) {
    return "";
  }
  return `
    <div class="card-image-wrap">
      <img class="card-image" src="/api/card-images/${encodeURIComponent(card.scryfall_id)}" alt="${escapeHtml(card.name)}">
    </div>
  `;
}

function chartSvg(points, currency) {
  if (points.length === 0) {
    return `<p class="muted">No priced snapshots are available for this card.</p>`;
  }
  if (points.length === 1) {
    return `<p class="muted">One snapshot: ${money(points[0].price, currency)}</p>`;
  }

  const width = 360;
  const height = 180;
  const padding = 18;
  const values = points.map(point => Number(point.price));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = max - min || 1;
  const coords = values.map((value, index) => {
    const x = padding + (index / (values.length - 1)) * (width - padding * 2);
    const y = height - padding - ((value - min) / spread) * (height - padding * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  return `
    <svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Price history chart">
      <rect x="0" y="0" width="${width}" height="${height}" fill="#f4f9ff"></rect>
      <polyline points="${coords.join(" ")}" fill="none" stroke="#2f6fae" stroke-width="3"></polyline>
      <text x="${padding}" y="${padding}" fill="#60758f" font-size="12">${money(max, currency)}</text>
      <text x="${padding}" y="${height - 6}" fill="#60758F" font-size="12">${money(min, currency)}</text>
    </svg>
  `;
}

function money(value, currency) {
  if (value === null || value === undefined) {
    return "n/a";
  }
  return `${Number(value).toFixed(2)} ${currency}`;
}

function signedMoney(value, currency) {
  if (value === null || value === undefined) {
    return "n/a";
  }
  const number = Number(value);
  const prefix = number > 0 ? "+" : "";
  return `${prefix}${number.toFixed(2)} ${currency}`;
}

function formatDate(value) {
  return DATE_FORMATTER.format(new Date(value));
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
