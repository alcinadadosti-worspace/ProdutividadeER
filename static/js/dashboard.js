/**
 * dashboard.js — Dashboard principal com KPIs e gráficos
 */

let _dashData = null;

async function renderDashboard() {
  const page = document.getElementById("page-dashboard");
  page.innerHTML = _skeletonDashboard();
  lucide.createIcons();

  try {
    const params = new URLSearchParams(window.APP_FILTROS || {});
    const res = await fetch("/api/dashboard?" + params.toString());
    _dashData = await res.json();

    if (!res.ok) throw new Error(_dashData.erro || "Erro ao carregar dashboard");

    page.innerHTML = _templateDashboard(_dashData);
    lucide.createIcons();
    _atualizarFiltrosBar(_dashData.filtros);
  } catch (err) {
    console.error("[Dashboard] Erro ao carregar:", err);
    page.innerHTML = `<div class="empty-state"><i data-lucide="alert-circle"></i><p>${err.message}</p></div>`;
    lucide.createIcons();
    return;
  }

  // Gráficos em try-catch separado: erros aqui não apagam KPIs já renderizados
  try {
    _renderGraficos(_dashData);
  } catch (err) {
    console.error("[Dashboard] Erro ao renderizar gráficos:", err);
  }
}

function _templateDashboard(d) {
  const kpi = d.kpis;
  const periodo = d.periodo.inicio
    ? `${_fmtData(d.periodo.inicio)} — ${_fmtData(d.periodo.fim)}`
    : "—";

  return `
    <div class="page-header">
      <div class="flex-row" style="justify-content:space-between;align-items:flex-start">
        <div>
          <div class="page-title">Dashboard</div>
          <div class="page-subtitle">
            ${d.arquivo_nome || "Sem arquivo"} &nbsp;·&nbsp; ${periodo} &nbsp;·&nbsp; ${fmtNum(d.total_registros)} registros
          </div>
        </div>
      </div>
    </div>

    <!-- KPIs -->
    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-header">
          <span class="kpi-label">Total Faturado</span>
          <div class="kpi-icon blue"><i data-lucide="trending-up"></i></div>
        </div>
        <div class="kpi-value">${fmtBRL(kpi.total_faturado)}</div>
        <div class="kpi-sub">Soma de todos os pedidos</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-header">
          <span class="kpi-label">Total de Pedidos</span>
          <div class="kpi-icon green"><i data-lucide="shopping-bag"></i></div>
        </div>
        <div class="kpi-value">${fmtNum(kpi.total_pedidos)}</div>
        <div class="kpi-sub">Pedidos únicos</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-header">
          <span class="kpi-label">Ticket Médio</span>
          <div class="kpi-icon purple"><i data-lucide="receipt"></i></div>
        </div>
        <div class="kpi-value">${fmtBRL(kpi.ticket_medio)}</div>
        <div class="kpi-sub">Por pedido</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-header">
          <span class="kpi-label">Itens Vendidos</span>
          <div class="kpi-icon orange"><i data-lucide="package"></i></div>
        </div>
        <div class="kpi-value">${fmtNum(kpi.total_itens)}</div>
        <div class="kpi-sub">Quantidade total</div>
      </div>
    </div>

    <!-- Charts row 1 -->
    <div class="charts-grid mb-12">
      <div class="chart-card">
        <div class="chart-title">Faturamento por Ciclo</div>
        <div class="chart-container"><canvas id="chart-ciclo"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">Distribuição IAF</div>
        <div class="chart-container"><canvas id="chart-iaf"></canvas></div>
      </div>
    </div>

    <!-- Charts row 2 -->
    <div class="charts-grid mb-12">
      <div class="chart-card full-width">
        <div class="chart-title">Evolução Diária de Faturamento</div>
        <div class="chart-container tall"><canvas id="chart-diario"></canvas></div>
      </div>
    </div>

    <!-- Charts row 3 -->
    <div class="charts-grid triple mb-12">
      <div class="chart-card">
        <div class="chart-title">Faturamento por Unidade</div>
        <div class="chart-container"><canvas id="chart-unidade"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">Formas de Pagamento</div>
        <div class="chart-container"><canvas id="chart-pagamento"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">Top 10 Vendedores</div>
        <div class="chart-container"><canvas id="chart-vendedores"></canvas></div>
      </div>
    </div>
  `;
}

function _renderGraficos(d) {
  // Ciclo
  if (d.por_ciclo.length) {
    criarOuAtualizar("chart-ciclo", "bar", {
      labels: d.por_ciclo.map(x => x.ciclo),
      datasets: [{
        data: d.por_ciclo.map(x => x.total),
        backgroundColor: "rgba(108,158,255,0.6)",
        borderColor: CHART_COLORS.blue,
        borderWidth: 1,
        borderRadius: 4,
      }],
    }, barOptions(false, { plugins: { tooltip: { ...TOOLTIP_STYLE, callbacks: { label: ctx => " " + fmtBRL(ctx.raw) } } } }));
  }

  // IAF donut
  if (d.por_iaf.length) {
    const iafColors = {
      "IAF Cabelos": CHART_COLORS.blue,
      "IAF Make":    CHART_COLORS.purple,
      "Geral":       "#3A3A3E",
    };
    criarOuAtualizar("chart-iaf", "doughnut", {
      labels: d.por_iaf.map(x => x.classificacao),
      datasets: [{
        data: d.por_iaf.map(x => x.total),
        backgroundColor: d.por_iaf.map(x => iafColors[x.classificacao] || CHART_COLORS.orange),
        borderWidth: 0,
        hoverOffset: 4,
      }],
    }, donutOptions({ plugins: { tooltip: { ...TOOLTIP_STYLE, callbacks: { label: ctx => " " + fmtBRL(ctx.raw) } } } }));
  }

  // Evolução diária (line)
  if (d.evolucao_diaria.length) {
    criarOuAtualizar("chart-diario", "line", {
      labels: d.evolucao_diaria.map(x => x.data),
      datasets: [{
        data: d.evolucao_diaria.map(x => x.total),
        borderColor: CHART_COLORS.blue,
        backgroundColor: "rgba(108,158,255,0.08)",
        borderWidth: 2,
        fill: true,
        tension: 0.3,
        pointRadius: d.evolucao_diaria.length > 60 ? 0 : 3,
        pointHoverRadius: 5,
      }],
    }, lineOptions({ plugins: { tooltip: { ...TOOLTIP_STYLE, callbacks: { label: ctx => " " + fmtBRL(ctx.raw) } } } }));
  }

  // Unidade
  if (d.por_unidade.length) {
    criarOuAtualizar("chart-unidade", "bar", {
      labels: d.por_unidade.map(x => x.unidade),
      datasets: [{
        data: d.por_unidade.map(x => x.total),
        backgroundColor: [CHART_COLORS.green, CHART_COLORS.orange, CHART_COLORS.teal],
        borderWidth: 0,
        borderRadius: 4,
      }],
    }, barOptions(false, { plugins: { tooltip: { ...TOOLTIP_STYLE, callbacks: { label: ctx => " " + fmtBRL(ctx.raw) } } } }));
  }

  // Pagamento
  if (d.por_pagamento.length) {
    const top = d.por_pagamento.slice(0, 8);
    criarOuAtualizar("chart-pagamento", "doughnut", {
      labels: top.map(x => x.pagamento),
      datasets: [{
        data: top.map(x => x.total),
        backgroundColor: PALETTE.slice(0, top.length),
        borderWidth: 0,
        hoverOffset: 4,
      }],
    }, donutOptions());
  }

  // Top vendedores (horizontal bar)
  if (d.top_vendedores.length) {
    criarOuAtualizar("chart-vendedores", "bar", {
      labels: d.top_vendedores.map(x => _abreviarNome(x.nome)),
      datasets: [{
        data: d.top_vendedores.map(x => x.total),
        backgroundColor: "rgba(167,139,250,0.6)",
        borderColor: CHART_COLORS.purple,
        borderWidth: 1,
        borderRadius: 4,
      }],
    }, barOptions(true, { plugins: { tooltip: { ...TOOLTIP_STYLE, callbacks: { label: ctx => " " + fmtBRL(ctx.raw) } } } }));
  }
}

function _atualizarFiltrosBar(filtros) {
  if (!filtros) return;

  // Ciclos
  const grpCiclo = document.getElementById("filtros-ciclo");
  if (grpCiclo) {
    grpCiclo.innerHTML = filtros.ciclos.map(c =>
      `<button class="filter-chip ${window.APP_FILTROS?.ciclo === c ? "active" : ""}" data-tipo="ciclo" data-valor="${c}">${c}</button>`
    ).join("");
  }

  // Unidades
  const grpUnidade = document.getElementById("filtros-unidade");
  if (grpUnidade) {
    grpUnidade.innerHTML = filtros.unidades.map(u =>
      `<button class="filter-chip ${window.APP_FILTROS?.unidade === u ? "active" : ""}" data-tipo="unidade" data-valor="${u}">${u}</button>`
    ).join("");
  }

  // IAF
  const grpIaf = document.getElementById("filtros-iaf");
  if (grpIaf) {
    grpIaf.innerHTML = filtros.classificacoes.map(clf =>
      `<button class="filter-chip ${window.APP_FILTROS?.classificacao === clf ? "active" : ""}" data-tipo="classificacao" data-valor="${clf}">${clf}</button>`
    ).join("");
  }

  // Vendedores (select)
  const grpVend = document.getElementById("filtros-vendedor");
  if (grpVend && filtros.vendedores?.length) {
    const ativo = window.APP_FILTROS?.vendedor || "";
    const options = filtros.vendedores.map(v =>
      `<option value="${v.codigo}" ${ativo === v.codigo ? "selected" : ""}>${_abreviarNome(v.nome)}</option>`
    ).join("");
    grpVend.innerHTML = `
      <select id="select-vendedor" class="filtros-select ${ativo ? "active" : ""}">
        <option value="">Todos os vendedores</option>
        ${options}
      </select>`;

    document.getElementById("select-vendedor").addEventListener("change", e => {
      const valor = e.target.value;
      if (valor) {
        window.APP_FILTROS["vendedor"] = valor;
        e.target.classList.add("active");
      } else {
        delete window.APP_FILTROS["vendedor"];
        e.target.classList.remove("active");
      }
      const temFiltros = Object.keys(window.APP_FILTROS).length > 0;
      document.getElementById("btn-limpar-filtros")?.classList.toggle("hidden", !temFiltros);
      if (_paginaAtual && PAGINAS[_paginaAtual]) PAGINAS[_paginaAtual].render();
    });
  }

  // Bind chips
  document.querySelectorAll(".filter-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      const tipo = chip.dataset.tipo;
      const valor = chip.dataset.valor;
      toggleFiltro(tipo, valor);
    });
  });
}

/**
 * Abrevia nome completo para exibição em gráficos.
 * "RODRIGO AUGUSTO TEIXEIRA DOS SANTOS" → "RODRIGO SANTOS"
 */
function _abreviarNome(nome) {
  if (!nome) return "";
  const partes = nome.trim().split(/\s+/);
  if (partes.length <= 2) return nome;
  return `${partes[0]} ${partes[partes.length - 1]}`;
}

function _fmtData(s) {
  if (!s) return "";
  const [y, m, d] = s.split("-");
  return `${d}/${m}/${y}`;
}

function _skeletonDashboard() {
  return `
    <div class="page-header">
      <div class="skeleton" style="width:200px;height:20px;margin-bottom:8px"></div>
      <div class="skeleton" style="width:320px;height:14px"></div>
    </div>
    <div class="kpi-grid">
      ${Array(4).fill('<div class="kpi-card"><div class="skeleton" style="height:80px"></div></div>').join("")}
    </div>
    <div class="charts-grid">
      ${Array(2).fill('<div class="chart-card"><div class="skeleton" style="height:260px"></div></div>').join("")}
    </div>
  `;
}
