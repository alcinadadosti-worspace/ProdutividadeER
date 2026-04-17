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
          <button class="btn-ghost btn-sm" id="vend-export"><i data-lucide="download"></i> Exportar CSV</button>
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

    document.getElementById("vend-export").addEventListener("click", () => {
      const header = ["Vendedor","Código","Faturamento","Pedidos","Ticket Médio","Itens","Marcas","Marca Principal","% Cabelos","% Make","% Marcas"];
      const rows = _vendData.map(v => [
        v.nome, v.codigo, v.total_faturado.toFixed(2), v.qtd_pedidos,
        v.ticket_medio.toFixed(2), v.quantidade, v.qtd_marcas ?? "",
        v.top_marca || "", v.pct_iaf_cabelos.toFixed(1), v.pct_iaf_make.toFixed(1),
        (v.pct_marcas ?? 0).toFixed(1)
      ]);
      _downloadCSV([header, ...rows], "vendedores.csv");
    });

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
    { key: "qtd_marcas",     label: "Marcas",         align: "right" },
    { key: "top_marca",      label: "Marca Principal",align: "left" },
    { key: "pct_iaf_cabelos",label: "% Cabelos",      align: "right" },
    { key: "pct_iaf_make",   label: "% Make",         align: "right" },
    { key: "pct_marcas",     label: "% Marcas",       align: "right" },
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
      <td class="mono" style="text-align:right">${v.qtd_marcas ?? "—"}</td>
      <td class="secondary" style="white-space:nowrap">${v.top_marca || "—"}</td>
      <td style="text-align:right">
        <span class="badge badge-cabelos">${v.pct_iaf_cabelos.toFixed(1)}%</span>
      </td>
      <td style="text-align:right">
        <span class="badge badge-make">${v.pct_iaf_make.toFixed(1)}%</span>
      </td>
      <td style="text-align:right">
        <span class="badge" style="background:rgba(251,146,60,0.15);color:#FB923C">${(v.pct_marcas ?? 0).toFixed(1)}%</span>
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
      <div style="display:flex;flex-direction:column;gap:8px;margin-bottom:24px">
        ${d.por_iaf.map(x => `
          <div style="background:var(--bg-tertiary);border-radius:8px;padding:12px 16px;display:flex;justify-content:space-between;align-items:center">
            <div style="font-size:13px;color:var(--text-secondary)">${x.classificacao}</div>
            <div style="font-size:15px;font-weight:600;font-family:monospace;color:${_iafColor(x.classificacao)}">${fmtBRL(x.total)}</div>
          </div>
        `).join("")}
      </div>

      <!-- Marcas -->
      ${d.por_marca?.length ? (() => {
          const totalMarcas = d.por_marca.reduce((s, x) => s + x.total, 0);
          const pctMarcasGeral = d.total_faturado ? (totalMarcas / d.total_faturado * 100) : 0;
          return `
      <div class="section-title" style="margin-bottom:12px">Marcas Vendidas <span style="font-size:12px;font-weight:400;color:#FB923C;margin-left:8px">${pctMarcasGeral.toFixed(1)}% do faturamento</span></div>
      <div style="display:flex;flex-direction:column;gap:6px;margin-bottom:24px">
        ${d.por_marca.map(x => {
          const pct = d.total_faturado ? (x.total / d.total_faturado * 100) : 0;
          const { cor } = _corMarca(x.marca);
          return `
          <div style="display:flex;align-items:center;gap:10px">
            <div style="width:120px;font-size:12px;color:${cor};white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-weight:600">${x.marca}</div>
            <div style="flex:1;background:var(--bg-tertiary);border-radius:4px;height:7px;overflow:hidden">
              <div style="width:${pct.toFixed(1)}%;height:100%;background:${cor};border-radius:4px"></div>
            </div>
            <div style="font-size:12px;font-family:monospace;color:var(--text-secondary);width:90px;text-align:right">${fmtBRL(x.total)}</div>
            <div style="font-size:11px;color:var(--text-tertiary);width:36px;text-align:right">${pct.toFixed(0)}%</div>
          </div>`;
        }).join("")}
      </div>`;
      })() : ""}

      <!-- Marcas mais vendidas juntas -->
      ${d.marcas_juntas?.length ? `
      <div class="section-title" style="margin-bottom:12px">Marcas Mais Vendidas Juntas</div>
      <div style="margin-bottom:24px">
        ${d.marcas_juntas.map((x, i) => {
          const c0 = _corMarca(x.marcas[0]);
          const c1 = _corMarca(x.marcas[1]);
          return `
          <div class="marcas-juntas-par">
            <span style="font-size:11px;color:var(--text-tertiary);width:18px;text-align:right;flex-shrink:0">${i + 1}.</span>
            <span class="marcas-juntas-badge" style="background:${c0.bg};color:${c0.cor}">${x.marcas[0]}</span>
            <span class="marcas-juntas-sep">+</span>
            <span class="marcas-juntas-badge" style="background:${c1.bg};color:${c1.cor}">${x.marcas[1]}</span>
            <span class="marcas-juntas-count">${x.pedidos} pedido${x.pedidos !== 1 ? "s" : ""}</span>
          </div>`;
        }).join("")}
      </div>` : ""}

      <!-- Categorias -->
      ${d.por_categoria?.length ? `
      <div class="section-title" style="margin-bottom:12px">Categorias de Produto</div>
      <div style="display:flex;flex-direction:column;gap:4px;margin-bottom:24px" id="cat-accordion">
        ${d.por_categoria.map((x, i) => {
          const pct = d.total_faturado ? (x.total / d.total_faturado * 100) : 0;
          const catId = `cat-items-${i}`;
          return `
          <div class="cat-row" style="border-radius:6px;overflow:hidden;background:var(--bg-secondary)">
            <div class="cat-header" data-cat="${x.categoria}" data-target="${catId}"
                 style="display:flex;align-items:center;gap:10px;padding:8px 10px;cursor:pointer;user-select:none">
              <div style="width:16px;height:16px;flex-shrink:0;display:flex;align-items:center;justify-content:center">
                <svg class="cat-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none"
                     stroke="currentColor" stroke-width="2.5" style="color:var(--text-tertiary);transition:transform 200ms">
                  <polyline points="9 18 15 12 9 6"></polyline>
                </svg>
              </div>
              <div style="width:130px;font-size:12px;color:var(--text-primary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${x.categoria}</div>
              <div style="flex:1;background:var(--bg-tertiary);border-radius:4px;height:6px;overflow:hidden">
                <div style="width:${pct.toFixed(1)}%;height:100%;background:var(--accent-blue);border-radius:4px;opacity:0.7"></div>
              </div>
              <div style="font-size:12px;font-family:monospace;color:var(--text-secondary);width:90px;text-align:right">${fmtBRL(x.total)}</div>
              <div style="font-size:11px;color:var(--text-tertiary);width:36px;text-align:right">${pct.toFixed(0)}%</div>
            </div>
            <div id="${catId}" style="display:none;padding:0 10px 10px 36px">
              <table style="width:100%;border-collapse:collapse">
                <thead>
                  <tr style="border-bottom:1px solid var(--border-subtle)">
                    <th style="text-align:left;font-size:11px;color:var(--text-tertiary);padding:4px 0;font-weight:500">Produto</th>
                    <th style="text-align:right;font-size:11px;color:var(--text-tertiary);padding:4px 0;font-weight:500;width:50px">Qtde</th>
                    <th style="text-align:right;font-size:11px;color:var(--text-tertiary);padding:4px 0;font-weight:500;width:90px">Total</th>
                  </tr>
                </thead>
                <tbody>
                  ${(d.produtos_por_categoria?.[x.categoria] || []).map(p => `
                    <tr style="border-bottom:1px solid var(--border-subtle)">
                      <td style="font-size:11px;padding:5px 0;color:var(--text-primary);max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${p.nome}</td>
                      <td style="font-size:11px;font-family:monospace;text-align:right;padding:5px 0;color:var(--text-secondary)">${fmtNum(p.quantidade)}</td>
                      <td style="font-size:11px;font-family:monospace;text-align:right;padding:5px 0;color:var(--text-secondary)">${fmtBRL(p.total)}</td>
                    </tr>
                  `).join("")}
                </tbody>
              </table>
            </div>
          </div>`;
        }).join("")}
      </div>` : ""}

      <!-- Ciclo chart -->
      <div class="section-title" style="margin-bottom:12px">Por Ciclo</div>
      <div style="height:180px;margin-bottom:24px">
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
                <td class="mono secondary" style="font-size:12px">${p.codigo}</td>
                <td class="secondary" style="font-size:12px">${p.data || "—"}</td>
                <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;font-size:12px">${p.revendedor || "—"}</td>
                <td class="mono" style="text-align:right;font-size:12px">${fmtBRL(p.total)}</td>
                <td class="mono" style="text-align:right;font-size:12px">${fmtNum(p.itens)}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `;

    // Accordion de categorias
    content.querySelectorAll(".cat-header").forEach(header => {
      header.addEventListener("click", () => {
        const targetId = header.dataset.target;
        const panel = document.getElementById(targetId);
        const chevron = header.querySelector(".cat-chevron");
        const open = panel.style.display !== "none";
        panel.style.display = open ? "none" : "block";
        chevron.style.transform = open ? "" : "rotate(90deg)";
      });
    });

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

const _MARCA_CORES = [
  { match: /eudora/i,              cor: "#A78BFA", bg: "rgba(167,139,250,0.15)" },   // roxo
  { match: /boticário|boticario/i, cor: "#4ADE80", bg: "rgba(74,222,128,0.15)"  },   // verde
  { match: /berenice/i,            cor: "#F472B6", bg: "rgba(244,114,182,0.15)" },   // rosa
  { match: /o\.u\.i|oui\b/i,       cor: "#F87171", bg: "rgba(248,113,113,0.15)" },   // vermelho
  { match: /aumigos|auamigos/i,    cor: "#FB923C", bg: "rgba(251,146,60,0.15)"  },   // laranja
];

function _corMarca(nome) {
  const n = nome || "";
  for (const { match, cor, bg } of _MARCA_CORES) {
    if (match.test(n)) return { cor, bg };
  }
  return { cor: "#6C9EFF", bg: "rgba(108,158,255,0.15)" }; // azul padrão
}
