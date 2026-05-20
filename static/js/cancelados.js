/**
 * cancelados.js — Gestão da lista permanente de pedidos cancelados
 *
 * Componentes:
 *  • Modal "Pergunta de cancelados" disparado pelo upload (antes de processar)
 *  • Página /cancelados com a lista atual, adição/remoção e detalhe das linhas
 */

// ─── Estado do modal ──────────────────────────────────────────────────────────
let _modalCancCallback = null;   // continuação após o usuário concluir o modal
let _modalCancAdicionados = [];  // códigos adicionados nesta sessão do modal

// ─── Helpers de API ──────────────────────────────────────────────────────────
async function _cancListar() {
  const r = await fetch("/api/cancelados");
  return r.json();
}

async function _cancAdicionar(codigos) {
  const r = await fetch("/api/cancelados", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ codigos }),
  });
  return r.json();
}

async function _cancRemover(codigo) {
  const r = await fetch(`/api/cancelados/${encodeURIComponent(codigo)}`, { method: "DELETE" });
  return r.json();
}

async function _cancDados() {
  const r = await fetch("/api/cancelados/dados");
  return r.json();
}

// ─── Modal disparado pelo upload ─────────────────────────────────────────────
/**
 * Mostra o modal "Existe algum pedido cancelado?" e chama `onConcluir()`
 * quando o usuário terminar (Não / Concluir após adicionar).
 */
function abrirModalCanceladosPergunta(onConcluir) {
  _modalCancCallback = onConcluir || (() => {});
  _modalCancAdicionados = [];

  const modal = document.getElementById("modal-cancelados");
  if (!modal) {
    console.error("Modal de cancelados não encontrado no DOM");
    _modalCancCallback();
    return;
  }
  modal.classList.remove("hidden");
  _renderModalCancPergunta();
}

function _fecharModalCanc() {
  document.getElementById("modal-cancelados")?.classList.add("hidden");
}

function _renderModalCancPergunta() {
  const body = document.getElementById("modal-canc-body");
  const footer = document.getElementById("modal-canc-footer");
  document.getElementById("modal-canc-title").textContent = "Existe algum pedido cancelado?";
  document.getElementById("modal-canc-sub").textContent =
    "Códigos informados aqui são excluídos da análise — permanentemente.";

  body.innerHTML = `
    <div class="canc-pergunta">
      <p class="modal-info">
        Pedidos cancelados não devem entrar nos KPIs do dashboard. Se você sabe
        de algum pedido nesta planilha (ou nas próximas) que foi cancelado pelo
        Boticário, registre o código aqui — ele ficará marcado <strong>para
        sempre</strong>, mesmo em planilhas futuras.
      </p>
      <p class="modal-info" style="margin-top:8px">
        Códigos já registrados: <strong id="canc-pergunta-total">…</strong>.
      </p>
    </div>
  `;

  footer.innerHTML = `
    <button class="btn-ghost" id="btn-canc-nao">Não, prosseguir</button>
    <button class="btn-primary" id="btn-canc-sim">
      <i data-lucide="ban"></i> Sim, informar agora
    </button>
  `;
  lucide.createIcons();

  // Buscar contagem atual para mostrar no rodapé do texto
  _cancListar().then(d => {
    const span = document.getElementById("canc-pergunta-total");
    if (span) span.textContent = `${d.total} código${d.total === 1 ? "" : "s"}`;
  }).catch(() => {});

  document.getElementById("btn-canc-nao").addEventListener("click", () => {
    _fecharModalCanc();
    const cb = _modalCancCallback; _modalCancCallback = null;
    if (cb) cb();
  });
  document.getElementById("btn-canc-sim").addEventListener("click", () => {
    _renderModalCancEditor();
  });
}

async function _renderModalCancEditor() {
  const body = document.getElementById("modal-canc-body");
  const footer = document.getElementById("modal-canc-footer");
  document.getElementById("modal-canc-title").textContent = "Pedidos Cancelados";
  document.getElementById("modal-canc-sub").textContent =
    "Digite o código (9 dígitos) e tecle Enter ou clique em Adicionar.";

  body.innerHTML = `
    <div class="canc-editor">
      <div class="canc-add-row">
        <input type="text" id="canc-input" class="canc-input"
               inputmode="numeric" maxlength="11"
               placeholder="Ex: 503.638.930 ou 503638930" />
        <button class="btn-primary btn-sm" id="canc-add-btn">
          <i data-lucide="plus"></i> Adicionar
        </button>
      </div>
      <div class="canc-feedback" id="canc-feedback"></div>
      <div class="canc-list-header">Códigos registrados</div>
      <div class="canc-list" id="canc-list">
        <div class="skeleton" style="height:120px;border-radius:8px"></div>
      </div>
    </div>
  `;

  footer.innerHTML = `
    <button class="btn-primary" id="btn-canc-concluir">
      <i data-lucide="check"></i> Concluir e processar
    </button>
  `;
  lucide.createIcons();

  document.getElementById("canc-input").addEventListener("keydown", e => {
    if (e.key === "Enter") { e.preventDefault(); _modalCancAddCodigo(); }
  });
  document.getElementById("canc-add-btn").addEventListener("click", _modalCancAddCodigo);
  document.getElementById("btn-canc-concluir").addEventListener("click", () => {
    _fecharModalCanc();
    const cb = _modalCancCallback; _modalCancCallback = null;
    if (cb) cb();
  });

  await _modalCancRecarregarLista();
}

async function _modalCancRecarregarLista() {
  const wrap = document.getElementById("canc-list");
  if (!wrap) return;
  try {
    const d = await _cancListar();
    if (!d.cancelados?.length) {
      wrap.innerHTML = `<div class="empty-state" style="padding:20px">
        <p>Nenhum código registrado ainda.</p>
      </div>`;
      return;
    }
    wrap.innerHTML = d.cancelados.map(cod => `
      <div class="canc-chip ${_modalCancAdicionados.includes(cod) ? "is-new" : ""}">
        <span class="canc-chip-codigo">${_fmtCodigoPedido(cod)}</span>
        ${_modalCancAdicionados.includes(cod) ? '<span class="canc-chip-tag">novo</span>' : ''}
        <button class="canc-chip-rm" data-cod="${cod}" title="Remover">
          <i data-lucide="x"></i>
        </button>
      </div>
    `).join("");
    lucide.createIcons();
    wrap.querySelectorAll(".canc-chip-rm").forEach(btn => {
      btn.addEventListener("click", async () => {
        const cod = btn.dataset.cod;
        const r = await _cancRemover(cod);
        if (!r.ok) {
          _modalCancFeedback("Não foi possível remover: " + (r.erro || ""), "error");
          return;
        }
        _modalCancAdicionados = _modalCancAdicionados.filter(c => c !== cod);
        _modalCancFeedback(`Código ${_fmtCodigoPedido(cod)} removido.`, "info");
        _modalCancRecarregarLista();
      });
    });
  } catch (err) {
    wrap.innerHTML = `<div class="empty-state"><p>Erro: ${err.message}</p></div>`;
  }
}

async function _modalCancAddCodigo() {
  const inp = document.getElementById("canc-input");
  const valor = (inp?.value || "").trim();
  if (!valor) return;
  const limpo = valor.replace(/\D/g, "");
  if (limpo.length !== 9) {
    _modalCancFeedback("O código deve ter exatamente 9 dígitos.", "error");
    return;
  }
  const r = await _cancAdicionar([limpo]);
  if (r.adicionados?.length) {
    _modalCancAdicionados.push(...r.adicionados);
    let msg = `Código ${_fmtCodigoPedido(limpo)} adicionado.`;
    if (r.linhas_movidas) {
      msg += ` ${r.linhas_movidas} linha${r.linhas_movidas === 1 ? "" : "s"} da planilha atual foi/foram movida(s) para a aba Cancelados.`;
    }
    _modalCancFeedback(msg, "success");
    // Atualiza o badge da sidebar caso linhas tenham sido movidas a partir de
    // dados já em memória (cenário de re-upload).
    if (r.linhas_movidas) atualizarStatusBadge_AposCancelar();
  } else if (r.rejeitados?.length) {
    _modalCancFeedback(`Rejeitado: ${r.rejeitados[0].motivo}.`, "error");
  } else {
    _modalCancFeedback("Nada para adicionar.", "info");
  }
  inp.value = "";
  inp.focus();
  await _modalCancRecarregarLista();
}

function _modalCancFeedback(texto, tipo) {
  const el = document.getElementById("canc-feedback");
  if (!el) return;
  el.className = `canc-feedback canc-feedback-${tipo || "info"}`;
  el.textContent = texto;
}

function _fmtCodigoPedido(cod) {
  const s = String(cod || "").replace(/\D/g, "");
  if (s.length !== 9) return s;
  return `${s.slice(0,3)}.${s.slice(3,6)}.${s.slice(6,9)}`;
}

// Após adicionar/remover, o status badge pode estar desatualizado se já havia
// dados. Refaz o /api/status para refletir o novo número de registros.
async function atualizarStatusBadge_AposCancelar() {
  try {
    const r = await fetch("/api/status");
    const d = await r.json();
    if (d.tem_dados) atualizarStatusBadge(d.total_registros, d.ciclos);
  } catch (_) {}
}

// ─── Página /cancelados ──────────────────────────────────────────────────────
async function renderCancelados() {
  const page = document.getElementById("page-cancelados");
  page.innerHTML = `
    <div class="page-header">
      <div class="page-title">Pedidos Cancelados</div>
      <div class="page-subtitle">
        Lista permanente. Pedidos aqui não entram em nenhuma análise — vale para
        a planilha atual e para qualquer planilha futura.
      </div>
    </div>

    <div class="canc-page-cards" id="canc-cards"></div>

    <div class="table-card" style="margin-top:16px">
      <div class="table-toolbar">
        <span class="table-toolbar-title">Adicionar código</span>
      </div>
      <div style="padding:16px">
        <div class="canc-add-row">
          <input type="text" id="canc-page-input" class="canc-input"
                 inputmode="numeric" maxlength="11"
                 placeholder="Digite o código de 9 dígitos (ex: 503.638.930)" />
          <button class="btn-primary btn-sm" id="canc-page-add">
            <i data-lucide="plus"></i> Adicionar
          </button>
        </div>
        <div class="canc-feedback" id="canc-page-feedback"></div>
      </div>
    </div>

    <div class="table-card" style="margin-top:16px">
      <div class="table-toolbar">
        <span class="table-toolbar-title" id="canc-page-tabtitle">Pedidos registrados</span>
      </div>
      <div class="table-wrapper" id="canc-page-table">
        <div class="skeleton" style="height:200px;margin:16px"></div>
      </div>
    </div>
  `;
  lucide.createIcons();

  document.getElementById("canc-page-input").addEventListener("keydown", e => {
    if (e.key === "Enter") { e.preventDefault(); _pageCancAdd(); }
  });
  document.getElementById("canc-page-add").addEventListener("click", _pageCancAdd);

  await _pageCancRecarregar();
}

async function _pageCancAdd() {
  const inp = document.getElementById("canc-page-input");
  const valor = (inp?.value || "").trim();
  if (!valor) return;
  const limpo = valor.replace(/\D/g, "");
  if (limpo.length !== 9) {
    _pageCancFeedback("O código deve ter exatamente 9 dígitos.", "error");
    return;
  }
  const r = await _cancAdicionar([limpo]);
  if (r.adicionados?.length) {
    let msg = `Código ${_fmtCodigoPedido(limpo)} adicionado.`;
    if (r.linhas_movidas) {
      msg += ` ${r.linhas_movidas} linha${r.linhas_movidas === 1 ? "" : "s"} excluída(s) da análise.`;
    }
    _pageCancFeedback(msg, "success");
    atualizarStatusBadge_AposCancelar();
  } else if (r.rejeitados?.length) {
    _pageCancFeedback(`Rejeitado: ${r.rejeitados[0].motivo}.`, "error");
  } else {
    _pageCancFeedback("Nada para adicionar.", "info");
  }
  inp.value = "";
  inp.focus();
  await _pageCancRecarregar();
}

function _pageCancFeedback(texto, tipo) {
  const el = document.getElementById("canc-page-feedback");
  if (!el) return;
  el.className = `canc-feedback canc-feedback-${tipo || "info"}`;
  el.textContent = texto;
}

async function _pageCancRecarregar() {
  let dados;
  try {
    dados = await _cancDados();
  } catch (err) {
    document.getElementById("canc-page-table").innerHTML =
      `<div class="empty-state"><p>Erro: ${err.message}</p></div>`;
    return;
  }

  // Cards de resumo
  const cards = document.getElementById("canc-cards");
  cards.innerHTML = `
    <div class="kpi-card">
      <div class="kpi-label">Códigos registrados</div>
      <div class="kpi-value">${fmtNum(dados.total_codigos)}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Linhas excluídas</div>
      <div class="kpi-value">${fmtNum(dados.total_linhas)}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Faturamento excluído</div>
      <div class="kpi-value">${fmtBRL(dados.total_faturado_excluido)}</div>
    </div>
  `;

  // Tabela
  const wrap = document.getElementById("canc-page-table");
  document.getElementById("canc-page-tabtitle").textContent =
    `Pedidos registrados (${dados.total_codigos})`;

  if (!dados.cancelados?.length) {
    wrap.innerHTML = `<div class="empty-state" style="padding:32px"><p>Nenhum pedido cancelado registrado.</p></div>`;
    return;
  }

  const rows = dados.cancelados.map((c, idx) => {
    const badge = c.encontrado
      ? `<span class="badge badge-make">${c.total_linhas} linha${c.total_linhas === 1 ? "" : "s"}</span>`
      : `<span class="badge badge-none">Sem dados na planilha</span>`;
    return `
      <tr class="canc-row" data-idx="${idx}">
        <td class="mono">${_fmtCodigoPedido(c.codigo)}</td>
        <td>${c.vendedor || "—"}</td>
        <td>${c.revendedor || "—"}</td>
        <td class="mono">${c.ciclo || "—"}</td>
        <td class="mono">${c.data || "—"}</td>
        <td class="mono" style="text-align:right">${fmtNum(c.qtd_itens)}</td>
        <td class="mono" style="text-align:right">${fmtBRL(c.total_faturado)}</td>
        <td>${badge}</td>
        <td style="text-align:right;white-space:nowrap">
          ${c.encontrado ? `<button class="btn-icon canc-toggle" data-idx="${idx}" title="Ver linhas">
            <i data-lucide="chevron-down"></i>
          </button>` : ""}
          <button class="btn-icon canc-rm" data-cod="${c.codigo}" title="Remover da lista">
            <i data-lucide="trash-2"></i>
          </button>
        </td>
      </tr>
      <tr class="canc-detail hidden" data-detail="${idx}">
        <td colspan="9" style="padding:0;background:var(--bg-tertiary)">
          ${_renderLinhasCanc(c.linhas)}
        </td>
      </tr>
    `;
  }).join("");

  wrap.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Código do pedido</th>
          <th>Vendedor</th>
          <th>Revendedor</th>
          <th>Ciclo</th>
          <th>Data</th>
          <th style="text-align:right">Qtde</th>
          <th style="text-align:right">Total</th>
          <th>Status</th>
          <th></th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
  lucide.createIcons();

  wrap.querySelectorAll(".canc-toggle").forEach(btn => {
    btn.addEventListener("click", () => {
      const idx = btn.dataset.idx;
      const det = wrap.querySelector(`tr[data-detail="${idx}"]`);
      if (!det) return;
      det.classList.toggle("hidden");
      const icon = btn.querySelector("i");
      if (icon) icon.setAttribute("data-lucide",
        det.classList.contains("hidden") ? "chevron-down" : "chevron-up");
      lucide.createIcons();
    });
  });

  wrap.querySelectorAll(".canc-rm").forEach(btn => {
    btn.addEventListener("click", async () => {
      const cod = btn.dataset.cod;
      if (!confirm(`Remover o código ${_fmtCodigoPedido(cod)} da lista de cancelados?\n\nAs linhas voltarão para a análise.`)) return;
      const r = await _cancRemover(cod);
      if (r.ok) {
        _pageCancFeedback(
          `Código ${_fmtCodigoPedido(cod)} removido. ${r.linhas_devolvidas} linha${r.linhas_devolvidas === 1 ? "" : "s"} devolvida(s) à análise.`,
          "info"
        );
        atualizarStatusBadge_AposCancelar();
        _pageCancRecarregar();
      } else {
        _pageCancFeedback("Erro: " + (r.erro || "falhou"), "error");
      }
    });
  });
}

function _renderLinhasCanc(linhas) {
  if (!linhas || !linhas.length) {
    return `<div style="padding:16px;color:var(--text-tertiary);font-size:12px">Sem itens.</div>`;
  }
  const rows = linhas.map(l => `
    <tr>
      <td class="mono secondary">${l.CodigoProduto || "—"}</td>
      <td>${l.Produto || "—"}</td>
      <td>${l.marca || "—"}</td>
      <td class="mono" style="text-align:right">${fmtNum(l.Quantidade || 0)}</td>
      <td class="mono" style="text-align:right">${fmtBRL(l.TotalPraticado || 0)}</td>
      <td>${l.NotaFiscal || "—"}</td>
      <td>${l.PlanoPagamento || "—"}</td>
      <td>${l.Unidade || "—"}</td>
    </tr>
  `).join("");
  return `
    <div style="padding:8px 16px 16px">
      <table class="canc-inner-table">
        <thead>
          <tr>
            <th>SKU</th>
            <th>Produto</th>
            <th>Marca</th>
            <th style="text-align:right">Qtde</th>
            <th style="text-align:right">Total</th>
            <th>NF</th>
            <th>Pagamento</th>
            <th>Unidade</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

// Bind do close do modal (DOM já tem o backdrop pronto no index.html).
// Fechar pelo X ou clicar fora do modal CANCELA a operação — só os botões
// explícitos (Não, prosseguir / Concluir e processar) seguem o fluxo.
function _modalCancCancelar() {
  _fecharModalCanc();
  _modalCancCallback = null;
  showToast("Processamento cancelado.", "info");
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("modal-canc-close")?.addEventListener("click", _modalCancCancelar);
  document.getElementById("modal-cancelados")?.addEventListener("click", e => {
    if (e.target === document.getElementById("modal-cancelados")) {
      _modalCancCancelar();
    }
  });
});
