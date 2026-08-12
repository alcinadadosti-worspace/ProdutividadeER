"""
cruzamento.py — Cruzamento de vendas com o banco de produtos
Fluxo:
  1. Cruza com `produtos`   → sabe se o item está no catálogo + pega marca
  2. Cruza com `iaf_cabelos` → classifica como IAF Cabelos
  3. Cruza com `iaf_make`    → classifica como IAF Make
  4. Fallbacks por nome      → capilar / palavras-chave Make
  5. Sem match               → Geral
"""

import re
import sqlite3
from processador import normalizar_sku

# ─── Heurística IAF Cabelos pelo nome do produto ──────────────────────────────
# Palavras que acompanham a marca Siàge na regra histórica (ver _contem_siage).
PALAVRAS_SIAGE = {"KIT", "COMB", "SHAMP", "COND"}

# As listas iaf_cabelos/iaf_make vêm da marca e não trazem NENHUM combo: o
# pacote é vendido no lugar dos componentes, e são os componentes que estão
# listados. Por isso todo combo depende deste fallback — e por isso ele só
# vale para pacote. Produto individual continua valendo o que a lista diz:
# shampoo infantil fora da lista fica fora do indicador, de propósito.
# Sachê entra junto: "CJ SCH SIAGE ... 3x7ml VDA" é conjunto vendável, não
# amostra de graça — é venda de cabelo e conta. Antes contava ou não conforme
# o rótulo ter abreviado "COND" ou "CON", que é o que a porta histórica olhava.
INDICADORES_PACOTE = (
    "COMBO", "COMB", "KIT", "ESTOJO", "ESTJ", "PRESENTE",
    "CJ", "SCH", "SACHET", "CONJ",
)

# Marcadores capilares dentro do nome do pacote.
INDICADORES_CABELOS = (
    "SIAGE", "SIÀGE", "MATCH", "CRONOLOGY", "HAIRPLASTIA",
    "SHAMPOO", "SHAMPO", "SHAMP", "SHP",
    "CONDICIONADOR", "CONDICION", "COND", "CND",
    "CABELO", "CAPILAR", "CACHO", "HAIR",
    "ANTIQUEDA", "ANTICASPA", "SCALP",
)

# Pacotes que trazem marcador capilar mas não contam como cabelo:
# "PERFECT MATCH" é linha de batom, não a linha capilar MATCH; shampoo de
# pet e de barba são outra categoria.
EXCLUSOES_CABELOS = (
    "PERFECT MATCH", "PETS", "AU MIGOS", "BARBA",
)

# ─── Heurística IAF Make pelo nome do produto ─────────────────────────────────
# Exclusões: se o nome bater em qualquer um destes, NÃO é maquiagem.
# Vem antes dos indicadores positivos para evitar falsos positivos (ex.: "BAT"
# em BATERIA/BATEDOR, "BASE" em produtos corporais, etc.).
EXCLUSOES_MAKE = (
    # Perfumaria
    "DES COL", "COLONIA", "EDP", "EDT", "EAU DE PARFUM",
    "SPLASH", "PARFUMEE", "PERFUM",
    # Corpo
    "BODY SPRAY", "BODY SPLASH", "BODY MIST",
    "CORPORAL", "LOC HID", "HID CPO",
    # Capilar
    "CABELO", "SHAMP", "COND", "MASCARA CAPILAR",
    "OLEO CAPILAR", "LEAVE", "CREME PENT",
    # Banho
    "SAB BARRA", "SAB LIQ", "SABONETE",
    # Falsos positivos de "BAT"
    "BATERIA", "BATEDOR",
    # Acessórios (pincel/esponja/maleta etc. não são IAF Make)
    "PINCEL", "PINCEIS", "ESPONJA", "ESPNJ", "APLICADOR",
    "MALETA", "NECESSAIRE", "NECESS", "FRASQUEIRA",
    "ESPELHO", "APONTADOR", "CURVADOR",
)

# Indicadores positivos: se o nome passou pelas exclusões e bate em qualquer
# um destes, classifica como IAF Make.
INDICADORES_MAKE = (
    # Batom
    "BATOM", "BAT HID", "BAT MATE", "BAT LIQ", "BAT CREM", "BAT SEMIMATE",
    "MAK BAT", "LIPSTICK", "LIP TINT", "LIP OIL", "LIP GLOSS",
    # Olhos
    "SOMBRA", "PALETA SOMBRA", "RIMEL", "MASCARA CILIOS",
    "DELINEADOR", "LAP OLHO", "LAP SOBR",
    # Boca ("GLOS" cobre GLOS/GLOSS/LIP GLOSS/GLOS LAB; "HID LAB" = hidratante labial)
    "GLOS", "LABIAL", "LAP BOCA", "HID LAB",
    # Rosto
    "BLUSH", "BRONZER", "ILUMINADOR", "PRIMER", "CORRETIVO",
    "PO COMPACTO", "PO FACIAL", "CONTORNO",
    "BASE LIQ", "BASE STICK", "BASE PO",
    # Linhas
    "MAKE B ", "EUD MAKE",
    "NIINA SECRETS GLOSS", "NIINA SECRETS BAT", "NIINA SECRETS SOMBRA",
    "NIINA SCR BAT", "NIINA SCR GLOS", "NIINA SCR SOMBRA",
    "QDB BAT", "QDB GLOS", "QDB SOMBRA", "QDB BASE", "QDB BLUSH",
)

# ─── Categorias de produto ────────────────────────────────────────────────────
# Ordem importa: categorias mais específicas primeiro.
# Dentro de cada categoria, keywords mais longas vêm antes para evitar
# falsos positivos de keywords curtas.
CATEGORIAS_KEYWORDS = [
    ("Demonstradores", [
        "DEMONSTRADOR", "DEMONSTRAD", "DEMON", "FLAC", "DEM", "CJ",
    ]),
    ("Cabelos", [
        "MASCARA CAPILAR", "MASC CAP", "LEAVE-IN", "LEAVE IN",
        "TRAT CAP", "CONDICIONADOR", "QUERATINA", "CAPILAR",
        "SHAMPOO", "SHAMPO", "CONDICION", "SIÀGE", "SIAGE",
        "CABELO", "CACHOS", "MATCH", "AMACI", "HAIR", "SHAMP", "COND",
        # Abreviações usadas nos nomes de combo: "COMBO NUTRI ACID SHP+CND".
        # Só funcionam porque _tokenizar quebra no "+".
        "SHP", "CND",
    ]),
    # Barba vem antes de Maquiagem: balm e creme pós-barba batiam com "BALM" e
    # "CREME" e viravam maquiagem — 25 produtos, incluindo a linha Malbec.
    ("Barba", [
        "BARBA", "BARB",
    ]),
    ("Maquiagem", [
        "MASC CILIO", "BASE STICK", "BASE LIQ", "BLUSH LIQ", "BAT LIQ",
        "FAC STICK", "HID LAB", "OIL SHIN", "PLT MULTIF", "PO COMP",
        "CORR LIQ", "SOBRANC", "CORRET", "LAP OLH", "BATOM", "PRIMER",
        "SOMBRA", "BLUSH", "GLOSS", "ILUM", "MAKE", "BALM", "GLIT",
        "SOUL", "BASE", "MASC", "SOMB", "GLOS", "PLT", "BAS", "BAT", "PO",
    ]),
    ("Perfumaria", [
        "PARFUM", "PARFUN", "EDP", "EAU", "COL",
    ]),
    ("Acessórios", [
        "MASSAGEADOR", "VAPORIZADOR", "FRASQUEIRA", "NECESSAIRE",
        "APONTADOR", "CURVADOR", "PINCEIS", "ESPELHO", "ESPONJA",
        "PALETA", "PINCEL", "NECESS", "MASSAG", "MALETA", "TOALHA",
        "BOLSA", "ESPNJ", "PORTA", "LENCO", "LUVA", "CASE", "CLIP",
    ]),
    ("Cuidados com a Pele", [
        # Combo da linha Instance (hidratante corporal Eudora). Precisa ser
        # explícito: o nome do combo não diz "creme" nem "corporal", então caía
        # nas keywords curtas de categorias abaixo — "PRALINE" batia com o "PR"
        # de Solar, "DESCONTO" com o "DES" de Desodorantes, "SACOLA" virava
        # Embalagens. O produto individual não entra aqui: sabonete e aerossol
        # da mesma linha continuam achando a categoria certa deles.
        "COMBO INSTANCE", "COMB INSTANCE",
        "INSTANCE CR", "CORPORAL", "CREME", "CRÈME", "MAOS", "CPO", "CREM", "HID", "MAO",
    ]),
    ("Cuidados Faciais", [
        "NEO DERMO", "FACIAL", "SKINQ", "NEO D", "SKIN", "FAC",
    ]),
    ("Desodorantes", [
        "AEROSSOL", "ROLL ON", "BDY SPR", "ANTIT", "AER", "ANT", "DES", "SPR",
    ]),
    ("Embalagens", [
        "KIT TAG", "SACOLA", "TAG",
    ]),
    ("Gifts", [
        "PMPCK", "ESTJ", "KIT",
    ]),
    ("Sabonete Corpo", [
        "ESF CPO", "SAB BARR", "SHW GEL", "SHW", "SAB",
    ]),
    ("Solar", [
        "PROT", "SOL", "PR",
    ]),
    ("Unhas", [
        "ESMALTE", "ESMLT",
    ]),
    ("Óleos", [
        "ÓLEO", "OLEO", "OL",
    ]),
]


def _tokenizar(nome):
    """Divide o nome em tokens separados por espaços e pontuação.

    O "+" separa os itens de um combo ("SHP+CND", "SH+COND"): sem quebrar nele
    o token inteiro não começa por nenhuma keyword e o combo caía em "Outros".
    """
    return re.split(r"[\s/\-_,\.\(\)\+&]+", nome.upper())


def classificar_categoria(nome_produto):
    """Classifica o produto em uma categoria baseado em keywords no nome.
    Retorna a categoria encontrada ou 'Outros'."""
    if not nome_produto:
        return "Outros"
    nome_u = nome_produto.upper()
    tokens = _tokenizar(nome_u)

    for categoria, keywords in CATEGORIAS_KEYWORDS:
        for kw in keywords:
            kw = kw.strip().upper()
            if not kw:
                continue
            if " " in kw:
                # Keyword multi-palavra: busca exata como substring
                if kw in nome_u:
                    return categoria
            else:
                # Keyword simples: qualquer token deve começar com ela
                if any(tok.startswith(kw) for tok in tokens if tok):
                    return categoria
    return "Outros"


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
    """Regra histórica: nome traz a marca Siàge escrita + palavra capilar."""
    n = nome.upper()
    if "SIAGE" not in n and "SIÀGE" not in n:
        return False
    return any(p in n for p in PALAVRAS_SIAGE)


def _e_pacote_capilar(nome):
    """O nome indica um pacote (combo/kit/estojo) de itens capilares?"""
    tokens = [t for t in _tokenizar(nome) if t]
    if not any(t.startswith(p) for t in tokens for p in INDICADORES_PACOTE):
        return False
    return any(t.startswith(c) for t in tokens for c in INDICADORES_CABELOS)


def is_hair_product(nome):
    """Heurística: o nome do produto conta como IAF Cabelos?

    Só deve ser chamada quando o SKU não foi encontrado em iaf_cabelos/iaf_make.

    Duas portas. A histórica exige a marca "Siàge" escrita no nome, e por isso
    pegava só metade dos combos: "COMBO SIAGE NUTRI ROSE SHP+CND" entrava e
    "COMBO NUTRI ACID SHP+CND" — mesma linha, mesma prateleira — caía em Geral.
    A segunda porta cobre o pacote independentemente da marca aparecer no nome,
    e vale também para o conjunto de sachês, que é vendável.

    O que decide é o nome do produto — o combo não é aberto nos componentes.
    Um pacote misto (cabelo + make) conta inteiro como cabelo.
    """
    if not nome:
        return False
    if any(excl in nome.upper() for excl in EXCLUSOES_CABELOS):
        return False
    return _contem_siage(nome) or _e_pacote_capilar(nome)


def is_makeup_product(nome):
    """Heurística: o nome do produto sugere que é maquiagem?

    Só deve ser chamada quando o SKU não foi encontrado em iaf_make/iaf_cabelos.
    Aplica exclusões antes dos indicadores positivos para evitar falsos
    positivos com perfumaria, corpo, capilar, banho e siglas ambíguas como BAT.
    """
    if not nome:
        return False
    n = nome.upper()
    if any(excl in n for excl in EXCLUSOES_MAKE):
        return False
    return any(ind in n for ind in INDICADORES_MAKE)


def cruzar_vendas(vendas, indice_produtos, indice_iaf):
    """
    Enriquece cada venda com:
      - marca          : marca do produto (da tabela `produtos`)
      - em_catalogo    : True se o SKU existe na tabela `produtos`
      - classificacao_iaf : "IAF Cabelos" | "IAF Make" | "Geral"
      - metodo_match   : "sku" | "fallback_cabelos" | "fallback_make" | "nenhum"
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

        # 2. Fallback capilar (pega os combos, que nunca estão nas listas IAF)
        elif is_hair_product(nome_produto):
            venda["classificacao_iaf"] = "IAF Cabelos"
            venda["metodo_match"] = "fallback_cabelos"

        # 3. Fallback Make (heurística pelo nome, com exclusões)
        elif is_makeup_product(nome_produto):
            venda["classificacao_iaf"] = "IAF Make"
            venda["metodo_match"] = "fallback_make"

        # 4. Sem match IAF
        else:
            venda["classificacao_iaf"] = "Geral"
            venda["metodo_match"] = "nenhum"

        # ── Categoria do produto ──────────────────────────────────────────
        venda["categoria"] = classificar_categoria(nome_produto)

    return vendas

