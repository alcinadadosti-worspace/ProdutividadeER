/**
 * iaf.js — Tela de Análise IAF detalhada
 */

async function renderIaf() {
  const page = document.getElementById("page-iaf");
  page.innerHTML = `
    <div class="page-header">
      <div class="page-title">Análise IAF</div>
      <div class="page-subtitle">Indicador de Ativação de Franquia — Cabelos e Make</div>
    </div>
    <div class="skeleton" style="height:400px;border-radius:10px"></div>
  `;
  lucide.createIcons();

  try {
    const params = new URLSearchParams(window.APP_FILTROS || {});
    const res = await fetch("/api/iaf?" + params.toString());
    const d = await res.json();
    if (!res.ok) throw new Error(d.erro || "Erro");

    const totalIaf = (d.iaf_cabelos.total || 0) + (d.iaf_make.total || 0);
    const pctIafTotal = d.total_geral ? (totalIaf / d.total_geral * 100) : 0;

    page.innerHTML = `
      <div class="page-header">
        <div class="page-title">Análise IAF</div>
        <div class="page-subtitle">Indicador de Ativação de Franquia — Cabelos e Make</div>
      </div>

      <!-- Resumo IAF -->
      <div class="iaf-summary-grid">
        <div class="iaf-card cabelos">
          <div class="iaf-card-title">IAF Cabelos</div>
          <div class="iaf-card-value">${d.iaf_cabelos.pct_total.toFixed(1)}%</div>
          <div class="iaf-card-sub">${fmtBRL(d.iaf_cabelos.total)} · ${fmtNum(d.iaf_cabelos.qtd_registros)} registros</div>
        </div>
        <div class="iaf-card make">
          <div class="iaf-card-title">IAF Make</div>
          <div class="iaf-card-value">${d.iaf_make.pct_total.toFixed(1)}%</div>
          <div class="iaf-card-sub">${fmtBRL(d.iaf_make.total)} · ${fmtNum(d.iaf_make.qtd_registros)} registros</div>
        </div>
        <div class="iaf-card geral">
          <div class="iaf-card-title">Geral (não IAF)</div>
          <div class="iaf-card-value">${d.geral.pct_total.toFixed(1)}%</div>
          <div class="iaf-card-sub">${fmtBRL(d.geral.total)} · ${fmtNum(d.geral.qtd_registros)} registros</div>
        </div>
      </div>

      <!-- Métodos de match -->
      <div class="section-title mb-12">Método de Classificação</div>
      <div class="match-grid mb-24">
        <div class="match-item">
          <div class="match-count text-green">${fmtNum(d.metodos_match.sku || 0)}</div>
          <div class="match-label">Por SKU</div>
        </div>
        <div class="match-item">
          <div class="match-count text-blue">${fmtNum(d.metodos_match.fallback_siage || 0)}</div>
          <div class="match-label">Fallback Siàge</div>
        </div>
        <div class="match-item">
          <div class="match-count" style="color:var(--accent-purple)">${fmtNum(d.metodos_match.fallback_make || 0)}</div>
          <div class="match-label">Fallback Make</div>
        </div>
        <div class="match-item">
          <div class="match-count text-muted">${fmtNum(d.metodos_match.nenhum || 0)}</div>
          <div class="match-label">Sem match</div>
        </div>
      </div>

      <!-- Charts IAF Cabelos -->
      <div class="section-title mb-12">IAF Cabelos — Detalhamento</div>
      <div class="charts-grid mb-24">
        <div class="chart-card">
          <div class="chart-title">Evolução por Ciclo</div>
          <div class="chart-container"><canvas id="chart-cabelos-ciclo"></canvas></div>
        </div>
        <div class="chart-card">
          <div class="chart-title">Top Vendedores</div>
          <div class="chart-container"><canvas id="chart-cabelos-vend"></canvas></div>
        </div>
      </div>

      <div class="table-card mb-24">
        <div class="table-toolbar">
          <span class="table-toolbar-title">Top Produtos — IAF Cabelos</span>
        </div>
        <div class="table-wrapper">
          ${_tabelaTopProdutos(d.iaf_cabelos.top_produtos)}
        </div>
      </div>

      <!-- Charts IAF Make -->
      <div class="section-title mb-12">IAF Make — Detalhamento</div>
      <div class="charts-grid mb-24">
        <div class="chart-card">
          <div class="chart-title">Evolução por Ciclo</div>
          <div class="chart-container"><canvas id="chart-make-ciclo"></canvas></div>
        </div>
        <div class="chart-card">
          <div class="chart-title">Top Vendedores</div>
          <div class="chart-container"><canvas id="chart-make-vend"></canvas></div>
        </div>
      </div>

      <div class="table-card">
        <div class="table-toolbar">
          <span class="table-toolbar-title">Top Produtos — IAF Make</span>
        </div>
        <div class="table-wrapper">
          ${_tabelaTopProdutos(d.iaf_make.top_produtos)}
        </div>
      </div>
    `;

    lucide.createIcons();

  } catch (err) {
    console.error("[IAF] Erro ao carregar:", err);
    page.innerHTML = `<div class="empty-state"><p>${err.message}</p></div>`;
    lucide.createIcons();
    return;
  }

  try {
    _renderGraficosIaf(d);
  } catch (err) {
    console.error("[IAF] Erro ao renderizar gráficos:", err);
  }
}

function _renderGraficosIaf(d) {
  // Cabelos ciclo
  if (d.iaf_cabelos.por_ciclo?.length) {
    criarOuAtualizar("chart-cabelos-ciclo", "bar", {
      labels: d.iaf_cabelos.por_ciclo.map(x => x.ciclo),
      datasets: [{
        data: d.iaf_cabelos.por_ciclo.map(x => x.total),
        backgroundColor: "rgba(108,158,255,0.55)",
        borderColor: CHART_COLORS.blue,
        borderWidth: 1,
        borderRadius: 3,
      }],
    }, barOptions(false, { plugins: { tooltip: { ...TOOLTIP_STYLE, callbacks: { label: ctx => " " + fmtBRL(ctx.raw) } } } }));
  }

  // Cabelos vendedores
  if (d.iaf_cabelos.top_vendedores?.length) {
    const tv = d.iaf_cabelos.top_vendedores.slice(0, 8);
    criarOuAtualizar("chart-cabelos-vend", "bar", {
      labels: tv.map(x => x.nome.split(" ")[0]),
      datasets: [{
        data: tv.map(x => x.total),
        backgroundColor: "rgba(108,158,255,0.55)",
        borderColor: CHART_COLORS.blue,
        borderWidth: 1,
        borderRadius: 3,
      }],
    }, barOptions(true, { plugins: { tooltip: { ...TOOLTIP_STYLE, callbacks: { label: ctx => " " + fmtBRL(ctx.raw) } } } }));
  }

  // Make ciclo
  if (d.iaf_make.por_ciclo?.length) {
    criarOuAtualizar("chart-make-ciclo", "bar", {
      labels: d.iaf_make.por_ciclo.map(x => x.ciclo),
      datasets: [{
        data: d.iaf_make.por_ciclo.map(x => x.total),
        backgroundColor: "rgba(167,139,250,0.55)",
        borderColor: CHART_COLORS.purple,
        borderWidth: 1,
        borderRadius: 3,
      }],
    }, barOptions(false, { plugins: { tooltip: { ...TOOLTIP_STYLE, callbacks: { label: ctx => " " + fmtBRL(ctx.raw) } } } }));
  }

  // Make vendedores
  if (d.iaf_make.top_vendedores?.length) {
    const tv = d.iaf_make.top_vendedores.slice(0, 8);
    criarOuAtualizar("chart-make-vend", "bar", {
      labels: tv.map(x => x.nome.split(" ")[0]),
      datasets: [{
        data: tv.map(x => x.total),
        backgroundColor: "rgba(167,139,250,0.55)",
        borderColor: CHART_COLORS.purple,
        borderWidth: 1,
        borderRadius: 3,
      }],
    }, barOptions(true, { plugins: { tooltip: { ...TOOLTIP_STYLE, callbacks: { label: ctx => " " + fmtBRL(ctx.raw) } } } }));
  }
}

function _tabelaTopProdutos(lista) {
  if (!lista || !lista.length) {
    return '<div class="empty-state" style="padding:24px"><p>Nenhum produto.</p></div>';
  }
  const rows = lista.map(p => `
    <tr>
      <td class="mono secondary">${p.sku}</td>
      <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis">${p.nome}</td>
      <td class="mono" style="text-align:right">${fmtBRL(p.total)}</td>
      <td class="mono" style="text-align:right">${fmtNum(p.quantidade)}</td>
    </tr>
  `).join("");

  return `
    <table>
      <thead>
        <tr>
          <th>SKU</th><th>Produto</th>
          <th style="text-align:right">Faturamento</th>
          <th style="text-align:right">Qtde</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}
