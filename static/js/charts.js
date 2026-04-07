/**
 * charts.js — Configurações globais de Chart.js + helpers
 */

// Defaults globais do Chart.js (condicional para sobreviver a falhas de CDN)
if (typeof Chart !== "undefined") {
  Chart.defaults.color = "#8B8B8E";
  Chart.defaults.font.family = "'SF Mono', 'JetBrains Mono', monospace";
  Chart.defaults.font.size = 11;
} else {
  console.warn("Chart.js não carregou — gráficos desabilitados.");
}

const CHART_COLORS = {
  blue:   "#6C9EFF",
  green:  "#4ADE80",
  purple: "#A78BFA",
  orange: "#FB923C",
  red:    "#F87171",
  yellow: "#FBBF24",
  teal:   "#2DD4BF",
  pink:   "#F472B6",
};

const PALETTE = Object.values(CHART_COLORS);

const GRID_STYLE = {
  color: "rgba(255,255,255,0.04)",
  drawTicks: false,
};

const TOOLTIP_STYLE = {
  backgroundColor: "#222225",
  borderColor: "rgba(255,255,255,0.10)",
  borderWidth: 1,
  titleColor: "#EDEDEF",
  bodyColor: "#8B8B8E",
  padding: 10,
  cornerRadius: 8,
  displayColors: true,
  boxWidth: 10,
  boxHeight: 10,
  usePointStyle: true,
};

function baseOptions(extra = {}) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 300 },
    plugins: {
      legend: { display: false },
      tooltip: TOOLTIP_STYLE,
      ...extra.plugins,
    },
    ...extra,
  };
}

function barOptions(horizontal = false, extra = {}) {
  const axis = horizontal ? "x" : "y";
  return baseOptions({
    indexAxis: horizontal ? "y" : "x",
    scales: {
      x: {
        grid: horizontal ? GRID_STYLE : { display: false },
        border: { display: false },
        ticks: horizontal ? {
          callback: v => fmtAbrev(v),
        } : {},
      },
      y: {
        grid: horizontal ? { display: false } : GRID_STYLE,
        border: { display: false },
        ticks: horizontal ? {
          maxTicksLimit: 10,
        } : {
          callback: v => fmtAbrev(v),
        },
      },
    },
    ...extra,
  });
}

function lineOptions(extra = {}) {
  return baseOptions({
    scales: {
      x: {
        grid: { display: false },
        border: { display: false },
        ticks: { maxTicksLimit: 8 },
      },
      y: {
        grid: GRID_STYLE,
        border: { display: false },
        ticks: { callback: v => fmtAbrev(v) },
      },
    },
    ...extra,
  });
}

function donutOptions(extra = {}) {
  return baseOptions({
    cutout: "65%",
    plugins: {
      legend: {
        display: true,
        position: "right",
        labels: {
          color: "#8B8B8E",
          font: { size: 11 },
          padding: 10,
          boxWidth: 10,
          usePointStyle: true,
        },
      },
      tooltip: TOOLTIP_STYLE,
      ...extra.plugins,
    },
    ...extra,
  });
}

/**
 * Formata número como abreviação (1K, 1M, etc.)
 */
function fmtAbrev(valor) {
  if (valor >= 1e6) return "R$" + (valor / 1e6).toFixed(1) + "M";
  if (valor >= 1e3) return "R$" + (valor / 1e3).toFixed(0) + "K";
  return "R$" + valor.toFixed(0);
}

/**
 * Formata valor monetário BR
 */
function fmtBRL(valor) {
  return new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: "BRL",
  }).format(valor || 0);
}

/**
 * Formata número inteiro BR
 */
function fmtNum(valor) {
  return new Intl.NumberFormat("pt-BR").format(valor || 0);
}

/**
 * Cria ou atualiza um gráfico. Se já existe no canvas, destrói antes.
 */
const _chartInstances = {};

function criarOuAtualizar(canvasId, tipo, dados, opcoes) {
  if (typeof Chart === "undefined") return null;
  const canvas = document.getElementById(canvasId);
  if (!canvas) return null;

  // Destruir instância anterior com segurança (canvas pode ter sido removido do DOM)
  if (_chartInstances[canvasId]) {
    try { _chartInstances[canvasId].destroy(); } catch (_) {}
    delete _chartInstances[canvasId];
  }

  // Limpar qualquer instância Chart.js travada no canvas via API interna
  const existing = Chart.getChart(canvas);
  if (existing) {
    try { existing.destroy(); } catch (_) {}
  }

  const chart = new Chart(canvas, { type: tipo, data: dados, options: opcoes });
  _chartInstances[canvasId] = chart;
  return chart;
}

/**
 * Destroi todos os gráficos de uma lista de IDs
 */
function destruirGraficos(...ids) {
  ids.forEach(id => {
    if (_chartInstances[id]) {
      try { _chartInstances[id].destroy(); } catch (_) {}
      delete _chartInstances[id];
    }
  });
}
