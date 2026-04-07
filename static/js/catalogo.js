/**
 * catalogo.js — Modal de cadastro de marcas para produtos novos
 */

let _produtosSemMarca = [];

async function abrirModalSemMarca() {
  const modal = document.getElementById("modal-sem-marca");
  const lista  = document.getElementById("modal-sem-marca-lista");
  const sub    = document.getElementById("modal-sem-marca-sub");

  modal.classList.remove("hidden");
  lista.innerHTML = '<div class="skeleton" style="height:200px;border-radius:8px"></div>';
  lucide.createIcons();

  // Carregar produtos sem marca e marcas conhecidas em paralelo
  try {
    const [resProd, resMarcas] = await Promise.all([
      fetch("/api/produtos/sem-marca").then(r => r.json()),
      fetch("/api/marcas").then(r => r.json()),
    ]);

    _produtosSemMarca = resProd.produtos || [];

    if (!_produtosSemMarca.length) {
      sub.textContent = "Nenhum produto sem marca encontrado.";
      lista.innerHTML = '<div class="empty-state" style="padding:32px"><p>Todos os produtos já têm marca cadastrada!</p></div>';
      return;
    }

    sub.textContent = `${fmtNum(_produtosSemMarca.length)} produto${_produtosSemMarca.length !== 1 ? "s" : ""} novo${_produtosSemMarca.length !== 1 ? "s" : ""} encontrado${_produtosSemMarca.length !== 1 ? "s" : ""}`;

    // Popular datalist com marcas conhecidas
    const datalist = document.getElementById("marcas-datalist");
    datalist.innerHTML = (resMarcas.marcas || []).map(m => `<option value="${m}">`).join("");

    // Renderizar tabela
    const rows = _produtosSemMarca.map((p, i) => `
      <tr>
        <td class="mono secondary" style="white-space:nowrap">${p.sku}</td>
        <td style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${p.nome}">${p.nome}</td>
        <td class="mono" style="text-align:right;white-space:nowrap">${fmtBRL(p.total)}</td>
        <td>
          <input
            type="text"
            list="marcas-datalist"
            class="marca-input"
            data-idx="${i}"
            placeholder="Marca..."
            autocomplete="off"
          />
        </td>
      </tr>
    `).join("");

    lista.innerHTML = `
      <table>
        <thead>
          <tr>
            <th>SKU</th>
            <th>Produto</th>
            <th style="text-align:right">Faturamento</th>
            <th style="min-width:160px">Marca</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    `;
  } catch (err) {
    lista.innerHTML = `<div class="empty-state"><p>Erro ao carregar: ${err.message}</p></div>`;
  }
}

async function salvarMarcas() {
  const inputs = document.querySelectorAll(".marca-input");
  const payload = [];

  inputs.forEach(inp => {
    const marca = inp.value.trim();
    if (!marca) return;
    const idx = parseInt(inp.dataset.idx);
    const p = _produtosSemMarca[idx];
    if (!p) return;
    payload.push({
      sku: p.sku,
      sku_original: p.sku_original,
      nome: p.nome,
      marca,
    });
  });

  if (!payload.length) {
    fecharModalSemMarca();
    return;
  }

  const btn = document.getElementById("modal-sem-marca-salvar");
  btn.disabled = true;
  btn.innerHTML = '<i data-lucide="loader"></i> Salvando...';
  lucide.createIcons();

  try {
    const res = await fetch("/api/produtos/cadastrar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.erro || "Erro ao salvar");

    showToast(`${fmtNum(data.salvos)} produto${data.salvos !== 1 ? "s" : ""} cadastrado${data.salvos !== 1 ? "s" : ""} com sucesso!`, "success");
    fecharModalSemMarca();
    fetch("/api/filtros").then(r => r.json()).then(f => _atualizarFiltrosBar(f)).catch(() => {});
    setTimeout(() => navegarPara("dashboard"), 400);
  } catch (err) {
    showToast("Erro ao salvar: " + err.message, "error");
    btn.disabled = false;
    btn.innerHTML = '<i data-lucide="save"></i> Salvar marcas';
    lucide.createIcons();
  }
}

function fecharModalSemMarca() {
  document.getElementById("modal-sem-marca").classList.add("hidden");
}

// Bind dos botões do modal (executado após DOM carregado)
document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("modal-sem-marca-close")?.addEventListener("click", fecharModalSemMarca);
  document.getElementById("modal-sem-marca-pular")?.addEventListener("click", () => {
    fecharModalSemMarca();
    setTimeout(() => navegarPara("dashboard"), 400);
  });
  document.getElementById("modal-sem-marca-salvar")?.addEventListener("click", salvarMarcas);

  // Fechar ao clicar fora da modal-box
  document.getElementById("modal-sem-marca")?.addEventListener("click", e => {
    if (e.target === document.getElementById("modal-sem-marca")) fecharModalSemMarca();
  });
});
