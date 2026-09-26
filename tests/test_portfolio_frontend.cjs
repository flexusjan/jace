const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");

function renderHistory(history) {
  const elements = new Map();
  const element = () => ({
    textContent: "",
    innerHTML: "",
    classList: { toggle() {}, add() {}, remove() {}, contains() { return true; } },
    addEventListener() {},
    setAttribute() {}
  });
  const context = vm.createContext({
    history,
    document: {
      body: element(),
      querySelector(selector) {
        if (!elements.has(selector)) elements.set(selector, element());
        return elements.get(selector);
      },
      querySelectorAll() { return []; },
      addEventListener() {}
    },
    window: { matchMedia() { return { matches: true, addEventListener() {} }; } },
    localStorage: { getItem() { return null; } },
    fetch: () => new Promise(() => {}),
    setInterval() {}
  });
  vm.runInContext(readFileSync(join(__dirname, "../jace/static/app.js"), "utf8"), context);
  vm.runInContext(`
    state.valueHistory = history;
    state.totalCurrency = "EUR";
    renderPortfolioChange();
    renderPortfolioHistory();
  `, context);
  return {
    metric: elements.get("#portfolio-change"),
    chart: elements.get("#portfolio-history-content").innerHTML
  };
}

const first = { captured_at: "2026-01-01", total_value: "10", currency: "EUR" };
const added = {
  captured_at: "2026-09-01", total_value: "30", currency: "EUR",
  price_change: "5", performance_started_at: "2026-01-01"
};

test("adding a copy increases value without presenting it as price gain", () => {
  const { metric, chart } = renderHistory([first, added]);
  assert.equal(metric.textContent, "(+5.00 EUR price gain)");
  assert.equal(metric.className, "metric-change gain");
  assert.match(chart, /Current<\/span><strong>30.00 EUR/);
  assert.match(chart, /Price gain<\/span><strong class="gain">\+5.00 EUR/);
  assert.doesNotMatch(chart, /\+20.00 EUR/);
  assert.match(chart, /value chart includes cards added or removed/);
});

test("legacy histories remain visible without claiming a calculated gain", () => {
  const { metric, chart } = renderHistory([first, { ...added, price_change: null, performance_started_at: null }]);
  assert.equal(metric.textContent, "");
  assert.match(chart, /Current<\/span><strong>30.00 EUR/);
  assert.match(chart, /Price gain<\/span><strong class="">n\/a/);
  assert.match(chart, /available after the next price update/);
});

test("a first corrected snapshot shows its accumulated gain, including zero or loss", () => {
  for (const [gain, display, css] of [["5", "+5.00", "gain"], ["0", "0.00", ""], ["-2", "-2.00", "loss"]]) {
    const { metric } = renderHistory([{ ...added, price_change: gain }]);
    assert.equal(metric.textContent, `(${display} EUR price gain)`);
    assert.equal(metric.className, `metric-change ${css}`);
    assert.match(metric.title, /Price gain since/);
  }
});
