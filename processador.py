"""
processador.py — Leitura e normalização da planilha de vendas
"""

import re
import pandas as pd
from datetime import datetime


# Mapeamento das colunas da planilha para campos internos
COLUNAS_MAPEAMENTO = {
    "Código Vendedor": "CodigoVendedor",
    "Vendedor": "Vendedor",
    "Código Produto": "CodigoProduto",
    "Produto": "Produto",
    "Qtde": "Quantidade",
    "Total Praticado": "TotalPraticado",
    "Código Pedido": "CodigoPedido",
    "Ciclo faturamento pedido": "Ciclo",
    "Data faturamento": "DataFaturamento",
    "Revendedor": "Revendedor",
    "Papel": "Papel",
    "Plano de pagamento": "PlanoPagamento",
    "Código usuário criação": "CodigoUsuarioCriacao",
    "Usuário criação": "UsuarioCriacao",
    "Código usuário finalização": "CodigoUsuarioFinalizacao",
    "Usuário finalização": "UsuarioFinalizacao",
    "Canal de distribuição": "CanalDistribuicao",
}


def normalizar_sku(valor):
    """
    Normaliza um SKU removendo caracteres não numéricos.
    Preserva zeros à esquerda. Trata floats do Excel (ex: 1234.0 → '1234').
    """
    if valor is None:
        return ""
    # Converter para string primeiro
    s = str(valor).strip()
    # Tratar float do Excel: "1234.0" → "1234"
    if re.match(r"^\d+\.0$", s):
        s = s[:-2]
    # Remover tudo que não é dígito
    s = re.sub(r"[^\d]", "", s)
    return s


def _identificar_unidade(canal):
    """
    Identifica a unidade a partir do Canal de Distribuição.
    """
    if not canal:
        return "Desconhecido"
    canal_str = str(canal).strip()
    if canal_str.startswith("13707"):
        return "Matriz Penedo"
    elif canal_str.startswith("13706"):
        return "Filial Palmeira dos Índios"
    return "Outra"


def _parse_data(valor):
    """
    Tenta converter um valor de data para string ISO (YYYY-MM-DD).
    """
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, datetime):
        return valor.strftime("%Y-%m-%d")
    if hasattr(valor, "strftime"):
        return valor.strftime("%Y-%m-%d")
    s = str(valor).strip()
    formatos = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"]
    for fmt in formatos:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return s


def _ler_todas_abas(caminho_arquivo):
    """
    Lê todas as abas do arquivo .xlsx e retorna um único DataFrame concatenado.
    """
    abas = pd.read_excel(caminho_arquivo, sheet_name=None, dtype=str, engine="openpyxl")

    frames = []
    for nome_aba, df_aba in abas.items():
        df_aba = df_aba.dropna(how="all")
        if not df_aba.empty:
            frames.append(df_aba)

    if not frames:
        return pd.DataFrame()

    # Concatenar todas as abas — alinha pelas colunas em comum
    return pd.concat(frames, ignore_index=True, sort=False)


def ler_planilha(caminho_arquivo):
    """
    Lê todas as abas da planilha .xlsx e retorna lista de dicionários normalizados.
    Retorna: (lista_de_vendas, lista_colunas_encontradas, total_linhas)
    """
    df = _ler_todas_abas(caminho_arquivo)

    if df.empty:
        return [], [], 0

    # Mapear apenas as colunas que existem na planilha
    colunas_presentes = {}
    for col_planilha, col_interna in COLUNAS_MAPEAMENTO.items():
        # Busca exata e depois busca case-insensitive
        if col_planilha in df.columns:
            colunas_presentes[col_planilha] = col_interna
        else:
            for col_real in df.columns:
                if str(col_real).strip().lower() == col_planilha.lower():
                    colunas_presentes[col_real] = col_interna
                    break

    # Selecionar apenas colunas mapeadas
    colunas_select = list(colunas_presentes.keys())
    df_filtrado = df[colunas_select].copy()
    df_filtrado.rename(columns=colunas_presentes, inplace=True)

    total_linhas = len(df_filtrado)
    vendas = []

    for _, row in df_filtrado.iterrows():
        venda = {}

        # Strings simples
        for campo in [
            "CodigoVendedor", "Vendedor", "Produto", "CodigoPedido",
            "Ciclo", "Revendedor", "Papel", "PlanoPagamento",
            "CodigoUsuarioCriacao", "UsuarioCriacao",
            "CodigoUsuarioFinalizacao", "UsuarioFinalizacao", "CanalDistribuicao",
        ]:
            val = row.get(campo)
            venda[campo] = str(val).strip() if val and str(val) != "nan" else ""

        # SKU — preservar original e normalizado
        sku_raw = row.get("CodigoProduto", "")
        if str(sku_raw) == "nan":
            sku_raw = ""
        venda["CodigoProduto"] = str(sku_raw).strip()
        venda["CodigoProduto_normalizado"] = normalizar_sku(sku_raw)

        # Quantidade
        try:
            qtd_val = row.get("Quantidade", "0")
            venda["Quantidade"] = int(float(str(qtd_val))) if str(qtd_val) != "nan" else 0
        except (ValueError, TypeError):
            venda["Quantidade"] = 0

        # Total Praticado
        try:
            total_val = row.get("TotalPraticado", "0")
            # Tratar formato BR: "1.234,56" → 1234.56
            total_str = str(total_val).strip().replace(".", "").replace(",", ".")
            venda["TotalPraticado"] = float(total_str) if total_str and total_str != "nan" else 0.0
        except (ValueError, TypeError):
            venda["TotalPraticado"] = 0.0

        # Data
        venda["DataFaturamento"] = _parse_data(row.get("DataFaturamento"))

        # Unidade derivada do canal
        venda["Unidade"] = _identificar_unidade(venda.get("CanalDistribuicao", ""))

        vendas.append(venda)

    colunas_encontradas = list(colunas_presentes.values())
    return vendas, colunas_encontradas, total_linhas


def preview_planilha(caminho_arquivo, n=10):
    """
    Retorna as primeiras n linhas da planilha já mapeadas (para preview).
    """
    vendas, colunas, total = ler_planilha(caminho_arquivo)
    return vendas[:n], colunas, total
