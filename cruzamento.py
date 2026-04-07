"""
cruzamento.py — Cruzamento de vendas com o banco de produtos
Fluxo:
  1. Cruza com `produtos`   → sabe se o item está no catálogo + pega marca
  2. Cruza com `iaf_cabelos` → classifica como IAF Cabelos
  3. Cruza com `iaf_make`    → classifica como IAF Make
  4. Fallbacks por nome      → Siàge / palavras-chave Make
  5. Sem match               → Geral
"""

import sqlite3
from processador import normalizar_sku

# Palavras-chave para fallback Siàge Cabelos
PALAVRAS_SIAGE = {"KIT", "COMB", "SHAMP", "COND"}

# Palavras-chave para fallback Make
PALAVRAS_MAKE = {
    "BATOM", "SOMBRA", "BLUSH", "BASE", "MASCARA", "DELINEADOR",
    "CORRETIVO", "PO COMPACTO", "GLOSS", "PRIMER", "PALETA",
    "CONTORNO", "ILUMINADOR", "FIXADOR", "LAPIS", "MAKE",
}


def _registrar_sku(indice, sku_norm, entrada):
    """Registra um SKU no índice com variações de zeros à esquerda (4↔5 dígitos)."""
    if not sku_norm:
        return
    indice[sku_norm] = entrada
    if len(sku_norm) == 5 and sku_norm.startswith("0"):
        indice.setdefault(sku_norm[1:], entrada)
    elif len(sku_norm) == 4:
        indice.setdefault("0" + sku_norm, entrada)


def criar_indices(caminho_db):
    """
    Carrega os três índices em memória a partir do banco:
      - indice_produtos : { sku_norm: { "nome": str, "marca": str } }
      - indice_iaf      : { sku_norm: { "origem": "IAF Cabelos"|"IAF Make", "descricao": str } }

    Retorna (indice_produtos, indice_iaf).
    """
    indice_produtos = {}
    indice_iaf = {}

    conn = sqlite3.connect(caminho_db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # ── 1. Tabela produtos (catálogo completo) ────────────────────────────
    try:
        cur.execute("SELECT sku, sku_normalizado, nome, marca FROM produtos")
        for row in cur.fetchall():
            sku_norm = normalizar_sku(row["sku"] or row["sku_normalizado"] or "")
            entrada = {
                "nome": str(row["nome"] or ""),
                "marca": str(row["marca"] or ""),
            }
            _registrar_sku(indice_produtos, sku_norm, entrada)
    except sqlite3.OperationalError:
        pass

    # ── 2. Tabelas IAF ────────────────────────────────────────────────────
    for tabela, origem in [("iaf_cabelos", "IAF Cabelos"), ("iaf_make", "IAF Make")]:
        try:
            cur.execute(f"SELECT sku, sku_normalizado, descricao FROM {tabela}")
            for row in cur.fetchall():
                sku_norm = normalizar_sku(row["sku"] or row["sku_normalizado"] or "")
                entrada = {
                    "origem": origem,
                    "descricao": str(row["descricao"] or ""),
                }
                _registrar_sku(indice_iaf, sku_norm, entrada)
        except sqlite3.OperationalError:
            continue

    conn.close()
    return indice_produtos, indice_iaf


# Mantém compatibilidade com app.py que ainda chama criar_indice_iaf
def criar_indice_iaf(caminho_db):
    _, indice_iaf = criar_indices(caminho_db)
    return indice_iaf


def _contem_siage(nome):
    n = nome.upper()
    if "SIAGE" not in n and "SIÀGE" not in n:
        return False
    return any(p in n for p in PALAVRAS_SIAGE)


def _contem_make(nome):
    n = nome.upper()
    return any(p in n for p in PALAVRAS_MAKE)


def cruzar_vendas(vendas, indice_produtos, indice_iaf):
    """
    Enriquece cada venda com:
      - marca          : marca do produto (da tabela `produtos`)
      - em_catalogo    : True se o SKU existe na tabela `produtos`
      - classificacao_iaf : "IAF Cabelos" | "IAF Make" | "Geral"
      - metodo_match   : "sku" | "fallback_siage" | "fallback_make" | "nenhum"
    """
    for venda in vendas:
        sku_norm = venda.get("CodigoProduto_normalizado", "")
        nome_produto = venda.get("Produto", "")

        # ── Cruzamento com catálogo de produtos ───────────────────────────
        prod_entry = indice_produtos.get(sku_norm)
        if prod_entry:
            venda["em_catalogo"] = True
            venda["marca"] = prod_entry["marca"]
            # Se o nome do banco for mais completo, usar como nome_db
            venda["nome_db"] = prod_entry["nome"]
        else:
            venda["em_catalogo"] = False
            venda["marca"] = ""
            venda["nome_db"] = ""

        # ── Classificação IAF ─────────────────────────────────────────────
        # 1. Match por SKU nas tabelas IAF
        if sku_norm and sku_norm in indice_iaf:
            venda["classificacao_iaf"] = indice_iaf[sku_norm]["origem"]
            venda["metodo_match"] = "sku"

        # 2. Fallback Siàge
        elif _contem_siage(nome_produto):
            venda["classificacao_iaf"] = "IAF Cabelos"
            venda["metodo_match"] = "fallback_siage"

        # 3. Fallback Make
        elif _contem_make(nome_produto):
            venda["classificacao_iaf"] = "IAF Make"
            venda["metodo_match"] = "fallback_make"

        # 4. Sem match IAF
        else:
            venda["classificacao_iaf"] = "Geral"
            venda["metodo_match"] = "nenhum"

    return vendas

