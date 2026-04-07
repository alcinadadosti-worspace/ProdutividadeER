"""
cruzamento.py — Cruzamento de vendas com tabelas IAF do banco de produtos
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


def criar_indice_iaf(caminho_db):
    """
    Carrega todos os SKUs de iaf_cabelos e iaf_make e cria índice em memória.
    Registra variações de zeros (4↔5 dígitos).
    Retorna dicionário: { sku_normalizado: {"origem": "iaf_cabelos"|"iaf_make", "descricao": str} }
    """
    indice = {}

    conn = sqlite3.connect(caminho_db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    for tabela, origem in [("iaf_cabelos", "IAF Cabelos"), ("iaf_make", "IAF Make")]:
        try:
            cur.execute(f"SELECT sku, sku_normalizado, descricao FROM {tabela}")
            rows = cur.fetchall()
        except sqlite3.OperationalError:
            continue

        for row in rows:
            sku_db = str(row["sku"] or "").strip()
            sku_norm = normalizar_sku(sku_db)
            descricao = str(row["descricao"] or "")

            entrada = {"origem": origem, "descricao": descricao}

            if sku_norm:
                indice[sku_norm] = entrada

                # Variação de zeros: 5 dígitos com zero → sem zero
                if len(sku_norm) == 5 and sku_norm.startswith("0"):
                    variacao = sku_norm[1:]
                    if variacao not in indice:
                        indice[variacao] = entrada

                # Variação de zeros: 4 dígitos → com zero à frente
                elif len(sku_norm) == 4:
                    variacao = "0" + sku_norm
                    if variacao not in indice:
                        indice[variacao] = entrada

    conn.close()
    return indice


def _contem_siage(nome_produto):
    """Verifica se o produto é Siàge de cabelos pelo nome."""
    nome_upper = nome_produto.upper()
    if "SIAGE" not in nome_upper and "SIÀGE" not in nome_upper:
        return False
    return any(p in nome_upper for p in PALAVRAS_SIAGE)


def _contem_make(nome_produto):
    """Verifica se o produto é Make pelo nome."""
    nome_upper = nome_produto.upper()
    for palavra in PALAVRAS_MAKE:
        if palavra in nome_upper:
            return True
    return False


def cruzar_vendas_com_iaf(vendas, indice_iaf):
    """
    Classifica cada venda como IAF Cabelos, IAF Make ou Geral.
    Adiciona campos: classificacao_iaf, metodo_match.
    Retorna lista de vendas enriquecidas (modifica in-place e retorna).
    """
    for venda in vendas:
        sku_norm = venda.get("CodigoProduto_normalizado", "")
        nome_produto = venda.get("Produto", "")

        # 1. Match por SKU
        if sku_norm and sku_norm in indice_iaf:
            entrada = indice_iaf[sku_norm]
            venda["classificacao_iaf"] = entrada["origem"]
            venda["metodo_match"] = "sku"

        # 2. Fallback Siàge
        elif _contem_siage(nome_produto):
            venda["classificacao_iaf"] = "IAF Cabelos"
            venda["metodo_match"] = "fallback_siage"

        # 3. Fallback Make
        elif _contem_make(nome_produto):
            venda["classificacao_iaf"] = "IAF Make"
            venda["metodo_match"] = "fallback_make"

        # 4. Sem match
        else:
            venda["classificacao_iaf"] = "Geral"
            venda["metodo_match"] = "nenhum"

    return vendas
