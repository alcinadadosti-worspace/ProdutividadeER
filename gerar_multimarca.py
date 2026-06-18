# -*- coding: utf-8 -*-
"""
gerar_multimarca.py — Planilha consolidada de multimarca por CLIENTE.

Usa exatamente a mesma lógica do app.py (_multimarca_por_cliente):
  - cliente ativo = revendedor com >=1 pedido no ciclo;
  - cliente multimarca = >=2 marcas distintas somando TODOS os pedidos;
  - cada cliente conta 1x, creditado ao vendedor do 1º pedido (ordem = Código do Pedido);
  - bônus +2% quando o cliente já é multimarca no 1º pedido; % com teto de 100%.

Para rodar em outro ciclo, troque ARQ pelo novo RelatorioItensPorVendedor_*.xlsx.
"""
import json
from collections import defaultdict
from processador import ler_planilha
from cruzamento import criar_indices, cruzar_vendas

ARQ = 'RelatorioItensPorVendedor_3280c9c9-62bc-40c7-aa89-fd0958eeb05b.xlsx'
DB = 'produtos.db'
BONUS = 0.02
META = 72.0


def disp_marca(m):
    return 'O Boticário' if m.startswith('oBotic') else m


def num_ped(p):
    d = ''.join(ch for ch in str(p) if ch.isdigit())
    return int(d) if d else 0


# 1. Mesmo pipeline do app: parse + cruzamento de marcas + fallback do catálogo
vendas, _, _ = ler_planilha(ARQ)
ip, ii = criar_indices(DB)
vendas = cruzar_vendas(vendas, ip, ii)
mc = json.load(open('marcas_catalog.json', encoding='utf-8'))
for v in vendas:
    sn = v.get('CodigoProduto_normalizado', '')
    if sn in mc and not v.get('marca'):
        v['marca'] = mc[sn].get('marca', '')

# 2. Agrupar por pedido
ped = {}
for v in vendas:
    p = v.get('CodigoPedido') or v.get('NotaFiscal')
    if not p:
        continue
    d = ped.get(p)
    if d is None:
        d = ped[p] = {'vend': '', 'vnome': '', 'rev': '', 'rnome': '',
                      'ordem': num_ped(p), 'canal': '', 'marcas': set()}
    if not d['vend'] and v.get('CodigoVendedor'):
        d['vend'] = v.get('CodigoVendedor')
        d['vnome'] = v.get('Vendedor') or v.get('CodigoVendedor')
    if not d['rev']:
        d['rev'] = v.get('CodigoRevendedor') or v.get('Revendedor') or ''
        d['rnome'] = v.get('Revendedor') or ''
    if not d['canal']:
        d['canal'] = str(v.get('CanalDistribuicao') or '')
    marca = v.get('marca') or ''
    if marca:
        d['marcas'].add(marca)

# 3. Pedidos por cliente
clientes = defaultdict(list)
for d in ped.values():
    if d['rev']:
        clientes[d['rev']].append(d)


def unidade_de(canal):
    if canal.startswith('13707'):
        return 'Matriz Penedo'
    if canal.startswith('13706'):
        return 'Filial Palmeira dos Índios'
    return 'Outra'


# 4. Creditar cada cliente ao vendedor do 1º pedido + montar detalhe
agg = defaultdict(lambda: {'vnome': '', 'unid_cont': defaultdict(int), 'ativos': 0,
                           'multi': 0, 'first': 0, 'built': 0, 'mono': 0, 'pontos': 0.0})
detalhe = []
for rev, peds in clientes.items():
    peds.sort(key=lambda x: x['ordem'])
    primeiro = peds[0]
    vchave = primeiro['vend'] or '?'
    vnome = primeiro['vnome'] or '(sem vendedor)'
    unid = unidade_de(primeiro['canal'])
    marcas_tot = set()
    for p in peds:
        marcas_tot |= p['marcas']
    is_multi = len(marcas_tot) >= 2
    first_multi = len(primeiro['marcas']) >= 2
    peso = 0.0
    if is_multi:
        peso = (1.0 + BONUS) if first_multi else 1.0
    m = agg[vchave]
    m['vnome'] = vnome
    m['unid_cont'][unid] += 1
    m['ativos'] += 1
    m['pontos'] += peso
    if is_multi:
        m['multi'] += 1
        if first_multi:
            m['first'] += 1
        else:
            m['built'] += 1
    else:
        m['mono'] += 1
    detalhe.append({
        'Unidade': unid, 'Vendedor (1º pedido)': vnome, 'Cód. Revendedor': rev,
        'Revendedor': primeiro['rnome'], 'Nº Pedidos': len(peds),
        'Marcas Distintas': len(marcas_tot),
        'Marcas': ', '.join(sorted(disp_marca(x) for x in marcas_tot)),
        'Multimarca?': 'Sim' if is_multi else 'Não',
        '1º Pedido já Multimarca?': 'Sim' if (is_multi and first_multi) else ('Não' if is_multi else '—'),
        'Pontos': round(peso, 2),
    })

resumo = []
for vchave, m in agg.items():
    pct = min(100.0, m['pontos'] / m['ativos'] * 100) if m['ativos'] else 0
    unid = max(m['unid_cont'], key=m['unid_cont'].get) if m['unid_cont'] else 'Outra'
    resumo.append({
        'Unidade': unid, 'Vendedor': m['vnome'], 'Código': ('' if vchave == '?' else vchave),
        'Clientes Ativos': m['ativos'], 'Clientes Multimarca': m['multi'],
        '→ já no 1º pedido': m['first'], '→ construídos no ciclo': m['built'],
        'Clientes Monomarca': m['mono'],
        'Pontos (c/ bônus +2%)': round(m['pontos'], 2),
        '% Multimarca (teto 100%)': round(pct, 1),
        'Meta': META, 'Atingiu Meta?': 'Sim' if pct >= META else 'Não',
    })

# 5. Escrever xlsx
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

wb = Workbook()
HFILL = PatternFill('solid', fgColor='305496')
HFONT = Font(bold=True, color='FFFFFF')
OKF = PatternFill('solid', fgColor='C6EFCE')
NOF = PatternFill('solid', fgColor='FFC7CE')
TOTF = PatternFill('solid', fgColor='D9E1F2')
BOLD = Font(bold=True)


def style_header(ws, ncol):
    for j in range(1, ncol + 1):
        cc = ws.cell(row=1, column=j)
        cc.fill = HFILL
        cc.font = HFONT
        cc.alignment = Alignment(vertical='center', horizontal='center', wrap_text=True)
    ws.freeze_panes = 'A2'
    ws.row_dimensions[1].height = 42
    ws.auto_filter.ref = f'A1:{get_column_letter(ncol)}{ws.max_row}'


ws = wb.active
ws.title = 'Resumo por Vendedor'
cols1 = ['Unidade', 'Vendedor', 'Código', 'Clientes Ativos', 'Clientes Multimarca',
         '→ já no 1º pedido', '→ construídos no ciclo', 'Clientes Monomarca',
         'Pontos (c/ bônus +2%)', '% Multimarca (teto 100%)', 'Meta', 'Atingiu Meta?']
ws.append(cols1)
ordem_un = ['Matriz Penedo', 'Filial Palmeira dos Índios', 'Outra']
un_tot = defaultdict(lambda: [0, 0.0])
linhas = sorted(resumo, key=lambda x: (ordem_un.index(x['Unidade']) if x['Unidade'] in ordem_un else 9,
                                       -x['% Multimarca (teto 100%)']))
for row in linhas:
    ws.append([row[k] for k in cols1])
    r = ws.max_row
    ws.cell(row=r, column=10).number_format = '0.0"%"'
    ws.cell(row=r, column=11).number_format = '0"%"'
    ws.cell(row=r, column=12).fill = OKF if row['Atingiu Meta?'] == 'Sim' else NOF
    un_tot[row['Unidade']][0] += row['Clientes Ativos']
    un_tot[row['Unidade']][1] += row['Pontos (c/ bônus +2%)']
for un in ordem_un:
    a, p = un_tot[un]
    if a:
        pct = min(100.0, p / a * 100)
        ws.append([f'TOTAL {un}', '', '', a, '', '', '', '', round(p, 2), round(pct, 1),
                   META, 'Sim' if pct >= META else 'Não'])
        r = ws.max_row
        for j in range(1, 13):
            ws.cell(row=r, column=j).fill = TOTF
            ws.cell(row=r, column=j).font = BOLD
        ws.cell(row=r, column=10).number_format = '0.0"%"'
        ws.cell(row=r, column=11).number_format = '0"%"'
for i, w in enumerate([26, 38, 12, 14, 16, 15, 18, 16, 18, 18, 8, 13], 1):
    ws.column_dimensions[get_column_letter(i)].width = w
style_header(ws, len(cols1))

ws2 = wb.create_sheet('Detalhe Clientes')
cols2 = ['Unidade', 'Vendedor (1º pedido)', 'Cód. Revendedor', 'Revendedor', 'Nº Pedidos',
         'Marcas Distintas', 'Marcas', 'Multimarca?', '1º Pedido já Multimarca?', 'Pontos']
ws2.append(cols2)
detalhe.sort(key=lambda x: (x['Unidade'], x['Vendedor (1º pedido)'], -x['Marcas Distintas']))
for d in detalhe:
    ws2.append([d[k] for k in cols2])
    r = ws2.max_row
    ws2.cell(row=r, column=10).number_format = '0.00'
    if d['Multimarca?'] == 'Sim':
        ws2.cell(row=r, column=8).fill = OKF
for i, w in enumerate([26, 38, 16, 40, 11, 15, 42, 12, 22, 9], 1):
    ws2.column_dimensions[get_column_letter(i)].width = w
style_header(ws2, len(cols2))

ws3 = wb.create_sheet('Metodologia')
texto = [
    ('CÁLCULO DE MULTIMARCA POR CLIENTE — Ciclo 08/2026', True),
    ('', False),
    ('Fonte: ' + ARQ, False),
    ('Mesma lógica do app.py (_multimarca_por_cliente).', False),
    ('', False),
    ('REGRA OFICIAL:', True),
    ('1. A unidade de contagem é o CLIENTE (revendedor), não o pedido.', False),
    ('2. Cliente ATIVO = revendedor com ao menos 1 pedido no ciclo.', False),
    ('3. Cliente MULTIMARCA = comprou 2+ marcas distintas somando TODOS os pedidos do ciclo.', False),
    ('   (marcas guarda-chuva: O Boticário, Eudora, Quem Disse Berenice, O.U.I, AuAmigos)', False),
    ('4. Cada cliente conta UMA vez no ciclo (pedidos repetidos não geram pontos extras).', False),
    ('5. O cliente é creditado ao vendedor do 1º pedido dele (ordem = Código do Pedido).', False),
    ('', False),
    ('PONTUAÇÃO:', True),
    ('   - Cliente monomarca .................................. 0 ponto', False),
    ('   - Cliente multimarca (construído ao longo do ciclo) .. 1,00 ponto', False),
    ('   - Cliente multimarca JÁ no 1º pedido (bônus +2%) ..... 1,02 ponto', False),
    ('', False),
    ('% MULTIMARCA = (soma dos pontos / clientes ativos) x 100, limitado a 100%.', False),
    ('Meta institucional: 72%.', False),
]
for i, (t, b) in enumerate(texto, 1):
    cc = ws3.cell(row=i, column=1, value=t)
    if b:
        cc.font = Font(bold=True, size=12 if i == 1 else 11, color='305496' if i == 1 else '000000')
ws3.column_dimensions['A'].width = 95

OUT = 'Multimarca_Clientes_2026-06-18.xlsx'
wb.save(OUT)
print('Planilha gerada:', OUT)
print('Vendedores:', len(resumo), '| Clientes:', len(detalhe))
for un in ordem_un:
    a, p = un_tot[un]
    if a:
        print(f'  {un}: ativos={a} => {round(min(100,p/a*100),1)}%')
