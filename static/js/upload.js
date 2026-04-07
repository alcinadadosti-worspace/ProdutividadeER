/**
 * upload.js — Tela de Upload e preview da planilha
 */

let _arquivoAtual = null;

function renderUpload() {
  const page = document.getElementById("page-upload");
  page.innerHTML = `
    <div class="upload-page">
      <div class="upload-hero">
        <h1>Importar Planilha de Vendas</h1>
        <p>Arraste seu arquivo .xlsx ou clique para selecionar</p>
      </div>

      <div class="drop-zone" id="drop-zone">
        <input type="file" id="file-input" accept=".xlsx,.xls" />
        <div class="drop-icon">
          <i data-lucide="file-spreadsheet"></i>
        </div>
        <div class="drop-title">Soltar arquivo aqui</div>
        <div class="drop-sub">ou clique para selecionar do computador</div>
        <div class="drop-formats">
          <span class="format-chip">.xlsx</span>
          <span class="format-chip">.xls</span>
        </div>
      </div>

      <div id="progress-section" class="progress-wrap hidden">
        <div class="progress-label" id="progress-label">Carregando...</div>
        <div class="progress-bar">
          <div class="progress-fill indeterminate" id="progress-fill"></div>
        </div>
      </div>

      <div id="preview-section" class="preview-section hidden">
        <div class="preview-header">
          <div class="flex-row">
            <span class="section-title" style="margin:0">Prévia dos dados</span>
          </div>
          <div class="preview-meta">
            <div class="meta-item">
              Arquivo: <strong id="meta-nome"></strong>
            </div>
            <div class="meta-item">
              Total de linhas: <strong id="meta-total"></strong>
            </div>
          </div>
        </div>
        <div class="table-card">
          <div class="table-wrapper" id="preview-table-wrap"></div>
        </div>
        <div style="display:flex;justify-content:flex-end;margin-top:16px;gap:8px">
          <button class="btn btn-secondary" id="btn-cancelar">
            <i data-lucide="x"></i> Cancelar
          </button>
          <button class="btn btn-primary" id="btn-processar">
            <i data-lucide="zap"></i> Processar Dados
          </button>
        </div>
      </div>
    </div>
  `;

  lucide.createIcons();
  _bindDropZone();
}

function _bindDropZone() {
  const dropZone = document.getElementById("drop-zone");
  const fileInput = document.getElementById("file-input");

  dropZone.addEventListener("click", () => fileInput.click());

  dropZone.addEventListener("dragover", e => {
    e.preventDefault();
    dropZone.classList.add("dragover");
  });

  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));

  dropZone.addEventListener("drop", e => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
    const file = e.dataTransfer.files[0];
    if (file) _handleFile(file);
  });

  fileInput.addEventListener("change", e => {
    const file = e.target.files[0];
    if (file) _handleFile(file);
  });

  document.getElementById("btn-cancelar")?.addEventListener("click", _cancelar);
  document.getElementById("btn-processar")?.addEventListener("click", _processar);
}

async function _handleFile(file) {
  if (!file.name.match(/\.(xlsx|xls)$/i)) {
    showToast("Formato inválido. Envie um arquivo .xlsx", "error");
    return;
  }

  _arquivoAtual = file;
  _mostrarProgress("Fazendo upload...");

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch("/api/upload", { method: "POST", body: formData });
    const data = await res.json();

    if (!res.ok || data.erro) {
      throw new Error(data.erro || "Erro no upload");
    }

    _esconderProgress();
    _mostrarPreview(data);
    _arquivoAtual._nome = data.arquivo_nome;
  } catch (err) {
    _esconderProgress();
    showToast(err.message, "error");
  }
}

function _mostrarProgress(label) {
  const sec = document.getElementById("progress-section");
  const lbl = document.getElementById("progress-label");
  const preview = document.getElementById("preview-section");
  sec.classList.remove("hidden");
  lbl.textContent = label;
  preview.classList.add("hidden");
}

function _esconderProgress() {
  document.getElementById("progress-section")?.classList.add("hidden");
}

function _mostrarPreview(data) {
  document.getElementById("preview-section").classList.remove("hidden");
  document.getElementById("meta-nome").textContent = data.arquivo_nome;
  document.getElementById("meta-total").textContent = fmtNum(data.total_linhas);

  const wrap = document.getElementById("preview-table-wrap");
  if (!data.preview || data.preview.length === 0) {
    wrap.innerHTML = '<div class="empty-state"><p>Nenhum dado encontrado na planilha.</p></div>';
    return;
  }

  const colunas = [
    { key: "CodigoVendedor", label: "Cód. Vendedor" },
    { key: "Vendedor",       label: "Vendedor" },
    { key: "CodigoProduto",  label: "SKU" },
    { key: "Produto",        label: "Produto" },
    { key: "Quantidade",     label: "Qtde" },
    { key: "TotalPraticado", label: "Total" },
    { key: "CodigoPedido",   label: "Pedido" },
    { key: "Ciclo",          label: "Ciclo" },
    { key: "DataFaturamento",label: "Data" },
    { key: "Unidade",        label: "Unidade" },
  ];

  const header = colunas.map(c => `<th>${c.label}</th>`).join("");
  const rows = data.preview.map(row => {
    const cells = colunas.map(c => {
      let val = row[c.key] ?? "";
      if (c.key === "TotalPraticado") val = fmtBRL(val);
      if (c.key === "Quantidade") val = fmtNum(val);
      return `<td class="${["CodigoProduto","CodigoPedido","Quantidade","TotalPraticado"].includes(c.key) ? "mono" : ""}">${val}</td>`;
    }).join("");
    return `<tr>${cells}</tr>`;
  }).join("");

  wrap.innerHTML = `
    <table>
      <thead><tr>${header}</tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
  lucide.createIcons();

  // Rebind buttons (re-rendered)
  document.getElementById("btn-cancelar")?.addEventListener("click", _cancelar);
  document.getElementById("btn-processar")?.addEventListener("click", _processar);
}

function _cancelar() {
  _arquivoAtual = null;
  document.getElementById("preview-section").classList.add("hidden");
  document.getElementById("progress-section").classList.add("hidden");
}

async function _processar() {
  if (!_arquivoAtual) return;

  const btn = document.getElementById("btn-processar");
  btn.disabled = true;
  btn.innerHTML = '<i data-lucide="loader"></i> Processando...';
  lucide.createIcons();

  _mostrarProgress("Cruzando dados com banco de produtos...");

  try {
    const res = await fetch("/api/processar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ arquivo_nome: _arquivoAtual._nome || _arquivoAtual.name }),
    });
    const data = await res.json();

    if (!res.ok || data.erro) {
      throw new Error(data.erro || "Erro no processamento");
    }

    _esconderProgress();
    showToast(`${fmtNum(data.total_processado)} registros processados com sucesso!`, "success");
    atualizarStatusBadge(data.total_processado);
    // Navegar ao dashboard
    setTimeout(() => navegarPara("dashboard"), 600);
  } catch (err) {
    _esconderProgress();
    btn.disabled = false;
    btn.innerHTML = '<i data-lucide="zap"></i> Processar Dados';
    lucide.createIcons();
    showToast(err.message, "error");
  }
}
