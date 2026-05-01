const state = {
  cards: [],
  selectedName: null,
  query: ""
};

const cardsBody = document.querySelector("#cards");
const detail = document.querySelector("#detail");
const search = document.querySelector("#search");
const refresh = document.querySelector("#refresh");
const cardCount = document.querySelector("#card-count");
const portfolioValue = document.querySelector("#portfolio-value");

refresh.addEventListener("click", loadCards);
search.addEventListener("input", event => {
  state.query = event.target.value.toLowerCase();
  render();
});

loadCards();

async function loadCards() {
  refresh.disabled = true;
  try {
    const response = await fetch("/api/cards", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Request failed with status ${response.status}`);
    }
    const payload = await response.json();
    state.cards = payload.cards;
    if (!state.selectedName && state.cards.length > 0) {
      state.selectedName = state.cards[0].name;
    }
    render();
  } catch (error) {
    detail.innerHTML = `<h2>Could not load prices</h2><p class="muted">${escapeHtml(error.message)}</p>`;
  } finally {
    refresh.disabled = false;
  }
}

function render() {
  const filtered = state.cards.filter(card => {
    const haystack = `${card.name} ${card.set_code} ${card.collector_number}`.toLowerCase();
    return haystack.includes(state.query);
  });

  cardsBody.innerHTML = filtered.map(card => rowTemplate(card)).join("");
  cardsBody.querySelectorAll("tr").forEach(row => {
    row.addEventListener("click", () => {
      state.selectedName = row.dataset.name;
      render();
    });
  });

  const total = state.cards.reduce((sum, card) => {
    const price = Number(card.latest_price || 0);
    return sum + price * card.quantity;
  }, 0);
  const currency = state.cards[0]?.currency || "";
  cardCount.textContent = `${state.cards.length} cards`;
  portfolioValue.textContent = `${total.toFixed(2)} ${currency}`.trim();

  const selected = state.cards.find(card => card.name === state.selectedName) || filtered[0];
  renderDetail(selected);
}

function rowTemplate(card) {
  const change = Number(card.change || 0);
  const changeClass = change > 0 ? "gain" : change < 0 ? "loss" : "";
  const selected = card.name === state.selectedName ? "selected" : "";
  return `
    <tr class="${selected}" data-name="${escapeHtml(card.name)}">
      <td class="card-name">${escapeHtml(card.name)}</td>
      <td>${escapeHtml(card.set_code.toUpperCase())} #${escapeHtml(card.collector_number)}</td>
      <td>${card.quantity}</td>
      <td>${money(card.latest_price, card.currency)}</td>
      <td class="${changeClass}">${signedMoney(card.change, card.currency)}</td>
      <td>${formatDate(card.latest_captured_at)}</td>
    </tr>
  `;
}

function renderDetail(card) {
  if (!card) {
    detail.innerHTML = `<h2>No cards tracked</h2><p class="muted">Run the tracker to create the first price snapshot.</p>`;
    return;
  }

  const points = card.history.filter(point => point.price !== null);
  detail.innerHTML = `
    <h2>${escapeHtml(card.name)}</h2>
    <p class="muted">${escapeHtml(card.set_code.toUpperCase())} #${escapeHtml(card.collector_number)} · ${card.quantity} tracked</p>
    ${chartSvg(points, card.currency)}
    <ul class="history-list">
      ${card.history.slice().reverse().map(point => `
        <li>
          <span>${formatDate(point.captured_at)}</span>
          <strong>${money(point.price, point.currency)}</strong>
        </li>
      `).join("")}
    </ul>
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
      <rect x="0" y="0" width="${width}" height="${height}" fill="#f8faf7"></rect>
      <polyline points="${coords.join(" ")}" fill="none" stroke="#236b5a" stroke-width="3"></polyline>
      <text x="${padding}" y="${padding}" fill="#6a746c" font-size="12">${money(max, currency)}</text>
      <text x="${padding}" y="${height - 6}" fill="#6a746c" font-size="12">${money(min, currency)}</text>
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
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(new Date(value));
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
