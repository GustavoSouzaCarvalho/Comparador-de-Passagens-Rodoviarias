# -*- coding: utf-8 -*-
"""
Geração de gráficos e tabelas dos experimentos
==============================================

Lê os CSVs produzidos por experimento.py e gera:
  - gráficos SVG em experimentos/graficos/  (abrem no navegador, no GitHub,
    e podem ser inseridos no Word/Google Docs/LibreOffice)
  - experimentos/RESULTADOS.md com as tabelas e os gráficos

Usa apenas Python puro (csv, sys, time): nenhuma biblioteca externa.
Os CSVs que ainda não existirem são simplesmente ignorados.

Como executar (a partir da pasta do projeto):
    python experimentos/gerar_graficos.py
"""

import csv
import sys
import time

# ============================================================================
# ESTILO (paleta validada para daltonismo: azul x laranja)
# ============================================================================
COR_SUPERFICIE = "#fcfcfb"
COR_TEXTO = "#0b0b0b"
COR_TEXTO_2 = "#52514e"
COR_GRADE = "#e4e3df"
COR_EIXO = "#b9b8b2"
COR_MODO = {"sequencial": "#2a78d6", "concorrente": "#eb6834"}
NOME_MODO = {"sequencial": "Sequencial", "concorrente": "Concorrente"}
FONTE = "system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"

LARGURA, ALTURA = 760, 440
MODOS = ("sequencial", "concorrente")


# ============================================================================
# UTILITÁRIOS
# ============================================================================
def pasta_do_script():
    caminho = __file__.replace("\\", "/")
    return caminho.rsplit("/", 1)[0] if "/" in caminho else "."


PASTA = pasta_do_script()
PASTA_GRAFICOS = PASTA + "/graficos"


def ler_csv(nome):
    """Lê um CSV da pasta experimentos. Devolve None se não existir."""
    try:
        with open(PASTA + "/" + nome, newline="", encoding="utf-8") as arquivo:
            return list(csv.DictReader(arquivo))
    except FileNotFoundError:
        return None


def media(valores):
    return sum(valores) / len(valores) if valores else 0.0


def num(valor, casas=1):
    """Formata número no padrão brasileiro: 3208.94 -> '3.208,9'."""
    texto = "{:,.{}f}".format(valor, casas)
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def esc(texto):
    """Escapa caracteres especiais de XML."""
    return (str(texto).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def escala(maximo, divisoes=5):
    """Calcula marcas 'redondas' para o eixo Y (sem o módulo math)."""
    if maximo <= 0:
        return [0, 1]
    bruto = maximo / divisoes
    potencia = 1.0
    while potencia * 10 <= bruto:
        potencia *= 10
    while potencia > bruto:
        potencia /= 10
    passo = potencia
    for m in (1, 2, 2.5, 5, 10):
        if m * potencia >= bruto:
            passo = m * potencia
            break
    n = int(-(-maximo // passo))
    return [passo * i for i in range(n + 1)]


def rotulo_eixo(v):
    if v == int(v):
        return num(v, 0)
    return num(v, 2).rstrip("0").rstrip(",")


def caminho_barra(x, y, w, h, r=4):
    """Barra com cantos arredondados (4px) só no topo; base reta."""
    r = min(r, h, w / 2)
    if h <= 0:
        return ""
    return ("M{x:.1f},{yb:.1f} L{x:.1f},{yr:.1f} Q{x:.1f},{y:.1f} {xr:.1f},{y:.1f} "
            "L{xw_r:.1f},{y:.1f} Q{xw:.1f},{y:.1f} {xw:.1f},{yr:.1f} L{xw:.1f},{yb:.1f} Z").format(
        x=x, y=y, yb=y + h, yr=y + r, xr=x + r, xw=x + w, xw_r=x + w - r)


class Svg:
    """Montador simples de SVG."""

    def __init__(self, titulo, subtitulo):
        self.partes = []
        self.titulo = titulo
        self.add('<rect width="{}" height="{}" fill="{}"/>'.format(LARGURA, ALTURA, COR_SUPERFICIE))
        self.texto(24, 34, titulo, 18, COR_TEXTO, peso=600)
        self.texto(24, 56, subtitulo, 12.5, COR_TEXTO_2)

    def add(self, elemento):
        self.partes.append(elemento)

    def texto(self, x, y, conteudo, tamanho=12, cor=COR_TEXTO_2, ancora="start", peso=400, extra=""):
        self.add('<text x="{:.1f}" y="{:.1f}" font-size="{}" fill="{}" text-anchor="{}" '
                 'font-weight="{}"{}>{}</text>'.format(x, y, tamanho, cor, ancora, peso, extra, esc(conteudo)))

    def legenda(self, itens, y=80):
        x = 24
        for nome, cor in itens:
            self.add('<rect x="{}" y="{}" width="12" height="12" rx="2" fill="{}"/>'.format(x, y - 10, cor))
            self.texto(x + 18, y, nome, 12.5, COR_TEXTO)
            x += 30 + len(nome) * 7.5

    def salvar(self, nome):
        conteudo = ('<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
                    'viewBox="0 0 {w} {h}" font-family="{f}" role="img" aria-label="{t}">\n'
                    '<title>{t}</title>\n{corpo}\n</svg>\n').format(
            w=LARGURA, h=ALTURA, f=esc(FONTE), t=esc(self.titulo), corpo="\n".join(self.partes))
        caminho = PASTA_GRAFICOS + "/" + nome
        with open(caminho, "w", encoding="utf-8") as arquivo:
            arquivo.write(conteudo)
        print("  gráfico gerado: graficos/{}".format(nome))
        return "graficos/" + nome


def eixo_y(svg, area, marcas, titulo_eixo):
    """Desenha grade horizontal, rótulos do eixo Y e o título do eixo."""
    x0, y0, x1, y1 = area
    topo = marcas[-1]
    for v in marcas:
        y = y1 - (v / topo) * (y1 - y0)
        svg.add('<line x1="{}" y1="{:.1f}" x2="{}" y2="{:.1f}" stroke="{}" stroke-width="1"/>'.format(
            x0, y, x1, y, COR_GRADE if v else COR_EIXO))
        svg.texto(x0 - 8, y + 4, rotulo_eixo(v), 11, COR_TEXTO_2, ancora="end")
    svg.texto(24, y0 - 14, titulo_eixo, 11, COR_TEXTO_2)


# ============================================================================
# TIPOS DE GRÁFICO
# ============================================================================
def grafico_barras(nome, titulo, subtitulo, categorias, series, titulo_eixo,
                   rotular=None, notas=None, unidade=" ms", casas=0):
    """
    Barras agrupadas. series = [(nome, cor, [valores por categoria])].
    rotular = índices das categorias que recebem o valor escrito (None = todas).
    notas = segunda linha de texto sob cada categoria (opcional).
    """
    svg = Svg(titulo, subtitulo)
    svg.legenda([(s[0], s[1]) for s in series])
    area = (84, 118, LARGURA - 28, ALTURA - (70 if notas else 52))
    x0, y0, x1, y1 = area
    maximo = max(max(s[2]) for s in series) * 1.12
    marcas = escala(maximo)
    topo = marcas[-1]
    eixo_y(svg, area, marcas, titulo_eixo)

    banda = (x1 - x0) / len(categorias)
    largura_barra = min(24, (banda * 0.62 - 2 * (len(series) - 1)) / len(series))
    largura_grupo = largura_barra * len(series) + 2 * (len(series) - 1)
    for ci, categoria in enumerate(categorias):
        inicio = x0 + banda * ci + (banda - largura_grupo) / 2
        for si, (nome_serie, cor, valores) in enumerate(series):
            v = valores[ci]
            h = (v / topo) * (y1 - y0)
            x = inicio + si * (largura_barra + 2)
            svg.add('<path d="{}" fill="{}"><title>{} - {}: {}{}</title></path>'.format(
                caminho_barra(x, y1 - h, largura_barra, h), cor, esc(categoria), esc(nome_serie),
                num(v, casas), unidade))
            if rotular is None or ci in rotular:
                svg.texto(x + largura_barra / 2, y1 - h - 6, num(v, casas), 11, COR_TEXTO, ancora="middle")
        cx = x0 + banda * ci + banda / 2
        svg.texto(cx, y1 + 20, categoria, 12, COR_TEXTO, ancora="middle")
        if notas:
            svg.texto(cx, y1 + 37, notas[ci], 11, COR_TEXTO_2, ancora="middle")
    return svg.salvar(nome)


def grafico_linhas(nome, titulo, subtitulo, xs, rotulos_x, titulo_x, series, titulo_eixo,
                   linear=True, referencias=None, casas=0, unidade=" ms"):
    """
    Linhas. series = [(nome, cor, [valores alinhados com xs])].
    linear=True usa escala proporcional em X; False espaça igualmente.
    referencias = [(valor_y, rótulo)] linhas tracejadas de referência.
    """
    svg = Svg(titulo, subtitulo)
    if len(series) > 1:
        svg.legenda([(s[0], s[1]) for s in series])
    area = (84, 118 if len(series) > 1 else 100, LARGURA - 130, ALTURA - 64)
    x0, y0, x1, y1 = area
    maximo = max(max(s[2]) for s in series)
    if referencias:
        maximo = max(maximo, max(r[0] for r in referencias))
    marcas = escala(maximo * 1.1)
    topo = marcas[-1]
    eixo_y(svg, area, marcas, titulo_eixo)

    def px(i):
        if linear:
            menor, maior = xs[0], xs[-1]
            return x0 + 12 + (xs[i] - menor) / ((maior - menor) or 1) * (x1 - x0 - 24)
        return x0 + 12 + i * (x1 - x0 - 24) / max(1, len(xs) - 1)

    def py(v):
        return y1 - (v / topo) * (y1 - y0)

    for i, rot in enumerate(rotulos_x):
        svg.texto(px(i), y1 + 20, rot, 11.5, COR_TEXTO_2, ancora="middle")
    svg.texto((x0 + x1) / 2, y1 + 44, titulo_x, 12, COR_TEXTO_2, ancora="middle")

    for valor, rotulo in (referencias or []):
        y = py(valor)
        svg.add('<line x1="{}" y1="{:.1f}" x2="{}" y2="{:.1f}" stroke="{}" stroke-width="1.5" '
                'stroke-dasharray="5 4"/>'.format(x0, y, x1, y, COR_EIXO))
        svg.texto(x1, y - 8, rotulo, 11, COR_TEXTO_2, ancora="end")

    # Rótulos no fim das linhas, afastados para não se sobreporem
    finais = sorted([[py(s[2][-1]), s] for s in series], key=lambda f: f[0])
    for k in range(1, len(finais)):
        if finais[k][0] - finais[k - 1][0] < 30:
            finais[k][0] = finais[k - 1][0] + 30

    for nome_serie, cor, valores in series:
        pontos = " ".join("{:.1f},{:.1f}".format(px(i), py(v)) for i, v in enumerate(valores))
        svg.add('<polyline points="{}" fill="none" stroke="{}" stroke-width="2" '
                'stroke-linejoin="round" stroke-linecap="round"/>'.format(pontos, cor))
        for i, v in enumerate(valores):
            svg.add('<circle cx="{:.1f}" cy="{:.1f}" r="4" fill="{}" stroke="{}" stroke-width="2">'
                    '<title>{} - {}: {}{}</title></circle>'.format(
                        px(i), py(v), cor, COR_SUPERFICIE, esc(nome_serie), esc(rotulos_x[i]),
                        num(v, casas), unidade))
    for y_rot, (nome_serie, cor, valores) in finais:
        x = px(len(xs) - 1) + 10
        if len(series) > 1:
            svg.texto(x, y_rot - 2, nome_serie, 11.5, COR_TEXTO, peso=600)
            svg.texto(x, y_rot + 12, num(valores[-1], casas) + unidade, 11, COR_TEXTO_2)
        else:
            svg.texto(x, y_rot + 4, num(valores[-1], casas) + unidade, 11.5, COR_TEXTO, peso=600)
    return svg.salvar(nome)


# ============================================================================
# EXPERIMENTOS
# ============================================================================
def exp_1_2(md):
    linhas = ler_csv("resultados.csv")
    if not linhas:
        print("  resultados.csv não encontrado: pulando experimentos 1 e 2")
        return
    tempos = {m: [float(l["tempo_ms"]) for l in linhas if l["modo"] == m] for m in MODOS}
    servicos = {m: [l["num_servicos"] for l in linhas if l["modo"] == m] for m in MODOS}
    n = min(len(tempos["sequencial"]), len(tempos["concorrente"]))
    m_seq, m_con = media(tempos["sequencial"]), media(tempos["concorrente"])
    speedup = m_seq / m_con if m_con else 0

    categorias = ["Rep. {}".format(i + 1) for i in range(n)] + ["Média"]
    series = [(NOME_MODO[m], COR_MODO[m], tempos[m][:n] + [media(tempos[m])]) for m in MODOS]
    img = grafico_barras(
        "grafico_1_sequencial_vs_concorrente.svg",
        "Experimentos 1 e 2: tempo total da consulta por modo",
        "Marabá → Belém, 4 serviços · média sequencial {} ms x concorrente {} ms · speedup {}x".format(
            num(m_seq, 0), num(m_con, 0), num(speedup, 2)),
        categorias, series, "Tempo total (ms)", rotular={n})

    md.append("## Experimentos 1 e 2: consulta sequencial x concorrente\n")
    md.append("Mesma consulta (Marabá → Belém, 2026-11-20) repetida {} vezes em cada modo. "
              "Arquivo: `resultados.csv`.\n".format(n))
    md.append("| Repetição | Sequencial (ms) | Concorrente (ms) | Serviços (seq / conc) |")
    md.append("|---:|---:|---:|:---:|")
    for i in range(n):
        md.append("| {} | {} | {} | {}/4 · {}/4 |".format(
            i + 1, num(tempos["sequencial"][i]), num(tempos["concorrente"][i]),
            servicos["sequencial"][i], servicos["concorrente"][i]))
    md.append("| **Média** | **{}** | **{}** | |".format(num(m_seq), num(m_con)))
    md.append("")
    md.append("- **Speedup** (sequencial ÷ concorrente): **{}x**".format(num(speedup, 2)))
    if m_seq:
        md.append("- **Redução de tempo** no modo concorrente: **{}%**".format(num((m_seq - m_con) / m_seq * 100)))
    md.append("\n![Gráfico 1]({})\n".format(img))


def exp_3(md):
    linhas = ler_csv("resultados_latencia.csv")
    if not linhas:
        print("  resultados_latencia.csv não encontrado: pulando experimento 3")
        return
    latencias = sorted(set(float(l["latencia_s"]) for l in linhas))
    medias = {m: [media([float(l["tempo_ms"]) for l in linhas
                         if l["modo"] == m and float(l["latencia_s"]) == lat]) for lat in latencias]
              for m in MODOS}
    speedups = [s / c if c else 0 for s, c in zip(medias["sequencial"], medias["concorrente"])]
    rotulos = [num(l, 2).rstrip("0").rstrip(",") + " s" for l in latencias]

    img1 = grafico_linhas(
        "grafico_2_efeito_da_latencia.svg",
        "Experimento 3: tempo médio da consulta x latência dos serviços",
        "Sequencial cresce com a SOMA das latências (≈ 4 × L); concorrente, com a MAIOR delas (≈ L)",
        latencias, rotulos, "Latência simulada em cada serviço",
        [(NOME_MODO[m], COR_MODO[m], medias[m]) for m in MODOS], "Tempo médio (ms)")
    img2 = grafico_linhas(
        "grafico_3_speedup_por_latencia.svg",
        "Experimento 3: speedup do modo concorrente",
        "Speedup = tempo sequencial ÷ tempo concorrente · limite teórico = 4 (número de serviços)",
        latencias, rotulos, "Latência simulada em cada serviço",
        [("Speedup", COR_MODO["concorrente"], speedups)], "Speedup (x)",
        referencias=[(4, "máximo teórico (4x)"), (1, "sem ganho (1x)")], casas=2, unidade="x")

    md.append("## Experimento 3: simulação de latência\n")
    md.append("A mesma consulta foi repetida para várias latências configuradas nos 4 serviços. "
              "Arquivo: `resultados_latencia.csv`.\n")
    md.append("| Latência por serviço | Sequencial (ms) | Concorrente (ms) | Speedup |")
    md.append("|---:|---:|---:|---:|")
    for i, lat in enumerate(latencias):
        md.append("| {} | {} | {} | {}x |".format(rotulos[i], num(medias["sequencial"][i]),
                                                 num(medias["concorrente"][i]), num(speedups[i], 2)))
    md.append("\n![Gráfico 2]({})\n".format(img1))
    md.append("![Gráfico 3]({})\n".format(img2))


def exp_4(md):
    linhas = ler_csv("resultados_multiplos_clientes.csv")
    if not linhas:
        print("  resultados_multiplos_clientes.csv não encontrado: pulando experimento 4")
        return
    clientes = sorted(set(int(l["num_clientes"]) for l in linhas))
    tabela = {}
    for m in MODOS:
        for c in clientes:
            sel = [l for l in linhas if l["modo"] == m and int(l["num_clientes"]) == c]
            ok = [float(l["tempo_ms"]) for l in sel if l["status"] == "sucesso"]
            lotes = {}
            for l in sel:
                lotes[l["rodada"]] = float(l["tempo_lote_ms"])
            lote = media(list(lotes.values()))
            tabela[(m, c)] = {"tempo": media(ok), "lote": lote, "vazao": c / (lote / 1000) if lote else 0,
                              "falhas": sum(1 for l in sel if l["status"] != "sucesso"), "total": len(sel)}
    rotulos = [str(c) for c in clientes]
    img1 = grafico_linhas(
        "grafico_4_multiplos_clientes_tempo.svg",
        "Experimento 4: tempo médio por cliente x clientes simultâneos",
        "Linhas quase planas: o agregador atende cada cliente em uma thread, sem fila entre eles",
        clientes, rotulos, "Clientes consultando ao mesmo tempo",
        [(NOME_MODO[m], COR_MODO[m], [tabela[(m, c)]["tempo"] for c in clientes]) for m in MODOS],
        "Tempo médio por cliente (ms)", linear=False)
    img2 = grafico_linhas(
        "grafico_5_multiplos_clientes_vazao.svg",
        "Experimento 4: vazão do agregador x clientes simultâneos",
        "Consultas concluídas por segundo (clientes ÷ duração da rodada)",
        clientes, rotulos, "Clientes consultando ao mesmo tempo",
        [(NOME_MODO[m], COR_MODO[m], [tabela[(m, c)]["vazao"] for c in clientes]) for m in MODOS],
        "Vazão (consultas/s)", linear=False, casas=1, unidade=" cons./s")

    md.append("## Experimento 4: múltiplos clientes simultâneos\n")
    md.append("Em cada rodada, N clientes disparam a consulta no mesmo instante. "
              "Arquivo: `resultados_multiplos_clientes.csv`.\n")
    md.append("| Clientes | Modo | Tempo médio por cliente (ms) | Duração média da rodada (ms) | Vazão (consultas/s) | Falhas |")
    md.append("|---:|:---|---:|---:|---:|---:|")
    for c in clientes:
        for m in MODOS:
            t = tabela[(m, c)]
            md.append("| {} | {} | {} | {} | {} | {}/{} |".format(
                c, NOME_MODO[m], num(t["tempo"]), num(t["lote"]), num(t["vazao"], 2), t["falhas"], t["total"]))
    md.append("\n![Gráfico 4]({})\n".format(img1))
    md.append("![Gráfico 5]({})\n".format(img2))


def exp_5(md):
    linhas = ler_csv("resultados_indisponibilidade.csv")
    if not linhas:
        print("  resultados_indisponibilidade.csv não encontrado: pulando experimento 5")
        return
    cenarios = []
    for l in linhas:
        if (l["cenario"], l["descricao"]) not in cenarios:
            cenarios.append((l["cenario"], l["descricao"]))
    dados = {}
    for cod, _ in cenarios:
        for m in MODOS:
            sel = [l for l in linhas if l["cenario"] == cod and l["modo"] == m]
            dados[(cod, m)] = {
                "tempo": media([float(l["tempo_ms"]) for l in sel]),
                "servicos": min(int(l["num_servicos"]) for l in sel),
                "viagens": int(sel[-1]["total_viagens"]),
                "avisos": sel[-1]["avisos"],
            }
    img = grafico_barras(
        "grafico_6_indisponibilidade.svg",
        "Experimento 5: tempo da consulta com serviços indisponíveis",
        "A: todos ativos · B: serviço 2 desligado · C: serviço 3 lento (timeout de 2 s) · D: serviços 2 e 4 desligados",
        ["Cenário " + c for c, _ in cenarios],
        [(NOME_MODO[m], COR_MODO[m], [dados[(c, m)]["tempo"] for c, _ in cenarios]) for m in MODOS],
        "Tempo médio (ms)",
        notas=["{}/4 serviços responderam".format(dados[(c, "concorrente")]["servicos"]) for c, _ in cenarios])

    md.append("## Experimento 5: indisponibilidade de serviço\n")
    md.append("Os serviços \"desligados\" fecham a porta TCP de verdade durante o cenário "
              "(operação `simular_queda`), e o serviço \"lento\" demora 3 s, mais que o timeout "
              "de 2 s do agregador. Arquivo: `resultados_indisponibilidade.csv`.\n")
    md.append("| Cenário | Descrição | Sequencial (ms) | Concorrente (ms) | Serviços que responderam | Viagens |")
    md.append("|:---:|:---|---:|---:|:---:|---:|")
    for c, d in cenarios:
        md.append("| {} | {} | {} | {} | {}/4 | {} |".format(
            c, d, num(dados[(c, "sequencial")]["tempo"]), num(dados[(c, "concorrente")]["tempo"]),
            dados[(c, "concorrente")]["servicos"], dados[(c, "concorrente")]["viagens"]))
    md.append("\nAvisos devolvidos ao cliente:\n")
    for c, d in cenarios:
        avisos = dados[(c, "concorrente")]["avisos"]
        md.append("- **{}**: {}".format(c, " / ".join("`{}`".format(a) for a in avisos.split(" | "))
                                       if avisos else "nenhum aviso"))
    md.append("\n![Gráfico 6]({})\n".format(img))


def main():
    try:
        open(PASTA_GRAFICOS + "/.gitkeep", "a").close()
    except FileNotFoundError:
        print("ERRO: crie a pasta experimentos/graficos antes de rodar este script.")
        sys.exit(1)

    md = ["# Resultados dos experimentos\n",
          "> Arquivo gerado automaticamente por `experimentos/gerar_graficos.py` em {}.".format(
              time.strftime("%d/%m/%Y %H:%M")),
          "> Ambiente: Python {} em `{}`, todos os processos na mesma máquina (localhost).\n".format(
              sys.version.split()[0], sys.platform),
          "Todos os tempos são o `tempo_total_ms` medido pelo agregador, do recebimento da "
          "consulta até a resposta consolidada.\n"]
    exp_1_2(md)
    exp_3(md)
    exp_4(md)
    exp_5(md)
    with open(PASTA + "/RESULTADOS.md", "w", encoding="utf-8") as arquivo:
        arquivo.write("\n".join(md) + "\n")
    print("  tabelas geradas: experimentos/RESULTADOS.md")


if __name__ == "__main__":
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    main()
