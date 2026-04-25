/**
 * metas.js — Aba de Metas por Vendedor
 */

// ID Slack de teste — substitua pelo mapa real quando cada vendedor tiver o seu
const SLACK_TEST_ID = "U0895CZ8HU7";

let _metasData = null;
let _metasSort = { col: "nome", asc: true };
let _metasSearch = "";

async function renderMetas() {
  const page = document.getElementById("page-metas");
  page.innerHTML = `
    <div class="page-header">
      <div class="page-title">Metas por Vendedor</div>
      <div class="page-subtitle">% Multimarca · IAF Cabelos · IAF Make</div>
    </div>
    <div class="skeleton" style="height:400px;border-radius:10px"></div>
  `;
  lucide.createIcons();

  try {
    const params = new URLSearchParams(window.APP_FILTROS || {});
    const res = await fetch("/api/metas?" + params.toString());
    _metasData = await res.json();
    if (!res.ok) throw new Error(_metasData.erro || "Erro");
    _renderMetasPage(_metasData);
  } catch (err) {
    console.error("[Metas] Erro ao carregar:", err);
    page.innerHTML = `<div class="empty-state"><p>${err.message}</p></div>`;
    lucide.createIcons();
  }
}

function _renderMetasPage(d) {
  const page = document.getElementById("page-metas");
  const vendedores = d.vendedores || [];
  const metas = d.metas || {};

  const totalVend = vendedores.length;
  const qtdMult   = vendedores.filter(v => v.atingiu_multimarca).length;
  const qtdCab    = vendedores.filter(v => v.atingiu_cabelos).length;
  const qtdMake   = vendedores.filter(v => v.atingiu_make).length;

  const alertaCiclo = (d.qtd_ciclos_total > 1 && !d.ciclo_filtrado) ? `
    <div class="metas-alerta">
      <i data-lucide="triangle-alert" style="width:15px;height:15px;flex-shrink:0"></i>
      <span><strong>${d.qtd_ciclos_total} ciclos</strong> importados sem filtro de ciclo ativo — os números abaixo agregam todos os ciclos. Selecione um ciclo na barra de filtros para ver a meta de um período específico.</span>
    </div>
  ` : "";

  page.innerHTML = `
    <div class="page-header">
      <div class="page-title">Metas por Vendedor</div>
      <div class="page-subtitle">% Multimarca · IAF Cabelos · IAF Make</div>
    </div>

    ${alertaCiclo}

    <!-- Cards de resumo -->
    <div class="metas-summary-grid">
      ${_cardMeta("Multimarca", metas.multimarca, qtdMult, totalVend, "#4ADE80", "shopping-bag")}
      ${_cardMeta("IAF Cabelos", metas.iaf_cabelos, qtdCab, totalVend, "var(--accent-blue)", "droplets")}
      ${_cardMeta("IAF Make", metas.iaf_make, qtdMake, totalVend, "var(--accent-purple)", "sparkles")}
    </div>

    <!-- Tabela -->
    <div class="table-card">
      <div class="table-toolbar">
        <span class="table-toolbar-title" id="metas-count">${fmtNum(totalVend)} vendedores</span>
        <div class="table-toolbar-right">
          <button class="btn-ghost btn-sm" id="metas-enviar-todos">
            <i data-lucide="send"></i> Enviar para todos
          </button>
          <button class="btn-ghost btn-sm" id="metas-export"><i data-lucide="download"></i> Exportar CSV</button>
          <input type="text" class="search-input" id="metas-search" placeholder="Buscar vendedor..." />
        </div>
      </div>
      <div id="metas-progresso" class="metas-progresso hidden"></div>
      <div class="table-wrapper" id="metas-table-wrap"></div>
    </div>
  `;

  lucide.createIcons();
  _metasSearch = "";
  _renderTabelaMetas(vendedores, metas);

  document.getElementById("metas-search").addEventListener("input", e => {
    _metasSearch = e.target.value.toLowerCase();
    const filtrado = (_metasData.vendedores || []).filter(v =>
      v.nome.toLowerCase().includes(_metasSearch) || v.codigo.toLowerCase().includes(_metasSearch)
    );
    document.getElementById("metas-count").textContent = `${fmtNum(filtrado.length)} vendedores`;
    _renderTabelaMetas(filtrado, metas);
  });

  document.getElementById("metas-export").addEventListener("click", () => _exportarMetasCSV(vendedores, metas));

  document.getElementById("metas-enviar-todos").addEventListener("click", () => _enviarParaTodos(vendedores, metas));
}

async function _enviarParaTodos(vendedores, metas) {
  if (!vendedores.length) return;

  const btn = document.getElementById("metas-enviar-todos");
  const progresso = document.getElementById("metas-progresso");
  btn.disabled = true;
  btn.innerHTML = `<i data-lucide="loader" style="width:13px;height:13px;animation:spin 1s linear infinite"></i> Enviando...`;
  lucide.createIcons();

  progresso.classList.remove("hidden");
  progresso.innerHTML = `<span id="prog-texto">Enviando 0 / ${vendedores.length}...</span><div class="prog-bar-wrap"><div class="prog-bar" id="prog-bar" style="width:0%"></div></div>`;

  let enviados = 0, erros = 0;
  for (const v of vendedores) {
    const payload = {
      slack_user_id:    SLACK_TEST_ID,
      vendedor_nome:    v.nome,
      pct_multimarca:   v.pct_multimarca,
      pct_iaf_cabelos:  v.pct_iaf_cabelos,
      pct_iaf_make:     v.pct_iaf_make,
      meta_multimarca:  metas.multimarca,
      meta_iaf_cabelos: metas.iaf_cabelos,
      meta_iaf_make:    metas.iaf_make,
    };
    try {
      const res = await fetch("/api/slack/enviar", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = await res.json();
      if (!res.ok || result.erro) throw new Error(result.erro);
      enviados++;
      // Marca o botão individual da linha como enviado
      const btnLinha = document.querySelector(`.btn-slack[data-vdata*="${encodeURIComponent(v.nome).slice(0,20)}"]`);
      if (btnLinha) {
        btnLinha.innerHTML = `<i data-lucide="check" style="width:13px;height:13px;color:#4ADE80"></i>`;
        lucide.createIcons();
      }
    } catch (_) {
      erros++;
    }
    const pct = Math.round(((enviados + erros) / vendedores.length) * 100);
    document.getElementById("prog-bar").style.width = pct + "%";
    document.getElementById("prog-texto").textContent = `Enviando ${enviados + erros} / ${vendedores.length}...`;
  }

  const msg = erros
    ? `${enviados} enviados, ${erros} com erro`
    : `${enviados} mensagens enviadas no Slack ✓`;
  progresso.innerHTML = `<span style="color:${erros ? "var(--accent-yellow)" : "#4ADE80"}">${msg}</span>`;
  showToast(msg, erros ? "info" : "success");

  btn.disabled = false;
  btn.innerHTML = `<i data-lucide="send"></i> Enviar para todos`;
  lucide.createIcons();
}

function _cardMeta(titulo, meta, qtdAcima, total, cor, icone) {
  const pct = total ? (qtdAcima / total * 100) : 0;
  return `
    <div class="metas-card">
      <div class="metas-card-header">
        <i data-lucide="${icone}" style="color:${cor}"></i>
        <span class="metas-card-title">${titulo}</span>
        <span class="metas-card-meta">Meta: ${meta}%</span>
      </div>
      <div class="metas-card-value" style="color:${cor}">${qtdAcima}<span class="metas-card-denom"> / ${total}</span></div>
      <div class="metas-card-sub">vendedores atingiram a meta</div>
      <div style="margin-top:10px">
        <div style="height:6px;background:var(--border);border-radius:3px;overflow:hidden">
          <div style="width:${Math.min(pct,100)}%;height:100%;background:${cor};border-radius:3px;transition:width 0.4s"></div>
        </div>
        <div class="metas-card-pct">${pct.toFixed(0)}% do time</div>
      </div>
    </div>
  `;
}

function _renderTabelaMetas(lista, metas) {
  const wrap = document.getElementById("metas-table-wrap");
  if (!wrap) return;
  if (!lista.length) {
    wrap.innerHTML = '<div class="empty-state" style="padding:32px"><p>Nenhum vendedor encontrado.</p></div>';
    return;
  }

  const sorted = [...lista].sort((a, b) => {
    let va = a[_metasSort.col], vb = b[_metasSort.col];
    if (typeof va === "string") va = va.toLowerCase(), vb = vb.toLowerCase();
    if (va < vb) return _metasSort.asc ? -1 : 1;
    if (va > vb) return _metasSort.asc ? 1 : -1;
    return 0;
  });

  const th = (col, label, align = "left") => {
    const ativo = _metasSort.col === col;
    const seta = ativo ? (_metasSort.asc ? " ↑" : " ↓") : "";
    return `<th style="text-align:${align};cursor:pointer" data-sort="${col}">${label}${seta}</th>`;
  };

  const rows = sorted.map(v => {
    const metas_count = (v.atingiu_multimarca ? 1 : 0) + (v.atingiu_cabelos ? 1 : 0) + (v.atingiu_make ? 1 : 0);
    const tagCor = metas_count === 3 ? "#4ADE80" : metas_count === 2 ? "#FCD34D" : metas_count === 1 ? "#FB923C" : "#F87171";
    const vData = encodeURIComponent(JSON.stringify({
      slack_user_id:   SLACK_TEST_ID,
      vendedor_nome:   v.nome,
      pct_multimarca:  v.pct_multimarca,
      pct_iaf_cabelos: v.pct_iaf_cabelos,
      pct_iaf_make:    v.pct_iaf_make,
      meta_multimarca:  metas.multimarca,
      meta_iaf_cabelos: metas.iaf_cabelos,
      meta_iaf_make:    metas.iaf_make,
    }));
    return `
      <tr>
        <td>
          <div style="display:flex;align-items:center;gap:8px">
            <button
              class="btn-slack"
              data-vdata="${vData}"
              title="Enviar metas no Slack"
            ><i data-lucide="send" style="width:13px;height:13px"></i></button>
            <span style="font-weight:500">${v.nome}</span>
          </div>
        </td>
        <td style="text-align:center">
          <span style="background:${tagCor}22;color:${tagCor};border-radius:12px;padding:2px 10px;font-size:12px;font-weight:700">${metas_count}/3</span>
        </td>
        <td style="min-width:160px">${_barMeta(v.pct_multimarca, metas.multimarca, "#4ADE80")}</td>
        <td style="min-width:160px">${_barMeta(v.pct_iaf_cabelos, metas.iaf_cabelos, "var(--accent-blue)")}</td>
        <td style="min-width:160px">${_barMeta(v.pct_iaf_make, metas.iaf_make, "var(--accent-purple)")}</td>
      </tr>
    `;
  }).join("");

  wrap.innerHTML = `
    <table id="metas-tabela">
      <thead>
        <tr>
          ${th("nome", "Vendedor")}
          ${th("_metas", "Metas", "center")}
          ${th("pct_multimarca", "% Multimarca", "left")}
          ${th("pct_iaf_cabelos", "IAF Cabelos", "left")}
          ${th("pct_iaf_make", "IAF Make", "left")}
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;

  lucide.createIcons();

  // Delegação de eventos para os botões Slack
  wrap.querySelectorAll(".btn-slack").forEach(btn => {
    btn.addEventListener("click", async () => {
      const payload = JSON.parse(decodeURIComponent(btn.dataset.vdata));
      btn.disabled = true;
      btn.innerHTML = `<i data-lucide="loader" style="width:13px;height:13px;animation:spin 1s linear infinite"></i>`;
      lucide.createIcons();
      try {
        const res = await fetch("/api/slack/enviar", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const result = await res.json();
        if (!res.ok || result.erro) throw new Error(result.erro || "Erro ao enviar");
        btn.innerHTML = `<i data-lucide="check" style="width:13px;height:13px;color:#4ADE80"></i>`;
        lucide.createIcons();
        showToast(`Metas enviadas para ${payload.vendedor_nome} no Slack ✓`, "success");
        setTimeout(() => {
          btn.disabled = false;
          btn.innerHTML = `<i data-lucide="send" style="width:13px;height:13px"></i>`;
          lucide.createIcons();
        }, 3000);
      } catch (err) {
        btn.disabled = false;
        btn.innerHTML = `<i data-lucide="send" style="width:13px;height:13px"></i>`;
        lucide.createIcons();
        showToast(`Slack: ${err.message}`, "error");
      }
    });
  });

  document.querySelectorAll("#metas-tabela th[data-sort]").forEach(th => {
    th.addEventListener("click", () => {
      const col = th.dataset.sort;
      if (_metasSort.col === col) {
        _metasSort.asc = !_metasSort.asc;
      } else {
        _metasSort.col = col;
        _metasSort.asc = col === "nome";
      }
      const lista_atual = (_metasData.vendedores || []).filter(v =>
        !_metasSearch || v.nome.toLowerCase().includes(_metasSearch) || v.codigo.toLowerCase().includes(_metasSearch)
      );
      _renderTabelaMetas(lista_atual, _metasData.metas);
    });
  });
}

function _barMeta(valor, meta, cor) {
  const atingiu = valor >= meta;
  const barCor = atingiu ? cor : (valor >= meta * 0.9 ? "#FCD34D" : "#F87171");
  const pctBar = Math.min((valor / meta) * 100, 100);
  return `
    <div style="display:flex;align-items:center;gap:8px">
      <div style="flex:1;height:6px;background:var(--border);border-radius:3px;overflow:hidden">
        <div style="width:${pctBar}%;height:100%;background:${barCor};border-radius:3px"></div>
      </div>
      <span class="mono" style="color:${barCor};font-weight:600;min-width:44px;text-align:right">${valor.toFixed(1)}%</span>
      <span style="font-size:11px;color:var(--text-muted);min-width:36px">/ ${meta}%</span>
    </div>
  `;
}

function _exportarMetasCSV(lista, metas) {
  const header = ["Vendedor", "Código", "% Multimarca", `Meta Multimarca (${metas.multimarca}%)`, "Atingiu Multimarca",
    "IAF Cabelos %", `Meta Cabelos (${metas.iaf_cabelos}%)`, "Atingiu Cabelos",
    "IAF Make %", `Meta Make (${metas.iaf_make}%)`, "Atingiu Make", "Metas Atingidas"];
  const rows = lista.map(v => {
    const cnt = (v.atingiu_multimarca ? 1 : 0) + (v.atingiu_cabelos ? 1 : 0) + (v.atingiu_make ? 1 : 0);
    return [
      v.nome, v.codigo,
      v.pct_multimarca.toFixed(1), metas.multimarca, v.atingiu_multimarca ? "Sim" : "Não",
      v.pct_iaf_cabelos.toFixed(1), metas.iaf_cabelos, v.atingiu_cabelos ? "Sim" : "Não",
      v.pct_iaf_make.toFixed(1), metas.iaf_make, v.atingiu_make ? "Sim" : "Não",
      cnt + "/3",
    ].join(",");
  });
  const csv = [header.join(","), ...rows].join("\n");
  const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "metas_vendedores.csv"; a.click();
  URL.revokeObjectURL(url);
}
