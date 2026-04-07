"""
app.py — Backend Flask principal
Analisador de Vendas — Grupo Alcina Maria / Grupo Boticário Alagoas
"""

import os
import io
import csv
import json
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
}


def _salvar_estado():
    """Persiste vendas e metadados em disco para sobreviver reinicializações."""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "vendas": _estado["vendas"],
                "arquivo_nome": _estado["arquivo_nome"],
                "processado_em": _estado["processado_em"],
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
        _estado["vendas"]        = data.get("vendas", [])
        _estado["arquivo_nome"]  = data.get("arquivo_nome")
        _estado["processado_em"] = data.get("processado_em")
        if _estado["vendas"]:
            app.logger.info(f"Estado restaurado: {len(_estado['vendas'])} registros")
    except Exception as e:
        app.logger.warning(f"Não foi possível carregar estado do disco: {e}")


def _carregar_indices():
    if _estado["indice_produtos"] is None or _estado["indice_iaf"] is None:
        _estado["indice_produtos"], _estado["indice_iaf"] = criar_indices(DB_PATH)
    return _estado["indice_produtos"], _estado["indice_iaf"]


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
    if not arquivo.filename.endswith((".xlsx", ".xls")):
        return jsonify({"erro": "Formato inválido. Envie um arquivo .xlsx"}), 400

    # Salvar temporariamente
    tmp_path = os.path.join(os.path.dirname(__file__), "_upload_tmp.xlsx")
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
    tmp_path = os.path.join(os.path.dirname(__file__), "_upload_tmp.xlsx")
    if not os.path.exists(tmp_path):
        return jsonify({"erro": "Nenhum arquivo para processar. Faça o upload primeiro."}), 400

    nome_arquivo = request.json.get("arquivo_nome", "planilha.xlsx") if request.is_json else "planilha.xlsx"

    try:
        vendas, _, total = ler_planilha(tmp_path)
        indice_produtos, indice_iaf = _carregar_indices()
        vendas = cruzar_vendas(vendas, indice_produtos, indice_iaf)

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
        "por_pagamento": [], "top_vendedores": [], "evolucao_diaria": [],
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

    resultado = []
    for cod, m in metricas.items():
        total = m["total"]
        pedidos = len(m["pedidos"])
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

    total = sum(_safe_float(v["TotalPraticado"]) for v in vendas_vendedor)

    return jsonify({
        "codigo": codigo,
        "nome": nome,
        "total_faturado": total,
        "qtd_pedidos": len(pedidos),
        "pedidos": lista_pedidos[:50],
        "por_iaf": [{"classificacao": k, "total": v} for k, v in por_iaf.items()],
        "por_ciclo": [{"ciclo": k, "total": v} for k, v in sorted(por_ciclo.items())],
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
