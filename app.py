"""
app.py — Backend Flask principal
Analisador de Vendas — Grupo Alcina Maria / Grupo Boticário Alagoas
"""

import os
import io
import csv
import json
import sqlite3
import base64
import threading
import urllib.request
import urllib.error
from collections import defaultdict
import secrets as _secrets_mod
from datetime import datetime, timedelta

from flask import Flask, request, jsonify, send_file, render_template, session, g

from processador import ler_planilha, preview_planilha, normalizar_sku
from cruzamento import criar_indices, cruzar_vendas

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100MB

# ─── Caminhos ─────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(__file__)
DB_PATH    = os.path.join(BASE_DIR, "produtos.db")
STATE_FILE = os.path.join(BASE_DIR, "_state.json")

# ─── GitHub — persistência permanente de marcas_catalog.json ──────────────────
_GH_TOKEN  = os.environ.get("GITHUB_TOKEN", "")
_GH_REPO   = os.environ.get("GITHUB_REPO", "alcinadadosti-worspace/ProdutividadeER")
_GH_BRANCH = os.environ.get("GITHUB_BRANCH", "master")
_GH_FILE   = "marcas_catalog.json"


def _gh_ok():
    return bool(_GH_TOKEN and _GH_REPO)


def _gh_request(method, path, body=None):
    url = f"https://api.github.com/repos/{_GH_REPO}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {_GH_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def _gh_ler_marcas():
    """Lê marcas_catalog.json do GitHub. Retorna {} se não existir ou sem token."""
    if not _gh_ok():
        return {}
    try:
        resp = _gh_request("GET", _GH_FILE)
        if not resp:
            return {}
        conteudo = base64.b64decode(resp["content"]).decode("utf-8")
        return json.loads(conteudo)
    except Exception as e:
        app.logger.warning(f"[GitHub] Erro ao ler marcas: {e}")
        return {}


def _gh_salvar_marcas(marcas_dict):
    """Salva marcas_catalog.json no GitHub. Retorna (ok, erro)."""
    if not _gh_ok():
        return False, "GITHUB_TOKEN não configurado"
    if not marcas_dict:
        return False, "marcas_dict vazio"
    try:
        conteudo = json.dumps(marcas_dict, ensure_ascii=False, indent=2)
        encoded  = base64.b64encode(conteudo.encode("utf-8")).decode()

        atual = _gh_request("GET", _GH_FILE)
        sha   = atual["sha"] if atual else None

        body = {
            "message": "chore: atualizar marcas do catálogo [auto]",
            "content": encoded,
            "branch":  _GH_BRANCH,
        }
        if sha:
            body["sha"] = sha

        _gh_request("PUT", _GH_FILE, body)
        app.logger.info(f"[GitHub] marcas_catalog.json atualizado ({len(marcas_dict)} entradas)")
        return True, None
    except urllib.error.HTTPError as e:
        corpo = e.read().decode("utf-8", errors="replace")
        msg = f"HTTP {e.code}: {corpo}"
        app.logger.warning(f"[GitHub] Erro ao salvar: {msg}")
        return False, msg
    except Exception as e:
        app.logger.warning(f"[GitHub] Erro ao salvar: {e}")
        return False, str(e)


# ─── Sessões por usuário ──────────────────────────────────────────────────────
# Cada browser recebe um session ID único (cookie). O estado (vendas, filtros,
# índices) fica isolado por sessão — múltiplos usuários não se interferem.

app.secret_key = os.environ.get("SECRET_KEY", "alcina-maria-2026-chave-sessao")
app.permanent_session_lifetime = timedelta(days=30)

_sessoes = {}   # sid -> estado dict

# ─── Cache de marcas do GitHub ────────────────────────────────────────────────
# Evita uma chamada HTTP de 8s a cada nova sessão carregada.
import time as _time_mod
_marcas_gh_cache: dict = {}
_marcas_gh_ts: float   = 0.0
_MARCAS_GH_TTL         = 300  # segundos (5 min)
_marcas_gh_lock        = threading.Lock()


def _gh_ler_marcas_cached():
    """Retorna marcas do GitHub usando cache em memória com TTL de 5 minutos."""
    global _marcas_gh_cache, _marcas_gh_ts
    agora = _time_mod.time()
    with _marcas_gh_lock:
        if agora - _marcas_gh_ts < _MARCAS_GH_TTL and _marcas_gh_cache:
            return dict(_marcas_gh_cache)
    # Busca fora do lock para não bloquear outras threads durante o HTTP
    marcas = _gh_ler_marcas()
    with _marcas_gh_lock:
        _marcas_gh_cache = marcas
        _marcas_gh_ts    = _time_mod.time()
    return dict(marcas)


def _gh_invalidar_cache():
    """Invalida o cache de marcas para forçar releitura na próxima requisição."""
    global _marcas_gh_ts
    with _marcas_gh_lock:
        _marcas_gh_ts = 0.0


def _sid():
    """Retorna (ou cria) o ID de sessão do browser atual."""
    if "sid" not in session:
        session["sid"] = _secrets_mod.token_hex(16)
        session.permanent = True
    return session["sid"]


def _state_file_sid(sid):
    return os.path.join(BASE_DIR, f"_state_{sid}.json")


def _tmp_path_sid(sid, ext):
    return os.path.join(BASE_DIR, f"_upload_tmp_{sid}{ext}")


def _estado_inicial():
    return {
        "vendas": [],
        "arquivo_nome": None,
        "processado_em": None,
        "indice_produtos": None,
        "indice_iaf": None,
        "marcas_usuario": {},
    }


def _carregar_estado_sessao(sid, est):
    """Carrega estado do disco para a sessão. Marcas do GitHub (cache) são mescladas."""
    sf = _state_file_sid(sid)
    if os.path.exists(sf):
        try:
            with open(sf, "r", encoding="utf-8") as f:
                data = json.load(f)
            est["vendas"]         = data.get("vendas", [])
            est["arquivo_nome"]   = data.get("arquivo_nome")
            est["processado_em"]  = data.get("processado_em")
            est["marcas_usuario"] = data.get("marcas_usuario", {})
            if est["vendas"]:
                app.logger.info(f"[Sessão {sid[:8]}] {len(est['vendas'])} registros restaurados do disco")
        except Exception as e:
            app.logger.error(f"[Sessão {sid[:8]}] Erro ao carregar estado do disco: {e}")
    else:
        app.logger.info(f"[Sessão {sid[:8]}] Nova sessão — sem arquivo de estado")

    # Marcas do GitHub usam cache em memória (sem bloquear a request com HTTP)
    try:
        marcas_gh = _gh_ler_marcas_cached()
        if marcas_gh:
            est["marcas_usuario"].update(marcas_gh)
    except Exception as e:
        app.logger.warning(f"[Sessão {sid[:8]}] Erro ao carregar marcas do GitHub: {e}")


@app.before_request
def _carregar_sessao():
    """Carrega estado da sessão em g.est antes de cada request."""
    if request.endpoint in (None, "static"):
        return
    sid = _sid()
    if sid not in _sessoes:
        est = _estado_inicial()
        _carregar_estado_sessao(sid, est)
        _sessoes[sid] = est
    else:
        # Cache em memória existe mas pode estar desatualizado se outro worker Gunicorn
        # processou dados após este worker ter inicializado a sessão com estado vazio.
        # Solução: se o cache local está vazio mas há arquivo no disco, recarregar.
        est = _sessoes[sid]
        if not est["vendas"]:
            sf = _state_file_sid(sid)
            if os.path.exists(sf):
                app.logger.info(f"[Sessão {sid[:8]}] Cache vazio com disco presente — recarregando (sync multi-worker)")
                _carregar_estado_sessao(sid, est)
    g.est = _sessoes[sid]


def _salvar_estado():
    """Persiste estado da sessão atual em disco."""
    try:
        sid = _sid()   # garante que o sid sempre existe na sessão
    except RuntimeError:
        app.logger.error("[_salvar_estado] Sem contexto de request — não foi possível salvar")
        return
    est = g.est
    sf  = _state_file_sid(sid)
    try:
        with open(sf, "w", encoding="utf-8") as f:
            json.dump({
                "vendas": est["vendas"],
                "arquivo_nome": est["arquivo_nome"],
                "processado_em": est["processado_em"],
                "marcas_usuario": est["marcas_usuario"],
            }, f, ensure_ascii=False)
        app.logger.info(f"[Sessão {sid[:8]}] Estado salvo: {len(est['vendas'])} registros → {sf}")
    except Exception as e:
        app.logger.error(f"[Sessão {sid[:8]}] FALHA ao salvar estado em {sf}: {e}")


def _carregar_indices():
    if g.est["indice_produtos"] is None or g.est["indice_iaf"] is None:
        g.est["indice_produtos"], g.est["indice_iaf"] = criar_indices(DB_PATH)
    return g.est["indice_produtos"], g.est["indice_iaf"]


def _persistir_produtos_novos(vendas):
    """Insere no produtos.db os produtos que ainda não estão no catálogo."""
    try:
        novos = {}
        for v in vendas:
            if v.get("em_catalogo"):
                continue
            sku_norm = v.get("CodigoProduto_normalizado", "")
            sku_orig = v.get("CodigoProduto", "")
            nome     = v.get("Produto", "")
            if sku_norm and sku_norm not in novos:
                novos[sku_norm] = {"sku_orig": sku_orig, "nome": nome}

        if not novos:
            return

        conn = sqlite3.connect(DB_PATH)
        cur  = conn.cursor()
        inseridos = 0
        for sku_norm, info in novos.items():
            cur.execute(
                "INSERT OR IGNORE INTO produtos (sku, sku_normalizado, nome, marca) VALUES (?, ?, ?, '')",
                (info["sku_orig"], sku_norm, info["nome"])
            )
            inseridos += cur.rowcount
        conn.commit()
        conn.close()

        if inseridos:
            app.logger.info(f"[Catálogo] {inseridos} produtos novos inseridos no DB")
            g.est["indice_produtos"] = None
            g.est["indice_iaf"]      = None
    except Exception as e:
        app.logger.warning(f"[Catálogo] Erro ao persistir produtos novos: {e}")


def _aplicar_marcas_usuario(vendas):
    """Aplica marcas definidas pelo usuário sobre vendas sem marca."""
    mu = g.est.get("marcas_usuario", {})
    if not mu:
        return vendas
    for v in vendas:
        sku_norm = v.get("CodigoProduto_normalizado", "")
        if sku_norm in mu and not v.get("marca"):
            v["marca"] = mu[sku_norm]["marca"]
            v["em_catalogo"] = True
    return vendas


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

    # Salvar temporariamente por sessão (cada usuário tem seu próprio arquivo)
    tmp_path = _tmp_path_sid(_sid(), ext)
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
    sid = _sid()
    tmp_path = None
    for ext in (".xlsx", ".xls", ".csv"):
        candidate = _tmp_path_sid(sid, ext)
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
        g.est["indice_produtos"] = None
        g.est["indice_iaf"] = None
        indice_produtos, indice_iaf = _carregar_indices()

        vendas = cruzar_vendas(vendas, indice_produtos, indice_iaf)

        # Persistir produtos novos no DB automaticamente
        _persistir_produtos_novos(vendas)

        # Marcas já estão em g.est["marcas_usuario"] (carregadas na sessão via cache)
        # Atualizar com eventuais novidades do GitHub (usando cache — sem HTTP extra)
        marcas_gh = _gh_ler_marcas_cached()
        if marcas_gh:
            g.est["marcas_usuario"].update(marcas_gh)

        vendas = _aplicar_marcas_usuario(vendas)

        # ── Mesclar com dados existentes (sem sobrescrever) ───────────────────
        # Chave de deduplicação: CodigoPedido + CodigoProduto_normalizado
        existentes = {
            (v.get("CodigoPedido") or "", v.get("CodigoProduto_normalizado") or "")
            for v in g.est["vendas"]
        }
        novas = [
            v for v in vendas
            if (v.get("CodigoPedido") or "", v.get("CodigoProduto_normalizado") or "") not in existentes
        ]
        g.est["vendas"] = g.est["vendas"] + novas
        g.est["arquivo_nome"] = nome_arquivo
        g.est["processado_em"] = datetime.now().isoformat()
        _salvar_estado()

        ciclos = sorted({v.get("Ciclo") or "" for v in g.est["vendas"]} - {""})
        return jsonify({
            "ok": True,
            "total_processado": len(g.est["vendas"]),
            "novos_registros": len(novas),
            "processado_em": g.est["processado_em"],
            "ciclos": ciclos,
        })
    except Exception as e:
        import traceback
        return jsonify({"erro": f"Erro no processamento: {str(e)}", "detalhe": traceback.format_exc()}), 500


@app.route("/api/limpar", methods=["POST"])
def limpar():
    """Remove todos os dados processados e reseta o estado."""
    sid = session.get("sid", "")
    g.est["vendas"] = []
    g.est["arquivo_nome"] = None
    g.est["processado_em"] = None
    g.est["indice_produtos"] = None
    g.est["indice_iaf"] = None
    try:
        sf = _state_file_sid(sid)
        if sid and os.path.exists(sf):
            os.remove(sf)
    except Exception:
        pass
    return jsonify({"ok": True})


@app.route("/api/limpar-ciclo", methods=["POST"])
def limpar_ciclo():
    """Remove as vendas de um ciclo específico sem apagar os demais."""
    ciclo = (request.json or {}).get("ciclo", "")
    if not ciclo:
        return jsonify({"erro": "Ciclo não informado"}), 400
    antes = len(g.est["vendas"])
    g.est["vendas"] = [v for v in g.est["vendas"] if v.get("Ciclo") != ciclo]
    removidos = antes - len(g.est["vendas"])
    if not g.est["vendas"]:
        g.est["arquivo_nome"] = None
        g.est["processado_em"] = None
    _salvar_estado()
    ciclos = sorted({v.get("Ciclo") or "" for v in g.est["vendas"]} - {""})
    return jsonify({"ok": True, "removidos": removidos, "total": len(g.est["vendas"]), "ciclos": ciclos})


@app.route("/api/status")
def status():
    """Retorna status atual do processamento."""

    vendas = g.est["vendas"]
    ciclos = sorted({v.get("Ciclo") or "" for v in vendas} - {""})
    return jsonify({
        "tem_dados": len(vendas) > 0,
        "arquivo_nome": g.est["arquivo_nome"],
        "total_registros": len(vendas),
        "processado_em": g.est["processado_em"],
        "ciclos": ciclos,
    })


@app.route("/api/gh-status")
def gh_status():
    """Diagnóstico da integração com GitHub."""
    resultado = {
        "token_configurado": bool(_GH_TOKEN),
        "repo": _GH_REPO,
        "branch": _GH_BRANCH,
        "arquivo": _GH_FILE,
    }
    if not _gh_ok():
        resultado["erro"] = "GITHUB_TOKEN não configurado"
        return jsonify(resultado), 200

    try:
        resp = _gh_request("GET", _GH_FILE)
        if resp:
            resultado["arquivo_existe"] = True
            resultado["tamanho_bytes"]  = resp.get("size", 0)
            resultado["ultimo_commit"]  = resp.get("sha", "")[:7]
        else:
            resultado["arquivo_existe"] = False
            resultado["info"] = "Arquivo ainda não criado — atribua marcas pelo modal para criá-lo"
    except Exception as e:
        resultado["erro_api"] = str(e)

    return jsonify(resultado)


@app.route("/api/dashboard")
def dashboard():
    """KPIs e dados agregados para o dashboard principal."""

    vendas = _aplicar_filtros(g.est["vendas"], request.args)

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
    ciclos = sorted({v.get("Ciclo") or "" for v in g.est["vendas"]} - {""})
    unidades = sorted({v.get("Unidade") or "" for v in g.est["vendas"]} - {""})
    classificacoes = ["IAF Cabelos", "IAF Make", "Geral"]
    vendedores_lista = sorted(
        {(v.get("CodigoVendedor") or "", v.get("Vendedor") or "") for v in g.est["vendas"]},
        key=lambda x: x[1]
    )
    papeis = sorted({v.get("Papel") or "" for v in g.est["vendas"]} - {""})

    return jsonify({
        "kpis": {
            "total_faturado": total_faturado,
            "total_pedidos": pedidos_unicos,
            "ticket_medio": ticket_medio,
            "total_itens": total_itens,
        },
        "periodo": {"inicio": periodo_inicio, "fim": periodo_fim},
        "arquivo_nome": g.est["arquivo_nome"],
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


@app.route("/api/comparativo")
def comparativo():
    """Comparativo de faturamento entre ciclos por vendedor e por categoria."""

    vendas = g.est["vendas"]
    if not vendas:
        return jsonify({"ciclos": [], "por_vendedor": [], "por_categoria": []})

    ciclos = sorted({v.get("Ciclo") or "" for v in vendas} - {""})

    # ── Por vendedor ──────────────────────────────────────────────────────────
    vend_ciclo = defaultdict(lambda: defaultdict(float))
    vend_nome  = {}
    for v in vendas:
        cod   = v.get("CodigoVendedor") or "?"
        ciclo = v.get("Ciclo") or "Sem Ciclo"
        vend_nome[cod] = v.get("Vendedor") or cod
        vend_ciclo[cod][ciclo] += _safe_float(v["TotalPraticado"])

    por_vendedor = sorted([
        {"codigo": cod, "nome": vend_nome[cod],
         "por_ciclo": {c: vend_ciclo[cod].get(c, 0) for c in ciclos}}
        for cod in vend_ciclo
    ], key=lambda x: sum(x["por_ciclo"].values()), reverse=True)

    # ── Por categoria ─────────────────────────────────────────────────────────
    cat_ciclo = defaultdict(lambda: defaultdict(float))
    for v in vendas:
        cat   = v.get("categoria") or "Outros"
        ciclo = v.get("Ciclo") or "Sem Ciclo"
        cat_ciclo[cat][ciclo] += _safe_float(v["TotalPraticado"])

    por_categoria = sorted([
        {"categoria": cat,
         "por_ciclo": {c: cat_ciclo[cat].get(c, 0) for c in ciclos}}
        for cat in cat_ciclo
    ], key=lambda x: sum(x["por_ciclo"].values()), reverse=True)

    return jsonify({"ciclos": ciclos, "por_vendedor": por_vendedor, "por_categoria": por_categoria})


@app.route("/api/vendedores")
def vendedores():
    """Lista de vendedores com métricas."""

    vendas = _aplicar_filtros(g.est["vendas"], request.args)

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

    vendas_vendedor = [v for v in g.est["vendas"] if v.get("CodigoVendedor") == codigo]
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

    # Por categoria + produtos por categoria
    por_categoria = defaultdict(float)
    prods_por_cat = defaultdict(lambda: defaultdict(lambda: {"sku": "", "nome": "", "total": 0.0, "quantidade": 0}))
    for v in vendas_vendedor:
        cat = v.get("categoria") or "Outros"
        val = _safe_float(v["TotalPraticado"])
        por_categoria[cat] += val
        sku = v.get("CodigoProduto") or v.get("CodigoProduto_normalizado") or "?"
        p = prods_por_cat[cat][sku]
        p["sku"] = sku
        p["nome"] = v.get("Produto") or sku
        p["total"] += val
        p["quantidade"] += v.get("Quantidade", 0)

    produtos_por_categoria = {
        cat: sorted(prods.values(), key=lambda x: x["total"], reverse=True)[:30]
        for cat, prods in prods_por_cat.items()
    }

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
        "por_categoria": [{"categoria": k, "total": v} for k, v in sorted(por_categoria.items(), key=lambda x: x[1], reverse=True)],
        "produtos_por_categoria": produtos_por_categoria,
    })


@app.route("/api/revendedores")
def revendedores():
    """Lista de revendedores com métricas, distribuição por papel e concentração 80/20."""

    vendas = _aplicar_filtros(g.est["vendas"], request.args)

    metricas = defaultdict(lambda: {
        "nome": "", "codigo": "", "papel": "",
        "total": 0.0, "pedidos": set(), "quantidade": 0,
        "vendedores": set(),
    })

    for v in vendas:
        cod = v.get("CodigoRevendedor") or v.get("Revendedor") or "?"
        m = metricas[cod]
        m["nome"] = (v.get("Revendedor") or cod).strip()
        m["codigo"] = cod
        m["papel"] = v.get("Papel") or "Sem papel"
        total = _safe_float(v["TotalPraticado"])
        m["total"] += total
        if v.get("CodigoPedido"):
            m["pedidos"].add(v["CodigoPedido"])
        m["quantidade"] += v.get("Quantidade", 0)
        vend_cod = v.get("CodigoVendedor") or ""
        if vend_cod:
            m["vendedores"].add(vend_cod)

    resultado = []
    for cod, m in metricas.items():
        total = m["total"]
        pedidos = len(m["pedidos"])
        resultado.append({
            "codigo": cod,
            "nome": m["nome"],
            "papel": m["papel"],
            "total_faturado": total,
            "qtd_pedidos": pedidos,
            "ticket_medio": total / pedidos if pedidos else 0,
            "quantidade": m["quantidade"],
            "qtd_vendedores": len(m["vendedores"]),
        })

    resultado.sort(key=lambda x: x["total_faturado"], reverse=True)

    # ── Distribuição por papel ────────────────────────────────────────────────
    papel_metricas = defaultdict(lambda: {"total": 0.0, "pedidos": set(), "revendedores": set()})
    for v in vendas:
        papel = v.get("Papel") or "Sem papel"
        papel_metricas[papel]["total"] += _safe_float(v["TotalPraticado"])
        if v.get("CodigoPedido"):
            papel_metricas[papel]["pedidos"].add(v["CodigoPedido"])
        cod = v.get("CodigoRevendedor") or v.get("Revendedor") or "?"
        papel_metricas[papel]["revendedores"].add(cod)

    por_papel = sorted([
        {
            "papel": k,
            "total_faturado": v["total"],
            "qtd_revendedores": len(v["revendedores"]),
            "qtd_pedidos": len(v["pedidos"]),
            "ticket_medio": v["total"] / len(v["pedidos"]) if v["pedidos"] else 0,
        }
        for k, v in papel_metricas.items()
    ], key=lambda x: x["total_faturado"], reverse=True)

    # ── Concentração 80/20 ────────────────────────────────────────────────────
    total_geral = sum(r["total_faturado"] for r in resultado)
    acum = 0.0
    qtd_80 = 0
    for r in resultado:
        acum += r["total_faturado"]
        qtd_80 += 1
        if acum >= total_geral * 0.8:
            break

    concentracao = {
        "total_revendedores": len(resultado),
        "qtd_80pct": qtd_80,
        "pct_rev_80pct": round(qtd_80 / len(resultado) * 100, 1) if resultado else 0,
        "total_faturado": total_geral,
    }

    return jsonify({
        "revendedores": resultado,
        "total": len(resultado),
        "por_papel": por_papel,
        "concentracao": concentracao,
    })


@app.route("/api/revendedor/<path:codigo>")
def revendedor_detalhe(codigo):
    """Detalhes de um revendedor específico."""

    vendas_rev = [v for v in g.est["vendas"]
                  if (v.get("CodigoRevendedor") or v.get("Revendedor") or "?") == codigo]
    if not vendas_rev:
        return jsonify({"erro": "Revendedor não encontrado"}), 404

    nome  = (vendas_rev[0].get("Revendedor") or codigo).strip()
    papel = vendas_rev[0].get("Papel") or "—"

    # Pedidos
    pedidos = defaultdict(lambda: {"codigo": "", "data": "", "vendedor": "", "total": 0.0, "itens": 0})
    for v in vendas_rev:
        cod_ped = v.get("CodigoPedido") or "?"
        p = pedidos[cod_ped]
        p["codigo"] = cod_ped
        p["data"] = v.get("DataFaturamento") or v.get("DataCaptacao") or ""
        p["vendedor"] = v.get("Vendedor") or "—"
        p["total"] += _safe_float(v["TotalPraticado"])
        p["itens"] += v.get("Quantidade", 0)
    lista_pedidos = sorted(pedidos.values(), key=lambda x: x["data"], reverse=True)

    # Por IAF
    por_iaf = defaultdict(float)
    for v in vendas_rev:
        por_iaf[v.get("classificacao_iaf", "Geral")] += _safe_float(v["TotalPraticado"])

    # Por ciclo
    por_ciclo = defaultdict(float)
    for v in vendas_rev:
        por_ciclo[v.get("Ciclo") or "Sem Ciclo"] += _safe_float(v["TotalPraticado"])

    # Top produtos
    top_prod = defaultdict(lambda: {"sku": "", "nome": "", "total": 0.0, "quantidade": 0})
    for v in vendas_rev:
        sku = v.get("CodigoProduto") or "?"
        top_prod[sku]["sku"] = sku
        top_prod[sku]["nome"] = v.get("Produto") or sku
        top_prod[sku]["total"] += _safe_float(v["TotalPraticado"])
        top_prod[sku]["quantidade"] += v.get("Quantidade", 0)
    lista_prod = sorted(top_prod.values(), key=lambda x: x["total"], reverse=True)[:20]

    # Vendedores que atenderam
    vendedores_map = defaultdict(lambda: {"codigo": "", "nome": "", "total": 0.0, "pedidos": set()})
    for v in vendas_rev:
        cod_v = v.get("CodigoVendedor") or "?"
        vendedores_map[cod_v]["codigo"] = cod_v
        vendedores_map[cod_v]["nome"] = v.get("Vendedor") or cod_v
        vendedores_map[cod_v]["total"] += _safe_float(v["TotalPraticado"])
        if v.get("CodigoPedido"):
            vendedores_map[cod_v]["pedidos"].add(v["CodigoPedido"])
    lista_vendedores = sorted(
        [{"codigo": k, "nome": v["nome"], "total": v["total"], "qtd_pedidos": len(v["pedidos"])}
         for k, v in vendedores_map.items()],
        key=lambda x: x["total"], reverse=True
    )

    total = sum(_safe_float(v["TotalPraticado"]) for v in vendas_rev)

    return jsonify({
        "codigo": codigo,
        "nome": nome,
        "papel": papel,
        "total_faturado": total,
        "qtd_pedidos": len(pedidos),
        "pedidos": lista_pedidos[:50],
        "por_iaf": [{"classificacao": k, "total": v} for k, v in por_iaf.items()],
        "por_ciclo": [{"ciclo": k, "total": v} for k, v in sorted(por_ciclo.items())],
        "top_produtos": lista_prod,
        "vendedores": lista_vendedores,
    })


@app.route("/api/produtos")
def produtos():
    """Lista de produtos com métricas."""

    vendas = _aplicar_filtros(g.est["vendas"], request.args)

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

    vendas = _aplicar_filtros(g.est["vendas"], request.args)

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

    vendas = g.est["vendas"]
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

    mu = g.est.get("marcas_usuario", {})
    vistos = {}
    for v in g.est["vendas"]:
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
        g.est["marcas_usuario"][sku_norm] = {"nome": nome, "marca": marca}
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
    g.est["indice_produtos"] = None
    g.est["indice_iaf"] = None

    # Salvar no GitHub (persistência permanente entre deploys)
    gh_ok, gh_erro = _gh_salvar_marcas(g.est["marcas_usuario"])
    # Invalida cache para que outros workers/sessões vejam as novas marcas
    if gh_ok:
        _gh_invalidar_cache()

    # Aplicar marcas do usuário diretamente nas vendas em memória
    _aplicar_marcas_usuario(g.est["vendas"])
    _salvar_estado()

    return jsonify({"ok": True, "salvos": salvos, "github": {"ok": gh_ok, "erro": gh_erro}})


@app.route("/api/dados")
def dados():
    """Dados brutos paginados."""

    vendas = _aplicar_filtros(g.est["vendas"], request.args)

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
    vendas = _aplicar_filtros(g.est["vendas"], request.args)

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
    nome_arquivo = (g.est["arquivo_nome"] or "vendas").replace(".xlsx", "")
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"{nome_arquivo}_processado.csv",
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
