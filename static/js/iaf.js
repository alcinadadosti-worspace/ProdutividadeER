/**
 * iaf.js — Tela de Análise IAF detalhada
 */

let _iafData = null;

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
    _iafData = await res.json();
    if (!res.ok) throw new Error(_iafData.erro || "Erro");
    const d = _iafData;

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

      <!-- Penetração Make por Vendedor -->
      <div class="section-title mb-12" style="margin-top:32px">Penetração Make por Vendedor</div>
      <div class="table-card">
        <div class="table-toolbar">
          <span class="table-toolbar-title">Revendedoras que compraram Make ÷ Total revendedoras compradoras no ciclo</span>
        </div>
        <div class="table-wrapper">
          ${_tabelaPenetracaoMake(d.penetracao_make_por_vendedor)}
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
    _renderGraficosIaf(_iafData);
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
      labels: tv.map(x => _abreviarNome(x.nome)),
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
      labels: tv.map(x => _abreviarNome(x.nome)),
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

function _tabelaPenetracaoMake(lista) {
  if (!lista || !lista.length) {
    return '<div class="empty-state" style="padding:24px"><p>Nenhum dado disponível.</p></div>';
  }
  const rows = lista.map(r => {
    const pct = r.pct_penetracao.toFixed(1);
    const barColor = r.pct_penetracao >= 50 ? "var(--accent-purple)" : r.pct_penetracao >= 25 ? "var(--accent-blue)" : "var(--text-muted)";
    return `
      <tr>
        <td>${r.nome}</td>
        <td class="mono" style="text-align:right">${fmtNum(r.rev_make)}</td>
        <td class="mono" style="text-align:right">${fmtNum(r.rev_compradoras)}</td>
        <td style="min-width:140px">
          <div style="display:flex;align-items:center;gap:8px">
            <div style="flex:1;height:6px;background:var(--border);border-radius:3px;overflow:hidden">
              <div style="width:${Math.min(r.pct_penetracao,100)}%;height:100%;background:${barColor};border-radius:3px"></div>
            </div>
            <span class="mono" style="color:${barColor};font-weight:600;min-width:44px;text-align:right">${pct}%</span>
          </div>
        </td>
      </tr>
    `;
  }).join("");

  return `
    <table>
      <thead>
        <tr>
          <th>Vendedor</th>
          <th style="text-align:right">Rev. c/ Make</th>
          <th style="text-align:right">Total Compradoras</th>
          <th>Penetração Make</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
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
