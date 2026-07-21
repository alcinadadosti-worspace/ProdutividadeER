/**
 * admin.js — Aba Admin: cadastro de vendedores e metas
 *
 * Acesso por senha, com escopo: a senha de cada unidade gerencia só o próprio
 * time; a senha geral enxerga as duas. As metas valem em cascata —
 * global → unidade → vendedor — e cada nível sobrescreve só os campos preenchidos.
 */

const META_LABELS = {
  multimarca:  "Multimarca",
  iaf_cabelos: "IAF Cabelos",
  iaf_make:    "IAF Make",
};
const META_CAMPOS = Object.keys(META_LABELS);

let _admin = null;

async function renderAdmin() {
  const page = document.getElementById("page-admin");
  page.innerHTML = `
    <div class="page-header">
      <div class="page-title">Admin</div>
      <div class="page-subtitle">Cadastro de vendedores · Metas por unidade e individuais</div>
    </div>
    <div class="skeleton" style="height:280px;border-radius:10px"></div>
  `;
  lucide.createIcons();

  try {
    const res = await fetch("/api/admin/cadastro");
    _admin = await res.json();
    if (!res.ok) throw new Error(_admin.erro || "Erro ao carregar cadastro");
  } catch (err) {
    page.innerHTML = `<div class="empty-state"><p>${err.message}</p></div>`;
    lucide.createIcons();
    return;
  }

  if (!_admin.escopo) _renderAdminLogin();
  else                _renderAdminPainel();
}

// ─── Tela de senha ──────────────────────────────────────────────────────────
function _renderAdminLogin() {
  const page = document.getElementById("page-admin");
  page.innerHTML = `
    <div class="page-header">
      <div class="page-title">Admin</div>
      <div class="page-subtitle">Área restrita — informe a senha da sua unidade</div>
    </div>
    <div class="admin-login">
      <div class="admin-login-box">
        <i data-lucide="lock" class="admin-login-icon"></i>
        <div class="admin-login-title">Gerenciar vendedores e metas</div>
        <div class="admin-login-sub">
          Cada unidade tem sua senha e gerencia apenas o próprio time.
        </div>
        <input type="password" id="admin-senha" class="admin-input" placeholder="Senha" autocomplete="current-password" />
        <div id="admin-login-erro" class="admin-erro hidden"></div>
        <button class="btn-primary" id="admin-entrar" style="width:100%;justify-content:center">
          <i data-lucide="log-in"></i> Entrar
        </button>
      </div>
    </div>
  `;
  lucide.createIcons();

  const input = document.getElementById("admin-senha");
  const erro  = document.getElementById("admin-login-erro");

  const entrar = async () => {
    const senha = input.value.trim();
    if (!senha) return;
    erro.classList.add("hidden");
    try {
      const res = await fetch("/api/admin/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ senha }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.erro || "Senha incorreta.");
      showToast("Acesso liberado ✓", "success");
      renderAdmin();
    } catch (err) {
      erro.textContent = err.message;
      erro.classList.remove("hidden");
      input.value = "";
      input.focus();
    }
  };

  document.getElementById("admin-entrar").addEventListener("click", entrar);
  input.addEventListener("keydown", e => { if (e.key === "Enter") entrar(); });
  input.focus();
}

// ─── Painel ─────────────────────────────────────────────────────────────────
function _renderAdminPainel() {
  const page = document.getElementById("page-admin");
  const d = _admin;
  const escopoLabel = d.escopo === "*" ? "Todas as unidades" : d.escopo;

  const avisoGh = d.github_ativo ? "" : `
    <div class="metas-alerta">
      <i data-lucide="triangle-alert" style="width:15px;height:15px;flex-shrink:0"></i>
      <span>GITHUB_TOKEN não configurado — as alterações ficam só no disco desta máquina e podem se perder no próximo deploy.</span>
    </div>
  `;

  page.innerHTML = `
    <div class="page-header admin-header">
      <div>
        <div class="page-title">Admin</div>
        <div class="page-subtitle">Cadastro de vendedores · Metas por unidade e individuais</div>
      </div>
      <div class="admin-escopo">
        <span class="admin-escopo-badge"><i data-lucide="shield-check"></i> ${escopoLabel}</span>
        <button class="btn-ghost btn-sm" id="admin-sair"><i data-lucide="log-out"></i> Sair</button>
      </div>
    </div>

    ${avisoGh}

    <div class="admin-secao">
      <div class="admin-secao-titulo">
        <i data-lucide="target"></i> Metas
        <span class="admin-secao-hint">Vendedor sobrescreve unidade, que sobrescreve a global. Campo vazio = herda o nível de cima.</span>
      </div>
      <div class="admin-metas-grid" id="admin-metas-grid"></div>
    </div>

    <div class="admin-secao">
      <div class="admin-secao-titulo">
        <i data-lucide="user-plus"></i> Adicionar vendedor
        <span class="admin-secao-hint">O nome precisa ser idêntico ao que vem na planilha, senão as vendas não batem.</span>
      </div>
      <div class="admin-form" id="admin-form-add"></div>
    </div>

    <div class="admin-secao">
      <div class="admin-secao-titulo">
        <i data-lucide="users"></i> Vendedores cadastrados
        <span class="admin-secao-hint" id="admin-qtd"></span>
      </div>
      <div class="table-card">
        <div class="table-wrapper" id="admin-tabela"></div>
      </div>
    </div>
  `;

  document.getElementById("admin-sair").addEventListener("click", async () => {
    await fetch("/api/admin/logout", { method: "POST" });
    _admin = null;
    renderAdmin();
  });

  _renderMetasCards();
  _renderFormAdd();
  _renderTabelaCadastro();
  lucide.createIcons();
}

// ─── Cards de metas (global + unidades) ─────────────────────────────────────
function _renderMetasCards() {
  const grid = document.getElementById("admin-metas-grid");
  const d = _admin;
  const cards = [];

  if (d.pode_meta_global) {
    cards.push(_cardMetaEditavel({
      id: "global",
      titulo: "Meta global",
      sub: "Base para todo o grupo",
      valores: d.metas_globais,
      herdado: null,
      obrigatorio: true,
    }));
  }

  for (const un of d.unidades) {
    cards.push(_cardMetaEditavel({
      id: `un:${un}`,
      titulo: un,
      sub: "Sobrescreve a meta global",
      valores: d.metas_unidade[un] || {},
      herdado: d.metas_globais,
      obrigatorio: false,
    }));
  }

  grid.innerHTML = cards.join("");

  grid.querySelectorAll(".admin-meta-salvar").forEach(btn => {
    btn.addEventListener("click", () => _salvarMetasCard(btn.dataset.card));
  });
}

function _cardMetaEditavel({ id, titulo, sub, valores, herdado, obrigatorio }) {
  const inputs = META_CAMPOS.map(campo => {
    const v = valores[campo];
    const temValor = v !== undefined && v !== null;
    const placeholder = herdado ? `herda ${herdado[campo]}` : "";
    return `
      <label class="admin-meta-campo">
        <span>${META_LABELS[campo]}</span>
        <div class="admin-meta-input-wrap">
          <input type="number" class="admin-input admin-input-sm" step="0.1" min="0" max="100"
                 data-card="${id}" data-campo="${campo}"
                 value="${temValor ? v : ""}" placeholder="${placeholder}" />
          <span class="admin-meta-sufixo">%</span>
        </div>
      </label>
    `;
  }).join("");

  return `
    <div class="admin-meta-card">
      <div class="admin-meta-card-head">
        <div class="admin-meta-card-titulo">${titulo}</div>
        <div class="admin-meta-card-sub">${sub}${obrigatorio ? "" : " · vazio = herda"}</div>
      </div>
      <div class="admin-meta-campos">${inputs}</div>
      <button class="btn-primary btn-sm admin-meta-salvar" data-card="${id}">
        <i data-lucide="save"></i> Salvar
      </button>
    </div>
  `;
}

async function _salvarMetasCard(cardId) {
  const metas = {};
  document.querySelectorAll(`.admin-input[data-card="${CSS.escape(cardId)}"]`).forEach(inp => {
    const val = inp.value.trim();
    metas[inp.dataset.campo] = val === "" ? null : val;
  });

  const body = cardId === "global"
    ? { nivel: "global", metas }
    : { nivel: "unidade", unidade: cardId.slice(3), metas };

  await _postAdmin("/api/admin/metas", body, "Metas salvas ✓");
}

// ─── Formulário de adicionar ────────────────────────────────────────────────
function _renderFormAdd() {
  const wrap = document.getElementById("admin-form-add");
  const opcoes = _admin.unidades.map(u => `<option value="${u}">${u}</option>`).join("");

  wrap.innerHTML = `
    <label class="admin-form-campo admin-form-campo-larga">
      <span>Nome (exatamente como na planilha)</span>
      <input type="text" id="add-nome" class="admin-input" placeholder="Ex.: AMANDA DE ARAUJO SANTOS" />
    </label>
    <label class="admin-form-campo">
      <span>Slack ID</span>
      <input type="text" id="add-slack" class="admin-input" placeholder="Ex.: U0BGA5QHHLJ" />
    </label>
    <label class="admin-form-campo">
      <span>Unidade</span>
      <select id="add-unidade" class="admin-input">${opcoes}</select>
    </label>
    <button class="btn-primary" id="add-btn"><i data-lucide="plus"></i> Adicionar</button>
  `;

  document.getElementById("add-btn").addEventListener("click", async () => {
    const nome    = document.getElementById("add-nome").value.trim();
    const slack   = document.getElementById("add-slack").value.trim();
    const unidade = document.getElementById("add-unidade").value;

    if (!nome)  return showToast("Informe o nome do vendedor.", "error");
    if (!slack) return showToast("Informe o Slack ID.", "error");

    const ok = await _postAdmin("/api/admin/vendedor",
      { nome, slack_id: slack, unidade },
      `${nome} cadastrado ✓`);
    if (ok) {
      document.getElementById("add-nome").value = "";
      document.getElementById("add-slack").value = "";
    }
  });
}

// ─── Tabela de vendedores ───────────────────────────────────────────────────
// Nome com sufixo "Cadastro" de propósito: todos os scripts da SPA dividem o
// mesmo escopo global, e vendedores.js já tem uma _renderTabelaVendedores.
// Repetir o nome aqui sobrescreveria a de lá e quebraria a aba Vendedores.
function _renderTabelaCadastro() {
  const wrap = document.getElementById("admin-tabela");
  const lista = _admin.vendedores || [];
  document.getElementById("admin-qtd").textContent =
    `${lista.length} ${lista.length === 1 ? "vendedor" : "vendedores"}`;

  if (!lista.length) {
    wrap.innerHTML = `<div class="empty-state" style="padding:32px"><p>Nenhum vendedor cadastrado ainda.</p></div>`;
    return;
  }

  const podeMover = _admin.escopo === "*";

  const rows = lista.map(v => {
    const nomeAttr = encodeURIComponent(v.nome);
    const unidadeCel = podeMover
      ? `<select class="admin-input admin-input-sm adm-unidade" data-nome="${nomeAttr}">
           ${_admin.unidades.map(u => `<option value="${u}" ${u === v.unidade ? "selected" : ""}>${u}</option>`).join("")}
         </select>`
      : `<span class="admin-cel-texto">${v.unidade}</span>`;

    const metasCels = META_CAMPOS.map(campo => {
      const individual = (v.metas || {})[campo];
      const temIndividual = individual !== undefined && individual !== null;
      const origem = (v.metas_origem || {})[campo] || "global";
      const efetiva = (v.metas_efetivas || {})[campo];
      return `
        <td>
          <div class="admin-meta-input-wrap">
            <input type="number" step="0.1" min="0" max="100"
                   class="admin-input admin-input-sm adm-meta ${temIndividual ? "adm-meta-custom" : ""}"
                   data-nome="${nomeAttr}" data-campo="${campo}"
                   value="${temIndividual ? individual : ""}"
                   placeholder="${efetiva}"
                   title="${temIndividual ? "Meta individual" : `Herdado (${origem === "unidade" ? "unidade" : "global"}): ${efetiva}%`}" />
            <span class="admin-meta-sufixo">%</span>
          </div>
        </td>
      `;
    }).join("");

    return `
      <tr data-nome="${nomeAttr}">
        <td><span style="font-weight:500">${v.nome}</span></td>
        <td>${unidadeCel}</td>
        <td><input type="text" class="admin-input admin-input-sm adm-slack" data-nome="${nomeAttr}" value="${v.slack_id || ""}" placeholder="U..." /></td>
        ${metasCels}
        <td>
          <div class="admin-acoes">
            <button class="btn-icon adm-salvar" data-nome="${nomeAttr}" title="Salvar alterações desta linha">
              <i data-lucide="save"></i>
            </button>
            <button class="btn-icon adm-remover" data-nome="${nomeAttr}" title="Remover vendedor">
              <i data-lucide="trash-2" style="color:var(--accent-red)"></i>
            </button>
          </div>
        </td>
      </tr>
    `;
  }).join("");

  wrap.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Vendedor</th>
          <th>Unidade</th>
          <th>Slack ID</th>
          ${META_CAMPOS.map(c => `<th title="Vazio = herda da unidade/global">${META_LABELS[c]}</th>`).join("")}
          <th style="text-align:right">Ações</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;

  wrap.querySelectorAll(".adm-salvar").forEach(btn => {
    btn.addEventListener("click", () => _salvarLinha(btn.dataset.nome));
  });
  wrap.querySelectorAll(".adm-remover").forEach(btn => {
    btn.addEventListener("click", () => _removerVendedor(btn.dataset.nome));
  });

  lucide.createIcons();
}

async function _salvarLinha(nomeAttr) {
  const nome = decodeURIComponent(nomeAttr);
  const sel  = `[data-nome="${CSS.escape(nomeAttr)}"]`;

  const metas = {};
  document.querySelectorAll(`.adm-meta${sel}`).forEach(inp => {
    const val = inp.value.trim();
    metas[inp.dataset.campo] = val === "" ? null : val;
  });

  const body = {
    nome,
    slack_id: document.querySelector(`.adm-slack${sel}`).value.trim(),
    metas,
  };
  const selUnidade = document.querySelector(`.adm-unidade${sel}`);
  if (selUnidade) body.unidade = selUnidade.value;

  await _postAdmin("/api/admin/vendedor/editar", body, `${nome} atualizado ✓`);
}

async function _removerVendedor(nomeAttr) {
  const nome = decodeURIComponent(nomeAttr);
  if (!confirm(`Remover ${nome} do cadastro?\n\nEle sai da aba Metas e do KPI "Pedidos com Vendedor". As vendas na planilha não são apagadas.`)) return;
  await _postAdmin("/api/admin/vendedor/remover", { nome }, `${nome} removido ✓`);
}

// ─── Helper de POST + recarga ───────────────────────────────────────────────
async function _postAdmin(url, body, msgSucesso) {
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    // Sessão caiu por inatividade: voltar para a tela de senha, senão o painel
    // continua aberto e cada clique falha de novo sem explicar por quê. Vai
    // pelo marcador "expirado", e não pelo 403, porque 403 também é o erro de
    // permissão (senha de unidade no time da outra) — nesse a sessão está viva
    // e derrubar o login seria só atrapalhar.
    if (data.expirado) {
      showToast("Sessão expirada por inatividade. Entre novamente.", "error");
      _admin = null;
      await renderAdmin();
      return false;
    }
    if (!res.ok) throw new Error(data.erro || "Erro ao salvar");
    showToast(msgSucesso, "success");
    if (data.aviso) showToast(data.aviso, "info");
    await renderAdmin();
    return true;
  } catch (err) {
    showToast(err.message, "error");
    return false;
  }
}
