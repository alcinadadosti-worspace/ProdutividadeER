/**
 * vendedores.js — Tela de análise de vendedores
 */

let _vendSort = { col: "total_faturado", asc: false };
let _vendData = [];

async function renderVendedores() {
  const page = document.getElementById("page-vendedores");
  page.innerHTML = `
    <div class="page-header">
      <div class="page-title">Vendedores</div>
      <div class="page-subtitle">Performance individual por faturamento</div>
    </div>
    <div class="table-card">
      <div class="table-toolbar">
        <span class="table-toolbar-title" id="vend-count">Carregando...</span>
        <div class="table-toolbar-right">
          <input type="text" class="search-input" id="vend-search" placeholder="Buscar vendedor..." />
        </div>
      </div>
      <div class="table-wrapper" id="vend-table-wrap">
        <div class="skeleton" style="height:300px;margin:16px"></div>
      </div>
    </div>
  `;
  lucide.createIcons();

  try {
    const params = new URLSearchParams(window.APP_FILTROS || {});
    const res = await fetch("/api/vendedores?" + params.toString());
    const data = await res.json();
    if (!res.ok) throw new Error(data.erro || "Erro");
    _vendData = data.vendedores;
    document.getElementById("vend-count").textContent = `${fmtNum(data.total)} vendedores`;
    _renderTabelaVendedores(_vendData);

    document.getElementById("vend-search").addEventListener("input", e => {
      const q = e.target.value.toLowerCase();
      const filtrado = _vendData.filter(v =>
        v.nome.toLowerCase().includes(q) || v.codigo.toLowerCase().includes(q)
      );
      _renderTabelaVendedores(filtrado);
    });
  } catch (err) {
    page.querySelector("#vend-table-wrap").innerHTML =
      `<div class="empty-state"><p>${err.message}</p></div>`;
  }
}

function _renderTabelaVendedores(lista) {
  const wrap = document.getElementById("vend-table-wrap");
  if (!wrap) return;

  if (!lista.length) {
    wrap.innerHTML = '<div class="empty-state"><p>Nenhum vendedor encontrado.</p></div>';
    return;
  }

  const cols = [
    { key: "nome",           label: "Vendedor",       align: "left" },
    { key: "codigo",         label: "Código",         align: "left" },
    { key: "total_faturado", label: "Faturamento",    align: "right" },
    { key: "qtd_pedidos",    label: "Pedidos",        align: "right" },
    { key: "ticket_medio",   label: "Ticket Médio",   align: "right" },
    { key: "quantidade",     label: "Itens",          align: "right" },
    { key: "pct_iaf_cabelos",label: "% Cabelos",      align: "right" },
    { key: "pct_iaf_make",   label: "% Make",         align: "right" },
  ];

  const sorted = [...lista].sort((a, b) => {
    const va = a[_vendSort.col], vb = b[_vendSort.col];
    const r = typeof va === "string" ? va.localeCompare(vb) : va - vb;
    return _vendSort.asc ? r : -r;
  });

  const thead = cols.map(c => {
    const active = _vendSort.col === c.key;
    const arrow = active ? (_vendSort.asc ? " ↑" : " ↓") : "";
    return `<th class="${active ? "sorted" : ""}" data-col="${c.key}" style="text-align:${c.align}">
      ${c.label}<span class="sort-icon">${arrow}</span>
    </th>`;
  }).join("");

  const tbody = sorted.map(v => `
    <tr class="vend-row" data-cod="${v.codigo}" style="cursor:pointer">
      <td>${v.nome}</td>
      <td class="mono secondary">${v.codigo}</td>
      <td class="mono" style="text-align:right">${fmtBRL(v.total_faturado)}</td>
      <td class="mono" style="text-align:right">${fmtNum(v.qtd_pedidos)}</td>
      <td class="mono" style="text-align:right">${fmtBRL(v.ticket_medio)}</td>
      <td class="mono" style="text-align:right">${fmtNum(v.quantidade)}</td>
      <td style="text-align:right">
        <span class="badge badge-cabelos">${v.pct_iaf_cabelos.toFixed(1)}%</span>
      </td>
      <td style="text-align:right">
        <span class="badge badge-make">${v.pct_iaf_make.toFixed(1)}%</span>
      </td>
    </tr>
  `).join("");

  wrap.innerHTML = `
    <table>
      <thead><tr>${thead}</tr></thead>
      <tbody>${tbody}</tbody>
    </table>
  `;

  // Sort headers
  wrap.querySelectorAll("thead th").forEach(th => {
    th.addEventListener("click", () => {
      const col = th.dataset.col;
      if (_vendSort.col === col) {
        _vendSort.asc = !_vendSort.asc;
      } else {
        _vendSort.col = col;
        _vendSort.asc = col === "nome";
      }
      _renderTabelaVendedores(lista);
    });
  });

  // Row click → drawer
  wrap.querySelectorAll(".vend-row").forEach(tr => {
    tr.addEventListener("click", () => abrirDrawerVendedor(tr.dataset.cod));
  });
}

async function abrirDrawerVendedor(codigo) {
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
    const res = await fetch(`/api/vendedor/${codigo}`);
    const d = await res.json();
    if (!res.ok) throw new Error(d.erro || "Erro");

    nomeEl.textContent = d.nome;
    codEl.textContent  = `Código: ${d.codigo} · ${fmtBRL(d.total_faturado)} · ${fmtNum(d.qtd_pedidos)} pedidos`;

    content.innerHTML = `
      <!-- IAF breakdown -->
      <div class="section-title" style="margin-bottom:12px">Distribuição IAF</div>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:20px">
        ${d.por_iaf.map(x => `
          <div style="background:var(--bg-tertiary);border-radius:8px;padding:12px;text-align:center">
            <div style="font-size:16px;font-weight:600;font-family:monospace;color:${_iafColor(x.classificacao)}">${fmtBRL(x.total)}</div>
            <div style="font-size:10px;color:var(--text-tertiary);margin-top:4px">${x.classificacao}</div>
          </div>
        `).join("")}
      </div>

      <!-- Ciclo chart -->
      <div class="section-title" style="margin-bottom:12px">Por Ciclo</div>
      <div style="height:160px;margin-bottom:20px">
        <canvas id="drawer-ciclo-chart"></canvas>
      </div>

      <!-- Pedidos -->
      <div class="section-title" style="margin-bottom:12px">Últimos Pedidos</div>
      <div style="overflow-x:auto">
        <table>
          <thead>
            <tr>
              <th>Pedido</th><th>Data</th><th>Revendedor</th><th style="text-align:right">Total</th><th style="text-align:right">Itens</th>
            </tr>
          </thead>
          <tbody>
            ${d.pedidos.map(p => `
              <tr>
                <td class="mono secondary">${p.codigo}</td>
                <td class="secondary">${p.data || "—"}</td>
                <td style="max-width:180px;overflow:hidden;text-overflow:ellipsis">${p.revendedor || "—"}</td>
                <td class="mono" style="text-align:right">${fmtBRL(p.total)}</td>
                <td class="mono" style="text-align:right">${fmtNum(p.itens)}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `;

    // Chart por ciclo
    if (d.por_ciclo.length) {
      criarOuAtualizar("drawer-ciclo-chart", "bar", {
        labels: d.por_ciclo.map(x => x.ciclo),
        datasets: [{
          data: d.por_ciclo.map(x => x.total),
          backgroundColor: "rgba(108,158,255,0.5)",
          borderColor: CHART_COLORS.blue,
          borderWidth: 1,
          borderRadius: 3,
        }],
      }, barOptions(false, {
        plugins: { tooltip: { ...TOOLTIP_STYLE, callbacks: { label: ctx => " " + fmtBRL(ctx.raw) } } }
      }));
    }

  } catch (err) {
    content.innerHTML = `<div class="empty-state"><p>${err.message}</p></div>`;
  }
}

function _iafColor(clf) {
  if (clf === "IAF Cabelos") return "var(--accent-blue)";
  if (clf === "IAF Make")    return "var(--accent-purple)";
  return "var(--text-secondary)";
}
