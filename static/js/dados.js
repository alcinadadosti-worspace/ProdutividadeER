/**
 * dados.js — Tela de dados brutos com paginação e exportação
 */

let _dadosPage  = 1;
let _dadosSize  = 50;
let _dadosSearch = "";
let _dadosTotal  = 0;
let _dadosTotalPages = 1;

async function renderDados() {
  const page = document.getElementById("page-dados");
  page.innerHTML = `
    <div class="page-header">
      <div class="page-title">Dados Brutos</div>
      <div class="page-subtitle">Todos os registros processados</div>
    </div>
    <div class="table-card">
      <div class="table-toolbar">
        <span class="table-toolbar-title" id="dados-count">Carregando...</span>
        <div class="table-toolbar-right">
          <input type="text" class="search-input" id="dados-search" placeholder="Buscar em todos os campos..." />
          <button class="btn btn-secondary btn-sm" id="btn-export">
            <i data-lucide="download"></i> Exportar CSV
          </button>
        </div>
      </div>
      <div class="table-wrapper" id="dados-table-wrap">
        <div class="skeleton" style="height:300px;margin:16px"></div>
      </div>
      <div class="pagination" id="dados-pagination"></div>
    </div>
  `;
  lucide.createIcons();

  document.getElementById("dados-search").addEventListener("input", _debounce(e => {
    _dadosSearch = e.target.value;
    _dadosPage = 1;
    _carregarDados();
  }, 350));

  document.getElementById("btn-export").addEventListener("click", () => {
    const params = new URLSearchParams(window.APP_FILTROS || {});
    if (_dadosSearch) params.set("search", _dadosSearch);
    window.location.href = "/api/export/csv?" + params.toString();
  });

  await _carregarDados();
}

async function _carregarDados() {
  const params = new URLSearchParams(window.APP_FILTROS || {});
  params.set("page", _dadosPage);
  params.set("size", _dadosSize);
  if (_dadosSearch) params.set("search", _dadosSearch);

  const wrap = document.getElementById("dados-table-wrap");
  if (wrap) wrap.innerHTML = '<div class="skeleton" style="height:250px;margin:16px"></div>';

  try {
    const res = await fetch("/api/dados?" + params.toString());
    const d = await res.json();
    if (!res.ok) throw new Error(d.erro || "Erro");

    _dadosTotal = d.total;
    _dadosTotalPages = d.total_pages;
    _dadosPage = d.page;

    document.getElementById("dados-count").textContent =
      `${fmtNum(d.total)} registros ${_dadosSearch ? "(filtrado)" : ""}`;

    _renderTabelaDados(d.dados);
    _renderPaginacao();
  } catch (err) {
    document.getElementById("dados-table-wrap").innerHTML =
      `<div class="empty-state"><p>${err.message}</p></div>`;
  }
}

const COLUNAS_DADOS = [
  { key: "CodigoVendedor", label: "Cód. Vend." },
  { key: "Vendedor",       label: "Vendedor" },
  { key: "CodigoProduto",  label: "SKU" },
  { key: "Produto",        label: "Produto" },
  { key: "Quantidade",     label: "Qtde" },
  { key: "TotalPraticado", label: "Total" },
  { key: "CodigoPedido",   label: "Pedido" },
  { key: "Ciclo",          label: "Ciclo" },
  { key: "DataFaturamento",label: "Data" },
  { key: "Revendedor",     label: "Revendedor" },
  { key: "Papel",          label: "Papel" },
  { key: "PlanoPagamento", label: "Pagamento" },
  { key: "Unidade",        label: "Unidade" },
  { key: "classificacao_iaf", label: "IAF" },
  { key: "metodo_match",   label: "Match" },
];

function _renderTabelaDados(lista) {
  const wrap = document.getElementById("dados-table-wrap");
  if (!wrap) return;

  if (!lista || !lista.length) {
    wrap.innerHTML = '<div class="empty-state"><p>Nenhum dado encontrado.</p></div>';
    return;
  }

  const thead = COLUNAS_DADOS.map(c => `<th>${c.label}</th>`).join("");

  const monoFields = new Set(["CodigoVendedor","CodigoProduto","CodigoPedido","Quantidade","TotalPraticado"]);
  const truncFields = new Set(["Produto","Revendedor","Vendedor"]);

  const tbody = lista.map(row => {
    const cells = COLUNAS_DADOS.map(c => {
      let val = row[c.key] ?? "";
      let cls = "";
      let style = "";

      if (c.key === "TotalPraticado") { val = fmtBRL(val); cls = "mono"; style = "text-align:right"; }
      else if (c.key === "Quantidade") { val = fmtNum(val); cls = "mono"; style = "text-align:right"; }
      else if (monoFields.has(c.key)) { cls = "mono secondary"; }
      else if (truncFields.has(c.key)) { style = "max-width:160px;overflow:hidden;text-overflow:ellipsis"; }

      if (c.key === "classificacao_iaf") {
        val = _badgeClfSmall(val);
      } else if (c.key === "metodo_match") {
        val = _badgeMatchSmall(val);
      }

      return `<td class="${cls}" style="${style}">${val}</td>`;
    }).join("");
    return `<tr>${cells}</tr>`;
  }).join("");

  wrap.innerHTML = `
    <table>
      <thead><tr>${thead}</tr></thead>
      <tbody>${tbody}</tbody>
    </table>
  `;
}

function _renderPaginacao() {
  const pag = document.getElementById("dados-pagination");
  if (!pag) return;

  const inicio = (_dadosPage - 1) * _dadosSize + 1;
  const fim = Math.min(_dadosPage * _dadosSize, _dadosTotal);

  const maxBtns = 5;
  let startPg = Math.max(1, _dadosPage - Math.floor(maxBtns / 2));
  let endPg   = Math.min(_dadosTotalPages, startPg + maxBtns - 1);
  if (endPg - startPg < maxBtns - 1) startPg = Math.max(1, endPg - maxBtns + 1);

  const btns = [];
  if (startPg > 1) btns.push(`<button class="btn-page" data-pg="1">1</button>`);
  if (startPg > 2) btns.push(`<span style="color:var(--text-tertiary);padding:0 4px">…</span>`);
  for (let p = startPg; p <= endPg; p++) {
    btns.push(`<button class="btn-page ${p === _dadosPage ? "active" : ""}" data-pg="${p}">${p}</button>`);
  }
  if (endPg < _dadosTotalPages - 1) btns.push(`<span style="color:var(--text-tertiary);padding:0 4px">…</span>`);
  if (endPg < _dadosTotalPages) btns.push(`<button class="btn-page" data-pg="${_dadosTotalPages}">${fmtNum(_dadosTotalPages)}</button>`);

  pag.innerHTML = `
    <span class="pagination-info">Exibindo ${fmtNum(inicio)}–${fmtNum(fim)} de ${fmtNum(_dadosTotal)}</span>
    <div class="pagination-controls">
      <button class="btn-page" data-pg="${_dadosPage - 1}" ${_dadosPage <= 1 ? "disabled" : ""}>‹</button>
      ${btns.join("")}
      <button class="btn-page" data-pg="${_dadosPage + 1}" ${_dadosPage >= _dadosTotalPages ? "disabled" : ""}>›</button>
    </div>
  `;

  pag.querySelectorAll("[data-pg]").forEach(btn => {
    btn.addEventListener("click", () => {
      const pg = parseInt(btn.dataset.pg);
      if (!isNaN(pg) && pg >= 1 && pg <= _dadosTotalPages) {
        _dadosPage = pg;
        _carregarDados();
      }
    });
  });
}

function _badgeClfSmall(clf) {
  const map = {
    "IAF Cabelos": "badge-cabelos",
    "IAF Make":    "badge-make",
    "Geral":       "badge-geral",
  };
  return `<span class="badge ${map[clf] || "badge-geral"}">${clf}</span>`;
}

function _badgeMatchSmall(m) {
  const map = {
    "sku":            ["badge-sku",    "SKU"],
    "fallback_siage": ["badge-siage",  "Siàge"],
    "fallback_make":  ["badge-make-fb","Make"],
    "nenhum":         ["badge-none",   "—"],
  };
  const [cls, label] = map[m] || ["badge-none", m];
  return `<span class="badge ${cls}">${label}</span>`;
}

function _debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}
