/**
 * revendedores.js — Tela de análise de revendedores
 */

let _revSort = { col: "total_faturado", asc: false };
let _revData = [];
let _revDrawerOpen = null;

async function renderRevendedores() {
  const page = document.getElementById("page-revendedores");
  page.innerHTML = `
    <div class="page-header">
      <div class="page-title">Revendedores</div>
      <div class="page-subtitle">Ranking, concentração de vendas e performance por papel</div>
    </div>
    <div id="rev-summary-cards" class="kpi-grid" style="margin-bottom:24px">
      <div class="skeleton" style="height:88px;border-radius:12px"></div>
      <div class="skeleton" style="height:88px;border-radius:12px"></div>
      <div class="skeleton" style="height:88px;border-radius:12px"></div>
      <div class="skeleton" style="height:88px;border-radius:12px"></div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:24px">
      <div class="chart-card" id="rev-papel-chart-wrap">
        <div class="chart-title">Faturamento por Papel</div>
        <div style="height:220px"><canvas id="rev-papel-chart"></canvas></div>
      </div>
      <div class="chart-card" id="rev-concentracao-wrap">
        <div class="chart-title">Concentração de Vendas (Curva 80/20)</div>
        <div id="rev-concentracao-content" style="height:220px;display:flex;align-items:center;justify-content:center">
          <div class="skeleton" style="width:100%;height:100%;border-radius:8px"></div>
        </div>
      </div>
    </div>
    <div class="table-card">
      <div class="table-toolbar">
        <span class="table-toolbar-title" id="rev-count">Carregando...</span>
        <div class="table-toolbar-right">
          <input type="text" class="search-input" id="rev-search" placeholder="Buscar revendedor..." />
        </div>
      </div>
      <div class="table-wrapper" id="rev-table-wrap">
        <div class="skeleton" style="height:300px;margin:16px"></div>
      </div>
    </div>
  `;
  lucide.createIcons();

  try {
    const params = new URLSearchParams(window.APP_FILTROS || {});
    const res = await fetch("/api/revendedores?" + params.toString());
    const data = await res.json();
    if (!res.ok) throw new Error(data.erro || "Erro");

    _revData = data.revendedores;
    const conc = data.concentracao;
    const porPapel = data.por_papel;

    // ── Cards de resumo ──────────────────────────────────────────────────────
    const totalFat = conc.total_faturado;
    const ticketGlobal = _revData.length
      ? _revData.reduce((s, r) => s + r.ticket_medio, 0) / _revData.length
      : 0;

    document.getElementById("rev-summary-cards").innerHTML = `
      <div class="kpi-card">
        <div class="kpi-header"><span class="kpi-label">Total de Revendedores</span><div class="kpi-icon blue"><i data-lucide="store"></i></div></div>
        <div class="kpi-value">${fmtNum(conc.total_revendedores)}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-header"><span class="kpi-label">Faturamento Total</span><div class="kpi-icon green"><i data-lucide="banknote"></i></div></div>
        <div class="kpi-value">${fmtBRL(totalFat)}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-header"><span class="kpi-label">Ticket Médio Geral</span><div class="kpi-icon purple"><i data-lucide="receipt"></i></div></div>
        <div class="kpi-value">${fmtBRL(ticketGlobal)}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-header"><span class="kpi-label">Papéis Distintos</span><div class="kpi-icon orange"><i data-lucide="tag"></i></div></div>
        <div class="kpi-value">${fmtNum(porPapel.length)}</div>
      </div>
    `;
    lucide.createIcons();

    // ── Gráfico por papel ────────────────────────────────────────────────────
    criarOuAtualizar("rev-papel-chart", "bar", {
      labels: porPapel.map(p => p.papel),
      datasets: [{
        data: porPapel.map(p => p.total_faturado),
        backgroundColor: PALETTE.map(c => c + "99"),
        borderColor: PALETTE,
        borderWidth: 1,
        borderRadius: 4,
      }],
    }, barOptions(false, {
      indexAxis: "y",
      plugins: {
        legend: { display: false },
        tooltip: { ...TOOLTIP_STYLE, callbacks: { label: ctx => " " + fmtBRL(ctx.raw) } },
      },
      scales: {
        x: { ticks: { callback: v => fmtBRL(v) } },
        y: { ticks: { color: "var(--text-secondary)", font: { size: 11 } } },
      },
    }));

    // ── Bloco de concentração 80/20 ──────────────────────────────────────────
    _renderConcentracao(conc, porPapel);

    // ── Contador e tabela ────────────────────────────────────────────────────
    document.getElementById("rev-count").textContent = `${fmtNum(data.total)} revendedores`;
    _renderTabelaRevendedores(_revData);

    document.getElementById("rev-search").addEventListener("input", e => {
      const q = e.target.value.toLowerCase();
      const filtrado = _revData.filter(r =>
        r.nome.toLowerCase().includes(q) ||
        r.codigo.toLowerCase().includes(q) ||
        (r.papel || "").toLowerCase().includes(q)
      );
      _renderTabelaRevendedores(filtrado);
    });

  } catch (err) {
    page.innerHTML += `<div class="empty-state"><p>${err.message}</p></div>`;
  }
}

function _renderConcentracao(conc, porPapel) {
  const wrap = document.getElementById("rev-concentracao-content");
  if (!wrap) return;

  const pctRev = conc.pct_rev_80pct;
  const qtd = conc.qtd_80pct;
  const total = conc.total_revendedores;

  // Ticket médio por papel
  const papelRows = porPapel.map(p => {
    const pct = conc.total_faturado ? (p.total_faturado / conc.total_faturado * 100) : 0;
    return `
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
        <div style="width:130px;font-size:12px;color:var(--text-secondary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${p.papel}</div>
        <div style="font-size:12px;font-family:monospace;width:80px;text-align:right;color:var(--text-primary)">${fmtBRL(p.ticket_medio)}</div>
        <div style="font-size:11px;color:var(--text-tertiary);width:28px;text-align:right">${pct.toFixed(0)}%</div>
      </div>`;
  }).join("");

  wrap.innerHTML = `
    <div style="width:100%;padding:8px 4px">
      <!-- Destaque 80/20 -->
      <div style="display:flex;align-items:center;gap:16px;margin-bottom:16px;padding:12px 16px;background:var(--bg-tertiary);border-radius:8px">
        <div style="text-align:center;flex-shrink:0">
          <div style="font-size:28px;font-weight:700;font-family:monospace;color:var(--accent-blue)">${pctRev}%</div>
          <div style="font-size:10px;color:var(--text-tertiary);margin-top:2px">dos revendedores</div>
        </div>
        <div style="font-size:12px;color:var(--text-secondary);line-height:1.5">
          <strong style="color:var(--text-primary)">${fmtNum(qtd)} de ${fmtNum(total)}</strong> revendedores<br>
          geram <strong style="color:var(--accent-blue)">80%</strong> do faturamento total
        </div>
      </div>
      <!-- Ticket médio por papel -->
      <div style="font-size:11px;font-weight:600;color:var(--text-tertiary);text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px">Ticket Médio por Papel</div>
      ${papelRows}
    </div>
  `;
}

function _renderTabelaRevendedores(lista) {
  const wrap = document.getElementById("rev-table-wrap");
  if (!wrap) return;

  if (!lista.length) {
    wrap.innerHTML = '<div class="empty-state"><p>Nenhum revendedor encontrado.</p></div>';
    return;
  }

  const cols = [
    { key: "nome",           label: "Revendedor",    align: "left" },
    { key: "papel",          label: "Papel",          align: "left" },
    { key: "total_faturado", label: "Faturamento",   align: "right" },
    { key: "qtd_pedidos",    label: "Pedidos",        align: "right" },
    { key: "ticket_medio",   label: "Ticket Médio",  align: "right" },
    { key: "quantidade",     label: "Itens",          align: "right" },
    { key: "qtd_vendedores", label: "Vendedores",    align: "right" },
  ];

  const sorted = [...lista].sort((a, b) => {
    const va = a[_revSort.col], vb = b[_revSort.col];
    const r = typeof va === "string" ? va.localeCompare(vb) : va - vb;
    return _revSort.asc ? r : -r;
  });

  const thead = cols.map(c => {
    const active = _revSort.col === c.key;
    const arrow = active ? (_revSort.asc ? " ↑" : " ↓") : "";
    return `<th class="${active ? "sorted" : ""}" data-col="${c.key}" style="text-align:${c.align}">
      ${c.label}<span class="sort-icon">${arrow}</span>
    </th>`;
  }).join("");

  const tbody = sorted.map((r, i) => `
    <tr class="rev-row" data-cod="${r.codigo}" style="cursor:pointer">
      <td>
        <div style="font-size:13px">${r.nome}</div>
        <div class="secondary" style="font-size:11px;font-family:monospace">${r.codigo}</div>
      </td>
      <td><span class="badge ${_papelBadgeClass(r.papel)}">${r.papel}</span></td>
      <td class="mono" style="text-align:right">${fmtBRL(r.total_faturado)}</td>
      <td class="mono" style="text-align:right">${fmtNum(r.qtd_pedidos)}</td>
      <td class="mono" style="text-align:right">${fmtBRL(r.ticket_medio)}</td>
      <td class="mono" style="text-align:right">${fmtNum(r.quantidade)}</td>
      <td class="mono" style="text-align:right">${r.qtd_vendedores}</td>
    </tr>
  `).join("");

  wrap.innerHTML = `
    <table>
      <thead><tr>${thead}</tr></thead>
      <tbody>${tbody}</tbody>
    </table>
  `;

  wrap.querySelectorAll("thead th").forEach(th => {
    th.addEventListener("click", () => {
      const col = th.dataset.col;
      if (_revSort.col === col) {
        _revSort.asc = !_revSort.asc;
      } else {
        _revSort.col = col;
        _revSort.asc = col === "nome" || col === "papel";
      }
      _renderTabelaRevendedores(lista);
    });
  });

  wrap.querySelectorAll(".rev-row").forEach(tr => {
    tr.addEventListener("click", () => abrirDrawerRevendedor(tr.dataset.cod));
  });
}

async function abrirDrawerRevendedor(codigo) {
  const overlay = document.getElementById("drawer-overlay");
  const drawer  = document.getElementById("vendedor-drawer");
  const content = document.getElementById("drawer-content");
  const nomeEl  = document.getElementById("drawer-nome");
  const codEl   = document.getElementById("drawer-codigo");

  overlay.classList.remove("hidden");
  drawer.classList.remove("hidden");
  content.innerHTML = '<div class="skeleton" style="height:400px;border-radius:8px"></div>';
  nomeEl.textContent = "Carregando...";
  codEl.textContent  = codigo;

  try {
    const res = await fetch(`/api/revendedor/${encodeURIComponent(codigo)}`);
    const d = await res.json();
    if (!res.ok) throw new Error(d.erro || "Erro");

    nomeEl.textContent = d.nome;
    codEl.textContent = `${d.papel} · ${fmtBRL(d.total_faturado)} · ${fmtNum(d.qtd_pedidos)} pedidos`;

    content.innerHTML = `
      <!-- IAF -->
      <div class="section-title" style="margin-bottom:12px">Distribuição IAF</div>
      <div style="display:flex;flex-direction:column;gap:8px;margin-bottom:24px">
        ${d.por_iaf.map(x => `
          <div style="background:var(--bg-tertiary);border-radius:8px;padding:12px 16px;display:flex;justify-content:space-between;align-items:center">
            <div style="font-size:13px;color:var(--text-secondary)">${x.classificacao}</div>
            <div style="font-size:15px;font-weight:600;font-family:monospace;color:${_iafColor(x.classificacao)}">${fmtBRL(x.total)}</div>
          </div>
        `).join("")}
      </div>

      <!-- Vendedores que atenderam -->
      ${d.vendedores?.length ? `
      <div class="section-title" style="margin-bottom:12px">Vendedores que Atenderam</div>
      <div style="display:flex;flex-direction:column;gap:6px;margin-bottom:24px">
        ${d.vendedores.map(v => {
          const pct = d.total_faturado ? (v.total / d.total_faturado * 100) : 0;
          return `
          <div style="display:flex;align-items:center;gap:10px">
            <div style="width:140px;font-size:12px;color:var(--text-primary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${v.nome}</div>
            <div style="flex:1;background:var(--bg-tertiary);border-radius:4px;height:7px;overflow:hidden">
              <div style="width:${pct.toFixed(1)}%;height:100%;background:var(--accent-blue);border-radius:4px;opacity:0.7"></div>
            </div>
            <div style="font-size:12px;font-family:monospace;color:var(--text-secondary);width:90px;text-align:right">${fmtBRL(v.total)}</div>
            <div style="font-size:11px;color:var(--text-tertiary);width:36px;text-align:right">${pct.toFixed(0)}%</div>
          </div>`;
        }).join("")}
      </div>` : ""}

      <!-- Ciclo chart -->
      <div class="section-title" style="margin-bottom:12px">Por Ciclo</div>
      <div style="height:160px;margin-bottom:24px">
        <canvas id="drawer-rev-ciclo-chart"></canvas>
      </div>

      <!-- Top produtos -->
      <div class="section-title" style="margin-bottom:12px">Produtos Mais Comprados</div>
      <div style="overflow-x:auto;margin-bottom:24px">
        <table>
          <thead>
            <tr>
              <th>Produto</th>
              <th style="text-align:right">Qtde</th>
              <th style="text-align:right">Total</th>
            </tr>
          </thead>
          <tbody>
            ${d.top_produtos.map(p => `
              <tr>
                <td style="font-size:12px;max-width:240px;overflow:hidden;text-overflow:ellipsis">${p.nome}</td>
                <td class="mono" style="text-align:right;font-size:12px">${fmtNum(p.quantidade)}</td>
                <td class="mono" style="text-align:right;font-size:12px">${fmtBRL(p.total)}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>

      <!-- Pedidos -->
      <div class="section-title" style="margin-bottom:12px">Últimos Pedidos</div>
      <div style="overflow-x:auto">
        <table>
          <thead>
            <tr>
              <th>Pedido</th><th>Data</th><th>Vendedor</th><th style="text-align:right">Total</th><th style="text-align:right">Itens</th>
            </tr>
          </thead>
          <tbody>
            ${d.pedidos.map(p => `
              <tr>
                <td class="mono secondary" style="font-size:12px">${p.codigo}</td>
                <td class="secondary" style="font-size:12px">${p.data || "—"}</td>
                <td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;font-size:12px">${p.vendedor || "—"}</td>
                <td class="mono" style="text-align:right;font-size:12px">${fmtBRL(p.total)}</td>
                <td class="mono" style="text-align:right;font-size:12px">${fmtNum(p.itens)}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `;

    if (d.por_ciclo.length) {
      criarOuAtualizar("drawer-rev-ciclo-chart", "bar", {
        labels: d.por_ciclo.map(x => x.ciclo),
        datasets: [{
          data: d.por_ciclo.map(x => x.total),
          backgroundColor: "rgba(108,158,255,0.5)",
          borderColor: CHART_COLORS.blue,
          borderWidth: 1,
          borderRadius: 3,
        }],
      }, barOptions(false, {
        plugins: { tooltip: { ...TOOLTIP_STYLE, callbacks: { label: ctx => " " + fmtBRL(ctx.raw) } } },
      }));
    }

  } catch (err) {
    content.innerHTML = `<div class="empty-state"><p>${err.message}</p></div>`;
  }
}

function _papelBadgeClass(papel) {
  if (!papel) return "badge-geral";
  const p = papel.toLowerCase();
  if (p.includes("diamante")) return "badge-cabelos";
  if (p.includes("ouro") || p.includes("gold")) return "badge-make";
  if (p.includes("prata") || p.includes("silver")) return "";
  return "badge-geral";
}
