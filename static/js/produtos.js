/**
 * produtos.js — Tela de análise de produtos
 */

let _prodSort  = { col: "total", asc: false };
let _prodData  = [];
let _prodFiltro = "";

async function renderProdutos() {
  const page = document.getElementById("page-produtos");
  page.innerHTML = `
    <div class="page-header">
      <div class="page-title">Produtos</div>
      <div class="page-subtitle">Top produtos por faturamento e quantidade</div>
    </div>

    <!-- Chips de classificação -->
    <div class="flex-row mb-12">
      <button class="filter-chip active" data-clf="">Todos</button>
      <button class="filter-chip" data-clf="IAF Cabelos">IAF Cabelos</button>
      <button class="filter-chip" data-clf="IAF Make">IAF Make</button>
      <button class="filter-chip" data-clf="Geral">Geral</button>
    </div>

    <div class="table-card">
      <div class="table-toolbar">
        <span class="table-toolbar-title" id="prod-count">Carregando...</span>
        <div class="table-toolbar-right">
          <input type="text" class="search-input" id="prod-search" placeholder="Buscar produto ou SKU..." />
        </div>
      </div>
      <div class="table-wrapper" id="prod-table-wrap">
        <div class="skeleton" style="height:300px;margin:16px"></div>
      </div>
    </div>
  `;
  lucide.createIcons();

  try {
    const params = new URLSearchParams(window.APP_FILTROS || {});
    const res = await fetch("/api/produtos?" + params.toString());
    const data = await res.json();
    if (!res.ok) throw new Error(data.erro || "Erro");

    _prodData = data.produtos;
    document.getElementById("prod-count").textContent =
      `Top ${fmtNum(_prodData.length)} de ${fmtNum(data.total)} produtos`;

    _renderTabelaProdutos(_prodData);

    // Chips
    page.querySelectorAll("[data-clf]").forEach(chip => {
      chip.addEventListener("click", () => {
        page.querySelectorAll("[data-clf]").forEach(c => c.classList.remove("active"));
        chip.classList.add("active");
        _prodFiltro = chip.dataset.clf;
        _aplicarFiltroProd();
      });
    });

    // Search
    document.getElementById("prod-search").addEventListener("input", e => {
      _aplicarFiltroProd(e.target.value);
    });

  } catch (err) {
    page.querySelector("#prod-table-wrap").innerHTML =
      `<div class="empty-state"><p>${err.message}</p></div>`;
  }
}

function _aplicarFiltroProd(busca = null) {
  const q = busca !== null ? busca : (document.getElementById("prod-search")?.value || "");
  let lista = _prodData;

  if (_prodFiltro) {
    lista = lista.filter(p => p.classificacao === _prodFiltro);
  }

  if (q.trim()) {
    const ql = q.toLowerCase();
    lista = lista.filter(p =>
      p.nome.toLowerCase().includes(ql) || p.sku.toLowerCase().includes(ql)
    );
  }

  _renderTabelaProdutos(lista);
}

function _renderTabelaProdutos(lista) {
  const wrap = document.getElementById("prod-table-wrap");
  if (!wrap) return;

  if (!lista.length) {
    wrap.innerHTML = '<div class="empty-state"><p>Nenhum produto encontrado.</p></div>';
    return;
  }

  const cols = [
    { key: "sku",           label: "SKU",            align: "left" },
    { key: "nome",          label: "Produto",        align: "left" },
    { key: "total",         label: "Faturamento",    align: "right" },
    { key: "quantidade",    label: "Qtde",           align: "right" },
    { key: "classificacao", label: "Classificação",  align: "left" },
    { key: "metodo_match",  label: "Match",          align: "left" },
  ];

  const sorted = [...lista].sort((a, b) => {
    const va = a[_prodSort.col], vb = b[_prodSort.col];
    const r = typeof va === "string" ? va.localeCompare(vb) : va - vb;
    return _prodSort.asc ? r : -r;
  });

  const thead = cols.map(c => {
    const active = _prodSort.col === c.key;
    const arrow = active ? (_prodSort.asc ? " ↑" : " ↓") : "";
    return `<th class="${active ? "sorted" : ""}" data-col="${c.key}" style="text-align:${c.align}">
      ${c.label}<span class="sort-icon">${arrow}</span>
    </th>`;
  }).join("");

  const tbody = sorted.map((p, i) => `
    <tr>
      <td class="mono secondary">${p.sku}</td>
      <td style="max-width:280px;overflow:hidden;text-overflow:ellipsis">${p.nome}</td>
      <td class="mono" style="text-align:right">${fmtBRL(p.total)}</td>
      <td class="mono" style="text-align:right">${fmtNum(p.quantidade)}</td>
      <td>${_badgeClf(p.classificacao)}</td>
      <td>${_badgeMatch(p.metodo_match)}</td>
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
      if (_prodSort.col === col) {
        _prodSort.asc = !_prodSort.asc;
      } else {
        _prodSort.col = col;
        _prodSort.asc = ["nome","sku","classificacao"].includes(col);
      }
      _renderTabelaProdutos(lista);
    });
  });
}

function _badgeClf(clf) {
  const map = {
    "IAF Cabelos": "badge-cabelos",
    "IAF Make":    "badge-make",
    "Geral":       "badge-geral",
  };
  return `<span class="badge ${map[clf] || "badge-geral"}">${clf}</span>`;
}

function _badgeMatch(m) {
  const map = {
    "sku":            ["badge-sku",     "SKU"],
    "fallback_siage": ["badge-siage",   "Siàge"],
    "fallback_make":  ["badge-make-fb", "Make FB"],
    "nenhum":         ["badge-none",    "—"],
  };
  const [cls, label] = map[m] || ["badge-none", m];
  return `<span class="badge ${cls}">${label}</span>`;
}
