/**
 * app.js — Router SPA + inicialização global
 */

// Garantir que lucide existe mesmo se CDN falhar
if (typeof lucide === "undefined") {
  window.lucide = { createIcons: () => {} };
  console.warn("Lucide CDN não carregou — ícones desabilitados.");
}

// ─── Estado global de filtros ─────────────────────────────────────────────
window.APP_FILTROS = {};

// ─── Páginas disponíveis ──────────────────────────────────────────────────
const PAGINAS = {
  upload:        { render: renderUpload,        semDados: true },
  dashboard:     { render: renderDashboard,     semDados: false },
  vendedores:    { render: renderVendedores,    semDados: false },
  revendedores:  { render: renderRevendedores,  semDados: false },
  comparativo:   { render: renderComparativo,   semDados: false },
  produtos:      { render: renderProdutos,      semDados: false },
  iaf:           { render: renderIaf,           semDados: false },
  metas:         { render: renderMetas,         semDados: false },
  dados:         { render: renderDados,         semDados: false },
};

let _paginaAtual = null;
let _temDados = false;

// ─── Inicialização ────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  // Criar container de toasts
  const toastContainer = document.createElement("div");
  toastContainer.id = "toast-container";
  document.body.appendChild(toastContainer);

  // Bind do drawer
  document.getElementById("drawer-close")?.addEventListener("click", fecharDrawer);
  document.getElementById("drawer-overlay")?.addEventListener("click", fecharDrawer);

  // Inicializar ícones
  lucide.createIcons();

  // Verificar se há dados em memória
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    _temDados = data.tem_dados;
    if (_temDados) {
      atualizarStatusBadge(data.total_registros, data.ciclos);
      // Popular filtros globais imediatamente (sem depender do dashboard carregar primeiro)
      fetch("/api/filtros").then(r => r.json()).then(f => _atualizarFiltrosBar(f)).catch(() => {});
    }
  } catch (e) {
    _temDados = false;
  }

  // Bind dos itens de navegação
  document.querySelectorAll(".nav-item").forEach(item => {
    item.addEventListener("click", e => {
      e.preventDefault();
      const pagina = item.dataset.page;
      navegarPara(pagina);
    });
  });

  // Bind limpar planilha
  document.getElementById("btn-limpar-planilha")?.addEventListener("click", limparPlanilha);

  // Bind limpar filtros
  document.getElementById("btn-limpar-filtros")?.addEventListener("click", () => {
    window.APP_FILTROS = {};
    document.querySelectorAll(".filter-chip").forEach(c => c.classList.remove("active"));
    const selVend = document.getElementById("select-vendedor");
    if (selVend) { selVend.value = ""; selVend.classList.remove("active"); }
    document.getElementById("btn-limpar-filtros").classList.add("hidden");
    if (_paginaAtual) navegarPara(_paginaAtual, true);
  });

  // Rota inicial
  const hash = window.location.hash.replace("#", "") || "upload";
  navegarPara(hash in PAGINAS ? hash : "upload");
});

// ─── Navegação ────────────────────────────────────────────────────────────
function navegarPara(pagina, forcar = false) {
  if (!PAGINAS[pagina]) pagina = "upload";

  // Se a página requer dados e não há dados, redirecionar ao upload
  if (!PAGINAS[pagina].semDados && !_temDados) {
    showToast("Importe uma planilha primeiro.", "error");
    pagina = "upload";
  }

  // Atualizar nav
  document.querySelectorAll(".nav-item").forEach(item => {
    item.classList.toggle("active", item.dataset.page === pagina);
  });

  // Mostrar/ocultar filtros bar
  const filtrosBar = document.getElementById("filtros-bar");
  if (pagina === "upload") {
    filtrosBar?.classList.add("hidden");
  } else {
    filtrosBar?.classList.remove("hidden");
  }

  // Ocultar todas as páginas
  document.querySelectorAll(".page").forEach(p => p.classList.add("hidden"));

  // Mostrar a página alvo
  const pageEl = document.getElementById(`page-${pagina}`);
  if (pageEl) pageEl.classList.remove("hidden");

  // Atualizar hash sem recarregar
  history.replaceState(null, "", "#" + pagina);
  _paginaAtual = pagina;

  // Renderizar
  if (forcar || pagina !== _paginaAtual) {
    PAGINAS[pagina].render();
  } else {
    PAGINAS[pagina].render();
  }
}

// ─── Filtros ──────────────────────────────────────────────────────────────
function toggleFiltro(tipo, valor) {
  if (window.APP_FILTROS[tipo] === valor) {
    delete window.APP_FILTROS[tipo];
  } else {
    window.APP_FILTROS[tipo] = valor;
  }

  // Atualizar visual dos chips
  document.querySelectorAll(`.filter-chip[data-tipo="${tipo}"]`).forEach(chip => {
    chip.classList.toggle("active", chip.dataset.valor === window.APP_FILTROS[tipo]);
  });

  // Mostrar/ocultar botão de limpar
  const temFiltros = Object.keys(window.APP_FILTROS).length > 0;
  document.getElementById("btn-limpar-filtros")?.classList.toggle("hidden", !temFiltros);

  // Re-renderizar página atual
  if (_paginaAtual && PAGINAS[_paginaAtual]) {
    PAGINAS[_paginaAtual].render();
  }
}

// ─── Status badge ──────────────────────────────────────────────────────────
function atualizarStatusBadge(total, ciclos) {
  _temDados = true;
  const badge = document.getElementById("status-badge");
  const text  = document.getElementById("status-text");
  if (badge) badge.className = "status-badge status-ok";
  if (text) {
    text.textContent = ciclos?.length
      ? `${ciclos.length} ciclo${ciclos.length > 1 ? "s" : ""} · ${fmtNum(total)} reg.`
      : `${fmtNum(total)} registros`;
  }
  document.getElementById("btn-limpar-planilha")?.classList.remove("hidden");
  lucide.createIcons();
}

// ─── Limpar planilha ───────────────────────────────────────────────────────
async function limparPlanilha() {
  try {
    await fetch("/api/limpar", { method: "POST" });
  } catch (_) {}

  _temDados = false;
  window.APP_FILTROS = {};

  const badge = document.getElementById("status-badge");
  const text  = document.getElementById("status-text");
  if (badge) badge.className = "status-badge status-empty";
  if (text)  text.textContent = "Sem dados";
  document.getElementById("btn-limpar-planilha")?.classList.add("hidden");
  document.getElementById("btn-limpar-filtros")?.classList.add("hidden");

  lucide.createIcons();
  navegarPara("upload");
}

// ─── Drawer vendedor ──────────────────────────────────────────────────────
function fecharDrawer() {
  document.getElementById("drawer-overlay")?.classList.add("hidden");
  const drawer = document.getElementById("vendedor-drawer");
  if (drawer) drawer.classList.add("hidden");
}

// ─── Toast notifications ──────────────────────────────────────────────────
function showToast(mensagem, tipo = "info") {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const icon = tipo === "error" ? "alert-circle" : "check-circle";
  const toast = document.createElement("div");
  toast.className = `toast ${tipo}`;
  toast.innerHTML = `<i data-lucide="${icon}"></i><span>${mensagem}</span>`;
  container.appendChild(toast);
  lucide.createIcons();

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(8px)";
    toast.style.transition = "all 200ms ease";
    setTimeout(() => toast.remove(), 200);
  }, 3500);
}
