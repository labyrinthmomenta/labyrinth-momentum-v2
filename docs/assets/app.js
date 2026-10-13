const state = {
  manifest: null,
  publicationRows: [],
  rows: [],
  filteredRows: [],
  sortKey: "momentum_63",
  sortDirection: "desc",
  search: "",
  tradeType: "all",
  sector: "all",
  pageView: "screener",
  strategyMode: "strong",
  strategyUniverse: "all",
  strategyLimit: 10,
  detailTab: "summary"
};

const els = {
  statusBadge: document.getElementById("statusBadge"),
  asOfDate: document.getElementById("asOfDate"),
  universeCount: document.getElementById("universeCount"),
  availableCount: document.getElementById("availableCount"),
  insufficientCount: document.getElementById("insufficientCount"),
  unavailableCount: document.getElementById("unavailableCount"),
  visibleCount: document.getElementById("visibleCount"),
  generatedAt: document.getElementById("generatedAt"),
  searchInput: document.getElementById("searchInput"),
  tradeFilterButtons: [
    ...document.querySelectorAll("[data-trade-filter]")
  ],
  sectorFilter: document.getElementById("sectorFilter"),
  body: document.getElementById("screenerBody"),
  errorBox: document.getElementById("errorBox"),
  csvDownload: document.getElementById("csvDownload"),
  jsonDownload: document.getElementById("jsonDownload"),
  metricGuideToggle: document.getElementById("metricGuideToggle"),
  metricGuidePanel: document.getElementById("metricGuidePanel"),

  pageViewButtons: [
    ...document.querySelectorAll("[data-page-view]")
  ],
  screenerView: document.getElementById("screenerView"),
  strategyView: document.getElementById("strategyView"),

  strategyModeButtons: [
    ...document.querySelectorAll("[data-strategy-mode]")
  ],
  strategyUniverseButtons: [
    ...document.querySelectorAll("[data-strategy-universe]")
  ],
  strategyLimitButtons: [
    ...document.querySelectorAll("[data-strategy-limit]")
  ],
  strategyHead: document.getElementById("strategyHead"),
  strategyBody: document.getElementById("strategyBody"),
  strategyCount: document.getElementById("strategyCount"),
  strategyContext: document.getElementById("strategyContext"),
  strategyTitle: document.getElementById("strategyTitle"),
  strategyDescription: document.getElementById("strategyDescription"),

  detailBackdrop: document.getElementById("detailBackdrop"),
  detailDrawer: document.getElementById("detailDrawer"),
  detailClose: document.getElementById("detailClose"),
  detailTicker: document.getElementById("detailTicker"),
  detailName: document.getElementById("detailName"),
  detailStatus: document.getElementById("detailStatus"),
  detailLoading: document.getElementById("detailLoading"),
  detailContent: document.getElementById("detailContent"),
  detailError: document.getElementById("detailError"),

  detailLastClose: document.getElementById("detailLastClose"),
  priceChart: document.getElementById("priceChart"),
  chartStartDate: document.getElementById("chartStartDate"),
  chartEndDate: document.getElementById("chartEndDate"),
  chartObservationCount: document.getElementById("chartObservationCount"),

  detailMom252: document.getElementById("detailMom252"),
  detailMom126: document.getElementById("detailMom126"),
  detailMom63: document.getElementById("detailMom63"),
  detailMom21: document.getElementById("detailMom21"),

  detailFip252: document.getElementById("detailFip252"),
  detailFip126: document.getElementById("detailFip126"),
  detailFip63: document.getElementById("detailFip63"),
  detailFip21: document.getElementById("detailFip21"),

  detailAtr: document.getElementById("detailAtr"),
  detailDeltaMom: document.getElementById("detailDeltaMom"),
  detailDeltaFip: document.getElementById("detailDeltaFip"),

  detailFirstTrade: document.getElementById("detailFirstTrade"),
  detailSector: document.getElementById("detailSector"),
  detailIndustry: document.getElementById("detailIndustry")
};

function numericValue(value) {
  if (value === null || value === undefined || value === "") return null;

  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function formatRatioPercent(value) {
  const number = numericValue(value);
  if (number === null) return "—";

  const pct = number * 100;
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%`;
}

function formatAtr(value) {
  const number = numericValue(value);
  if (number === null) return "—";

  return `${number.toFixed(2)}%`;
}

function formatFip(value) {
  const number = numericValue(value);
  if (number === null) return "—";

  return number.toFixed(3);
}

function valueClass(value) {
  const number = numericValue(value);

  if (number === null) return "value-null";
  if (number > 0) return "value-positive";
  if (number < 0) return "value-negative";

  return "";
}

function fipValueClass(value) {
  const number = numericValue(value);

  if (number === null) return "value-null";
  if (number < 0) return "value-positive";
  if (number > 0) return "value-negative";

  return "";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}


function formatRankPercent(value) {
  const number = numericValue(value);
  if (number === null) return "—";
  return `${number.toFixed(1)}%`;
}


function formatPlainNumber(value, digits = 2) {
  const number = numericValue(value);
  if (number === null) return "—";
  return number.toFixed(digits);
}



function formatInteger(value) {
  const number = numericValue(value);
  if (number === null) return "—";
  return String(Math.trunc(number));
}


function sessionGapClass(value) {
  const number = numericValue(value);
  if (number === null) return "value-null";
  return number === 0 ? "session-gap-ok" : "session-gap-bad";
}


function publishedDataUrl(filename) {
  const clean = String(filename ?? "")
    .replace(/^\.?\//, "");

  return new URL(
    `./data/${clean}`,
    window.location.href
  ).href;
}


function downloadPublishedFile(filename) {
  if (!filename) return;

  const anchor = document.createElement("a");
  anchor.href = publishedDataUrl(filename);
  anchor.download = filename.split("/").pop() || "download";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}


function strategySuffix() {
  return state.strategyUniverse === "viop" ? "viop" : "all";
}


function strategyRankValue(row, base) {
  return numericValue(
    row[`${base}_${strategySuffix()}`]
  );
}


function strategyPublicationError() {
  const manifest = state.manifest;

  if (!manifest) {
    return "Production manifest is not available.";
  }

  if (manifest.status !== "PASS") {
    return `Production manifest status is ${manifest.status ?? "UNKNOWN"}.`;
  }

  if (manifest.dry_run !== false) {
    return "Strategy View requires a non-dry-run production publication.";
  }

  if (
    manifest.securities_published !== undefined
    && manifest.securities_published !== null
    && Number(manifest.securities_published) !== state.publicationRows.length
  ) {
    return "Published screener row count does not match the manifest.";
  }

  const asOf = manifest.as_of;

  const mismatch = state.publicationRows.some(
    row => row.as_of !== asOf
  );

  if (mismatch) {
    return "Screener as_of does not match the production manifest.";
  }

  return null;
}


function setActiveButtons(buttons, dataKey, value) {
  buttons.forEach(button => {
    const active = button.dataset[dataKey] === String(value);
    button.classList.toggle("active", active);
    button.setAttribute(
      "aria-pressed",
      active ? "true" : "false"
    );
  });
}


function renderStrategyMessage(message) {
  els.strategyHead.innerHTML = "";
  els.strategyBody.innerHTML = `
    <tr>
      <td class="empty-row strategy-empty">
        ${escapeHtml(message)}
      </td>
    </tr>
  `;
  els.strategyCount.textContent = "0";
}


function strategyTickerCell(row) {
  return `
    <button
      type="button"
      class="ticker-button strategy-ticker-button"
      data-ticker="${escapeHtml(row.ticker)}"
      title="${escapeHtml(row.ticker)} detayını aç"
    >
      <span>${escapeHtml(row.ticker)}</span>
      ${
        row.is_viop === true
          ? '<span class="viop-badge">VİOP</span>'
          : ''
      }
    </button>
  `;
}


function renderMomentumStrategy() {
  const mode = state.strategyMode;
  const suffix = strategySuffix();

  const candidates = state.publicationRows
    .filter(row => {
      if (row.data_status !== "OK") return false;
      if (row.ranking_status !== "OK") return false;
      if (row.core_ready !== true) return false;

      if (
        state.strategyUniverse === "viop"
        && row.is_viop !== true
      ) {
        return false;
      }

      return numericValue(
        row[`core_momentum_pct_${suffix}`]
      ) !== null;
    })
    .sort((a, b) => {
      const av = numericValue(
        a[`core_momentum_pct_${suffix}`]
      );
      const bv = numericValue(
        b[`core_momentum_pct_${suffix}`]
      );

      const difference = mode === "strong"
        ? bv - av
        : av - bv;

      if (difference !== 0) return difference;

      return String(a.ticker).localeCompare(
        String(b.ticker),
        "tr",
        { sensitivity: "base" }
      );
    });

  const selected = candidates.slice(
    0,
    state.strategyLimit
  );

  els.strategyTitle.textContent =
    mode === "strong"
      ? "Strong Momentum"
      : "Weak Momentum";

  els.strategyDescription.textContent =
    mode === "strong"
      ? "Published core momentum percentile dağılımının güçlü ucu. Bu görünüm bir Buy/Long sinyali değildir."
      : "Published core momentum percentile dağılımının zayıf ucu. Bu görünüm bir Sell/Short sinyali değildir.";

  els.strategyContext.textContent =
    `${candidates.length} eligible · `
    + `${state.strategyUniverse.toUpperCase()} · `
    + `published ranks only`;

  els.strategyCount.textContent = selected.length;

  els.strategyHead.innerHTML = `
    <tr>
      <th>#</th>
      <th>Security</th>
      <th>Company</th>
      <th>Sector</th>
      <th class="numeric">Core%</th>
      <th class="numeric">FIP-Q%</th>
      <th class="numeric">M126%</th>
      <th class="numeric">M63%</th>
      <th class="numeric">M21%</th>
      <th class="numeric">FIP12-1</th>
      <th>VCP</th>
    </tr>
  `;

  if (!selected.length) {
    renderStrategyMessage(
      "No eligible securities for this strategy view."
    );
    return;
  }

  els.strategyBody.innerHTML = selected
    .map((row, index) => {
      const vcpText =
        row.vcp_status === "OK"
          ? (row.vcp_state || "OK")
          : "N/A";

      return `
        <tr class="strategy-row strategy-${mode}">
          <td class="strategy-rank">
            ${index + 1}
          </td>
          <td class="ticker-cell">
            ${strategyTickerCell(row)}
          </td>
          <td
            class="company-cell"
            title="${escapeHtml(row.name)}"
          >
            ${escapeHtml(row.name)}
          </td>
          <td class="strategy-sector">
            ${escapeHtml(row.sector || "—")}
          </td>
          <td class="numeric strategy-core">
            ${formatRankPercent(
              row[`core_momentum_pct_${suffix}`]
            )}
          </td>
          <td class="numeric">
            ${formatRankPercent(
              row[`core_quality_pct_${suffix}`]
            )}
          </td>
          <td class="numeric">
            ${formatRankPercent(
              row[`momentum_126_pct_${suffix}`]
            )}
          </td>
          <td class="numeric">
            ${formatRankPercent(
              row[`momentum_63_pct_${suffix}`]
            )}
          </td>
          <td class="numeric">
            ${formatRankPercent(
              row[`momentum_21_pct_${suffix}`]
            )}
          </td>
          <td class="numeric fip-cell ${fipValueClass(row.fip_12_1)}">
            ${formatFip(row.fip_12_1)}
          </td>
          <td>
            <span class="vcp-badge ${
              row.vcp_status === "OK"
                ? "available"
                : "unavailable"
            }">
              ${escapeHtml(vcpText)}
            </span>
          </td>
        </tr>
      `;
    })
    .join("");
}


function renderVcpStrategy() {
  const suffix = strategySuffix();

  const candidates = state.publicationRows
    .filter(row => {
      if (row.data_status !== "OK") return false;

      if (
        state.strategyUniverse === "viop"
        && row.is_viop !== true
      ) {
        return false;
      }

      return row.vcp_status === "OK";
    })
    .sort((a, b) =>
      String(a.ticker).localeCompare(
        String(b.ticker),
        "tr",
        { sensitivity: "base" }
      )
    );

  const selected = candidates.slice(
    0,
    state.strategyLimit
  );

  els.strategyTitle.textContent = "VCP";
  els.strategyDescription.textContent =
    "VCP bağımsız bir structural setup görünümüdür. Momentum ranking veya FIP quality skoruna dahil edilmez.";

  els.strategyContext.textContent =
    `${candidates.length} production VCP setups · `
    + `${state.strategyUniverse.toUpperCase()} · `
    + `no composite score`;

  els.strategyCount.textContent = selected.length;

  els.strategyHead.innerHTML = `
    <tr>
      <th>Security</th>
      <th>Company</th>
      <th>Sector</th>
      <th>VCP State</th>
      <th class="numeric">Contractions</th>
      <th class="numeric">Pivot</th>
      <th class="numeric">Dist %</th>
      <th class="numeric">Dist ATR</th>
      <th class="numeric">Range 5%</th>
      <th class="numeric">TR Comp</th>
      <th class="numeric">Vol Ratio</th>
      <th class="numeric">Core%</th>
      <th class="numeric">FIP-Q%</th>
    </tr>
  `;

  if (!selected.length) {
    renderStrategyMessage(
      "No production VCP setup is currently available. "
      + "VCP remains independent and will appear here only "
      + "when an explicit production VCP configuration publishes it."
    );
    return;
  }

  els.strategyBody.innerHTML = selected
    .map(row => `
      <tr class="strategy-row strategy-vcp">
        <td class="ticker-cell">
          ${strategyTickerCell(row)}
        </td>
        <td
          class="company-cell"
          title="${escapeHtml(row.name)}"
        >
          ${escapeHtml(row.name)}
        </td>
        <td class="strategy-sector">
          ${escapeHtml(row.sector || "—")}
        </td>
        <td>
          <span class="vcp-badge available">
            ${escapeHtml(row.vcp_state || "OK")}
          </span>
        </td>
        <td class="numeric">
          ${formatPlainNumber(
            row.vcp_confirmed_contractions,
            0
          )}
        </td>
        <td class="numeric">
          ${formatPlainNumber(row.vcp_pivot, 2)}
        </td>
        <td class="numeric">
          ${formatPlainNumber(
            row.vcp_distance_to_pivot_pct,
            2
          )}
        </td>
        <td class="numeric">
          ${formatPlainNumber(
            row.vcp_distance_to_pivot_atr,
            2
          )}
        </td>
        <td class="numeric">
          ${formatPlainNumber(row.vcp_range_5_pct, 2)}
        </td>
        <td class="numeric">
          ${formatPlainNumber(
            row.vcp_true_range_compression_10_40,
            2
          )}
        </td>
        <td class="numeric">
          ${formatPlainNumber(
            row.vcp_final_contraction_volume_ratio_50,
            2
          )}
        </td>
        <td class="numeric">
          ${formatRankPercent(
            row[`core_momentum_pct_${suffix}`]
          )}
        </td>
        <td class="numeric">
          ${formatRankPercent(
            row[`core_quality_pct_${suffix}`]
          )}
        </td>
      </tr>
    `)
    .join("");
}


function renderStrategy() {
  const publicationError = strategyPublicationError();

  if (publicationError) {
    els.strategyTitle.textContent =
      "Strategy View unavailable";
    els.strategyDescription.textContent =
      "Production publication contract validation failed.";
    els.strategyContext.textContent =
      "Fail-closed presentation";
    renderStrategyMessage(publicationError);
    return;
  }

  if (state.strategyMode === "vcp") {
    renderVcpStrategy();
    return;
  }

  renderMomentumStrategy();
}


function setPageView(value) {
  state.pageView = value;

  els.pageViewButtons.forEach(button => {
    const active = button.dataset.pageView === value;

    button.classList.toggle("active", active);
    button.setAttribute(
      "aria-pressed",
      active ? "true" : "false"
    );
  });

  els.screenerView.hidden = value !== "screener";
  els.strategyView.hidden = value !== "strategy";

  if (value === "strategy") {
    renderStrategy();
  }
}


function renderManifest() {
  const m = state.manifest;

  els.statusBadge.textContent = m.status ?? "UNKNOWN";
  els.statusBadge.className =
    `status-badge ${(m.status ?? "").toLowerCase() === "pass" ? "pass" : "fail"}`;

  els.asOfDate.textContent = m.as_of ?? "—";
  els.universeCount.textContent = m.securities_expected ?? "—";
  els.availableCount.textContent = m.data_available ?? "—";
  els.insufficientCount.textContent = m.insufficient_trading_data ?? 0;
  els.unavailableCount.textContent = m.provider_unavailable ?? 0;

  if (m.generated_at) {
    const generated = new Date(m.generated_at);

    els.generatedAt.textContent = Number.isNaN(generated.getTime())
      ? `Generated ${m.generated_at}`
      : `Generated ${generated.toLocaleString("tr-TR")}`;
  }
}

function populateSectorFilter() {
  const sectors = [
    ...new Set(
      state.rows
        .map(row => row.sector)
        .filter(Boolean)
    )
  ].sort((a, b) =>
    String(a).localeCompare(
      String(b),
      "tr",
      { sensitivity: "base" }
    )
  );

  els.sectorFilter.replaceChildren();

  const allOption = document.createElement("option");
  allOption.value = "all";
  allOption.textContent = "Tüm Sektörler";
  els.sectorFilter.appendChild(allOption);

  sectors.forEach(sector => {
    const option = document.createElement("option");
    option.value = sector;
    option.textContent = sector;
    els.sectorFilter.appendChild(option);
  });

  state.sector = "all";
  els.sectorFilter.value = "all";
}


function compareRows(a, b) {
  const key = state.sortKey;
  const direction = state.sortDirection === "asc" ? 1 : -1;

  const av = a[key];
  const bv = b[key];

  const an = numericValue(av);
  const bn = numericValue(bv);

  if (an !== null || bn !== null) {
    if (an === null) return 1;
    if (bn === null) return -1;
    if (an === bn) return 0;

    return (an - bn) * direction;
  }

  return String(av ?? "").localeCompare(
    String(bv ?? ""),
    "tr",
    { sensitivity: "base" }
  ) * direction;
}

function renderRows() {
  const query = state.search.trim().toLocaleUpperCase("tr-TR");

  const filtered = state.rows.filter(row => {
    const tradeMatches =
      state.tradeType === "all"
      || (state.tradeType === "viop" && row.is_viop === true)
      || (state.tradeType === "spot" && row.is_viop === false);

    if (!tradeMatches) return false;

    const sectorMatches =
      state.sector === "all"
      || row.sector === state.sector;

    if (!sectorMatches) return false;

    if (!query) return true;

    const haystack =
      `${row.ticker ?? ""} ${row.name ?? ""} ${row.sector ?? ""} ${row.industry ?? ""}`
        .toLocaleUpperCase("tr-TR");

    return haystack.includes(query);
  });

  state.filteredRows = filtered.sort(compareRows);
  els.visibleCount.textContent = state.filteredRows.length;

  if (!state.filteredRows.length) {
    els.body.innerHTML = `
      <tr>
        <td colspan="17" class="empty-row">
          No matching securities.
        </td>
      </tr>
    `;
    return;
  }

  els.body.innerHTML = state.filteredRows.map(row => `
    <tr>
      <td class="ticker-cell">
        <button
          type="button"
          class="ticker-button"
          data-ticker="${escapeHtml(row.ticker)}"
          title="${escapeHtml(row.ticker)} detayını aç"
        >
          <span>${escapeHtml(row.ticker)}</span>
          ${row.is_viop === true
            ? '<span class="viop-badge">VİOP</span>'
            : ''}
        </button>
      </td>

      <td class="company-cell" title="${escapeHtml(row.name)}">
        ${escapeHtml(row.name)}
      </td>

      <td class="numeric ${valueClass(row.momentum_252)}">
        ${formatRatioPercent(row.momentum_252)}
      </td>
      <td class="numeric ${valueClass(row.momentum_126)}">
        ${formatRatioPercent(row.momentum_126)}
      </td>
      <td class="numeric ${valueClass(row.momentum_63)}">
        ${formatRatioPercent(row.momentum_63)}
      </td>
      <td class="numeric ${valueClass(row.momentum_21)}">
        ${formatRatioPercent(row.momentum_21)}
      </td>

      <td class="numeric fip-cell ${fipValueClass(row.fip_252)}">
        ${formatFip(row.fip_252)}
      </td>
      <td class="numeric fip-cell ${fipValueClass(row.fip_126)}">
        ${formatFip(row.fip_126)}
      </td>
      <td class="numeric fip-cell ${fipValueClass(row.fip_63)}">
        ${formatFip(row.fip_63)}
      </td>
      <td class="numeric fip-cell ${fipValueClass(row.fip_21)}">
        ${formatFip(row.fip_21)}
      </td>

      <td class="numeric atr-cell">
        ${formatAtr(row.atr14_percent)}
      </td>

      <td class="numeric ${valueClass(row.delta_momentum_21_63)}">
        ${formatRatioPercent(row.delta_momentum_21_63)}
      </td>

      <td class="numeric ${fipValueClass(row.delta_fip_21_63)}">
        ${formatFip(row.delta_fip_21_63)}
      </td>

      <td class="numeric month-negative">
        ${formatInteger(row.current_month_negative)}
      </td>

      <td class="numeric month-positive">
        ${formatInteger(row.current_month_positive)}
      </td>

      <td class="numeric">
        ${formatInteger(row.current_month_flat)}
      </td>

      <td class="numeric ${sessionGapClass(row.current_month_session_gap)}">
        ${formatInteger(row.current_month_session_gap)}
      </td>
    </tr>
  `).join("");

  updateSortIndicators();
}

function updateSortIndicators() {
  document.querySelectorAll("th.sortable").forEach(th => {
    const indicator = th.querySelector(".sort-indicator");

    if (!indicator) return;

    indicator.textContent =
      th.dataset.key === state.sortKey
        ? state.sortDirection === "asc" ? "↑" : "↓"
        : "";
  });
}


function setMetric(
  element,
  value,
  formatter,
  classResolver = valueClass
) {
  element.textContent = formatter(value);
  element.classList.remove(
    "value-positive",
    "value-negative",
    "value-null"
  );

  const cls = classResolver(value);
  if (cls) {
    element.classList.add(cls);
  }
}

function formatClose(value) {
  const number = numericValue(value);
  if (number === null) return "—";

  if (Math.abs(number) >= 1000) {
    return number.toLocaleString("tr-TR", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });
  }

  return number.toLocaleString("tr-TR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4
  });
}

function renderPriceChart(daily) {
  const valid = (daily ?? [])
    .map(row => ({
      date: row.date,
      close: numericValue(row.close)
    }))
    .filter(row => row.date && row.close !== null)
    .sort((a, b) => a.date.localeCompare(b.date));

  if (!valid.length) {
    els.priceChart.innerHTML =
      '<div class="detail-loading">No daily price data.</div>';

    els.chartStartDate.textContent = "—";
    els.chartEndDate.textContent = "—";
    els.chartObservationCount.textContent = "0 observations";
    els.detailLastClose.textContent = "—";
    return;
  }

  // Keep the chart readable while retaining roughly six months
  // of recent trading history.
  const rows = valid.slice(-126);

  const width = 900;
  const height = 250;
  const padX = 16;
  const padTop = 18;
  const padBottom = 20;

  const values = rows.map(row => row.close);
  let min = Math.min(...values);
  let max = Math.max(...values);

  if (min === max) {
    const delta = Math.abs(min || 1) * 0.02;
    min -= delta;
    max += delta;
  }

  const range = max - min;

  const points = rows.map((row, index) => {
    const x = rows.length === 1
      ? width / 2
      : padX + (
          index / (rows.length - 1)
        ) * (width - padX * 2);

    const y =
      padTop +
      ((max - row.close) / range) *
      (height - padTop - padBottom);

    return { ...row, x, y };
  });

  const polyline = points
    .map(point => `${point.x.toFixed(2)},${point.y.toFixed(2)}`)
    .join(" ");

  const area = [
    `${points[0].x.toFixed(2)},${height - padBottom}`,
    ...points.map(
      point => `${point.x.toFixed(2)},${point.y.toFixed(2)}`
    ),
    `${points[points.length - 1].x.toFixed(2)},${height - padBottom}`
  ].join(" ");

  const last = points[points.length - 1];

  els.priceChart.innerHTML = `
    <svg
      viewBox="0 0 ${width} ${height}"
      preserveAspectRatio="none"
      role="img"
      aria-label="Daily closing price chart"
    >
      <defs>
        <linearGradient
          id="priceAreaGradient"
          x1="0"
          y1="0"
          x2="0"
          y2="1"
        >
          <stop offset="0%" stop-color="#c96b45" stop-opacity="0.22"></stop>
          <stop offset="100%" stop-color="#c96b45" stop-opacity="0"></stop>
        </linearGradient>
      </defs>

      <polygon
        class="price-area"
        points="${area}"
      ></polygon>

      <polyline
        class="price-line"
        points="${polyline}"
      ></polyline>

      <circle
        class="last-point"
        cx="${last.x}"
        cy="${last.y}"
        r="4"
      ></circle>

      <text
        class="axis-value"
        x="8"
        y="14"
      >${escapeHtml(formatClose(max))}</text>

      <text
        class="axis-value"
        x="8"
        y="${height - 5}"
      >${escapeHtml(formatClose(min))}</text>
    </svg>
  `;

  els.detailLastClose.textContent = formatClose(last.close);
  els.chartStartDate.textContent = rows[0].date;
  els.chartEndDate.textContent = last.date;
  els.chartObservationCount.textContent =
    `${rows.length} recent observations`;
}


function initializeDetailTabs() {
  if (!els.detailContent) return;
  if (document.getElementById("detailTabs")) return;

  const existingSections = [
    ...els.detailContent.querySelectorAll(":scope > .detail-section")
  ];

  const tabs = document.createElement("div");
  tabs.id = "detailTabs";
  tabs.className = "detail-tabs";
  tabs.innerHTML = `
    <button type="button" class="detail-tab active" data-detail-tab="summary">
      Özet
    </button>
    <button type="button" class="detail-tab" data-detail-tab="monthly">
      Aylık Detay
    </button>
    <button type="button" class="detail-tab" data-detail-tab="daily">
      Günlük Kapanış
    </button>
    <button type="button" class="detail-tab" data-detail-tab="source">
      Veri Kaynağı
    </button>
  `;

  els.detailContent.insertBefore(
    tabs,
    els.detailContent.firstChild
  );

  const summaryPane = document.createElement("div");
  summaryPane.className = "detail-pane";
  summaryPane.dataset.detailPane = "summary";

  existingSections.forEach(section => {
    summaryPane.appendChild(section);
  });

  els.detailContent.appendChild(summaryPane);

  const monthlyPane = document.createElement("div");
  monthlyPane.className = "detail-pane";
  monthlyPane.dataset.detailPane = "monthly";
  monthlyPane.hidden = true;
  monthlyPane.innerHTML = `
    <section class="detail-section">
      <div class="detail-section-heading">
        <div>
          <div class="section-kicker">MONTHLY DETAIL</div>
          <h3>Son 13 Ay</h3>
        </div>
      </div>

      <p class="detail-help">
        NEG / POS / FLAT sayıları official BIST session kapanışlarının
        close-to-close yönünü gösterir. GAP, beklenen session ile
        canonical veride bulunan session arasındaki farktır.
      </p>

      <div class="detail-table-wrap">
        <table class="detail-data-table">
          <thead>
            <tr>
              <th>Ay</th>
              <th class="numeric">Momentum</th>
              <th class="numeric">FIP</th>
              <th class="numeric">NEG</th>
              <th class="numeric">POS</th>
              <th class="numeric">FLAT</th>
              <th class="numeric">Sessions</th>
              <th class="numeric">GAP</th>
            </tr>
          </thead>
          <tbody id="detailMonthlyBody"></tbody>
        </table>
      </div>
    </section>
  `;

  els.detailContent.appendChild(monthlyPane);

  const dailyPane = document.createElement("div");
  dailyPane.className = "detail-pane";
  dailyPane.dataset.detailPane = "daily";
  dailyPane.hidden = true;
  dailyPane.innerHTML = `
    <section class="detail-section">
      <div class="detail-section-heading">
        <div>
          <div class="section-kicker">CANONICAL DAILY DATA</div>
          <h3>Günlük Kapanış</h3>
        </div>
        <div class="detail-table-count" id="detailDailyCount">—</div>
      </div>

      <div class="detail-table-wrap daily-history-wrap">
        <table class="detail-data-table">
          <thead>
            <tr>
              <th>Tarih</th>
              <th class="numeric">Close</th>
              <th class="numeric">Return</th>
              <th class="numeric">Volume</th>
              <th>Durum</th>
            </tr>
          </thead>
          <tbody id="detailDailyBody"></tbody>
        </table>
      </div>
    </section>
  `;

  els.detailContent.appendChild(dailyPane);

  const sourcePane = document.createElement("div");
  sourcePane.className = "detail-pane";
  sourcePane.dataset.detailPane = "source";
  sourcePane.hidden = true;
  sourcePane.innerHTML = `
    <section class="detail-section data-source-section">
      <div class="section-kicker">DATA PIPELINE</div>
      <h3>Veri Kaynağı ve Güncelleme Mantığı</h3>

      <div id="detailSourceContent" class="data-source-content"></div>
    </section>
  `;

  els.detailContent.appendChild(sourcePane);

  els.detailMonthlyBody =
    document.getElementById("detailMonthlyBody");
  els.detailDailyBody =
    document.getElementById("detailDailyBody");
  els.detailDailyCount =
    document.getElementById("detailDailyCount");
  els.detailSourceContent =
    document.getElementById("detailSourceContent");

  tabs.addEventListener("click", event => {
    const button = event.target.closest("[data-detail-tab]");
    if (!button) return;
    setDetailTab(button.dataset.detailTab);
  });
}


function setDetailTab(value) {
  state.detailTab = value;

  document.querySelectorAll("[data-detail-tab]").forEach(button => {
    const active = button.dataset.detailTab === value;
    button.classList.toggle("active", active);
  });

  document.querySelectorAll("[data-detail-pane]").forEach(pane => {
    pane.hidden = pane.dataset.detailPane !== value;
  });
}


function renderMonthlyHistory(payload) {
  if (!els.detailMonthlyBody) return;

  const rows = [
    ...(payload.monthly_history ?? [])
  ].reverse();

  if (!rows.length) {
    els.detailMonthlyBody.innerHTML = `
      <tr>
        <td colspan="8" class="empty-row">
          Monthly history is not available.
        </td>
      </tr>
    `;
    return;
  }

  els.detailMonthlyBody.innerHTML = rows
    .map(row => `
      <tr class="${row.is_current ? "current-month-row" : ""}">
        <td>
          <strong>${escapeHtml(row.month ?? "—")}</strong>
          ${
            row.is_current
              ? '<span class="current-month-badge">CURRENT</span>'
              : ''
          }
        </td>
        <td class="numeric ${valueClass(row.momentum)}">
          ${formatRatioPercent(row.momentum)}
        </td>
        <td class="numeric fip-cell ${fipValueClass(row.fip)}">
          ${formatFip(row.fip)}
        </td>
        <td class="numeric month-negative">
          ${formatInteger(row.negative)}
        </td>
        <td class="numeric month-positive">
          ${formatInteger(row.positive)}
        </td>
        <td class="numeric">
          ${formatInteger(row.flat)}
        </td>
        <td class="numeric">
          ${formatInteger(row.sessions)}
          /
          ${formatInteger(row.expected_sessions)}
        </td>
        <td class="numeric ${sessionGapClass(row.session_gap)}">
          ${formatInteger(row.session_gap)}
        </td>
      </tr>
    `)
    .join("");
}


function dailyDirection(value) {
  const number = numericValue(value);

  if (number === null) {
    return {
      label: "—",
      cls: "daily-neutral"
    };
  }

  if (number > 0) {
    return {
      label: "POS",
      cls: "daily-positive"
    };
  }

  if (number < 0) {
    return {
      label: "NEG",
      cls: "daily-negative"
    };
  }

  return {
    label: "FLAT",
    cls: "daily-neutral"
  };
}


function renderDailyHistory(payload) {
  if (!els.detailDailyBody) return;

  const rows = [
    ...(payload.daily ?? [])
  ].reverse();

  els.detailDailyCount.textContent =
    `${rows.length} observations`;

  if (!rows.length) {
    els.detailDailyBody.innerHTML = `
      <tr>
        <td colspan="5" class="empty-row">
          Daily price history is not available.
        </td>
      </tr>
    `;
    return;
  }

  els.detailDailyBody.innerHTML = rows
    .map(row => {
      const direction = dailyDirection(row.return);

      return `
        <tr>
          <td>${escapeHtml(row.date ?? "—")}</td>
          <td class="numeric">
            ${formatClose(row.close)}
          </td>
          <td class="numeric ${valueClass(row.return)}">
            ${formatRatioPercent(row.return)}
          </td>
          <td class="numeric">
            ${
              numericValue(row.volume) === null
                ? "—"
                : Number(row.volume).toLocaleString("tr-TR")
            }
          </td>
          <td>
            <span class="daily-direction ${direction.cls}">
              ${direction.label}
            </span>
          </td>
        </tr>
      `;
    })
    .join("");
}


function renderDataSource(payload) {
  if (!els.detailSourceContent) return;

  const security = payload.security ?? {};
  const manifest = state.manifest ?? {};

  let generated = manifest.generated_at ?? "—";

  if (manifest.generated_at) {
    const dateValue = new Date(manifest.generated_at);

    if (!Number.isNaN(dateValue.getTime())) {
      generated = dateValue.toLocaleString("tr-TR");
    }
  }

  els.detailSourceContent.innerHTML = `
    <article class="source-card">
      <strong>Canonical kaynak</strong>
      <p>
        SQLite canonical OHLCV verisi sistemin source-of-truth katmanıdır.
        Web sayfası momentum, FIP, ranking veya VCP hesaplamaz.
      </p>
    </article>

    <article class="source-card">
      <strong>Evren ve takvim</strong>
      <p>
        Aktif BIST equity evreni official KAP / Borsa İstanbul kaynaklarıyla
        doğrulanır. Session bütünlüğü BIST trading calendar üzerinden kontrol edilir.
      </p>
    </article>

    <article class="source-card">
      <strong>Market data</strong>
      <p>
        Günlük OHLCV verisi guarded provider pipeline üzerinden canonical
        database'e alınır. Eksik veya şüpheli veri fail-closed kontrollerinden geçer.
      </p>
    </article>

    <article class="source-card">
      <strong>Publication</strong>
      <p>
        Validation sonrasında manifest.json, screener.json, screener.csv ve
        ticker detail JSON dosyaları staged publication gate üzerinden üretilir.
        GitHub Pages yalnız bu yayınlanmış dosyaları görselleştirir.
      </p>
    </article>

    <div class="source-run-grid">
      <div>
        <span>Security</span>
        <strong>${escapeHtml(security.ticker ?? "—")}</strong>
      </div>
      <div>
        <span>Data as of</span>
        <strong>${escapeHtml(manifest.as_of ?? "—")}</strong>
      </div>
      <div>
        <span>Manifest</span>
        <strong>${escapeHtml(manifest.status ?? "—")}</strong>
      </div>
      <div>
        <span>Generated</span>
        <strong>${escapeHtml(generated)}</strong>
      </div>
    </div>
  `;
}


function renderDetailExtras(payload) {
  renderMonthlyHistory(payload);
  renderDailyHistory(payload);
  renderDataSource(payload);
}


function populateDetail(payload) {
  const security = payload.security ?? {};
  const snapshot = payload.snapshot ?? {};

  els.detailTicker.textContent = security.ticker ?? "—";
  els.detailName.textContent = security.name ?? "—";
  els.detailStatus.textContent = payload.data_status ?? "OK";

  setMetric(
    els.detailMom252,
    snapshot.momentum_252,
    formatRatioPercent
  );
  setMetric(
    els.detailMom126,
    snapshot.momentum_126,
    formatRatioPercent
  );
  setMetric(
    els.detailMom63,
    snapshot.momentum_63,
    formatRatioPercent
  );
  setMetric(
    els.detailMom21,
    snapshot.momentum_21,
    formatRatioPercent
  );

  setMetric(els.detailFip252, snapshot.fip_252, formatFip, fipValueClass);
  setMetric(els.detailFip126, snapshot.fip_126, formatFip, fipValueClass);
  setMetric(els.detailFip63, snapshot.fip_63, formatFip, fipValueClass);
  setMetric(els.detailFip21, snapshot.fip_21, formatFip, fipValueClass);

  setMetric(
    els.detailAtr,
    snapshot.atr14_percent,
    formatAtr
  );
  setMetric(
    els.detailDeltaMom,
    snapshot.delta_momentum_21_63,
    formatRatioPercent
  );
  setMetric(els.detailDeltaFip, snapshot.delta_fip_21_63, formatFip, fipValueClass);

  els.detailFirstTrade.textContent =
    security.first_trade_date ?? "—";

  els.detailSector.textContent =
    security.sector ?? "—";

  els.detailIndustry.textContent =
    security.industry ?? "—";

  renderPriceChart(payload.daily);
  renderDetailExtras(payload);
  setDetailTab("summary");
}

async function openDetail(ticker) {
  els.detailBackdrop.hidden = false;
  els.detailDrawer.classList.add("open");
  els.detailDrawer.setAttribute("aria-hidden", "false");
  document.body.classList.add("drawer-open");

  els.detailTicker.textContent = ticker;
  els.detailName.textContent = "Loading…";

  els.detailLoading.hidden = false;
  els.detailContent.hidden = true;
  els.detailError.hidden = true;

  try {
    const response = await fetch(
      `./data/details/${encodeURIComponent(ticker)}.json`,
      { cache: "no-store" }
    );

    if (!response.ok) {
      throw new Error(
        `${ticker} detail returned HTTP ${response.status}`
      );
    }

    const payload = await response.json();

    populateDetail(payload);

    els.detailLoading.hidden = true;
    els.detailContent.hidden = false;
  } catch (error) {
    console.error(error);

    els.detailLoading.hidden = true;
    els.detailContent.hidden = true;
    els.detailError.hidden = false;
    els.detailError.textContent =
      `Security detail could not be loaded: ${error.message}`;
  }
}

function closeDetail() {
  els.detailDrawer.classList.remove("open");
  els.detailDrawer.setAttribute("aria-hidden", "true");
  els.detailBackdrop.hidden = true;
  document.body.classList.remove("drawer-open");
}

function bindEvents() {
  if (els.csvDownload) {
    els.csvDownload.addEventListener("click", () => {
      downloadPublishedFile(
        state.manifest?.files?.screener_csv
        || "screener.csv"
      );
    });
  }

  if (els.jsonDownload) {
    els.jsonDownload.addEventListener("click", () => {
      downloadPublishedFile(
        state.manifest?.files?.screener
        || "screener.json"
      );
    });
  }

  if (els.metricGuideToggle && els.metricGuidePanel) {
    els.metricGuideToggle.addEventListener("click", () => {
      const opening = els.metricGuidePanel.hidden;

      els.metricGuidePanel.hidden = !opening;
      els.metricGuideToggle.setAttribute(
        "aria-expanded",
        opening ? "true" : "false"
      );

      els.metricGuideToggle.textContent =
        opening
          ? "× Metrikleri Kapat"
          : "? Metrikleri Açıkla";
    });
  }

  els.pageViewButtons.forEach(button => {
    button.addEventListener("click", () => {
      setPageView(
        button.dataset.pageView || "screener"
      );
    });
  });

  els.strategyModeButtons.forEach(button => {
    button.addEventListener("click", () => {
      state.strategyMode =
        button.dataset.strategyMode || "strong";

      setActiveButtons(
        els.strategyModeButtons,
        "strategyMode",
        state.strategyMode
      );

      renderStrategy();
    });
  });

  els.strategyUniverseButtons.forEach(button => {
    button.addEventListener("click", () => {
      state.strategyUniverse =
        button.dataset.strategyUniverse || "all";

      setActiveButtons(
        els.strategyUniverseButtons,
        "strategyUniverse",
        state.strategyUniverse
      );

      renderStrategy();
    });
  });

  els.strategyLimitButtons.forEach(button => {
    button.addEventListener("click", () => {
      state.strategyLimit =
        Number(button.dataset.strategyLimit) || 10;

      setActiveButtons(
        els.strategyLimitButtons,
        "strategyLimit",
        state.strategyLimit
      );

      renderStrategy();
    });
  });

  els.strategyBody.addEventListener("click", event => {
    const button = event.target.closest(
      ".strategy-ticker-button"
    );

    if (!button) return;

    openDetail(button.dataset.ticker);
  });

  els.searchInput.addEventListener("input", event => {
    state.search = event.target.value;
    renderRows();
  });

  els.sectorFilter.addEventListener("change", event => {
    state.sector = event.target.value || "all";
    renderRows();
  });

  document.querySelectorAll("th.sortable").forEach(th => {
    th.addEventListener("click", () => {
      const key = th.dataset.key;

      if (state.sortKey === key) {
        state.sortDirection =
          state.sortDirection === "asc" ? "desc" : "asc";
      } else {
        state.sortKey = key;
        state.sortDirection =
          key === "ticker" || key === "name" ? "asc" : "desc";
      }

      renderRows();
    });
  });

  els.body.addEventListener("click", event => {
    const button = event.target.closest(".ticker-button");

    if (!button) return;

    openDetail(button.dataset.ticker);
  });

  els.detailClose.addEventListener("click", closeDetail);
  els.detailBackdrop.addEventListener("click", closeDetail);

  document.addEventListener("keydown", event => {
    if (
      event.key === "Escape" &&
      els.detailDrawer.classList.contains("open")
    ) {
      closeDetail();
    }
  });
}

function showError(error) {
  console.error(error);

  els.statusBadge.textContent = "ERROR";
  els.statusBadge.className = "status-badge fail";

  els.errorBox.hidden = false;
  els.errorBox.textContent =
    `Dashboard data could not be loaded: ${error.message}`;

  els.body.innerHTML = `
    <tr>
      <td colspan="17" class="empty-row">
        Data could not be loaded.
      </td>
    </tr>
  `;
}

async function loadDashboard() {
  try {
    const [manifestResponse, screenerResponse] = await Promise.all([
      fetch("./data/manifest.json", { cache: "no-store" }),
      fetch("./data/screener.json", { cache: "no-store" })
    ]);

    if (!manifestResponse.ok) {
      throw new Error(
        `manifest.json returned HTTP ${manifestResponse.status}`
      );
    }

    if (!screenerResponse.ok) {
      throw new Error(
        `screener.json returned HTTP ${screenerResponse.status}`
      );
    }

    const [manifest, screener] = await Promise.all([
      manifestResponse.json(),
      screenerResponse.json()
    ]);

    if (!Array.isArray(screener)) {
      throw new Error("screener.json is not an array");
    }

    state.manifest = manifest;
    state.publicationRows = screener;

    // Main screener intentionally contains only calculation-ready securities.
    state.rows = screener.filter(
      row => row.data_status === "OK"
    );

    populateSectorFilter();
    renderManifest();
    renderRows();
    renderStrategy();
  } catch (error) {
    showError(error);
  }
}

initializeDetailTabs();
bindEvents();
loadDashboard();


function setTradeTypeFilter(value) {
  state.tradeType = value;

  els.tradeFilterButtons.forEach(button => {
    const active = button.dataset.tradeFilter === value;

    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });

  renderRows();
}

els.tradeFilterButtons.forEach(button => {
  button.addEventListener("click", () => {
    setTradeTypeFilter(button.dataset.tradeFilter || "all");
  });
});
