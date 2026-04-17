/**
 * comparativo.js — Comparativo de faturamento entre ciclos
 */

let _compData = null;
let _compCicloA = null;
let _compCicloB = null;
let _compView = "vendedor"; // "vendedor" | "categoria"

async function renderComparativo() {
  const page = document.getElementById("page-comparativo");
  page.innerHTML = `
    <div class="page-header">
      <div class="page-title">Comparativo de Ciclos</div>
      <div class="page-subtitle">Crescimento e variação entre ciclos por vendedor e categoria</div>
    </div>
    <div id="comp-body">
      <div class="skeleton" style="height:400px;border-radius:12px"></div>
    </div>
  `;

  try {
    // Envia todos os filtros globais exceto ciclo (ciclo é controlado pela própria UI)
    const filtros = Object.fromEntries(
      Object.entries(window.APP_FILTROS || {}).filter(([k]) => k !== "ciclo")
    );
    const params = new URLSearchParams(filtros);
    const res = await fetch("/api/comparativo?" + params.toString());
    const data = await res.json();
    if (!res.ok) throw new Error(data.erro || "Erro");
    _compData = data;

    if (!data.ciclos.length) {
      document.getElementById("comp-body").innerHTML =
        '<div class="empty-state"><p>Importe dados com pelo menos um ciclo.</p></div>';
      return;
    }

    // Defaults: últimos dois ciclos
    const ciclos = data.ciclos;
    _compCicloA = ciclos.length >= 2 ? ciclos[ciclos.length - 2] : ciclos[0];
    _compCicloB = ciclos[ciclos.length - 1];

    _renderComparativoUI();
  } catch (err) {
    document.getElementById("comp-body").innerHTML =
      `<div class="empty-state"><p>${err.message}</p></div>`;
  }
}

function _renderComparativoUI() {
  const { ciclos } = _compData;

  document.getElementById("comp-body").innerHTML = `
    <!-- Controles -->
    <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin-bottom:20px">
      <div style="display:flex;align-items:center;gap:8px">
        <span style="font-size:12px;color:var(--text-tertiary)">De:</span>
        <select id="comp-ciclo-a" class="search-input" style="width:auto;padding:6px 10px">
          ${ciclos.map(c => `<option value="${c}" ${c === _compCicloA ? "selected" : ""}>${c}</option>`).join("")}
        </select>
        <span style="font-size:12px;color:var(--text-tertiary)">Para:</span>
        <select id="comp-ciclo-b" class="search-input" style="width:auto;padding:6px 10px">
          ${ciclos.map(c => `<option value="${c}" ${c === _compCicloB ? "selected" : ""}>${c}</option>`).join("")}
        </select>
      </div>
      <div style="display:flex;gap:4px">
        <button id="comp-btn-vendedor" class="filter-chip ${_compView === "vendedor" ? "active" : ""}"
                onclick="_compSetView('vendedor')">Por Vendedor</button>
        <button id="comp-btn-categoria" class="filter-chip ${_compView === "categoria" ? "active" : ""}"
                onclick="_compSetView('categoria')">Por Categoria</button>
      </div>
      <div style="margin-left:auto">
        <button class="btn-ghost btn-sm" onclick="_exportarComparativo()">
          <i data-lucide="download"></i> Exportar CSV
        </button>
      </div>
    </div>

    <!-- Sumário -->
    <div id="comp-summary" class="kpi-grid" style="margin-bottom:20px"></div>

    <!-- Tabela -->
    <div class="table-card">
      <div class="table-wrapper" id="comp-table-wrap"></div>
    </div>
  `;

  lucide.createIcons();

  document.getElementById("comp-ciclo-a").addEventListener("change", e => {
    _compCicloA = e.target.value;
    _renderCompTabela();
  });
  document.getElementById("comp-ciclo-b").addEventListener("change", e => {
    _compCicloB = e.target.value;
    _renderCompTabela();
  });

  _renderCompTabela();
}

function _compSetView(view) {
  _compView = view;
  document.getElementById("comp-btn-vendedor").classList.toggle("active", view === "vendedor");
  document.getElementById("comp-btn-categoria").classList.toggle("active", view === "categoria");
  _renderCompTabela();
}

function _renderCompTabela() {
  const lista = _compView === "vendedor" ? _compData.por_vendedor : _compData.por_categoria;
  const labelKey = _compView === "vendedor" ? "nome" : "categoria";

  const rows = lista.map(item => {
    const a = item.por_ciclo[_compCicloA] || 0;
    const b = item.por_ciclo[_compCicloB] || 0;
    const diff = b - a;
    const pct = a > 0 ? ((b - a) / a * 100) : (b > 0 ? 100 : 0);
    return { label: item[labelKey], codigo: item.codigo || "", a, b, diff, pct };
  }).filter(r => r.a > 0 || r.b > 0)
    .sort((x, y) => Math.abs(y.diff) - Math.abs(x.diff));

  // Sumário
  const totalA = rows.reduce((s, r) => s + r.a, 0);
  const totalB = rows.reduce((s, r) => s + r.b, 0);
  const totalDiff = totalB - totalA;
  const totalPct = totalA > 0 ? ((totalB - totalA) / totalA * 100) : 0;
  const cresceram = rows.filter(r => r.pct > 0).length;
  const cairam = rows.filter(r => r.pct < 0).length;

  document.getElementById("comp-summary").innerHTML = `
    <div class="kpi-card">
      <div class="kpi-header"><span class="kpi-label">${_compCicloA}</span><div class="kpi-icon blue"><i data-lucide="calendar"></i></div></div>
      <div class="kpi-value">${fmtBRL(totalA)}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-header"><span class="kpi-label">${_compCicloB}</span><div class="kpi-icon ${totalDiff >= 0 ? "green" : "orange"}"><i data-lucide="calendar"></i></div></div>
      <div class="kpi-value">${fmtBRL(totalB)}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-header"><span class="kpi-label">Variação</span><div class="kpi-icon ${totalDiff >= 0 ? "green" : "orange"}"><i data-lucide="${totalDiff >= 0 ? "trending-up" : "trending-down"}"></i></div></div>
      <div class="kpi-value" style="color:${totalDiff >= 0 ? "var(--accent-green)" : "var(--accent-orange)"}">${totalDiff >= 0 ? "+" : ""}${totalPct.toFixed(1)}%</div>
      <div class="kpi-sub">${totalDiff >= 0 ? "+" : ""}${fmtBRL(totalDiff)}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-header"><span class="kpi-label">Cresceram / Caíram</span><div class="kpi-icon purple"><i data-lucide="bar-chart-2"></i></div></div>
      <div class="kpi-value"><span style="color:var(--accent-green)">${cresceram}</span> / <span style="color:var(--accent-orange)">${cairam}</span></div>
    </div>
  `;
  lucide.createIcons();

  if (!rows.length) {
    document.getElementById("comp-table-wrap").innerHTML =
      `<div class="empty-state"><p>Selecione dois ciclos diferentes.</p></div>`;
    return;
  }

  const tbody = rows.map(r => {
    const seta = r.pct > 0 ? "↑" : r.pct < 0 ? "↓" : "—";
    const cor = r.pct > 0 ? "var(--accent-green)" : r.pct < 0 ? "var(--accent-orange)" : "var(--text-tertiary)";
    const barMax = Math.max(...rows.map(x => Math.max(x.a, x.b)));
    const wA = barMax ? (r.a / barMax * 100).toFixed(1) : 0;
    const wB = barMax ? (r.b / barMax * 100).toFixed(1) : 0;
    const rowClick = _compView === "vendedor" && r.codigo
      ? `style="cursor:pointer" onclick="abrirDrawerVendedor('${r.codigo}')"` : "";
    return `
      <tr ${rowClick}>
        <td style="font-size:13px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${r.label}</td>
        <td style="text-align:right" class="mono">${fmtBRL(r.a)}</td>
        <td style="text-align:right" class="mono">${fmtBRL(r.b)}</td>
        <td style="min-width:140px;padding:8px 12px">
          <div style="display:flex;flex-direction:column;gap:3px">
            <div style="display:flex;align-items:center;gap:4px">
              <div style="font-size:9px;color:var(--text-tertiary);width:14px">${_compCicloA.split("/")[0]}</div>
              <div style="flex:1;background:var(--bg-tertiary);border-radius:2px;height:5px">
                <div style="width:${wA}%;height:100%;background:var(--accent-blue);border-radius:2px;opacity:0.6"></div>
              </div>
            </div>
            <div style="display:flex;align-items:center;gap:4px">
              <div style="font-size:9px;color:var(--text-tertiary);width:14px">${_compCicloB.split("/")[0]}</div>
              <div style="flex:1;background:var(--bg-tertiary);border-radius:2px;height:5px">
                <div style="width:${wB}%;height:100%;background:${cor};border-radius:2px;opacity:0.8"></div>
              </div>
            </div>
          </div>
        </td>
        <td style="text-align:right" class="mono">${r.diff >= 0 ? "+" : ""}${fmtBRL(r.diff)}</td>
        <td style="text-align:right;font-weight:600;color:${cor};font-family:monospace">
          ${seta} ${Math.abs(r.pct).toFixed(1)}%
        </td>
      </tr>`;
  }).join("");

  document.getElementById("comp-table-wrap").innerHTML = `
    <table>
      <thead>
        <tr>
          <th>${_compView === "vendedor" ? "Vendedor" : "Categoria"}</th>
          <th style="text-align:right">${_compCicloA}</th>
          <th style="text-align:right">${_compCicloB}</th>
          <th>Comparativo</th>
          <th style="text-align:right">Variação R$</th>
          <th style="text-align:right">Variação %</th>
        </tr>
      </thead>
      <tbody>${tbody}</tbody>
    </table>
  `;
}

function _exportarComparativo() {
  const lista = _compView === "vendedor" ? _compData.por_vendedor : _compData.por_categoria;
  const labelKey = _compView === "vendedor" ? "nome" : "categoria";
  const rows = lista.map(item => {
    const a = item.por_ciclo[_compCicloA] || 0;
    const b = item.por_ciclo[_compCicloB] || 0;
    const pct = a > 0 ? ((b - a) / a * 100) : (b > 0 ? 100 : 0);
    return [item[labelKey], a.toFixed(2), b.toFixed(2), (b - a).toFixed(2), pct.toFixed(1) + "%"];
  });
  const header = [_compView === "vendedor" ? "Vendedor" : "Categoria", _compCicloA, _compCicloB, "Variação R$", "Variação %"];
  _downloadCSV([header, ...rows], `comparativo_${_compCicloA}_vs_${_compCicloB}.csv`);
}
