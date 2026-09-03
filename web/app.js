const form = document.querySelector("#ticker-form");
const input = document.querySelector("#ticker");
const button = document.querySelector("#load-button");
const chainSection = document.querySelector("#chain");
const status = document.querySelector("#form-status");
const empty = document.querySelector("#empty-state");
const tableWrap = document.querySelector("#table-wrap");
const body = document.querySelector("#chain-body");
const authGate = document.querySelector("#auth-gate");
const authForm = document.querySelector("#auth-form");
const authStatus = document.querySelector("#auth-status");
const signOutButton = document.querySelector("#sign-out");
let supabaseClient = null;
let accessToken = null;

function readableUserName(session) {
  const user = session?.user;
  const metadataName = user?.user_metadata?.full_name || user?.user_metadata?.name;
  const source = metadataName || user?.email?.split("@")[0] || "Demo User";
  return source
    .replace(/[._-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function updateUserName(session) {
  const name = readableUserName(session);
  const firstName = name.split(/\s+/)[0];
  document.querySelectorAll("[data-user-name]").forEach((node) => { node.textContent = name; });
  document.querySelectorAll("[data-user-first-name]").forEach((node) => { node.textContent = firstName; });
}

async function apiFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  const response = await fetch(url, { ...options, headers });
  if (response.status === 401 && supabaseClient) {
    authGate.hidden = false;
    document.querySelector(".app-shell").hidden = true;
    signOutButton.hidden = true;
  }
  return response;
}

function showAuthenticated(session) {
  accessToken = session?.access_token || null;
  const signedIn = Boolean(session);
  authGate.hidden = signedIn;
  document.querySelector(".app-shell").hidden = !signedIn;
  signOutButton.hidden = !signedIn;
  updateUserName(session);
}

async function initializeAuth() {
  try {
    const response = await fetch("/api/runtime-config");
    const config = await response.json();
    if (!config.auth_required) {
      authGate.hidden = true;
      document.querySelector(".app-shell").hidden = false;
      runStockScreen(false);
      return;
    }
    supabaseClient = window.supabase.createClient(
      config.supabase_url,
      config.supabase_anon_key,
      { auth: { persistSession: true, autoRefreshToken: true } },
    );
    const { data } = await supabaseClient.auth.getSession();
    showAuthenticated(data.session);
    if (data.session) runStockScreen(false);
    supabaseClient.auth.onAuthStateChange((_event, session) => {
      const wasSignedOut = !accessToken;
      showAuthenticated(session);
      if (session && wasSignedOut) runStockScreen(false);
    });
  } catch (error) {
    authStatus.textContent = "Authentication could not be initialized.";
    authGate.hidden = false;
    document.querySelector(".app-shell").hidden = true;
  }
}
const dashboardView = document.querySelector("#dashboard-view");
const screenerView = document.querySelector("#screener-view");
const dashboardNav = document.querySelector("#dashboard-nav");
const screenerNav = document.querySelector("#screener-nav");
const dashboardRun = document.querySelector("#dashboard-run");
const dashboardEmpty = document.querySelector("#dashboard-empty");
const dashboardResults = document.querySelector("#dashboard-results");
let dashboardResearchStatus = "pending";
let activeSymbol = "";
let firstDashboardSymbol = "";

const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const number = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function text(value, fallback = "—") {
  return value === null || value === undefined ? fallback : value;
}

function relativeAge(timestamp) {
  const seconds = Math.max(0, Math.round((Date.now() - new Date(timestamp).getTime()) / 1000));
  if (seconds < 60) return `${seconds} seconds ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.round(minutes / 60);
  return `${hours} hour${hours === 1 ? "" : "s"} ago`;
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
    const response = await apiFetch(`/api/screen?${params}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "The stock screen could not be completed.");
    dashboardResearchStatus = data.research_status || "not_requested";
    firstDashboardSymbol = data.candidates[0]?.symbol || "";
    dashboardResults.replaceChildren(
      ...data.candidates.slice(0, 10).map(renderCandidate)
    );
    dashboardEmpty.hidden = true;
    dashboardResults.hidden = false;
    document.querySelector("#dashboard-qualified").textContent = `${data.qualified_count} stocks`;
    document.querySelector("#dashboard-top-count").textContent = `${data.candidates.length} candidates`;
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
    const response = await apiFetch(`/api/options?symbol=${encodeURIComponent(symbol)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "The option chain could not be loaded.");
    activeSymbol = data.symbol;
    input.value = data.symbol;
    document.querySelector("#context-symbol").textContent = data.symbol;
    document.querySelector("#context-price").textContent = money.format(data.spot);
    const bestPut = data.contracts.find((row) => row.strategy === "Cash-secured put");
    const collateral = bestPut ? bestPut.strike * 100 : null;
    document.querySelector("#context-collateral").textContent = collateral ? money.format(collateral) : "—";
    document.querySelector("#context-freshness").textContent = relativeAge(data.trade_timestamp);
    const earnings = data.next_earnings ? new Date(data.next_earnings) : null;
    const expiry = new Date(`${data.expiration}T23:59:59`);
    document.querySelector("#context-earnings").textContent = earnings
      ? `${earnings <= expiry ? "Before" : "After"} expiration`
      : "Not available";
    document.querySelector("#context-earnings-detail").textContent = earnings
      ? earnings.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
      : "Yahoo MCP calendar unavailable";
    document.querySelector("#operational-detail").textContent = `Alpaca response: ${data.latency_ms} ms · ${data.source_count} contracts scanned · Expiration ${new Date(`${data.expiration}T12:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}`;
    body.replaceChildren(...data.contracts.map(renderRow));
    empty.hidden = true;
    tableWrap.hidden = false;
  } catch (error) {
    const isEligibilityRejection = error.message.includes("No expiration has five eligible");
    status.textContent = isEligibilityRejection
      ? `${symbol} does not meet the screener’s current eligibility criteria. No expiration has at least five quoted OTM puts and five quoted OTM calls after the delta, bid, and spread filters. This is a current-data result and may change as prices and liquidity update.`
      : error.message;
    if (isEligibilityRejection) {
      document.querySelector("#context-symbol").textContent = symbol;
      document.querySelector("#context-price").textContent = "Not eligible";
      document.querySelector("#context-collateral").textContent = "—";
      document.querySelector("#context-freshness").textContent = "Screened live";
      document.querySelector("#context-earnings").textContent = "Not evaluated";
      document.querySelector("#context-earnings-detail").textContent = "Ticker did not pass contract rules";
      document.querySelector("#operational-detail").textContent = "Try again as prices, quotes, and liquidity change.";
    }
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

showView(location.hash === "#screener" ? "screener" : "dashboard");
initializeAuth();

const chatForm = document.querySelector("#chat-form");
const chatQuestion = document.querySelector("#chat-question");
const chatMessages = document.querySelector("#chat-messages");

function tickerFromQuestion(question) {
  const ignored = new Set(["I", "AI", "CSP", "DTE", "ETF", "ITM", "OTM", "SEC", "USD"]);
  const prefixed = question.match(/^\s*\$?([A-Za-z][A-Za-z.\-]{0,9})\s*:/);
  const cashtag = question.match(/\$([A-Za-z][A-Za-z.\-]{0,9})\b/);
  const uppercase = question.match(/\b[A-Z][A-Z.\-]{0,9}\b/g) || [];
  const candidates = [prefixed?.[1], cashtag?.[1], ...uppercase].filter(Boolean);
  return candidates
    .map((candidate) => candidate.toUpperCase())
    .find((candidate) => !ignored.has(candidate) && /^[A-Z][A-Z.\-]{0,9}$/.test(candidate));
}

async function askCspAnalyst(questionText) {
  const question = questionText.trim();
  if (!question) return;
  const symbol = tickerFromQuestion(question) || activeSymbol || firstDashboardSymbol;
  if (!symbol) {
    const message = document.createElement("p");
    message.className = "assistant-message";
    message.textContent = "Choose a dashboard candidate or enter a ticker before asking ticker-specific questions.";
    chatMessages.append(message);
    return;
  }
  activeSymbol = symbol;
  input.value = symbol;
  const displayQuestion = question.replace(
    /^\s*\$?[A-Za-z][A-Za-z.\-]{0,9}\s*:\s*/,
    "",
  ).trim() || question;
  const userMessage = document.createElement("p");
  userMessage.className = "user-message";
  userMessage.textContent = displayQuestion;
  const answerMessage = document.createElement("div");
  answerMessage.className = "assistant-message agent-response";
  answerMessage.textContent = "Researching Yahoo evidence via MCP…";
  chatMessages.append(userMessage, answerMessage);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  chatForm.querySelector("button").disabled = true;
  try {
    const response = await apiFetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol, question }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "CSP Research Bot could not answer.");
    answerMessage.textContent = "";
    const bulletList = document.createElement("ul");
    bulletList.className = "chat-bullets";
    data.answer
      .split(/\r?\n/)
      .map((line) => line.replace(/^\s*[-•]\s*/, "").trim())
      .filter(Boolean)
      .slice(0, 10)
      .forEach((text) => {
        const bullet = document.createElement("li");
        bullet.textContent = text;
        bulletList.append(bullet);
      });
    answerMessage.append(bulletList);
    // Evidence URLs remain in the backend response and Arize trace for audit and
    // debugging; the user-facing chat shows only concise material findings.
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

document.querySelectorAll(".chat-hints button[data-question]").forEach((promptButton) => {
  promptButton.addEventListener("click", () => askCspAnalyst(promptButton.dataset.question));
});

chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const question = chatQuestion.value;
  chatQuestion.value = "";
  askCspAnalyst(question);
});

authForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  authStatus.textContent = "Signing in…";
  const email = document.querySelector("#auth-email").value.trim();
  const password = document.querySelector("#auth-password").value;
  const { error } = await supabaseClient.auth.signInWithPassword({ email, password });
  authStatus.textContent = error ? error.message : "";
});

document.querySelector("#sign-up").addEventListener("click", async () => {
  authStatus.textContent = "Creating account…";
  const email = document.querySelector("#auth-email").value.trim();
  const password = document.querySelector("#auth-password").value;
  if (!email || password.length < 6) {
    authStatus.textContent = "Enter an email and a password of at least six characters.";
    return;
  }
  const { data, error } = await supabaseClient.auth.signUp({ email, password });
  authStatus.textContent = error
    ? error.message
    : data.session
      ? ""
      : "Check your email to confirm the account, then sign in.";
});

signOutButton.addEventListener("click", async () => {
  await supabaseClient?.auth.signOut();
});

const appShell = document.querySelector(".app-shell");
const sidebarToggle = document.querySelector("#sidebar-toggle");
const chatToggle = document.querySelector("#chat-toggle");
const chatHintsToggle = document.querySelector("#chat-hints-toggle");
const chatHints = document.querySelector("#chat-hints");
const themeToggle = document.querySelector("#theme-toggle");

function applyTheme(theme) {
  const dark = theme === "dark";
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  themeToggle.setAttribute("aria-checked", String(dark));
  themeToggle.setAttribute("aria-label", dark ? "Use light theme" : "Use dark theme");
  themeToggle.querySelector("b").textContent = dark ? "Dark" : "Light";
  localStorage.setItem("csp-theme", dark ? "dark" : "light");
}

applyTheme(localStorage.getItem("csp-theme") || "light");
themeToggle.addEventListener("click", () => {
  applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
});

chatHintsToggle.addEventListener("click", () => {
  const collapsed = !chatHints.hidden;
  chatHints.hidden = collapsed;
  chatHintsToggle.setAttribute("aria-expanded", String(!collapsed));
  chatHintsToggle.querySelector("b").textContent = collapsed ? "+" : "−";
});

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
