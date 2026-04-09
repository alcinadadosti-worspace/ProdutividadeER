"""
app.py — Backend Flask principal
Analisador de Vendas — Grupo Alcina Maria / Grupo Boticário Alagoas
"""

import os
import io
import csv
import json
import sqlite3
from collections import defaultdict
from datetime import datetime

from flask import Flask, request, jsonify, send_file, render_template

from processador import ler_planilha, preview_planilha, normalizar_sku
from cruzamento import criar_indices, cruzar_vendas

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100MB

# ─── Caminhos ─────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(__file__)
DB_PATH    = os.path.join(BASE_DIR, "produtos.db")
STATE_FILE = os.path.join(BASE_DIR, "_state.json")   # persistência em disco

# ─── Estado em memória ────────────────────────────────────────────────────────
_estado = {
    "vendas": [],
    "arquivo_nome": None,
    "processado_em": None,
    "indice_produtos": None,
    "indice_iaf": None,
    "marcas_usuario": {},   # {sku_norm: {"nome": str, "marca": str}} — persiste entre importações
}


def _salvar_estado():
    """Persiste vendas, metadados e marcas do usuário em disco."""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "vendas": _estado["vendas"],
                "arquivo_nome": _estado["arquivo_nome"],
                "processado_em": _estado["processado_em"],
                "marcas_usuario": _estado["marcas_usuario"],
            }, f, ensure_ascii=False)
    except Exception as e:
        app.logger.warning(f"Não foi possível salvar estado: {e}")


def _carregar_estado_disco():
    """Carrega estado salvo em disco ao iniciar (se existir)."""
    if not os.path.exists(STATE_FILE):
        return
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        _estado["vendas"]         = data.get("vendas", [])
        _estado["arquivo_nome"]   = data.get("arquivo_nome")
        _estado["processado_em"]  = data.get("processado_em")
        _estado["marcas_usuario"] = data.get("marcas_usuario", {})
        if _estado["vendas"]:
            app.logger.info(f"Estado restaurado: {len(_estado['vendas'])} registros, {len(_estado['marcas_usuario'])} marcas do usuário")
    except Exception as e:
        app.logger.warning(f"Não foi possível carregar estado do disco: {e}")


def _carregar_indices():
    if _estado["indice_produtos"] is None or _estado["indice_iaf"] is None:
        _estado["indice_produtos"], _estado["indice_iaf"] = criar_indices(DB_PATH)
    return _estado["indice_produtos"], _estado["indice_iaf"]


def _aplicar_marcas_usuario(vendas):
    """Aplica marcas definidas pelo usuário sobre vendas sem marca (sobrescreve resultado do cruzamento)."""
    mu = _estado.get("marcas_usuario", {})
    if not mu:
        return vendas
    for v in vendas:
        sku_norm = v.get("CodigoProduto_normalizado", "")
        if sku_norm in mu and not v.get("marca"):
            v["marca"] = mu[sku_norm]["marca"]
            v["em_catalogo"] = True
    return vendas


def _garantir_estado():
    """Se a memória está vazia, tenta recarregar do disco (resiliência a reinicializações)."""
    if not _estado["vendas"] and os.path.exists(STATE_FILE):
        _carregar_estado_disco()


# Carregar estado salvo ao iniciar
with app.app_context():
    _carregar_estado_disco()


# ─── Helpers de filtro ────────────────────────────────────────────────────────

def _aplicar_filtros(vendas, args):
    """Aplica filtros de query string à lista de vendas."""
    ciclo = args.get("ciclo", "").strip()
    unidade = args.get("unidade", "").strip()
    classificacao = args.get("classificacao", "").strip()
    vendedor = args.get("vendedor", "").strip()
    papel = args.get("papel", "").strip()

    resultado = vendas
    if ciclo:
        resultado = [v for v in resultado if v.get("Ciclo", "") == ciclo]
    if unidade:
        resultado = [v for v in resultado if v.get("Unidade", "") == unidade]
    if classificacao:
        resultado = [v for v in resultado if v.get("classificacao_iaf", "") == classificacao]
    if vendedor:
        resultado = [v for v in resultado if v.get("CodigoVendedor", "") == vendedor]
    if papel:
        resultado = [v for v in resultado if v.get("Papel", "") == papel]

    return resultado


def _safe_float(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


# ─── Rotas ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/upload", methods=["POST"])
def upload():
    """Recebe .xlsx, faz preview e retorna as primeiras 10 linhas."""
    if "file" not in request.files:
        return jsonify({"erro": "Nenhum arquivo enviado"}), 400

    arquivo = request.files["file"]
    ext = os.path.splitext(arquivo.filename)[1].lower()
    if ext not in (".xlsx", ".xls", ".csv"):
        return jsonify({"erro": "Formato inválido. Envie um arquivo .xlsx ou .csv"}), 400

    # Salvar temporariamente preservando a extensão (processador detecta pelo nome)
    tmp_path = os.path.join(os.path.dirname(__file__), f"_upload_tmp{ext}")
    arquivo.save(tmp_path)

    try:
        preview, colunas, total = preview_planilha(tmp_path, n=10)
        return jsonify({
            "ok": True,
            "arquivo_nome": arquivo.filename,
            "total_linhas": total,
            "colunas_encontradas": colunas,
            "preview": preview,
        })
    except Exception as e:
        return jsonify({"erro": f"Erro ao ler planilha: {str(e)}"}), 500


@app.route("/api/processar", methods=["POST"])
def processar():
    """Processa o arquivo temporário já uploadado."""
    base = os.path.dirname(__file__)
    tmp_path = None
    for ext in (".xlsx", ".xls", ".csv"):
        candidate = os.path.join(base, f"_upload_tmp{ext}")
        if os.path.exists(candidate):
            tmp_path = candidate
            break
    if not tmp_path:
        return jsonify({"erro": "Nenhum arquivo para processar. Faça o upload primeiro."}), 400

    nome_arquivo = request.json.get("arquivo_nome", "planilha.xlsx") if request.is_json else "planilha.xlsx"

    try:
        vendas, _, total = ler_planilha(tmp_path)

        # Forçar recarregamento dos índices do DB para pegar produtos cadastrados
        # manualmente em sessões anteriores (invalida cache)
        _estado["indice_produtos"] = None
        _estado["indice_iaf"] = None
        indice_produtos, indice_iaf = _carregar_indices()

        vendas = cruzar_vendas(vendas, indice_produtos, indice_iaf)

        # Recarregar marcas_usuario do disco antes de aplicar (garante consistência
        # mesmo com múltiplos workers ou após restart)
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    _disk = json.load(f)
                _estado["marcas_usuario"] = _disk.get("marcas_usuario", _estado.get("marcas_usuario", {}))
            except Exception:
                pass

        vendas = _aplicar_marcas_usuario(vendas)

        _estado["vendas"] = vendas
        _estado["arquivo_nome"] = nome_arquivo
        _estado["processado_em"] = datetime.now().isoformat()
        _salvar_estado()

        return jsonify({
            "ok": True,
            "total_processado": len(vendas),
            "processado_em": _estado["processado_em"],
        })
    except Exception as e:
        import traceback
        return jsonify({"erro": f"Erro no processamento: {str(e)}", "detalhe": traceback.format_exc()}), 500


@app.route("/api/limpar", methods=["POST"])
def limpar():
    """Remove todos os dados processados e reseta o estado."""
    _estado["vendas"] = []
    _estado["arquivo_nome"] = None
    _estado["processado_em"] = None
    _estado["indice_produtos"] = None
    _estado["indice_iaf"] = None
    try:
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
    except Exception:
        pass
    return jsonify({"ok": True})


@app.route("/api/status")
def status():
    """Retorna status atual do processamento."""
    _garantir_estado()
    vendas = _estado["vendas"]
    return jsonify({
        "tem_dados": len(vendas) > 0,
        "arquivo_nome": _estado["arquivo_nome"],
        "total_registros": len(vendas),
        "processado_em": _estado["processado_em"],
    })


@app.route("/api/dashboard")
def dashboard():
    """KPIs e dados agregados para o dashboard principal."""
    _garantir_estado()
    vendas = _aplicar_filtros(_estado["vendas"], request.args)

    if not vendas:
        return jsonify(_dashboard_vazio())

    total_faturado = sum(_safe_float(v["TotalPraticado"]) for v in vendas)
    pedidos_unicos = len({v["CodigoPedido"] for v in vendas if v.get("CodigoPedido")})
    ticket_medio = total_faturado / pedidos_unicos if pedidos_unicos else 0
    total_itens = sum(v.get("Quantidade", 0) for v in vendas)

    datas = [v["DataFaturamento"] for v in vendas if v.get("DataFaturamento")]
    periodo_inicio = min(datas) if datas else None
    periodo_fim = max(datas) if datas else None

    # Por ciclo
    por_ciclo = defaultdict(float)
    for v in vendas:
        por_ciclo[v.get("Ciclo") or "Sem Ciclo"] += _safe_float(v["TotalPraticado"])

    # Por unidade
    por_unidade = defaultdict(float)
    for v in vendas:
        por_unidade[v.get("Unidade") or "Desconhecido"] += _safe_float(v["TotalPraticado"])

    # Por classificação IAF
    por_iaf = defaultdict(float)
    for v in vendas:
        por_iaf[v.get("classificacao_iaf") or "Geral"] += _safe_float(v["TotalPraticado"])

    # Por plano de pagamento
    por_pagamento = defaultdict(float)
    for v in vendas:
        por_pagamento[v.get("PlanoPagamento") or "Não informado"] += _safe_float(v["TotalPraticado"])

    # Top 10 vendedores
    fat_vendedor = defaultdict(lambda: {"nome": "", "total": 0.0})
    for v in vendas:
        cod = v.get("CodigoVendedor") or "?"
        fat_vendedor[cod]["nome"] = v.get("Vendedor") or cod
        fat_vendedor[cod]["total"] += _safe_float(v["TotalPraticado"])
    top_vendedores = sorted(fat_vendedor.items(), key=lambda x: x[1]["total"], reverse=True)[:10]

    # Evolução diária
    por_dia = defaultdict(float)
    for v in vendas:
        dia = v.get("DataFaturamento") or "Sem data"
        por_dia[dia] += _safe_float(v["TotalPraticado"])
    evolucao_diaria = [{"data": k, "total": v} for k, v in sorted(por_dia.items())]

    # Evolução diária por vendedor (top 10 por faturamento)
    por_dia_vend = defaultdict(lambda: defaultdict(float))
    fat_vend_total = defaultdict(float)
    for v in vendas:
        dia = v.get("DataFaturamento") or "Sem data"
        nome = v.get("Vendedor") or v.get("CodigoVendedor") or "?"
        total_v = _safe_float(v["TotalPraticado"])
        por_dia_vend[nome][dia] += total_v
        fat_vend_total[nome] += total_v
    top_nomes_vend = [n for n, _ in sorted(fat_vend_total.items(), key=lambda x: x[1], reverse=True)[:10]]
    evolucao_por_vendedor = [
        {"nome": nome, "serie": [{"data": d, "total": t} for d, t in sorted(por_dia_vend[nome].items())]}
        for nome in top_nomes_vend
    ]

    # Filtros disponíveis
    ciclos = sorted({v.get("Ciclo") or "" for v in _estado["vendas"]} - {""})
    unidades = sorted({v.get("Unidade") or "" for v in _estado["vendas"]} - {""})
    classificacoes = ["IAF Cabelos", "IAF Make", "Geral"]
    vendedores_lista = sorted(
        {(v.get("CodigoVendedor") or "", v.get("Vendedor") or "") for v in _estado["vendas"]},
        key=lambda x: x[1]
    )
    papeis = sorted({v.get("Papel") or "" for v in _estado["vendas"]} - {""})

    return jsonify({
        "kpis": {
            "total_faturado": total_faturado,
            "total_pedidos": pedidos_unicos,
            "ticket_medio": ticket_medio,
            "total_itens": total_itens,
        },
        "periodo": {"inicio": periodo_inicio, "fim": periodo_fim},
        "arquivo_nome": _estado["arquivo_nome"],
        "total_registros": len(vendas),
        "por_ciclo": [{"ciclo": k, "total": v} for k, v in sorted(por_ciclo.items())],
        "por_unidade": [{"unidade": k, "total": v} for k, v in por_unidade.items()],
        "por_iaf": [{"classificacao": k, "total": v} for k, v in por_iaf.items()],
        "por_pagamento": [{"pagamento": k, "total": v} for k, v in sorted(por_pagamento.items(), key=lambda x: x[1], reverse=True)],
        "top_vendedores": [{"codigo": k, "nome": v["nome"], "total": v["total"]} for k, v in top_vendedores],
        "evolucao_diaria": evolucao_diaria,
        "evolucao_por_vendedor": evolucao_por_vendedor,
        "filtros": {
            "ciclos": ciclos,
            "unidades": unidades,
            "classificacoes": classificacoes,
            "vendedores": [{"codigo": c, "nome": n} for c, n in vendedores_lista],
            "papeis": papeis,
        }
    })


def _dashboard_vazio():
    return {
        "kpis": {"total_faturado": 0, "total_pedidos": 0, "ticket_medio": 0, "total_itens": 0},
        "periodo": {"inicio": None, "fim": None},
        "arquivo_nome": None,
        "total_registros": 0,
        "por_ciclo": [], "por_unidade": [], "por_iaf": [],
        "por_pagamento": [], "top_vendedores": [], "evolucao_diaria": [], "evolucao_por_vendedor": [],
        "filtros": {"ciclos": [], "unidades": [], "classificacoes": [], "vendedores": [], "papeis": []},
    }


@app.route("/api/vendedores")
def vendedores():
    """Lista de vendedores com métricas."""
    _garantir_estado()
    vendas = _aplicar_filtros(_estado["vendas"], request.args)

    metricas = defaultdict(lambda: {
        "nome": "", "codigo": "",
        "total": 0.0, "pedidos": set(), "quantidade": 0,
        "iaf_cabelos": 0.0, "iaf_make": 0.0, "geral": 0.0,
        "marcas": defaultdict(float),
    })

    for v in vendas:
        cod = v.get("CodigoVendedor") or "?"
        m = metricas[cod]
        m["nome"] = v.get("Vendedor") or cod
        m["codigo"] = cod
        total = _safe_float(v["TotalPraticado"])
        m["total"] += total
        if v.get("CodigoPedido"):
            m["pedidos"].add(v["CodigoPedido"])
        m["quantidade"] += v.get("Quantidade", 0)
        clf = v.get("classificacao_iaf", "Geral")
        if clf == "IAF Cabelos":
            m["iaf_cabelos"] += total
        elif clf == "IAF Make":
            m["iaf_make"] += total
        else:
            m["geral"] += total
        marca = v.get("marca") or ""
        if marca:
            m["marcas"][marca] += total

    resultado = []
    for cod, m in metricas.items():
        total = m["total"]
        pedidos = len(m["pedidos"])
        marcas_ord = sorted(m["marcas"].items(), key=lambda x: x[1], reverse=True)
        resultado.append({
            "codigo": cod,
            "nome": m["nome"],
            "total_faturado": total,
            "qtd_pedidos": pedidos,
            "ticket_medio": total / pedidos if pedidos else 0,
            "quantidade": m["quantidade"],
            "pct_iaf_cabelos": (m["iaf_cabelos"] / total * 100) if total else 0,
            "pct_iaf_make": (m["iaf_make"] / total * 100) if total else 0,
            "pct_geral": (m["geral"] / total * 100) if total else 0,
            "qtd_marcas": len(marcas_ord),
            "top_marca": marcas_ord[0][0] if marcas_ord else "—",
        })

    resultado.sort(key=lambda x: x["total_faturado"], reverse=True)
    return jsonify({"vendedores": resultado, "total": len(resultado)})


@app.route("/api/vendedor/<path:codigo>")
def vendedor_detalhe(codigo):
    """Detalhes de um vendedor específico."""
    _garantir_estado()
    vendas_vendedor = [v for v in _estado["vendas"] if v.get("CodigoVendedor") == codigo]
    if not vendas_vendedor:
        return jsonify({"erro": "Vendedor não encontrado"}), 404

    nome = vendas_vendedor[0].get("Vendedor", codigo)

    # Pedidos com detalhes
    pedidos = defaultdict(lambda: {"codigo": "", "data": "", "revendedor": "", "total": 0.0, "itens": 0})
    for v in vendas_vendedor:
        cod_ped = v.get("CodigoPedido") or "?"
        p = pedidos[cod_ped]
        p["codigo"] = cod_ped
        p["data"] = v.get("DataFaturamento") or ""
        p["revendedor"] = v.get("Revendedor") or ""
        p["total"] += _safe_float(v["TotalPraticado"])
        p["itens"] += v.get("Quantidade", 0)

    lista_pedidos = sorted(pedidos.values(), key=lambda x: x["data"], reverse=True)

    # Breakdown por IAF
    por_iaf = defaultdict(float)
    for v in vendas_vendedor:
        por_iaf[v.get("classificacao_iaf", "Geral")] += _safe_float(v["TotalPraticado"])

    # Por ciclo
    por_ciclo = defaultdict(float)
    for v in vendas_vendedor:
        por_ciclo[v.get("Ciclo") or "Sem Ciclo"] += _safe_float(v["TotalPraticado"])

    # Por marca
    por_marca = defaultdict(float)
    for v in vendas_vendedor:
        marca = v.get("marca") or ""
        if marca:
            por_marca[marca] += _safe_float(v["TotalPraticado"])

    # Marcas mais vendidas juntas (pares por pedido)
    from itertools import combinations
    pedido_marcas = defaultdict(set)
    for v in vendas_vendedor:
        marca = v.get("marca") or ""
        if marca:
            pedido_marcas[v.get("CodigoPedido") or "?"].add(marca)

    pares_contagem = defaultdict(int)
    for marcas in pedido_marcas.values():
        if len(marcas) >= 2:
            for a, b in combinations(sorted(marcas), 2):
                pares_contagem[(a, b)] += 1

    top_pares = sorted(pares_contagem.items(), key=lambda x: x[1], reverse=True)[:10]
    marcas_juntas = [{"marcas": list(par), "pedidos": count} for par, count in top_pares]

    total = sum(_safe_float(v["TotalPraticado"]) for v in vendas_vendedor)

    return jsonify({
        "codigo": codigo,
        "nome": nome,
        "total_faturado": total,
        "qtd_pedidos": len(pedidos),
        "pedidos": lista_pedidos[:50],
        "por_iaf": [{"classificacao": k, "total": v} for k, v in por_iaf.items()],
        "por_ciclo": [{"ciclo": k, "total": v} for k, v in sorted(por_ciclo.items())],
        "por_marca": [{"marca": k, "total": v} for k, v in sorted(por_marca.items(), key=lambda x: x[1], reverse=True)],
        "marcas_juntas": marcas_juntas,
    })


@app.route("/api/produtos")
def produtos():
    """Lista de produtos com métricas."""
    _garantir_estado()
    vendas = _aplicar_filtros(_estado["vendas"], request.args)

    metricas = defaultdict(lambda: {
        "sku": "", "nome": "", "marca": "", "em_catalogo": False,
        "quantidade": 0, "total": 0.0,
        "classificacao": "Geral", "metodo_match": "nenhum",
    })

    for v in vendas:
        sku = v.get("CodigoProduto") or v.get("CodigoProduto_normalizado") or "?"
        m = metricas[sku]
        m["sku"] = sku
        m["nome"] = v.get("Produto") or sku
        m["marca"] = v.get("marca") or m["marca"]
        m["em_catalogo"] = v.get("em_catalogo", False) or m["em_catalogo"]
        m["quantidade"] += v.get("Quantidade", 0)
        m["total"] += _safe_float(v["TotalPraticado"])
        m["classificacao"] = v.get("classificacao_iaf", "Geral")
        m["metodo_match"] = v.get("metodo_match", "nenhum")

    # Top 100 por faturamento
    resultado = sorted(metricas.values(), key=lambda x: x["total"], reverse=True)[:100]
    return jsonify({"produtos": resultado, "total": len(metricas)})


@app.route("/api/iaf")
def iaf():
    """Dados detalhados de análise IAF."""
    _garantir_estado()
    vendas = _aplicar_filtros(_estado["vendas"], request.args)

    total_geral = sum(_safe_float(v["TotalPraticado"]) for v in vendas)

    def _resumo_iaf(clf):
        subset = [v for v in vendas if v.get("classificacao_iaf") == clf]
        total_clf = sum(_safe_float(v["TotalPraticado"]) for v in subset)

        # Top produtos
        prod = defaultdict(lambda: {"sku": "", "nome": "", "total": 0.0, "quantidade": 0})
        for v in subset:
            sku = v.get("CodigoProduto") or "?"
            prod[sku]["sku"] = sku
            prod[sku]["nome"] = v.get("Produto") or sku
            prod[sku]["total"] += _safe_float(v["TotalPraticado"])
            prod[sku]["quantidade"] += v.get("Quantidade", 0)
        top_prod = sorted(prod.values(), key=lambda x: x["total"], reverse=True)[:10]

        # Top vendedores
        vend = defaultdict(lambda: {"codigo": "", "nome": "", "total": 0.0})
        for v in subset:
            cod = v.get("CodigoVendedor") or "?"
            vend[cod]["codigo"] = cod
            vend[cod]["nome"] = v.get("Vendedor") or cod
            vend[cod]["total"] += _safe_float(v["TotalPraticado"])
        top_vend = sorted(vend.values(), key=lambda x: x["total"], reverse=True)[:10]

        # Por ciclo
        por_ciclo = defaultdict(float)
        for v in subset:
            por_ciclo[v.get("Ciclo") or "Sem Ciclo"] += _safe_float(v["TotalPraticado"])

        return {
            "total": total_clf,
            "pct_total": (total_clf / total_geral * 100) if total_geral else 0,
            "qtd_registros": len(subset),
            "top_produtos": top_prod,
            "top_vendedores": top_vend,
            "por_ciclo": [{"ciclo": k, "total": v} for k, v in sorted(por_ciclo.items())],
        }

    # Métodos de match
    metodos = defaultdict(int)
    for v in vendas:
        metodos[v.get("metodo_match", "nenhum")] += 1

    return jsonify({
        "total_geral": total_geral,
        "iaf_cabelos": _resumo_iaf("IAF Cabelos"),
        "iaf_make": _resumo_iaf("IAF Make"),
        "geral": _resumo_iaf("Geral"),
        "metodos_match": dict(metodos),
    })


@app.route("/api/filtros")
def filtros():
    """Retorna as opções de filtro disponíveis (ciclos, unidades, classificações)."""
    _garantir_estado()
    vendas = _estado["vendas"]
    if not vendas:
        return jsonify({"ciclos": [], "unidades": [], "classificacoes": [], "vendedores": [], "papeis": []})

    ciclos = sorted({v.get("Ciclo") or "" for v in vendas} - {""})
    unidades = sorted({v.get("Unidade") or "" for v in vendas} - {""})
    classificacoes = ["IAF Cabelos", "IAF Make", "Geral"]
    vendedores_lista = sorted(
        {(v.get("CodigoVendedor") or "", v.get("Vendedor") or "") for v in vendas},
        key=lambda x: x[1]
    )
    papeis = sorted({v.get("Papel") or "" for v in vendas} - {""})

    return jsonify({
        "ciclos": ciclos,
        "unidades": unidades,
        "classificacoes": classificacoes,
        "vendedores": [{"codigo": c, "nome": n} for c, n in vendedores_lista],
        "papeis": papeis,
    })


@app.route("/api/produtos/sem-marca")
def produtos_sem_marca():
    """Retorna produtos únicos sem marca (nem no DB nem nas marcas do usuário)."""
    _garantir_estado()
    mu = _estado.get("marcas_usuario", {})
    vistos = {}
    for v in _estado["vendas"]:
        if v.get("marca"):
            continue
        sku = v.get("CodigoProduto_normalizado") or v.get("CodigoProduto") or "?"
        if not sku or sku == "?":
            continue
        if sku in mu:   # já foi atribuído pelo usuário antes
            continue
        if sku not in vistos:
            vistos[sku] = {
                "sku": sku,
                "sku_original": v.get("CodigoProduto") or sku,
                "nome": v.get("Produto") or sku,
                "quantidade": 0,
                "total": 0.0,
            }
        vistos[sku]["quantidade"] += v.get("Quantidade", 0)
        vistos[sku]["total"] += _safe_float(v["TotalPraticado"])

    resultado = sorted(vistos.values(), key=lambda x: x["total"], reverse=True)
    return jsonify({"produtos": resultado, "total": len(resultado)})


@app.route("/api/marcas")
def marcas():
    """Retorna lista de marcas distintas já cadastradas no banco."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT marca FROM produtos WHERE marca != '' ORDER BY marca")
        lista = [row[0] for row in cur.fetchall()]
        conn.close()
    except Exception:
        lista = []
    return jsonify({"marcas": lista})


@app.route("/api/produtos/cadastrar", methods=["POST"])
def cadastrar_produtos():
    """Salva marcas atribuídas pelo usuário em memória, no state.json e tenta gravar no DB."""
    dados = request.json
    if not dados or not isinstance(dados, list):
        return jsonify({"erro": "Envie uma lista de produtos"}), 400

    salvos = 0
    for p in dados:
        sku_orig = str(p.get("sku_original") or p.get("sku") or "").strip()
        sku_norm = normalizar_sku(sku_orig)
        nome = str(p.get("nome") or "").strip()
        marca = str(p.get("marca") or "").strip()
        if not sku_norm or not marca:
            continue

        # 1. Guardar nas marcas do usuário (persiste no state.json — fonte da verdade)
        _estado["marcas_usuario"][sku_norm] = {"nome": nome, "marca": marca}
        salvos += 1

        # 2. Tentar gravar no DB (best-effort; no Render é efêmero mas funciona na sessão)
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("SELECT id FROM produtos WHERE sku_normalizado = ?", (sku_norm,))
            row = cur.fetchone()
            if row:
                cur.execute(
                    "UPDATE produtos SET nome=?, marca=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (nome, marca, row[0])
                )
            else:
                cur.execute(
                    "INSERT INTO produtos (sku, sku_normalizado, nome, marca) VALUES (?, ?, ?, ?)",
                    (sku_orig, sku_norm, nome, marca)
                )
            conn.commit()
            conn.close()
        except Exception as e:
            app.logger.warning(f"Não foi possível gravar no DB: {e}")

    # Invalidar cache dos índices para que a próxima importação recarregue do DB
    # (que agora inclui os produtos recém-cadastrados)
    _estado["indice_produtos"] = None
    _estado["indice_iaf"] = None

    # Aplicar marcas do usuário diretamente nas vendas em memória
    _aplicar_marcas_usuario(_estado["vendas"])
    _salvar_estado()

    return jsonify({"ok": True, "salvos": salvos})


@app.route("/api/dados")
def dados():
    """Dados brutos paginados."""
    _garantir_estado()
    vendas = _aplicar_filtros(_estado["vendas"], request.args)

    # Busca global
    search = request.args.get("search", "").strip().lower()
    if search:
        def _match(v):
            campos = ["Vendedor", "Produto", "CodigoPedido", "Revendedor", "Ciclo", "CodigoProduto"]
            return any(search in str(v.get(c, "")).lower() for c in campos)
        vendas = [v for v in vendas if _match(v)]

    # Paginação
    try:
        page = max(1, int(request.args.get("page", 1)))
        size = min(200, max(10, int(request.args.get("size", 50))))
    except ValueError:
        page, size = 1, 50

    total = len(vendas)
    total_pages = max(1, (total + size - 1) // size)
    inicio = (page - 1) * size
    fim = inicio + size

    # Campos a retornar (excluir campos internos pesados)
    campos = [
        "CodigoVendedor", "Vendedor", "CodigoProduto", "Produto",
        "marca", "em_catalogo",
        "Quantidade", "TotalPraticado", "CodigoPedido", "Ciclo",
        "DataFaturamento", "Revendedor", "Papel", "PlanoPagamento",
        "Unidade", "classificacao_iaf", "metodo_match",
    ]

    pagina = [{c: v.get(c) for c in campos} for v in vendas[inicio:fim]]

    return jsonify({
        "dados": pagina,
        "page": page,
        "size": size,
        "total": total,
        "total_pages": total_pages,
    })


@app.route("/api/export/csv")
def export_csv():
    """Exporta todos os dados processados como CSV."""
    vendas = _aplicar_filtros(_estado["vendas"], request.args)

    campos = [
        "CodigoVendedor", "Vendedor", "CodigoProduto", "Produto",
        "marca", "em_catalogo",
        "Quantidade", "TotalPraticado", "CodigoPedido", "Ciclo",
        "DataFaturamento", "Revendedor", "Papel", "PlanoPagamento",
        "Unidade", "CanalDistribuicao", "classificacao_iaf", "metodo_match",
        "CodigoUsuarioCriacao", "UsuarioCriacao", "CodigoUsuarioFinalizacao", "UsuarioFinalizacao",
    ]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=campos, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(vendas)

    output.seek(0)
    nome_arquivo = (_estado["arquivo_nome"] or "vendas").replace(".xlsx", "")
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"{nome_arquivo}_processado.csv",
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
