const state = {
  cards: [],
  selectedId: null,
  query: "",
  sortKey: "name",
  sortDirection: "asc",
  page: 1,
  pageSize: 100,
  totalPages: 1,
  totalCount: 0,
  totalValue: null,
  totalCurrency: "",
  selectedIds: new Set(),
  visibleColumns: new Set(),
  histories: new Map(),
  historyErrors: new Map(),
  historyRequests: new Map(),
  historyPagination: new Map(),
  valueHistory: null,
  valueHistoryError: "",
  detailRenderKey: "",
  detailOpen: false
};

const COLUMN_STORAGE_KEY = "jace.visibleColumns";
const DEFAULT_VISIBLE_COLUMNS = [
  "name",
  "set",
  "quantity",
  "condition",
  "language",
  "finish",
  "latest_price",
  "total_price",
  "change",
  "latest_captured_at"
];
const DATE_FORMATTER = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short"
});
const DATE_ONLY_FORMATTER = new Intl.DateTimeFormat(undefined, {
  dateStyle: "short"
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
    render: card => escapeHtml(conditionLabel(card.condition))
  },
  {
    key: "language",
    render: card => escapeHtml(card.language || "English")
  },
  {
    key: "finish",
    render: card => escapeHtml(finishLabel(card.finish))
  },
  {
    key: "latest_price",
    render: card => money(card.latest_price, card.currency)
  },
  {
    key: "total_price",
    render: card => money(totalPrice(card), card.currency)
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
const detailContent = document.querySelector("#detail-content");
const detailBackdrop = document.querySelector("#detail-backdrop");
const detailClose = document.querySelector("#detail-close");
const search = document.querySelector("#search");
const priceRefresh = document.querySelector("#price-refresh");
const refreshState = document.querySelector("#refresh-state");
const refreshTimes = document.querySelector("#refresh-times");
const refreshProgress = document.querySelector("#refresh-progress");
const refreshProgressBar = document.querySelector("#refresh-progress-bar");
const cardCount = document.querySelector("#card-count");
const portfolioValue = document.querySelector("#portfolio-value");
const portfolioChange = document.querySelector("#portfolio-change");
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
const pageStatus = document.querySelector("#page-status");
const pageSize = document.querySelector("#page-size");
const pagePrev = document.querySelector("#page-prev");
const pageNext = document.querySelector("#page-next");
const ACTIVE_IMPORT_JOB_KEY = "jace.activeImportJobId";
const mobileDetailQuery = window.matchMedia("(max-width: 720px)");
let searchTimer = null;

initializeColumns();
priceRefresh.addEventListener("click", refreshPricesNow);
search.addEventListener("input", event => {
  state.query = event.target.value.toLowerCase();
  state.page = 1;
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(loadCards, 180);
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
pageSize.addEventListener("change", event => {
  state.pageSize = Number(event.target.value) || 100;
  state.page = 1;
  loadCards();
});
pagePrev.addEventListener("click", () => {
  if (state.page > 1) {
    state.page -= 1;
    loadCards();
  }
});
pageNext.addEventListener("click", () => {
  if (state.page < state.totalPages) {
    state.page += 1;
    loadCards();
  }
});
detailClose.addEventListener("click", closeDetail);
detailBackdrop.addEventListener("click", closeDetail);
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && state.detailOpen) {
    closeDetail();
  }
});
mobileDetailQuery.addEventListener("change", updateDetailMode);
cardsBody.addEventListener("click", event => {
  const checkbox = event.target.closest(".row-select");
  if (checkbox) {
    return;
  }
  const row = event.target.closest("tr");
  if (!row || !row.dataset.cardId) {
    return;
  }
  state.selectedId = row.dataset.cardId;
  updateSelectedRows();
  openDetail(state.cards.find(card => card.id === state.selectedId));
});
cardsBody.addEventListener("change", event => {
  const checkbox = event.target.closest(".row-select");
  if (!checkbox) {
    return;
  }
  setCardSelection(checkbox.value, checkbox.checked);
  updateSelectionControls(visibleSortedCards());
});

loadInitialData();
loadRefreshStatus();
updateDetailMode();
setInterval(loadRefreshStatus, 30000);
resumeActiveImport();

async function loadInitialData() {
  await loadCards();
  deferValueHistoryLoad();
}

function deferValueHistoryLoad() {
  const load = () => loadValueHistory();
  if ("requestIdleCallback" in window) {
    window.requestIdleCallback(load, { timeout: 2000 });
  } else {
    window.setTimeout(load, 500);
  }
}

async function loadCards() {
  try {
    const params = new URLSearchParams({
      page: String(state.page),
      page_size: String(state.pageSize),
      q: state.query,
      sort: state.sortKey,
      direction: state.sortDirection
    });
    const response = await fetch(`/api/cards?${params.toString()}`, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Request failed with status ${response.status}`);
    }
    const payload = await response.json();
    state.cards = payload.cards;
    const pagination = payload.pagination || {};
    state.page = Number(pagination.page || state.page);
    state.pageSize = Number(pagination.page_size || state.pageSize);
    state.totalPages = Number(pagination.total_pages || 1);
    state.totalCount = Number(pagination.total_count || state.cards.length);
    state.totalValue = pagination.total_value;
    state.totalCurrency = pagination.currency || "";
    if (state.cards.length === 0 && state.page > 1) {
      state.page -= 1;
      await loadCards();
      return;
    }
    state.histories.clear();
    state.historyErrors.clear();
    state.historyRequests.clear();
    state.historyPagination.clear();
    state.detailRenderKey = "";
    reconcileSelection();
    if (!state.selectedId && state.cards.length > 0) {
      state.selectedId = state.cards[0].id;
    }
    render();
  } catch (error) {
    renderRowsMessage(`Could not load cards: ${error.message}`);
    showDetailMessage("Could not load prices", error.message);
  }
}

async function loadValueHistory() {
  try {
    const response = await fetch("/api/collection/value-history", { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || `Request failed with status ${response.status}`);
    }
    state.valueHistory = payload.history || [];
    state.valueHistoryError = "";
  } catch (error) {
    state.valueHistory = [];
    state.valueHistoryError = error.message;
  }
  renderPortfolioChange();
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
      await loadValueHistory();
      return;
    }
  }
}

function renderRefreshStatus(status) {
  priceRefresh.disabled = Boolean(status.running);
  const total = Number(status.total || 0);
  const processed = Number(status.processed || 0);
  if (status.running) {
    const refreshed = Number(status.refreshed || 0);
    const failed = Number(status.failed || 0);
    refreshState.textContent = total > 0
      ? `Updating prices ${processed}/${total}, ${refreshed} refreshed, ${failed} failed`
      : "Preparing price update...";
  } else if (status.error) {
    refreshState.textContent = "Last price update failed";
  } else {
    const refreshed = Number(status.refreshed || 0);
    const failed = Number(status.failed || 0);
    const failures = failed ? `, ${failed} failed` : "";
    refreshState.textContent = status.last_finished_at ? `Last update refreshed ${refreshed} cards${failures}` : "Prices idle";
  }

  const last = status.last_finished_at ? formatDate(status.last_finished_at) : "n/a";
  const next = status.next_run_at ? formatDate(status.next_run_at) : (status.running ? "after current update" : "n/a");
  refreshTimes.textContent = `Last check ${last} · Next check ${next}`;
  renderRefreshProgress(status.running, total, processed);
}

function renderRefreshProgress(running, total, processed) {
  if (!running) {
    refreshProgress.classList.add("hidden");
    refreshProgress.setAttribute("aria-hidden", "true");
    refreshProgressBar.style.width = "0%";
    return;
  }

  refreshProgress.classList.remove("hidden");
  refreshProgress.setAttribute("aria-hidden", "false");
  const percent = total > 0 ? Math.round((processed / total) * 100) : 5;
  refreshProgressBar.style.width = `${Math.min(Math.max(percent, 5), 100)}%`;
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
  await loadValueHistory();
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
  const bulk = job.status === "running" && total > 1 && processed < total
    ? `, processing bulk ${Math.min(processed + 1, total)} of ${total}`
    : "";
  const current = job.current_card && total === 1 && processed < total ? `, working on ${job.current_card}` : "";
  importStatus.textContent = `${processed}/${total} processed, ${imported} imported, ${failed} failed${bulk}${current}`;
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
  const visible = visibleSortedCards();

  updateSortButtons();
  updateColumnVisibility();
  updateSelectionControls(visible);
  updatePaginationControls();
  renderRows(visible);

  cardCount.textContent = `${state.totalCount} cards`;
  portfolioValue.textContent = state.totalValue === null || state.totalValue === undefined
    ? "n/a"
    : `${Number(state.totalValue).toFixed(2)} ${state.totalCurrency}`.trim();

  if (!state.selectedId && visible.length > 0) {
    state.selectedId = visible[0].id;
  }
  updateSelectedRows();
  if (!isMobileDetail() || state.detailOpen) {
    renderDetail(state.cards.find(card => card.id === state.selectedId));
  }
  renderPortfolioChange();
}

function reconcileSelection() {
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
  return state.cards;
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
    showDetailMessage("Could not delete cards", error.message);
    deleteSelected.disabled = false;
  }
}

function initializeColumns() {
  const saved = readSavedColumns();
  const allowed = new Set(columns.map(column => column.key));
  const initial = Array.isArray(saved) ? saved.filter(key => allowed.has(key)) : DEFAULT_VISIBLE_COLUMNS;
  if (Array.isArray(saved) && !initial.includes("total_price")) {
    initial.splice(Math.max(initial.indexOf("latest_price") + 1, 0), 0, "total_price");
  }
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
  state.page = 1;
  loadCards();
}

function defaultSortDirection(key) {
  return ["quantity", "latest_price", "total_price", "change", "latest_captured_at"].includes(key) ? "desc" : "asc";
}

function updateSortButtons() {
  sortButtons.forEach(button => {
    const active = button.dataset.sort === state.sortKey;
    button.classList.toggle("active", active);
    button.setAttribute("aria-sort", active ? (state.sortDirection === "asc" ? "ascending" : "descending") : "none");
    button.dataset.direction = active ? state.sortDirection : "";
  });
}

function updatePaginationControls() {
  pageSize.value = String(state.pageSize);
  pageStatus.textContent = `Page ${state.page} of ${state.totalPages}`;
  pagePrev.disabled = state.page <= 1;
  pageNext.disabled = state.page >= state.totalPages;
}

function renderRows(cards) {
  if (cards.length === 0) {
    const message = state.query
      ? `No cards match "${state.query}"`
      : "No cards tracked";
    renderRowsMessage(message);
    return;
  }
  cardsBody.innerHTML = cards.map(card => rowTemplate(card)).join("");
}

function renderRowsMessage(message) {
  cardsBody.innerHTML = `
    <tr class="empty-row">
      <td colspan="${columns.length + 2}">${escapeHtml(message)}</td>
    </tr>
  `;
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
      <td class="mobile-card-thumb">${cardThumb(card)}</td>
      ${columns.map(column => columnTemplate(column, card)).join("")}
    </tr>
  `;
}

function columnTemplate(column, card) {
  const hidden = state.visibleColumns.has(column.key) ? "" : " column-hidden";
  const extraClass = typeof column.className === "function" ? column.className(card) : column.className || "";
  return `<td class="${extraClass}${hidden}" data-column="${column.key}" data-label="${columnLabel(column.key)}">${column.render(card)}</td>`;
}

function changeClass(card) {
  const change = Number(card.change || 0);
  return change > 0 ? "gain" : change < 0 ? "loss" : "";
}

function totalPrice(card) {
  if (card.latest_price === null || card.latest_price === undefined) {
    return null;
  }
  return Number(card.latest_price) * Number(card.quantity || 0);
}

function renderDetail(card) {
  if (!card) {
    state.detailRenderKey = "empty";
    detailContent.innerHTML = `<h2 id="detail-title">No cards tracked</h2><p class="muted">Run the tracker to create the first price snapshot.</p>`;
    return;
  }

  const history = state.histories.get(card.id);
  const pagination = state.historyPagination.get(card.id);
  const error = state.historyErrors.get(card.id);
  const loading = state.historyRequests.has(card.id);
  const renderKey = `${card.id}:${error || (history ? history.length : loading ? "loading" : "missing")}:${pagination ? pagination.total_count : ""}`;
  if (state.detailRenderKey === renderKey) {
    return;
  }
  state.detailRenderKey = renderKey;

  if (!history && !loading && !error) {
    loadCardHistory(card.id);
  }

  const points = (history || []).filter(point => point.price !== null);
  detailContent.innerHTML = `
    <div class="detail-grid">
      ${cardImage(card)}
      <div class="detail-main">
        <h2 id="detail-title">${escapeHtml(card.name)}</h2>
        <dl class="card-facts">
          <div><dt>Edition</dt><dd>${escapeHtml(card.set_code.toUpperCase())} #${escapeHtml(card.collector_number)}</dd></div>
          <div><dt>Quantity</dt><dd>${card.quantity}</dd></div>
          <div><dt>Condition</dt><dd>${escapeHtml(conditionLabel(card.condition))}</dd></div>
          <div><dt>Language</dt><dd>${escapeHtml(card.language || "English")}</dd></div>
          <div><dt>Finish</dt><dd>${escapeHtml(finishLabel(card.finish))}</dd></div>
          <div><dt>Total value</dt><dd>${money(totalPrice(card), card.currency)}</dd></div>
          <div><dt>Captured</dt><dd>${formatDate(card.latest_captured_at)}</dd></div>
        </dl>
        ${scryfallLink(card)}
      </div>
    </div>
    <section class="history-chart" aria-label="Price history">
      <h3>Price history</h3>
      ${historyStatus(history, points, card.currency, error)}
      ${historyPaginationStatus(history, pagination)}
    </section>
  `;
}

function openDetail(card) {
  state.detailOpen = true;
  applyDetailVisibility();
  state.detailRenderKey = "";
  renderDetail(card);
  if (isMobileDetail()) {
    detailClose.focus({ preventScroll: true });
  }
}

function closeDetail() {
  state.detailOpen = false;
  applyDetailVisibility();
}

function showDetailMessage(title, message) {
  state.detailOpen = true;
  applyDetailVisibility();
  detailContent.innerHTML = `<h2 id="detail-title">${escapeHtml(title)}</h2><p class="muted">${escapeHtml(message)}</p>`;
  if (isMobileDetail()) {
    detailClose.focus({ preventScroll: true });
  }
}

function updateDetailMode() {
  applyDetailVisibility();
  state.detailRenderKey = "";
  if (!isMobileDetail()) {
    renderDetail(state.cards.find(card => card.id === state.selectedId));
  }
}

function applyDetailVisibility() {
  const mobile = isMobileDetail();
  detail.classList.toggle("hidden", mobile && !state.detailOpen);
  detailBackdrop.classList.toggle("hidden", !mobile || !state.detailOpen);
  detailClose.classList.toggle("hidden", !mobile);
  detail.setAttribute("aria-hidden", mobile && !state.detailOpen ? "true" : "false");
  detail.setAttribute("role", mobile ? "dialog" : "region");
  detail.setAttribute("aria-modal", mobile ? "true" : "false");
  detailBackdrop.setAttribute("aria-hidden", mobile && state.detailOpen ? "false" : "true");
  document.body.classList.toggle("modal-open", mobile && state.detailOpen);
}

function isMobileDetail() {
  return mobileDetailQuery.matches;
}

async function loadCardHistory(cardId) {
  const params = new URLSearchParams({ page: "1", page_size: "100" });
  const request = fetch(`/api/cards/${encodeURIComponent(cardId)}/price-history?${params.toString()}`, { cache: "no-store" })
    .then(async response => {
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || `Request failed with status ${response.status}`);
      }
      state.histories.set(cardId, payload.history || []);
      if (payload.pagination) {
        state.historyPagination.set(cardId, payload.pagination);
      } else {
        state.historyPagination.delete(cardId);
      }
      state.historyErrors.delete(cardId);
    })
    .catch(error => {
      state.historyErrors.set(cardId, error.message);
      state.historyPagination.delete(cardId);
    })
    .finally(() => {
      state.historyRequests.delete(cardId);
      state.detailRenderKey = "";
      if (state.selectedId === cardId && (!isMobileDetail() || state.detailOpen)) {
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

function historyPaginationStatus(history, pagination) {
  if (!history || !pagination) {
    return "";
  }
  const total = Number(pagination.total_count || history.length);
  if (total <= history.length) {
    return "";
  }
  return `<p class="muted">Showing latest ${history.length} of ${total} price snapshots.</p>`;
}

function renderPortfolioChange() {
  if (!portfolioChange) {
    return;
  }
  if (state.valueHistoryError) {
    portfolioChange.textContent = "";
    portfolioChange.className = "metric-change";
    return;
  }
  if (!state.valueHistory) {
    portfolioChange.textContent = "";
    portfolioChange.className = "metric-change";
    return;
  }

  const points = state.valueHistory.filter(point => point.total_value !== null && point.currency);
  if (points.length === 0) {
    portfolioChange.textContent = "";
    portfolioChange.className = "metric-change";
    return;
  }

  const first = points[0];
  const latest = points[points.length - 1];
  const change = Number(latest.total_value) - Number(first.total_value);
  portfolioChange.textContent = `(${signedMoney(change, latest.currency)})`;
  portfolioChange.className = `metric-change ${changeClass({ change })}`;
}

function cardImage(card) {
  if (!card.has_image_url && !card.has_cached_image) {
    return `<div class="card-image-wrap"><div class="card-image-placeholder" aria-hidden="true"></div></div>`;
  }
  return `
    <div class="card-image-wrap">
      <img class="card-image" src="/api/card-images/${encodeURIComponent(card.scryfall_id)}" alt="${escapeHtml(card.name)}">
    </div>
  `;
}

function scryfallLink(card) {
  if (!card.source_url) {
    return "";
  }
  return `<a class="scryfall-link" href="${escapeHtml(card.source_url)}" target="_blank" rel="noopener noreferrer">Open Scryfall</a>`;
}

function cardThumb(card) {
  if (!card.has_image_url && !card.has_cached_image) {
    return `<div class="mobile-card-thumb-placeholder" aria-hidden="true"></div>`;
  }
  return `<img src="/api/card-images/${encodeURIComponent(card.scryfall_id)}" alt="" loading="lazy">`;
}

function columnLabel(key) {
  const labels = {
    name: "Card",
    set: "Set",
    quantity: "Qty",
    condition: "Condition",
    language: "Language",
    finish: "Finish",
    latest_price: "Latest",
    total_price: "Total",
    change: "Change",
    latest_captured_at: "Captured"
  };
  return labels[key] || key;
}

function chartSvg(points, currency) {
  if (points.length === 0) {
    return `<p class="muted">No priced snapshots are available for this card.</p>`;
  }
  return `
    ${chartSummary(points, currency)}
    ${lineChartSvg(points, currency, "Price history chart", 720)}
  `;
}

function chartSummary(points, currency) {
  const values = points.map(point => Number(point.price));
  const first = points[0];
  const latest = points[points.length - 1];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const change = Number(latest.price) - Number(first.price);
  return `
    <div class="chart-summary">
      <div><span>Latest</span><strong>${money(latest.price, currency)}</strong></div>
      <div><span>Change</span><strong class="${changeClass({ change })}">${signedMoney(change, latest.currency || currency)}</strong></div>
      <div><span>Low</span><strong>${money(min, currency)}</strong></div>
      <div><span>High</span><strong>${money(max, currency)}</strong></div>
    </div>
  `;
}

function lineChartSvg(points, currency, label, width) {
  const height = 220;
  const paddingX = 42;
  const paddingTop = 18;
  const paddingBottom = 34;
  const values = points.map(point => Number(point.price));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = max - min || 1;
  const singlePoint = values.length === 1;
  const coords = values.map((value, index) => {
    const x = singlePoint ? width / 2 : paddingX + (index / (values.length - 1)) * (width - paddingX * 2);
    const y = height - paddingBottom - ((value - min) / spread) * (height - paddingTop - paddingBottom);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const firstDate = formatShortDate(points[0].captured_at);
  const latestDate = formatShortDate(points[points.length - 1].captured_at);
  const mid = min + spread / 2;
  const gridY = [paddingTop, height - paddingBottom - (height - paddingTop - paddingBottom) / 2, height - paddingBottom];
  const areaPoints = singlePoint
    ? ""
    : `${paddingX},${height - paddingBottom} ${coords.join(" ")} ${width - paddingX},${height - paddingBottom}`;

  return `
    <svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(label)}">
      <rect x="0" y="0" width="${width}" height="${height}" class="chart-bg"></rect>
      ${gridY.map(y => `<line x1="${paddingX}" y1="${y.toFixed(1)}" x2="${width - paddingX}" y2="${y.toFixed(1)}" class="chart-grid"></line>`).join("")}
      ${singlePoint ? "" : `<polygon points="${areaPoints}" class="chart-area"></polygon>`}
      ${singlePoint ? "" : `<polyline points="${coords.join(" ")}" class="chart-line"></polyline>`}
      <text x="10" y="${paddingTop + 4}" class="chart-label">${money(max, currency)}</text>
      <text x="10" y="${(height - paddingBottom - (height - paddingTop - paddingBottom) / 2 + 4).toFixed(1)}" class="chart-label">${money(mid, currency)}</text>
      <text x="10" y="${height - paddingBottom + 4}" class="chart-label">${money(min, currency)}</text>
      <text x="${paddingX}" y="${height - 10}" class="chart-label">${escapeHtml(firstDate)}</text>
      <text x="${width - paddingX}" y="${height - 10}" class="chart-label chart-label-end">${escapeHtml(latestDate)}</text>
    </svg>
  `;
}

function money(value, currency) {
  if (value === null || value === undefined) {
    return "n/a";
  }
  return `${Number(value).toFixed(2)} ${currency}`;
}

function conditionLabel(value) {
  const normalized = String(value || "Near Mint").trim().toLowerCase().replaceAll("_", " ");
  const labels = {
    "nm": "Near Mint",
    "near mint": "Near Mint",
    "lp": "Lightly Played",
    "lightly played": "Lightly Played",
    "mp": "Moderately Played",
    "moderately played": "Moderately Played",
    "hp": "Heavily Played",
    "heavily played": "Heavily Played",
    "dmg": "Damaged",
    "damaged": "Damaged"
  };
  return labels[normalized] || String(value || "Near Mint");
}

function finishLabel(value) {
  const normalized = String(value || "Non-Foil").trim().toLowerCase().replaceAll("_", "-");
  const labels = {
    "nonfoil": "Non-Foil",
    "non-foil": "Non-Foil",
    "foil": "Foil",
    "etched": "Etched"
  };
  return labels[normalized] || String(value || "Non-Foil");
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

function formatShortDate(value) {
  return DATE_ONLY_FORMATTER.format(new Date(value));
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
