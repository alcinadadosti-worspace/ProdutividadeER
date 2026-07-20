"""
app.py — Backend Flask principal
Analisador de Vendas — Grupo Alcina Maria / Grupo Boticário Alagoas
"""

import os
import io
import re
import csv
import json
import sqlite3
import base64
import hashlib
import threading
import unicodedata
import urllib.request
import urllib.error
from collections import defaultdict
import secrets as _secrets_mod
from datetime import datetime, timedelta


def _norm_nome(s):
    s = (s or "").strip().lower()
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


# Os vendedores oficiais do grupo vivem em vendedores.json e sao gerenciados
# pela aba Admin (ver _CADASTRO mais abaixo). Usado no KPI "Pedidos com
# Vendedor" do dashboard e para filtrar a aba Metas.

# Carrega variáveis do .env se existir (sem dependência externa)
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_path):
    with open(_env_path, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

from flask import Flask, request, jsonify, send_file, render_template, session, g

from processador import ler_planilha, preview_planilha, normalizar_sku
from cruzamento import criar_indices, cruzar_vendas

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100MB

# ─── Caminhos ─────────────────────────────────────────────────────────────────
BASE_DIR        = os.path.dirname(__file__)
DB_PATH         = os.path.join(BASE_DIR, "produtos.db")
STATE_FILE      = os.path.join(BASE_DIR, "_state.json")
CANCELADOS_FILE = os.path.join(BASE_DIR, "cancelados.json")
VENDEDORES_FILE = os.path.join(BASE_DIR, "vendedores.json")

# ─── GitHub — persistência permanente de arquivos de estado ──────────────────
# marcas_catalog.json e cancelados.json sobrevivem a deploys do Render gravando
# o JSON via Contents API do GitHub a cada modificação.
_GH_TOKEN          = os.environ.get("GITHUB_TOKEN", "")
_GH_REPO           = os.environ.get("GITHUB_REPO", "alcinadadosti-worspace/ProdutividadeER")
_GH_BRANCH         = os.environ.get("GITHUB_BRANCH", "master")
_GH_FILE_MARCAS    = "marcas_catalog.json"
_GH_FILE_CANCELADOS = "cancelados.json"
_GH_FILE_VENDEDORES = "vendedores.json"


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
        resp = _gh_request("GET", _GH_FILE_MARCAS)
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

        atual = _gh_request("GET", _GH_FILE_MARCAS)
        sha   = atual["sha"] if atual else None

        body = {
            "message": "chore: atualizar marcas do catálogo [auto]",
            "content": encoded,
            "branch":  _GH_BRANCH,
        }
        if sha:
            body["sha"] = sha

        _gh_request("PUT", _GH_FILE_MARCAS, body)
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


def _gh_ler_cancelados():
    """Lê cancelados.json do GitHub. Retorna lista de strings (códigos)."""
    if not _gh_ok():
        return []
    try:
        resp = _gh_request("GET", _GH_FILE_CANCELADOS)
        if not resp:
            return []
        conteudo = base64.b64decode(resp["content"]).decode("utf-8")
        data = json.loads(conteudo)
        if isinstance(data, dict):
            return data.get("cancelados", []) or []
        return []
    except Exception as e:
        app.logger.warning(f"[GitHub] Erro ao ler cancelados: {e}")
        return []


def _gh_salvar_cancelados(codigos_set):
    """Salva cancelados.json no GitHub. Retorna (ok, erro).
    Aceita salvar lista vazia (diferente das marcas) — remover o último código
    deve refletir no repositório."""
    if not _gh_ok():
        return False, "GITHUB_TOKEN não configurado"
    try:
        conteudo = json.dumps(
            {"cancelados": sorted(codigos_set)},
            ensure_ascii=False, indent=2,
        )
        encoded = base64.b64encode(conteudo.encode("utf-8")).decode()

        atual = _gh_request("GET", _GH_FILE_CANCELADOS)
        sha   = atual["sha"] if atual else None

        body = {
            "message": f"chore: atualizar lista de pedidos cancelados ({len(codigos_set)}) [auto]",
            "content": encoded,
            "branch":  _GH_BRANCH,
        }
        if sha:
            body["sha"] = sha

        _gh_request("PUT", _GH_FILE_CANCELADOS, body)
        app.logger.info(f"[GitHub] cancelados.json atualizado ({len(codigos_set)} códigos)")
        return True, None
    except urllib.error.HTTPError as e:
        corpo = e.read().decode("utf-8", errors="replace")
        msg = f"HTTP {e.code}: {corpo}"
        app.logger.warning(f"[GitHub] Erro ao salvar cancelados: {msg}")
        return False, msg
    except Exception as e:
        app.logger.warning(f"[GitHub] Erro ao salvar cancelados: {e}")
        return False, str(e)


def _gh_ler_vendedores():
    """Lê vendedores.json do GitHub. Retorna dict ou None se não existir."""
    if not _gh_ok():
        return None
    try:
        resp = _gh_request("GET", _GH_FILE_VENDEDORES)
        if not resp:
            return None
        conteudo = base64.b64decode(resp["content"]).decode("utf-8")
        data = json.loads(conteudo)
        return data if isinstance(data, dict) else None
    except Exception as e:
        app.logger.warning(f"[GitHub] Erro ao ler vendedores: {e}")
        return None


def _gh_salvar_vendedores(cadastro):
    """Salva vendedores.json no GitHub. Retorna (ok, erro)."""
    if not _gh_ok():
        return False, "GITHUB_TOKEN não configurado"
    try:
        conteudo = json.dumps(cadastro, ensure_ascii=False, indent=2)
        encoded  = base64.b64encode(conteudo.encode("utf-8")).decode()

        atual = _gh_request("GET", _GH_FILE_VENDEDORES)
        sha   = atual["sha"] if atual else None

        body = {
            "message": "chore: atualizar cadastro de vendedores/metas [auto]",
            "content": encoded,
            "branch": _GH_BRANCH,
        }
        if sha:
            body["sha"] = sha

        _gh_request("PUT", _GH_FILE_VENDEDORES, body)
        qtd = len(cadastro.get("vendedores", []))
        app.logger.info(f"[GitHub] vendedores.json atualizado ({qtd} vendedores)")
        return True, None
    except urllib.error.HTTPError as e:
        corpo = e.read().decode("utf-8", errors="replace")
        msg = f"HTTP {e.code}: {corpo}"
        app.logger.warning(f"[GitHub] Erro ao salvar vendedores: {msg}")
        return False, msg
    except Exception as e:
        app.logger.warning(f"[GitHub] Erro ao salvar vendedores: {e}")
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

# Carregamento da lista global de pedidos cancelados acontece em
# _carregar_cancelados_disco() (definida adiante). A chamada efetiva é feita
# logo depois que a função existe, garantindo o set populado antes de qualquer
# request chegar.


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


# ─── Pedidos cancelados — lista global permanente ─────────────────────────────
# A lista é única para o app inteiro (não por sessão). Vendas cujo CodigoPedido
# bate com qualquer código aqui são separadas em "vendas_canceladas" e não
# contribuem para o dashboard / KPIs.

_CANCELADOS_LOCK = threading.Lock()
_CANCELADOS_SET: set = set()


def _normalizar_codigo_pedido(valor):
    """Extrai apenas dígitos do código do pedido. Ex: '503.638.930' → '503638930'."""
    if valor is None:
        return ""
    return re.sub(r"[^\d]", "", str(valor))


def _carregar_cancelados_disco():
    """Lê cancelados.json (disco local) para o set em memória.
    Tolerante a arquivo ausente."""
    global _CANCELADOS_SET
    try:
        if os.path.exists(CANCELADOS_FILE):
            with open(CANCELADOS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            lista = data.get("cancelados", []) if isinstance(data, dict) else []
            _CANCELADOS_SET = {
                _normalizar_codigo_pedido(c) for c in lista
                if _normalizar_codigo_pedido(c)
            }
            app.logger.info(f"[Cancelados] {len(_CANCELADOS_SET)} pedidos carregados do disco")
    except Exception as e:
        app.logger.warning(f"[Cancelados] Erro ao carregar {CANCELADOS_FILE}: {e}")
        _CANCELADOS_SET = set()


def _sincronizar_cancelados_github():
    """Baixa cancelados.json do GitHub e mescla (união) com o set em memória.
    Roda no startup — em ambientes efêmeros (Render) o disco local é zerado
    a cada deploy, então o GitHub é a fonte de verdade. A união evita perder
    códigos adicionados localmente caso a sincronização anterior tenha falhado.
    Sobre conflito: se o GitHub e o disco divergirem, ambos os códigos são
    mantidos. Remoções precisam ser propagadas via DELETE."""
    global _CANCELADOS_SET
    if not _gh_ok():
        return
    try:
        remotos = _gh_ler_cancelados()
        remotos_set = {
            _normalizar_codigo_pedido(c) for c in remotos
            if _normalizar_codigo_pedido(c)
        }
        antes = len(_CANCELADOS_SET)
        _CANCELADOS_SET = _CANCELADOS_SET | remotos_set
        depois = len(_CANCELADOS_SET)
        app.logger.info(
            f"[Cancelados] Sincronizado com GitHub: "
            f"{len(remotos_set)} no remoto, {antes} local, {depois} mesclado"
        )
        # Se a mesclagem mudou alguma coisa, persiste no disco local pra próximas
        # leituras coincidirem com o estado em memória.
        if depois != len(remotos_set) or depois != antes:
            _salvar_cancelados_disco()
    except Exception as e:
        app.logger.warning(f"[Cancelados] Erro na sincronização com GitHub: {e}")


def _salvar_cancelados_disco():
    """Persiste o set atual em cancelados.json."""
    try:
        with open(CANCELADOS_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {"cancelados": sorted(_CANCELADOS_SET)},
                f, ensure_ascii=False, indent=2,
            )
    except Exception as e:
        app.logger.error(f"[Cancelados] Erro ao salvar {CANCELADOS_FILE}: {e}")


def _eh_cancelado(venda):
    return _normalizar_codigo_pedido(venda.get("CodigoPedido")) in _CANCELADOS_SET


# Popula o set imediatamente após a definição da função.
# Primeiro lê o disco (fallback), depois mescla com GitHub (fonte de verdade
# em ambientes efêmeros como o Render).
_carregar_cancelados_disco()
_sincronizar_cancelados_github()


# ─── Cadastro de vendedores e metas ───────────────────────────────────────────
# vendedores.json guarda o time oficial e as metas em tres niveis:
#   metas_globais            → valem para todo mundo
#   metas_unidade[unidade]   → sobrescrevem a global para aquela unidade
#   vendedores[].metas       → sobrescrevem tudo para aquela pessoa
# Cada nivel pode sobrescrever so um dos campos (ex.: so multimarca) — os
# demais continuam herdados do nivel de cima.

UNIDADES = ["Matriz Penedo", "Filial Palmeira dos Índios"]
_METAS_CAMPOS = ("multimarca", "iaf_cabelos", "iaf_make")
_METAS_PADRAO = {"multimarca": 72.0, "iaf_cabelos": 37.0, "iaf_make": 38.0}

_CADASTRO_LOCK = threading.Lock()
_CADASTRO: dict = {"metas_globais": dict(_METAS_PADRAO), "metas_unidade": {}, "vendedores": []}


def _cadastro_normalizado(data):
    """Valida/normaliza a estrutura lida do disco ou do GitHub."""
    if not isinstance(data, dict):
        return None
    globais = dict(_METAS_PADRAO)
    for k, v in (data.get("metas_globais") or {}).items():
        if k in _METAS_CAMPOS and v is not None:
            try:
                globais[k] = float(v)
            except (TypeError, ValueError):
                pass

    por_unidade = {}
    for un, metas in (data.get("metas_unidade") or {}).items():
        limpo = {}
        for k, v in (metas or {}).items():
            if k in _METAS_CAMPOS and v is not None:
                try:
                    limpo[k] = float(v)
                except (TypeError, ValueError):
                    pass
        if limpo:
            por_unidade[un] = limpo

    vendedores = []
    vistos = set()
    for v in (data.get("vendedores") or []):
        if not isinstance(v, dict):
            continue
        nome = (v.get("nome") or "").strip()
        if not nome or _norm_nome(nome) in vistos:
            continue
        vistos.add(_norm_nome(nome))
        metas = {}
        for k, val in (v.get("metas") or {}).items():
            if k in _METAS_CAMPOS and val is not None:
                try:
                    metas[k] = float(val)
                except (TypeError, ValueError):
                    pass
        vendedores.append({
            "nome": nome,
            "slack_id": (v.get("slack_id") or "").strip().upper(),
            "unidade": (v.get("unidade") or "").strip(),
            "metas": metas,
        })

    return {"metas_globais": globais, "metas_unidade": por_unidade, "vendedores": vendedores}


def _carregar_cadastro_disco():
    """Lê vendedores.json do disco local. Tolerante a arquivo ausente."""
    global _CADASTRO
    try:
        if os.path.exists(VENDEDORES_FILE):
            with open(VENDEDORES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            limpo = _cadastro_normalizado(data)
            if limpo:
                _CADASTRO = limpo
                app.logger.info(f"[Cadastro] {len(limpo['vendedores'])} vendedores carregados do disco")
    except Exception as e:
        app.logger.warning(f"[Cadastro] Erro ao carregar {VENDEDORES_FILE}: {e}")


def _sincronizar_cadastro_github():
    """Baixa vendedores.json do GitHub e adota como fonte de verdade.
    Diferente dos cancelados (que fazem união), aqui o remoto substitui o local:
    uma remoção de vendedor precisa se propagar, e mesclar traria de volta quem
    foi removido em outra instância."""
    global _CADASTRO
    if not _gh_ok():
        return
    try:
        remoto = _gh_ler_vendedores()
        limpo = _cadastro_normalizado(remoto) if remoto else None
        if not limpo:
            return
        _CADASTRO = limpo
        _salvar_cadastro_disco()
        app.logger.info(f"[Cadastro] Sincronizado com GitHub: {len(limpo['vendedores'])} vendedores")
    except Exception as e:
        app.logger.warning(f"[Cadastro] Erro na sincronização com GitHub: {e}")


def _salvar_cadastro_disco():
    try:
        with open(VENDEDORES_FILE, "w", encoding="utf-8") as f:
            json.dump(_CADASTRO, f, ensure_ascii=False, indent=2)
    except Exception as e:
        app.logger.error(f"[Cadastro] Erro ao salvar {VENDEDORES_FILE}: {e}")


def _persistir_cadastro():
    """Grava no disco e no GitHub. Retorna aviso (str) se o GitHub falhou."""
    _salvar_cadastro_disco()
    if not _gh_ok():
        return "Alteração salva apenas no disco local (GITHUB_TOKEN não configurado) — pode se perder no próximo deploy."
    ok, erro = _gh_salvar_vendedores(_CADASTRO)
    if not ok:
        return f"Alteração salva localmente, mas falhou ao gravar no GitHub: {erro}"
    return None


def _buscar_vendedor(nome):
    alvo = _norm_nome(nome)
    for v in _CADASTRO["vendedores"]:
        if _norm_nome(v["nome"]) == alvo:
            return v
    return None


def _vendedores_oficiais_norm():
    """Set de nomes normalizados do time oficial (para KPIs e filtros)."""
    return {_norm_nome(v["nome"]) for v in _CADASTRO["vendedores"]}


def _metas_resolvidas(vend):
    """Metas efetivas de um vendedor: global < unidade < individual."""
    metas = dict(_METAS_PADRAO)
    metas.update(_CADASTRO.get("metas_globais") or {})
    unidade = (vend or {}).get("unidade") or ""
    metas.update(_CADASTRO.get("metas_unidade", {}).get(unidade) or {})
    metas.update((vend or {}).get("metas") or {})
    return {k: float(metas.get(k, _METAS_PADRAO[k])) for k in _METAS_CAMPOS}


def _metas_origem(vend):
    """De qual nível veio cada meta — usado para mostrar 'herdado' na aba Admin."""
    unidade = (vend or {}).get("unidade") or ""
    da_unidade = _CADASTRO.get("metas_unidade", {}).get(unidade) or {}
    individual = (vend or {}).get("metas") or {}
    origem = {}
    for k in _METAS_CAMPOS:
        if k in individual:
            origem[k] = "individual"
        elif k in da_unidade:
            origem[k] = "unidade"
        else:
            origem[k] = "global"
    return origem


_carregar_cadastro_disco()
_sincronizar_cadastro_github()


# ─── Autenticação da aba Admin ────────────────────────────────────────────────
# Tres senhas, cada uma com um escopo: cada unidade gerencia so o proprio time,
# e a senha geral enxerga as duas. As senhas nao ficam em texto puro no codigo
# (o repo vai pro GitHub) — guardamos o SHA-256 com salt. Para trocar, defina
# ADMIN_SENHA_GERAL / ADMIN_SENHA_PENEDO / ADMIN_SENHA_PALMEIRA no ambiente,
# que tem precedencia sobre os hashes abaixo.

ESCOPO_GERAL = "*"
_ADMIN_SALT = "alcina-admin-v1|"
_ADMIN_HASHES = {
    ESCOPO_GERAL:                 "05f64fa7d9ba0b393a8de9ecf0614876912f199457aea60e1a8b3fe545860586",
    "Matriz Penedo":              "29b4f52eecca90dc4e005eb7a2a585e973fcab864169a74a23a3ba6e8a2e6cb1",
    "Filial Palmeira dos Índios": "67f5ea384e32af9a773beb8097577a9cf0c2e5962a3aa24e1e2104db21564851",
}
_ADMIN_ENV = {
    ESCOPO_GERAL:                 "ADMIN_SENHA_GERAL",
    "Matriz Penedo":              "ADMIN_SENHA_PENEDO",
    "Filial Palmeira dos Índios": "ADMIN_SENHA_PALMEIRA",
}


def _escopo_da_senha(senha):
    """Retorna o escopo correspondente à senha, ou None."""
    senha = (senha or "").strip()
    if not senha:
        return None
    digest = hashlib.sha256((_ADMIN_SALT + senha).encode("utf-8")).hexdigest()
    for escopo, hash_padrao in _ADMIN_HASHES.items():
        env_valor = os.environ.get(_ADMIN_ENV[escopo], "").strip()
        if env_valor:
            if secrets_compare(senha, env_valor):
                return escopo
        elif secrets_compare(digest, hash_padrao):
            return escopo
    return None


def secrets_compare(a, b):
    return _secrets_mod.compare_digest(str(a), str(b))


def _escopo_atual():
    return session.get("admin_escopo") or None


def _unidades_do_escopo(escopo):
    return list(UNIDADES) if escopo == ESCOPO_GERAL else [escopo]


def _pode_gerenciar(escopo, unidade):
    return bool(escopo) and (escopo == ESCOPO_GERAL or escopo == unidade)


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
        "vendas_canceladas": [],
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
            est["vendas"]             = data.get("vendas", [])
            est["vendas_canceladas"]  = data.get("vendas_canceladas", [])
            est["arquivo_nome"]       = data.get("arquivo_nome")
            est["processado_em"]      = data.get("processado_em")
            est["marcas_usuario"]     = data.get("marcas_usuario", {})
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
    if request.endpoint in (None, "static", "ping"):
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
                "vendas_canceladas": est.get("vendas_canceladas", []),
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


def _multimarca_por_cliente(vendas, bonus_primeiro=0.02, teto=100.0):
    """Multimarca por CLIENTE (revendedor), agrupado por vendedor.

    Regra oficial:
      - Cliente ativo = revendedor com ao menos 1 pedido no período.
      - Cliente multimarca = comprou 2+ marcas distintas somando TODOS os pedidos.
      - Cada cliente conta UMA vez; é creditado ao vendedor do 1º pedido dele
        (ordenado pelo Código do Pedido, que é cronológico).
      - Bônus de +2% quando o cliente já é multimarca no 1º pedido.
      - % = soma dos pontos / clientes ativos, limitado a `teto` (100%).

    Retorna { cod_vendedor: {ativos, multi, mono, first, built, pontos, pct} }.
    """
    # 1. Agrupar linhas por pedido
    pedidos = {}
    for v in vendas:
        ped = v.get("CodigoPedido") or v.get("NotaFiscal")
        if not ped:
            continue
        p = pedidos.get(ped)
        if p is None:
            digs = "".join(ch for ch in str(ped) if ch.isdigit())
            p = pedidos[ped] = {"vend": "", "rev": "", "ordem": int(digs) if digs else 0, "marcas": set()}
        if not p["vend"] and v.get("CodigoVendedor"):
            p["vend"] = v.get("CodigoVendedor")
        if not p["rev"]:
            p["rev"] = v.get("CodigoRevendedor") or v.get("Revendedor") or ""
        marca = v.get("marca") or ""
        if marca:
            p["marcas"].add(marca)

    # 2. Agrupar pedidos por cliente
    clientes = defaultdict(list)
    for p in pedidos.values():
        if p["rev"]:
            clientes[p["rev"]].append(p)

    # 3. Creditar cada cliente ao vendedor do 1º pedido
    agg = defaultdict(lambda: {"ativos": 0, "multi": 0, "mono": 0,
                               "first": 0, "built": 0, "pontos": 0.0})
    for peds in clientes.values():
        peds.sort(key=lambda x: x["ordem"])
        primeiro = peds[0]
        vend = primeiro["vend"] or "?"
        marcas_tot = set()
        for p in peds:
            marcas_tot |= p["marcas"]
        is_multi = len(marcas_tot) >= 2
        first_multi = len(primeiro["marcas"]) >= 2
        m = agg[vend]
        m["ativos"] += 1
        if is_multi:
            m["multi"] += 1
            m["pontos"] += (1.0 + bonus_primeiro) if first_multi else 1.0
            if first_multi:
                m["first"] += 1
            else:
                m["built"] += 1
        else:
            m["mono"] += 1

    for m in agg.values():
        m["pct"] = min(teto, m["pontos"] / m["ativos"] * 100) if m["ativos"] else 0.0
    return agg


# ─── Rotas ────────────────────────────────────────────────────────────────────

@app.route("/ping", methods=["GET", "HEAD"])
def ping():
    """Endpoint leve para monitoramento (UptimeRobot, etc.) — sem sessão."""
    return "", 200


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

        # ── Separar vendas canceladas (lista global permanente) ───────────────
        # Linhas cujo CodigoPedido bate com a lista de cancelados não vão para
        # análise — ficam isoladas em "vendas_canceladas" para a aba dedicada.
        vendas_ok   = [v for v in vendas if not _eh_cancelado(v)]
        vendas_canc = [v for v in vendas if     _eh_cancelado(v)]

        # ── Mesclar com dados existentes (sem sobrescrever) ───────────────────
        # Chave de deduplicação: CodigoPedido + CodigoProduto_normalizado
        def _chave(v):
            return (v.get("CodigoPedido") or "", v.get("CodigoProduto_normalizado") or "")

        existentes = {_chave(v) for v in g.est["vendas"]}
        novas = [v for v in vendas_ok if _chave(v) not in existentes]
        g.est["vendas"] = g.est["vendas"] + novas

        existentes_canc = {_chave(v) for v in g.est.get("vendas_canceladas", [])}
        novas_canc = [v for v in vendas_canc if _chave(v) not in existentes_canc]
        g.est["vendas_canceladas"] = g.est.get("vendas_canceladas", []) + novas_canc

        g.est["arquivo_nome"] = nome_arquivo
        g.est["processado_em"] = datetime.now().isoformat()
        _salvar_estado()

        ciclos = sorted({v.get("Ciclo") or "" for v in g.est["vendas"]} - {""})
        return jsonify({
            "ok": True,
            "total_processado": len(g.est["vendas"]),
            "novos_registros": len(novas),
            "registros_cancelados_excluidos": len(novas_canc),
            "total_cancelados_acumulado": len(g.est["vendas_canceladas"]),
            "processado_em": g.est["processado_em"],
            "ciclos": ciclos,
        })
    except Exception as e:
        import traceback
        return jsonify({"erro": f"Erro no processamento: {str(e)}", "detalhe": traceback.format_exc()}), 500


@app.route("/api/cancelados", methods=["GET"])
def cancelados_listar():
    """Retorna a lista permanente de códigos de pedido cancelados."""
    with _CANCELADOS_LOCK:
        lista = sorted(_CANCELADOS_SET)
    return jsonify({"cancelados": lista, "total": len(lista)})


@app.route("/api/cancelados", methods=["POST"])
def cancelados_adicionar():
    """Adiciona um ou mais códigos de pedido à lista permanente.
    Body: {"codigos": ["503638930", ...]}  (aceita também 'codigo' singular).
    Cada código deve ter exatamente 9 dígitos após normalização (remoção de
    pontos, espaços, traços). Move vendas correspondentes em memória para
    'vendas_canceladas'."""
    body = request.json or {}
    entrada = body.get("codigos")
    if entrada is None and "codigo" in body:
        entrada = [body["codigo"]]
    if not isinstance(entrada, list):
        return jsonify({"erro": "Envie 'codigos' como lista ou 'codigo' como string"}), 400

    adicionados = []
    rejeitados  = []
    for raw in entrada:
        cod = _normalizar_codigo_pedido(raw)
        if len(cod) != 9:
            rejeitados.append({"valor": str(raw), "motivo": "deve conter exatamente 9 dígitos"})
            continue
        with _CANCELADOS_LOCK:
            if cod in _CANCELADOS_SET:
                rejeitados.append({"valor": str(raw), "motivo": "já estava na lista"})
                continue
            _CANCELADOS_SET.add(cod)
        adicionados.append(cod)

    gh_ok = None
    gh_erro = None
    if adicionados:
        with _CANCELADOS_LOCK:
            _salvar_cancelados_disco()
            snapshot = set(_CANCELADOS_SET)

        # Persistência permanente: salva no GitHub para sobreviver a redeploys.
        gh_ok, gh_erro = _gh_salvar_cancelados(snapshot)

        # Move linhas já presentes em g.est["vendas"] para vendas_canceladas
        movidas = [v for v in g.est["vendas"] if _eh_cancelado(v)]
        if movidas:
            g.est["vendas"] = [v for v in g.est["vendas"] if not _eh_cancelado(v)]
            existentes_canc = {
                (v.get("CodigoPedido") or "", v.get("CodigoProduto_normalizado") or "")
                for v in g.est.get("vendas_canceladas", [])
            }
            novas_canc = [
                v for v in movidas
                if (v.get("CodigoPedido") or "", v.get("CodigoProduto_normalizado") or "") not in existentes_canc
            ]
            g.est["vendas_canceladas"] = g.est.get("vendas_canceladas", []) + novas_canc
            _salvar_estado()
        movidas_total = len(movidas)
    else:
        movidas_total = 0

    with _CANCELADOS_LOCK:
        total = len(_CANCELADOS_SET)
        lista = sorted(_CANCELADOS_SET)

    return jsonify({
        "ok": True,
        "adicionados": adicionados,
        "rejeitados": rejeitados,
        "linhas_movidas": movidas_total,
        "total": total,
        "cancelados": lista,
        "github": {"ok": gh_ok, "erro": gh_erro},
    })


@app.route("/api/cancelados/<codigo>", methods=["DELETE"])
def cancelados_remover(codigo):
    """Remove um código de pedido da lista. Devolve as linhas correspondentes
    para 'vendas' (deixa de tratá-las como canceladas)."""
    cod = _normalizar_codigo_pedido(codigo)
    if len(cod) != 9:
        return jsonify({"erro": "Código deve conter 9 dígitos"}), 400

    with _CANCELADOS_LOCK:
        existia = cod in _CANCELADOS_SET
        _CANCELADOS_SET.discard(cod)
        if existia:
            _salvar_cancelados_disco()
        snapshot = set(_CANCELADOS_SET)

    if not existia:
        return jsonify({"erro": "Código não estava na lista"}), 404

    # Persistência permanente: sincroniza remoção com GitHub.
    gh_ok, gh_erro = _gh_salvar_cancelados(snapshot)

    # Devolve linhas para vendas
    voltam = [
        v for v in g.est.get("vendas_canceladas", [])
        if _normalizar_codigo_pedido(v.get("CodigoPedido")) == cod
    ]
    if voltam:
        g.est["vendas_canceladas"] = [
            v for v in g.est.get("vendas_canceladas", [])
            if _normalizar_codigo_pedido(v.get("CodigoPedido")) != cod
        ]
        existentes = {
            (v.get("CodigoPedido") or "", v.get("CodigoProduto_normalizado") or "")
            for v in g.est["vendas"]
        }
        novas = [
            v for v in voltam
            if (v.get("CodigoPedido") or "", v.get("CodigoProduto_normalizado") or "") not in existentes
        ]
        g.est["vendas"] = g.est["vendas"] + novas
        _salvar_estado()

    with _CANCELADOS_LOCK:
        total = len(_CANCELADOS_SET)
        lista = sorted(_CANCELADOS_SET)

    return jsonify({
        "ok": True,
        "removido": cod,
        "linhas_devolvidas": len(voltam),
        "total": total,
        "cancelados": lista,
        "github": {"ok": gh_ok, "erro": gh_erro},
    })


@app.route("/api/cancelados/dados")
def cancelados_dados():
    """Retorna detalhes (todas as linhas) de cada pedido cancelado.
    Agrupado por código de pedido. Inclui códigos da lista que ainda não
    apareceram em nenhuma planilha (encontrado=false)."""
    with _CANCELADOS_LOCK:
        codigos = sorted(_CANCELADOS_SET)

    por_codigo = defaultdict(list)
    for v in g.est.get("vendas_canceladas", []):
        cod = _normalizar_codigo_pedido(v.get("CodigoPedido"))
        if cod:
            por_codigo[cod].append(v)

    campos = [
        "CodigoVendedor", "Vendedor", "CodigoProduto", "Produto", "marca",
        "Quantidade", "TotalPraticado", "CodigoPedido", "Ciclo",
        "DataFaturamento", "Revendedor", "Papel", "PlanoPagamento",
        "Unidade", "CanalDistribuicao", "classificacao_iaf",
        "NotaFiscal", "UsuarioCriacao", "UsuarioFinalizacao",
    ]

    resultado = []
    for cod in codigos:
        linhas_raw = por_codigo.get(cod, [])
        linhas = [{c: v.get(c) for c in campos} for v in linhas_raw]
        total = sum(_safe_float(v.get("TotalPraticado")) for v in linhas_raw)
        qtd_itens = sum(int(v.get("Quantidade") or 0) for v in linhas_raw)
        primeira = linhas_raw[0] if linhas_raw else {}
        resultado.append({
            "codigo": cod,
            "encontrado": bool(linhas_raw),
            "total_linhas": len(linhas_raw),
            "total_faturado": total,
            "qtd_itens": qtd_itens,
            "vendedor": primeira.get("Vendedor") or "",
            "revendedor": primeira.get("Revendedor") or "",
            "ciclo": primeira.get("Ciclo") or "",
            "data": primeira.get("DataFaturamento") or "",
            "linhas": linhas,
        })

    return jsonify({
        "cancelados": resultado,
        "total_codigos": len(codigos),
        "total_linhas": sum(r["total_linhas"] for r in resultado),
        "total_faturado_excluido": sum(r["total_faturado"] for r in resultado),
    })


@app.route("/api/limpar", methods=["POST"])
def limpar():
    """Remove todos os dados processados e reseta o estado.
    Não toca em cancelados.json (lista permanente) — apenas nas linhas
    em memória que estavam classificadas como canceladas."""
    sid = session.get("sid", "")
    g.est["vendas"] = []
    g.est["vendas_canceladas"] = []
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
    g.est["vendas_canceladas"] = [
        v for v in g.est.get("vendas_canceladas", []) if v.get("Ciclo") != ciclo
    ]
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
    """Diagnóstico da integração com GitHub (marcas + cancelados)."""
    resultado = {
        "token_configurado": bool(_GH_TOKEN),
        "repo": _GH_REPO,
        "branch": _GH_BRANCH,
        "arquivos": {
            "marcas":     {"path": _GH_FILE_MARCAS},
            "cancelados": {"path": _GH_FILE_CANCELADOS},
        },
    }
    if not _gh_ok():
        resultado["erro"] = "GITHUB_TOKEN não configurado"
        return jsonify(resultado), 200

    for chave, path in (("marcas", _GH_FILE_MARCAS), ("cancelados", _GH_FILE_CANCELADOS)):
        try:
            resp = _gh_request("GET", path)
            if resp:
                resultado["arquivos"][chave].update({
                    "existe": True,
                    "tamanho_bytes": resp.get("size", 0),
                    "ultimo_commit": resp.get("sha", "")[:7],
                })
            else:
                resultado["arquivos"][chave]["existe"] = False
        except Exception as e:
            resultado["arquivos"][chave]["erro_api"] = str(e)

    return jsonify(resultado)


@app.route("/api/dashboard")
def dashboard():
    """KPIs e dados agregados para o dashboard principal."""

    vendas = _aplicar_filtros(g.est["vendas"], request.args)

    if not vendas:
        return jsonify(_dashboard_vazio())

    total_faturado = sum(_safe_float(v["TotalPraticado"]) for v in vendas)

    # Pedidos contados por Nota Fiscal (uma nota = um pedido). Fallback para CodigoPedido se faltar.
    # "Pedidos com Vendedor" considera APENAS o time cadastrado em vendedores.json —
    # pedidos atribuidos a outros usuarios (gerentes, supervisores) nao entram nesse card.
    oficiais        = _vendedores_oficiais_norm()
    notas_total     = set()
    notas_sem       = set()
    notas_oficiais  = set()
    fat_sem_vend    = 0.0
    for v in vendas:
        nf = v.get("NotaFiscal") or v.get("CodigoPedido")
        if not nf:
            continue
        notas_total.add(nf)
        if v.get("sem_codigo_vendedor"):
            notas_sem.add(nf)
            fat_sem_vend += _safe_float(v["TotalPraticado"])
        if _norm_nome(v.get("Vendedor")) in oficiais:
            notas_oficiais.add(nf)

    pedidos_unicos    = len(notas_total)
    pedidos_sem_vend  = len(notas_sem)
    pedidos_com_vend  = len(notas_oficiais)
    pct_sem_vend      = (pedidos_sem_vend / pedidos_unicos * 100) if pedidos_unicos else 0
    pct_com_vend      = (pedidos_com_vend / pedidos_unicos * 100) if pedidos_unicos else 0
    ticket_medio      = total_faturado / pedidos_unicos if pedidos_unicos else 0
    total_itens       = sum(v.get("Quantidade", 0) for v in vendas)

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
            "pedidos_com_vendedor": pedidos_com_vend,
            "pedidos_sem_vendedor": pedidos_sem_vend,
            "pct_pedidos_com_vendedor": pct_com_vend,
            "pct_pedidos_sem_vendedor": pct_sem_vend,
            "fat_sem_vendedor": fat_sem_vend,
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
        "kpis": {
            "total_faturado": 0, "total_pedidos": 0, "ticket_medio": 0, "total_itens": 0,
            "pedidos_com_vendedor": 0, "pedidos_sem_vendedor": 0,
            "pct_pedidos_com_vendedor": 0, "pct_pedidos_sem_vendedor": 0,
            "fat_sem_vendedor": 0,
        },
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

    # Aplica filtros exceto ciclo (ciclo é controlado pela própria UI do comparativo)
    args_sem_ciclo = {k: v for k, v in request.args.items() if k != "ciclo"}
    vendas = _aplicar_filtros(g.est["vendas"], args_sem_ciclo)
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
        ped = v.get("NotaFiscal") or v.get("CodigoPedido")
        if ped:
            m["pedidos"].add(ped)
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

    # Retenção: calculada de TODOS os dados (sem filtro), pois é indicador histórico
    ret_dados = defaultdict(lambda: defaultdict(set))  # vend_cod -> rev_cod -> set(ciclos)
    for v in g.est["vendas"]:
        cod_vend = v.get("CodigoVendedor") or "?"
        cod_rev = v.get("CodigoRevendedor") or v.get("Revendedor") or "?"
        ciclo = v.get("Ciclo") or ""
        if ciclo:
            ret_dados[cod_vend][cod_rev].add(ciclo)

    total_ciclos = len({v.get("Ciclo") or "" for v in g.est["vendas"]} - {""})

    total_pedidos_geral = sum(len(m["pedidos"]) for m in metricas.values())

    # Multimarca por CLIENTE (revendedor), creditado ao vendedor do 1º pedido
    mm = _multimarca_por_cliente(vendas)

    resultado = []
    for cod, m in metricas.items():
        total = m["total"]
        pedidos = len(m["pedidos"])
        marcas_ord = sorted(m["marcas"].items(), key=lambda x: x[1], reverse=True)
        rev_ciclos = ret_dados.get(cod, {})
        qtd_revendedores = len(rev_ciclos)
        qtd_retidos = sum(1 for cs in rev_ciclos.values() if len(cs) > 1)

        # Clientes multi/monomarca (regra por cliente, com bônus de 1º pedido)
        mmv = mm.get(cod, {})
        qtd_multimarca = mmv.get("multi", 0)
        qtd_monomarca  = mmv.get("mono", 0)
        base_marca     = mmv.get("ativos", 0)

        resultado.append({
            "codigo": cod,
            "nome": m["nome"],
            "total_faturado": total,
            "qtd_pedidos": pedidos,
            "pct_pedidos": (pedidos / total_pedidos_geral * 100) if total_pedidos_geral else 0,
            "ticket_medio": total / pedidos if pedidos else 0,
            "quantidade": m["quantidade"],
            "pct_iaf_cabelos": (m["iaf_cabelos"] / total * 100) if total else 0,
            "pct_iaf_make": (m["iaf_make"] / total * 100) if total else 0,
            "pct_geral": (m["geral"] / total * 100) if total else 0,
            "qtd_marcas": len(marcas_ord),
            "top_marca": marcas_ord[0][0] if marcas_ord else "—",
            "qtd_revendedores": qtd_revendedores,
            "qtd_retidos": qtd_retidos,
            "pct_retencao": (qtd_retidos / qtd_revendedores * 100) if qtd_revendedores else 0,
            "qtd_pedidos_multimarca": qtd_multimarca,
            "qtd_pedidos_monomarca": qtd_monomarca,
            "pct_pedidos_multimarca": mmv.get("pct", 0),
            "pct_pedidos_monomarca": (qtd_monomarca / base_marca * 100) if base_marca else 0,
        })

    resultado.sort(key=lambda x: x["total_faturado"], reverse=True)
    return jsonify({"vendedores": resultado, "total": len(resultado), "total_ciclos": total_ciclos})


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

    # Retenção por ciclo
    rev_por_ciclo = defaultdict(set)
    for v in vendas_vendedor:
        ciclo = v.get("Ciclo") or ""
        if ciclo:
            cod_rev = v.get("CodigoRevendedor") or v.get("Revendedor") or "?"
            rev_por_ciclo[ciclo].add(cod_rev)

    ciclos_ord = sorted(rev_por_ciclo.keys())
    retencao_por_ciclo = []
    vistos_antes = set()
    for ciclo in ciclos_ord:
        revs = rev_por_ciclo[ciclo]
        retidos = revs & vistos_antes
        novos = revs - vistos_antes
        retencao_por_ciclo.append({
            "ciclo": ciclo,
            "total": len(revs),
            "novos": len(novos),
            "retidos": len(retidos),
            "pct_retencao": round(len(retidos) / len(revs) * 100, 1) if revs else 0,
        })
        vistos_antes.update(revs)

    todos_revs = {v.get("CodigoRevendedor") or v.get("Revendedor") or "?" for v in vendas_vendedor}
    rev_ciclos_count = defaultdict(set)
    for v in vendas_vendedor:
        ciclo = v.get("Ciclo") or ""
        if ciclo:
            rev_ciclos_count[v.get("CodigoRevendedor") or v.get("Revendedor") or "?"].add(ciclo)
    qtd_retidos_total = sum(1 for cs in rev_ciclos_count.values() if len(cs) > 1)

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
        "retencao": {
            "qtd_revendedores": len(todos_revs),
            "qtd_retidos": qtd_retidos_total,
            "pct_retencao": round(qtd_retidos_total / len(todos_revs) * 100, 1) if todos_revs else 0,
            "por_ciclo": retencao_por_ciclo,
        },
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

    # Penetração Make e Cabelos por vendedor:
    # revendedoras que compraram make (ou cabelos) / total revendedoras compradoras no ciclo
    _vend_rev_total   = defaultdict(set)
    _vend_rev_make    = defaultdict(set)
    _vend_rev_cabelos = defaultdict(set)
    for v in vendas:
        cod_vend = v.get("CodigoVendedor") or "?"
        cod_rev  = v.get("CodigoRevendedor") or v.get("Revendedor") or "?"
        _vend_rev_total[cod_vend].add(cod_rev)
        clf = v.get("classificacao_iaf")
        if clf == "IAF Make":
            _vend_rev_make[cod_vend].add(cod_rev)
        elif clf == "IAF Cabelos":
            _vend_rev_cabelos[cod_vend].add(cod_rev)

    _vend_nomes = {}
    for v in vendas:
        cod_vend = v.get("CodigoVendedor") or "?"
        if cod_vend not in _vend_nomes:
            _vend_nomes[cod_vend] = v.get("Vendedor") or cod_vend

    penetracao_make    = []
    penetracao_cabelos = []
    for cod_vend, rev_total in _vend_rev_total.items():
        total   = len(rev_total)
        make    = len(_vend_rev_make.get(cod_vend, set()))
        cabelos = len(_vend_rev_cabelos.get(cod_vend, set()))
        nome    = _vend_nomes.get(cod_vend, cod_vend)
        penetracao_make.append({
            "codigo": cod_vend, "nome": nome,
            "rev_compradoras": total, "rev_iaf": make,
            "pct_penetracao": (make / total * 100) if total else 0,
        })
        penetracao_cabelos.append({
            "codigo": cod_vend, "nome": nome,
            "rev_compradoras": total, "rev_iaf": cabelos,
            "pct_penetracao": (cabelos / total * 100) if total else 0,
        })
    penetracao_make.sort(key=lambda x: x["pct_penetracao"], reverse=True)
    penetracao_cabelos.sort(key=lambda x: x["pct_penetracao"], reverse=True)

    return jsonify({
        "total_geral": total_geral,
        "iaf_cabelos": _resumo_iaf("IAF Cabelos"),
        "iaf_make": _resumo_iaf("IAF Make"),
        "geral": _resumo_iaf("Geral"),
        "metodos_match": dict(metodos),
        "penetracao_make_por_vendedor": penetracao_make,
        "penetracao_cabelos_por_vendedor": penetracao_cabelos,
    })


@app.route("/api/metas")
def metas():
    """Metas por vendedor: % multimarca, IAF Cabelos (penetração), IAF Make (penetração)."""

    vendas = _aplicar_filtros(g.est["vendas"], request.args)

    METAS = _metas_resolvidas(None)   # metas globais, usadas nos cards de resumo

    metricas = defaultdict(lambda: {
        "nome": "", "codigo": "",
        "rev_total": set(),
        "rev_cabelos": set(),
        "rev_make": set(),
    })

    for v in vendas:
        cod = v.get("CodigoVendedor") or "?"
        m = metricas[cod]
        m["nome"] = v.get("Vendedor") or cod
        m["codigo"] = cod
        cod_rev = v.get("CodigoRevendedor") or v.get("Revendedor") or "?"
        m["rev_total"].add(cod_rev)
        clf = v.get("classificacao_iaf")
        if clf == "IAF Cabelos":
            m["rev_cabelos"].add(cod_rev)
        elif clf == "IAF Make":
            m["rev_make"].add(cod_rev)

    # Multimarca por CLIENTE (revendedor), creditado ao vendedor do 1º pedido
    mm = _multimarca_por_cliente(vendas)

    # A aba Metas mostra apenas o time cadastrado — gerentes e supervisores que
    # aparecem na planilha ficam de fora. Quem estiver na planilha sem cadastro
    # volta em "nao_cadastrados" para o admin saber que falta cadastrar.
    resultado = []
    nao_cadastrados = []
    com_vendas = set()
    for cod, m in metricas.items():
        vend = _buscar_vendedor(m["nome"])
        if not vend:
            nao_cadastrados.append(m["nome"])
            continue
        com_vendas.add(_norm_nome(vend["nome"]))

        pct_multimarca = mm.get(cod, {}).get("pct", 0)

        rev_total = len(m["rev_total"])
        pct_cabelos = (len(m["rev_cabelos"]) / rev_total * 100) if rev_total else 0
        pct_make = (len(m["rev_make"]) / rev_total * 100) if rev_total else 0

        metas_v = _metas_resolvidas(vend)
        resultado.append({
            "codigo": cod,
            "nome": m["nome"],
            "unidade": vend.get("unidade") or "",
            "slack_id": vend.get("slack_id") or "",
            "metas": metas_v,
            "pct_multimarca": round(pct_multimarca, 1),
            "pct_iaf_cabelos": round(pct_cabelos, 1),
            "pct_iaf_make": round(pct_make, 1),
            "atingiu_multimarca": pct_multimarca >= metas_v["multimarca"],
            "atingiu_cabelos": pct_cabelos >= metas_v["iaf_cabelos"],
            "atingiu_make": pct_make >= metas_v["iaf_make"],
        })

    sem_vendas = [
        v["nome"] for v in _CADASTRO["vendedores"]
        if _norm_nome(v["nome"]) not in com_vendas
    ]

    resultado.sort(key=lambda x: x["nome"])
    todos_ciclos = sorted({v.get("Ciclo") or "" for v in g.est["vendas"]} - {""})
    return jsonify({
        "vendedores": resultado,
        "metas": METAS,
        "nao_cadastrados": sorted(set(nao_cadastrados)),
        "cadastrados_sem_vendas": sorted(sem_vendas),
        "qtd_ciclos_total": len(todos_ciclos),
        "ciclo_filtrado": request.args.get("ciclo", ""),
    })


# ─── Admin: cadastro de vendedores e metas ────────────────────────────────────

def _parse_metas(body, campo="metas"):
    """Lê metas do corpo da request. Valor null/"" significa herdar do nível de
    cima (remove o override). Retorna (dict, erro)."""
    bruto = body.get(campo)
    if bruto is None:
        return {}, None
    if not isinstance(bruto, dict):
        return None, "Campo 'metas' inválido."
    metas = {}
    for k, v in bruto.items():
        if k not in _METAS_CAMPOS:
            return None, f"Meta desconhecida: {k}"
        if v is None or v == "":
            metas[k] = None      # herdar
            continue
        try:
            num = float(str(v).replace(",", "."))
        except (TypeError, ValueError):
            return None, f"Meta '{k}' precisa ser um número."
        if not (0 <= num <= 100):
            return None, f"Meta '{k}' precisa estar entre 0 e 100."
        metas[k] = round(num, 1)
    return metas, None


def _aplicar_metas(destino, metas):
    """Aplica overrides em um dict de metas — None remove o override (herda)."""
    for k, v in metas.items():
        if v is None:
            destino.pop(k, None)
        else:
            destino[k] = v


@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    body = request.get_json(silent=True) or {}
    escopo = _escopo_da_senha(body.get("senha"))
    if not escopo:
        return jsonify({"erro": "Senha incorreta."}), 401
    session["admin_escopo"] = escopo
    session.permanent = True
    app.logger.info(f"[Admin] Login no escopo: {escopo}")
    return jsonify({"escopo": escopo, "unidades": _unidades_do_escopo(escopo)})


@app.route("/api/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("admin_escopo", None)
    return jsonify({"ok": True})


@app.route("/api/admin/cadastro")
def admin_cadastro():
    """Cadastro visível para o escopo logado. Sem login, devolve escopo nulo
    (a aba mostra a tela de senha)."""
    escopo = _escopo_atual()
    if not escopo:
        return jsonify({"escopo": None, "unidades": UNIDADES})

    unidades = _unidades_do_escopo(escopo)
    vendedores = []
    for v in _CADASTRO["vendedores"]:
        if v.get("unidade") not in unidades and escopo != ESCOPO_GERAL:
            continue
        vendedores.append({
            **v,
            "metas_efetivas": _metas_resolvidas(v),
            "metas_origem": _metas_origem(v),
        })
    vendedores.sort(key=lambda x: (x.get("unidade") or "", x["nome"]))

    return jsonify({
        "escopo": escopo,
        "unidades": unidades,
        "pode_meta_global": escopo == ESCOPO_GERAL,
        "vendedores": vendedores,
        "metas_globais": _metas_resolvidas(None),
        "metas_unidade": {un: (_CADASTRO.get("metas_unidade", {}).get(un) or {}) for un in unidades},
        "github_ativo": _gh_ok(),
    })


@app.route("/api/admin/vendedor", methods=["POST"])
def admin_add_vendedor():
    escopo = _escopo_atual()
    if not escopo:
        return jsonify({"erro": "Faça login na aba Admin."}), 403

    body = request.get_json(silent=True) or {}
    nome     = (body.get("nome") or "").strip()
    slack_id = (body.get("slack_id") or "").strip().upper()
    unidade  = (body.get("unidade") or "").strip()

    if not nome:
        return jsonify({"erro": "Informe o nome exatamente como aparece na planilha."}), 400
    if not re.fullmatch(r"[UW][A-Z0-9]{6,}", slack_id):
        return jsonify({"erro": "Slack ID inválido — deve começar com U e ter só letras/números (ex.: U0BGA5QHHLJ)."}), 400
    if unidade not in UNIDADES:
        return jsonify({"erro": "Unidade inválida."}), 400
    if not _pode_gerenciar(escopo, unidade):
        return jsonify({"erro": f"Sua senha só gerencia {escopo}."}), 403

    metas, erro = _parse_metas(body)
    if erro:
        return jsonify({"erro": erro}), 400

    with _CADASTRO_LOCK:
        if _buscar_vendedor(nome):
            return jsonify({"erro": f"{nome} já está cadastrado."}), 409
        novo = {
            "nome": nome,
            "slack_id": slack_id,
            "unidade": unidade,
            "metas": {k: v for k, v in metas.items() if v is not None},
        }
        _CADASTRO["vendedores"].append(novo)
        _CADASTRO["vendedores"].sort(key=lambda x: (x.get("unidade") or "", x["nome"]))
        aviso = _persistir_cadastro()

    app.logger.info(f"[Admin] Vendedor adicionado: {nome} ({unidade})")
    return jsonify({"ok": True, "vendedor": novo, "aviso": aviso})


@app.route("/api/admin/vendedor/remover", methods=["POST"])
def admin_remover_vendedor():
    escopo = _escopo_atual()
    if not escopo:
        return jsonify({"erro": "Faça login na aba Admin."}), 403

    body = request.get_json(silent=True) or {}
    nome = (body.get("nome") or "").strip()

    with _CADASTRO_LOCK:
        vend = _buscar_vendedor(nome)
        if not vend:
            return jsonify({"erro": f"{nome} não está cadastrado."}), 404
        if not _pode_gerenciar(escopo, vend.get("unidade")):
            return jsonify({"erro": f"Sua senha só gerencia {escopo}."}), 403
        _CADASTRO["vendedores"] = [
            v for v in _CADASTRO["vendedores"]
            if _norm_nome(v["nome"]) != _norm_nome(nome)
        ]
        aviso = _persistir_cadastro()

    app.logger.info(f"[Admin] Vendedor removido: {vend['nome']}")
    return jsonify({"ok": True, "aviso": aviso})


@app.route("/api/admin/vendedor/editar", methods=["POST"])
def admin_editar_vendedor():
    """Edita Slack ID, unidade e/ou metas individuais de um vendedor."""
    escopo = _escopo_atual()
    if not escopo:
        return jsonify({"erro": "Faça login na aba Admin."}), 403

    body = request.get_json(silent=True) or {}
    nome = (body.get("nome") or "").strip()

    with _CADASTRO_LOCK:
        vend = _buscar_vendedor(nome)
        if not vend:
            return jsonify({"erro": f"{nome} não está cadastrado."}), 404
        if not _pode_gerenciar(escopo, vend.get("unidade")):
            return jsonify({"erro": f"Sua senha só gerencia {escopo}."}), 403

        # Valida tudo ANTES de alterar: uma falha no meio deixaria o objeto em
        # memória divergindo do que foi gravado no disco.
        novo_slack = None
        if "slack_id" in body:
            novo_slack = (body.get("slack_id") or "").strip().upper()
            if not re.fullmatch(r"[UW][A-Z0-9]{6,}", novo_slack):
                return jsonify({"erro": "Slack ID inválido — deve começar com U (ex.: U0BGA5QHHLJ)."}), 400

        nova_unidade = None
        if "unidade" in body:
            nova_unidade = (body.get("unidade") or "").strip()
            if nova_unidade not in UNIDADES:
                return jsonify({"erro": "Unidade inválida."}), 400
            if not _pode_gerenciar(escopo, nova_unidade):
                return jsonify({"erro": "Você não pode mover um vendedor para outra unidade."}), 403

        novas_metas = None
        if "metas" in body:
            novas_metas, erro = _parse_metas(body)
            if erro:
                return jsonify({"erro": erro}), 400

        if novo_slack is not None:
            vend["slack_id"] = novo_slack
        if nova_unidade is not None:
            vend["unidade"] = nova_unidade
        if novas_metas is not None:
            _aplicar_metas(vend.setdefault("metas", {}), novas_metas)

        aviso = _persistir_cadastro()
        resposta = {**vend, "metas_efetivas": _metas_resolvidas(vend), "metas_origem": _metas_origem(vend)}

    app.logger.info(f"[Admin] Vendedor editado: {vend['nome']}")
    return jsonify({"ok": True, "vendedor": resposta, "aviso": aviso})


@app.route("/api/admin/metas", methods=["POST"])
def admin_salvar_metas():
    """Salva metas globais (só escopo geral) ou de uma unidade."""
    escopo = _escopo_atual()
    if not escopo:
        return jsonify({"erro": "Faça login na aba Admin."}), 403

    body    = request.get_json(silent=True) or {}
    nivel   = (body.get("nivel") or "").strip()
    unidade = (body.get("unidade") or "").strip()

    metas, erro = _parse_metas(body)
    if erro:
        return jsonify({"erro": erro}), 400

    with _CADASTRO_LOCK:
        if nivel == "global":
            if escopo != ESCOPO_GERAL:
                return jsonify({"erro": "Só a senha geral edita a meta global."}), 403
            if any(v is None for v in metas.values()):
                return jsonify({"erro": "A meta global não pode ficar vazia — ela é a base de todas."}), 400
            _CADASTRO.setdefault("metas_globais", {}).update(metas)
        elif nivel == "unidade":
            if unidade not in UNIDADES:
                return jsonify({"erro": "Unidade inválida."}), 400
            if not _pode_gerenciar(escopo, unidade):
                return jsonify({"erro": f"Sua senha só gerencia {escopo}."}), 403
            alvo = _CADASTRO.setdefault("metas_unidade", {}).setdefault(unidade, {})
            _aplicar_metas(alvo, metas)
            if not alvo:
                _CADASTRO["metas_unidade"].pop(unidade, None)
        else:
            return jsonify({"erro": "Nível inválido — use 'global' ou 'unidade'."}), 400

        aviso = _persistir_cadastro()

    app.logger.info(f"[Admin] Metas salvas (nível={nivel} unidade={unidade or '-'})")
    return jsonify({
        "ok": True,
        "aviso": aviso,
        "metas_globais": _metas_resolvidas(None),
        "metas_unidade": _CADASTRO.get("metas_unidade", {}),
    })


@app.route("/api/slack/enviar", methods=["POST"])
def slack_enviar():
    """Envia metas de um vendedor via DM no Slack."""
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not token:
        return jsonify({"erro": "SLACK_BOT_TOKEN não configurado no servidor"}), 500

    body = request.json or {}
    slack_user_id  = body.get("slack_user_id", "")
    vendedor_nome  = body.get("vendedor_nome", "Vendedor")
    pct_mult       = float(body.get("pct_multimarca", 0))
    pct_cab        = float(body.get("pct_iaf_cabelos", 0))
    pct_make       = float(body.get("pct_iaf_make", 0))
    meta_mult      = float(body.get("meta_multimarca", 72))
    meta_cab       = float(body.get("meta_iaf_cabelos", 37))
    meta_make      = float(body.get("meta_iaf_make", 38))
    ok_mult        = pct_mult  >= meta_mult
    ok_cab         = pct_cab   >= meta_cab
    ok_make        = pct_make  >= meta_make
    cnt            = sum([ok_mult, ok_cab, ok_make])

    def _linha(emoji, label, valor, meta, ok):
        sinal = "✅" if ok else "❌"
        return f"{sinal} {emoji} *{label}:* `{valor:.1f}%` _(meta: {meta:.0f}%)_"

    texto_fallback = f"Metas de {vendedor_nome}: Multimarca {pct_mult:.1f}% | IAF Cabelos {pct_cab:.1f}% | IAF Make {pct_make:.1f}%"

    payload = {
        "channel": slack_user_id,
        "text": texto_fallback,
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"📊 Metas — {vendedor_nome}", "emoji": True},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        _linha("🛍️", "Multimarca", pct_mult, meta_mult, ok_mult) + "\n"
                        + _linha("💇", "IAF Cabelos", pct_cab, meta_cab, ok_cab) + "\n"
                        + _linha("💄", "IAF Make", pct_make, meta_make, ok_make)
                    ),
                },
            },
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"Metas atingidas: *{cnt} de 3*"}],
            },
        ],
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resultado = json.loads(resp.read())
    except urllib.error.URLError as e:
        return jsonify({"erro": str(e)}), 502

    if not resultado.get("ok"):
        return jsonify({"erro": resultado.get("error", "Slack retornou erro")}), 400

    return jsonify({"ok": True})


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
