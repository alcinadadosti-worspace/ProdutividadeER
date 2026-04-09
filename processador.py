"""
processador.py — Leitura e normalização da planilha de vendas
"""

import os
import re
import unicodedata
import pandas as pd
from datetime import datetime


# ─── Normalização de nomes de coluna ──────────────────────────────────────────
def _norm_col(s):
    """
    Normaliza um nome de coluna para comparação:
    remove acentos, converte para minúsculo, mantém apenas letras/números/espaço.
    Ex: 'Código Vendedor' → 'codigo vendedor'
        'C\ufffdigo Vendedor' → 'codigo vendedor'
    """
    s = str(s).lower().strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]", "", s)
    return s


# Mapeamento: nome normalizado → campo interno
# Inclui variações reais encontradas nos arquivos
COLUNAS_MAPEAMENTO = {
    "codigo vendedor":              "CodigoVendedor",
    "vendedor":                     "Vendedor",
    "codigo produto":               "CodigoProduto",
    "produto":                      "Produto",
    "qtde":                         "Quantidade",
    "total praticado":              "TotalPraticado",
    "codigo pedido":                "CodigoPedido",
    "ciclo faturamento pedido":     "Ciclo",   # nome original do prompt
    "ciclo faturamento":            "Ciclo",   # nome real nos arquivos
    "data faturamento":             "DataFaturamento",
    "codigo revendedor":            "CodigoRevendedor",
    "revendedor":                   "Revendedor",
    "papel":                        "Papel",
    "plano de pagamento":           "PlanoPagamento",
    "codigo usuario criacao":       "CodigoUsuarioCriacao",
    "usuario criacao":              "UsuarioCriacao",
    "codigo usuario finalizacao":   "CodigoUsuarioFinalizacao",
    "usuario finalizacao":          "UsuarioFinalizacao",
    "canal de distribuicao":        "CanalDistribuicao",
}


def normalizar_sku(valor):
    """
    Normaliza um SKU removendo caracteres não numéricos.
    Preserva zeros à esquerda. Trata floats do Excel (ex: 1234.0 → '1234').
    """
    if valor is None:
        return ""
    s = str(valor).strip()
    if re.match(r"^\d+\.0$", s):
        s = s[:-2]
    s = re.sub(r"[^\d]", "", s)
    return s


def _identificar_unidade(canal):
    if not canal:
        return "Desconhecido"
    canal_str = str(canal).strip()
    if canal_str.startswith("13707"):
        return "Matriz Penedo"
    elif canal_str.startswith("13706"):
        return "Filial Palmeira dos Índios"
    return "Outra"


def _parse_data(valor):
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, datetime):
        return valor.strftime("%Y-%m-%d")
    if hasattr(valor, "strftime"):
        return valor.strftime("%Y-%m-%d")
    s = str(valor).strip()
    # Tratar datetime completo: "01/04/2026 10:48:04"
    for fmt in ["%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"]:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return s


def _parse_valor(valor):
    """
    Converte valor monetário para float.
    Suporta: 'R$ 147,60', '1.234,56', '1234.56', '147,60'
    """
    if valor is None:
        return 0.0
    s = str(valor).strip()
    if s in ("", "nan"):
        return 0.0
    # Remover símbolo monetário e espaços
    s = re.sub(r"[R$\s]", "", s)
    # Formato BR: 1.234,56 → remover ponto de milhar, vírgula → ponto decimal
    if "," in s and "." in s:
        # Assume ponto como separador de milhar e vírgula como decimal
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def _ler_todas_abas(caminho_arquivo):
    """Lê todas as abas do arquivo Excel e retorna DataFrame concatenado."""
    abas = pd.read_excel(caminho_arquivo, sheet_name=None, dtype=str, engine="openpyxl")
    frames = []
    for df_aba in abas.values():
        df_aba = df_aba.dropna(how="all")
        if not df_aba.empty:
            frames.append(df_aba)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False)


def _ler_csv(caminho_arquivo):
    """Lê arquivo CSV detectando encoding e separador automaticamente."""
    for encoding in ["utf-8-sig", "utf-8", "latin-1", "cp1252"]:
        try:
            df = pd.read_csv(
                caminho_arquivo, dtype=str, encoding=encoding,
                sep=None, engine="python", on_bad_lines="skip"
            )
            df = df.dropna(how="all")
            return df
        except Exception:
            continue
    raise ValueError("Não foi possível ler o arquivo CSV. Verifique o encoding.")


def _ler_arquivo(caminho_arquivo):
    """Detecta o formato pelo nome do arquivo e retorna DataFrame."""
    ext = os.path.splitext(caminho_arquivo)[1].lower()
    if ext == ".csv":
        return _ler_csv(caminho_arquivo)
    return _ler_todas_abas(caminho_arquivo)


def _mapear_colunas(df):
    """
    Mapeia colunas do DataFrame para campos internos usando comparação normalizada.
    Retorna dicionário: { nome_real_no_df: campo_interno }
    """
    # Construir índice: norm → nome_real
    norm_para_real = {_norm_col(c): c for c in df.columns}

    mapeamento = {}
    campos_ja_mapeados = set()

    for nome_norm, campo_interno in COLUNAS_MAPEAMENTO.items():
        if campo_interno in campos_ja_mapeados:
            continue  # já mapeado por outro alias
        if nome_norm in norm_para_real:
            col_real = norm_para_real[nome_norm]
            mapeamento[col_real] = campo_interno
            campos_ja_mapeados.add(campo_interno)

    return mapeamento


def ler_planilha(caminho_arquivo):
    """
    Lê planilha Excel (todas as abas) ou CSV e retorna lista de dicionários normalizados.
    Retorna: (lista_de_vendas, lista_colunas_encontradas, total_linhas)
    """
    df = _ler_arquivo(caminho_arquivo)
    if df.empty:
        return [], [], 0

    mapeamento = _mapear_colunas(df)

    # Renomear colunas mapeadas e descartar o resto
    df_filtrado = df[list(mapeamento.keys())].copy()
    df_filtrado.rename(columns=mapeamento, inplace=True)

    # ── Passo 1: propagar CodigoPedido globalmente (é a chave de agrupamento)
    if "CodigoPedido" in df_filtrado.columns:
        df_filtrado["CodigoPedido"] = df_filtrado["CodigoPedido"].replace("nan", pd.NA).ffill()

    # ── Passo 2: preencher campos de cabeçalho DENTRO de cada pedido
    # Assim dados de um pedido/vendedor não vazam para linhas de outros pedidos
    CAMPOS_CABECALHO = [
        "CodigoVendedor", "Vendedor", "Ciclo",
        "CanalDistribuicao", "CodigoRevendedor", "Revendedor", "Papel", "PlanoPagamento",
        "CodigoUsuarioCriacao", "UsuarioCriacao",
        "CodigoUsuarioFinalizacao", "UsuarioFinalizacao",
    ]
    for campo in CAMPOS_CABECALHO:
        if campo not in df_filtrado.columns:
            continue
        df_filtrado[campo] = df_filtrado[campo].replace("nan", pd.NA)
        if "CodigoPedido" in df_filtrado.columns:
            df_filtrado[campo] = df_filtrado.groupby("CodigoPedido", sort=False)[campo].transform("ffill")
        else:
            df_filtrado[campo] = df_filtrado[campo].ffill()

    # Fallback: se CodigoVendedor ainda vazio, usar UsuarioCriacao (é quem criou o pedido = vendedor)
    if "CodigoVendedor" in df_filtrado.columns and "CodigoUsuarioCriacao" in df_filtrado.columns:
        mask_vazio = df_filtrado["CodigoVendedor"].isna() | (df_filtrado["CodigoVendedor"] == "")
        df_filtrado.loc[mask_vazio, "CodigoVendedor"] = df_filtrado.loc[mask_vazio, "CodigoUsuarioCriacao"]
    if "Vendedor" in df_filtrado.columns and "UsuarioCriacao" in df_filtrado.columns:
        mask_vazio = df_filtrado["Vendedor"].isna() | (df_filtrado["Vendedor"] == "")
        df_filtrado.loc[mask_vazio, "Vendedor"] = df_filtrado.loc[mask_vazio, "UsuarioCriacao"]

    total_linhas = len(df_filtrado)
    vendas = []

    for _, row in df_filtrado.iterrows():

        def sv(campo):
            val = row.get(campo)
            if val is None:
                return ""
            s = str(val).strip()
            return "" if s in ("nan", "None", "<NA>") else s

        venda = {}

        # Strings simples
        for campo in [
            "CodigoVendedor", "Vendedor", "Produto", "CodigoPedido",
            "Ciclo", "CodigoRevendedor", "Revendedor", "Papel", "PlanoPagamento",
            "CodigoUsuarioCriacao", "UsuarioCriacao",
            "CodigoUsuarioFinalizacao", "UsuarioFinalizacao", "CanalDistribuicao",
        ]:
            venda[campo] = sv(campo)

        # SKU
        sku_raw = sv("CodigoProduto")
        venda["CodigoProduto"] = sku_raw
        venda["CodigoProduto_normalizado"] = normalizar_sku(sku_raw)

        # Quantidade
        try:
            qtd = sv("Quantidade")
            venda["Quantidade"] = int(float(qtd)) if qtd else 0
        except (ValueError, TypeError):
            venda["Quantidade"] = 0

        # Total Praticado
        venda["TotalPraticado"] = _parse_valor(sv("TotalPraticado"))

        # Data
        venda["DataFaturamento"] = _parse_data(sv("DataFaturamento"))

        # Unidade
        venda["Unidade"] = _identificar_unidade(venda["CanalDistribuicao"])

        vendas.append(venda)

    # Normalização: cada vendedor é fixado na sua unidade dominante (maioria dos registros).
    # Evita que poucos pedidos com canal errado na origem façam o vendedor aparecer em outra unidade.
    contagem_unidade = {}
    for v in vendas:
        cod = v.get("CodigoVendedor") or "?"
        unidade = v.get("Unidade", "Desconhecido")
        if cod not in contagem_unidade:
            contagem_unidade[cod] = {}
        contagem_unidade[cod][unidade] = contagem_unidade[cod].get(unidade, 0) + 1

    unidade_dominante = {
        cod: max(unidades, key=unidades.get)
        for cod, unidades in contagem_unidade.items()
    }

    for v in vendas:
        cod = v.get("CodigoVendedor") or "?"
        v["Unidade"] = unidade_dominante.get(cod, v["Unidade"])

    colunas_encontradas = list(mapeamento.values())
    return vendas, colunas_encontradas, total_linhas


def preview_planilha(caminho_arquivo, n=10):
    vendas, colunas, total = ler_planilha(caminho_arquivo)
    return vendas[:n], colunas, total
