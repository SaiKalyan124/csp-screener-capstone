const form = document.querySelector("#ticker-form");
const input = document.querySelector("#ticker");
const button = document.querySelector("#load-button");
const chainSection = document.querySelector("#chain");
const status = document.querySelector("#form-status");
const empty = document.querySelector("#empty-state");
const tableWrap = document.querySelector("#table-wrap");
const body = document.querySelector("#chain-body");
const dashboardView = document.querySelector("#dashboard-view");
const screenerView = document.querySelector("#screener-view");
const dashboardNav = document.querySelector("#dashboard-nav");
const screenerNav = document.querySelector("#screener-nav");
const dashboardRun = document.querySelector("#dashboard-run");
const dashboardEmpty = document.querySelector("#dashboard-empty");
const dashboardResults = document.querySelector("#dashboard-results");
let dashboardResearchStatus = "pending";

const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const number = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function text(value, fallback = "—") {
  return value === null || value === undefined ? fallback : value;
}

function readableContract(row) {
  const match = row.symbol.match(/^(.*?)(\d{2})(\d{2})(\d{2})([CP])(\d{8})$/);
  if (!match) return row.symbol;
  const [, , year, month, day] = match;
  const expiry = new Date(2000 + Number(year), Number(month) - 1, Number(day));
  const date = expiry.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
  return `${date} · ${money.format(row.strike)} ${row.type}`;
}

function renderRow(row, index) {
  const tr = document.createElement("tr");
  if (index === 5) tr.className = "group-start";
  const iv = row.implied_volatility == null ? "—" : `${(row.implied_volatility * 100).toFixed(1)}%`;
  const delta = row.delta == null ? "—" : row.delta.toFixed(3);
  tr.innerHTML = `
    <td><span class="money ${row.type.toLowerCase()}">${row.strategy}</span> <small>Score ${row.rank_score} · ${row.distance_pct > 0 ? "+" : ""}${row.distance_pct}%</small></td>
    <td class="contract"><strong></strong><small></small></td><td class="number">${number.format(row.strike)}</td>
    <td class="number">${number.format(row.bid)}</td><td class="number">${number.format(row.ask)}</td>
    <td class="number optional">${iv}</td><td class="number optional">${delta}</td>`;
  tr.querySelector(".contract strong").textContent = readableContract(row);
  tr.querySelector(".contract small").textContent = row.symbol;
  return tr;
}

function renderCandidate(candidate, index) {
  const row = document.createElement("button");
  row.type = "button";
  row.className = "candidate-row";
  row.setAttribute("aria-label", `Load ${candidate.symbol} option chain`);
  const returnClass = candidate.return_3m_pct >= 0 ? "candidate-positive" : "candidate-negative";
  const classification = candidate.classification || (
    dashboardResearchStatus === "fallback" ? "research unavailable" : "deterministic"
  );
  const researchLabel = classification === "research unavailable"
    ? classification
    : `${classification.replace("_", " ")} research`;
  row.innerHTML = `
    <span class="candidate-rank">${index + 1}</span>
    <span class="candidate-symbol"><strong></strong><small></small></span>
    <span class="candidate-reason"><strong>${researchLabel}</strong><span></span></span>
    <span class="candidate-metric liquidity"><strong>$${number.format(candidate.avg_dollar_volume_m)}M</strong><small>avg dollar volume</small></span>
    <span class="candidate-metric"><strong class="${returnClass}">${candidate.return_3m_pct > 0 ? "+" : ""}${candidate.return_3m_pct}%</strong><small>3-month return</small></span>
    <span class="candidate-score">${candidate.score}</span>`;
  row.querySelector(".candidate-symbol strong").textContent = candidate.symbol;
  row.querySelector(".candidate-symbol small").textContent = money.format(candidate.price);
  row.querySelector(".candidate-reason span").textContent = candidate.research_reason || candidate.reason;
  row.addEventListener("click", async () => {
    showView("screener");
    input.value = candidate.symbol;
    await loadChain(candidate.symbol);
    chainSection.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  return row;
}

function showView(view) {
  const dashboardIsActive = view === "dashboard";
  dashboardView.hidden = !dashboardIsActive;
  screenerView.hidden = dashboardIsActive;
  dashboardNav.classList.toggle("active", dashboardIsActive);
  screenerNav.classList.toggle("active", !dashboardIsActive);
  history.replaceState(null, "", dashboardIsActive ? "#dashboard" : "#screener");
}

async function runStockScreen(force = false) {
  dashboardRun.disabled = true;
  dashboardRun.textContent = "Screening…";
  status.textContent = "";
  try {
    const params = new URLSearchParams({ research: "1" });
    if (force) params.set("refresh", "1");
    const response = await fetch(`/api/screen?${params}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "The stock screen could not be completed.");
    dashboardResearchStatus = data.research_status || "not_requested";
    dashboardResults.replaceChildren(
      ...data.candidates.slice(0, 10).map(renderCandidate)
    );
    dashboardEmpty.hidden = true;
    dashboardResults.hidden = false;
    document.querySelector("#dashboard-qualified").textContent = `${data.qualified_count} stocks`;
    document.querySelector("#dashboard-updated").textContent = new Date(data.generated_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    document.querySelector("#dashboard-latency").textContent = `${data.cache_status} · ${data.latency_ms} ms`;
  } catch (error) {
    status.textContent = error.message;
  } finally {
    dashboardRun.disabled = false;
    dashboardRun.textContent = "Refresh top 10";
  }
}

async function loadChain(symbol) {
  chainSection.setAttribute("aria-busy", "true");
  button.disabled = true;
  button.querySelector("span").textContent = "Loading…";
  status.textContent = "";
  try {
    const response = await fetch(`/api/options?symbol=${encodeURIComponent(symbol)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "The option chain could not be loaded.");
    document.querySelector("#context-symbol").textContent = data.symbol;
    document.querySelector("#context-price").textContent = `${money.format(data.spot)} latest trade`;
    document.querySelector("#context-expiry").textContent = new Date(`${data.expiration}T12:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" });
    document.querySelector("#context-count").textContent = `${data.contracts.length} contracts`;
    document.querySelector("#context-latency").textContent = `${data.latency_ms} ms`;
    document.querySelector("#context-scanned").textContent = `${data.source_count} contracts scanned`;
    body.replaceChildren(...data.contracts.map(renderRow));
    empty.hidden = true;
    tableWrap.hidden = false;
  } catch (error) {
    status.textContent = error.message;
    tableWrap.hidden = true;
    empty.hidden = false;
  } finally {
    chainSection.setAttribute("aria-busy", "false");
    button.disabled = false;
    button.querySelector("span").textContent = "Screen ticker";
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const symbol = input.value.trim().toUpperCase();
  input.value = symbol;
  if (!/^[A-Z][A-Z.\-]{0,9}$/.test(symbol)) {
    status.textContent = "Enter a valid ticker such as MU, AAPL, or SPY.";
    return;
  }
  loadChain(symbol);
});

dashboardRun.addEventListener("click", () => runStockScreen(true));
dashboardNav.addEventListener("click", (event) => {
  event.preventDefault();
  showView("dashboard");
});
screenerNav.addEventListener("click", (event) => {
  event.preventDefault();
  showView("screener");
});

showView(location.hash === "#dashboard" ? "dashboard" : "screener");
runStockScreen(false);

const chatForm = document.querySelector("#chat-form");
const chatQuestion = document.querySelector("#chat-question");
const chatMessages = document.querySelector("#chat-messages");

async function askKezzy(questionText) {
  const question = questionText.trim();
  if (!question) return;
  const symbol = input.value.trim().toUpperCase() || "MU";
  const userMessage = document.createElement("p");
  userMessage.className = "user-message";
  userMessage.textContent = `${symbol}: ${question}`;
  const answerMessage = document.createElement("div");
  answerMessage.className = "assistant-message agent-response";
  answerMessage.textContent = "Researching filing metadata…";
  chatMessages.append(userMessage, answerMessage);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  chatForm.querySelector("button").disabled = true;
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol, question }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Kezzy could not answer.");
    answerMessage.textContent = data.answer;
    const risk = document.createElement("span");
    risk.className = "risk-tag";
    risk.textContent = `Research risk: ${data.risk_level} · ${data.evidence_scope}`;
    answerMessage.append(document.createElement("br"), risk);
    if (data.citations.length) {
      const citations = document.createElement("span");
      citations.className = "chat-citations";
      data.citations.forEach((citation) => {
        const link = document.createElement("a");
        link.href = citation.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = citation.label;
        citations.append(link);
      });
      answerMessage.append(citations);
    }
    if (data.ui_candidates?.length) {
      const cards = document.createElement("span");
      cards.className = "chat-candidate-cards";
      data.ui_candidates.forEach((candidate) => {
        const card = document.createElement("button");
        card.type = "button";
        card.className = "chat-candidate-card";
        const put = candidate.put;
        const title = document.createElement("strong");
        title.textContent = `${candidate.symbol} · ${money.format(candidate.spot)}`;
        const detail = document.createElement("span");
        detail.textContent = put
          ? `${candidate.expiration} · ${money.format(put.strike)} put · Δ ${number.format(put.delta)} · ${money.format(put.cash_required)} cash · ${put.premium_yield_pct}% yield`
          : "Open available option contracts";
        card.append(title, detail);
        card.addEventListener("click", async () => {
          input.value = candidate.symbol;
          showView("screener");
          await loadChain(candidate.symbol);
        });
        cards.append(card);
      });
      answerMessage.append(cards);
    }
    if (data.ui_action?.type === "load_options") {
      input.value = data.ui_action.symbol;
      showView("screener");
      await loadChain(data.ui_action.symbol);
    }
  } catch (error) {
    answerMessage.textContent = error.message;
  } finally {
    chatForm.querySelector("button").disabled = false;
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }
}

document.querySelectorAll(".chat-actions > button").forEach((promptButton) => {
  promptButton.addEventListener("click", () => askKezzy(promptButton.dataset.question));
});

chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const question = chatQuestion.value;
  chatQuestion.value = "";
  askKezzy(question);
});

const appShell = document.querySelector(".app-shell");
const sidebarToggle = document.querySelector("#sidebar-toggle");
const chatToggle = document.querySelector("#chat-toggle");

sidebarToggle.addEventListener("click", () => {
  const collapsed = appShell.classList.toggle("left-collapsed");
  sidebarToggle.textContent = collapsed ? "›" : "‹";
  sidebarToggle.setAttribute("aria-expanded", String(!collapsed));
  sidebarToggle.setAttribute(
    "aria-label",
    collapsed ? "Expand navigation" : "Collapse navigation"
  );
});

chatToggle.addEventListener("click", () => {
  const collapsed = appShell.classList.toggle("right-collapsed");
  chatToggle.setAttribute("aria-expanded", String(!collapsed));
  chatToggle.setAttribute(
    "aria-label",
    collapsed ? "Expand chat" : "Collapse chat"
  );
});
