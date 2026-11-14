# -*- coding: utf-8 -*-
"""
Cliente - Comparador de Passagens Rodoviárias
=============================================

Interface de terminal usada pelo passageiro. Pede origem, destino, data e modo
de consulta, envia a requisição em JSON ao agregador via socket TCP (porta 6000)
e exibe a tabela de viagens ordenada por preço.

Como executar:
    python cliente.py                 -> conecta em 127.0.0.1:6000
    python cliente.py 192.168.0.10    -> conecta no agregador de outra máquina
"""

import socket
import json
import time
import sys

# ============================================================================
# CONFIGURAÇÕES
# ============================================================================
HOST_AGREGADOR = "127.0.0.1"
PORTA_AGREGADOR = 6000
TIMEOUT_SEGUNDOS = 20        # o modo sequencial pode levar até 4 x 2 s no pior caso
TAMANHO_BUFFER = 4096

# Valores sugeridos (basta apertar Enter)
PADRAO_ORIGEM = "Marabá"
PADRAO_DESTINO = "Belém"
PADRAO_DATA = "2026-11-20"

LARGURA = 78


# ============================================================================
# COMUNICAÇÃO COM O AGREGADOR
# ============================================================================
def receber_linha(conexao):
    dados = b""
    while b"\n" not in dados:
        bloco = conexao.recv(TAMANHO_BUFFER)
        if not bloco:
            break
        dados += bloco
    if not dados.strip():
        raise ConnectionError("o agregador encerrou a conexão sem responder")
    return dados.split(b"\n", 1)[0].decode("utf-8", errors="replace")


def consultar_agregador(requisicao):
    """Abre a conexão TCP, envia a requisição JSON e devolve a resposta (dict)."""
    with socket.create_connection((HOST_AGREGADOR, PORTA_AGREGADOR), timeout=TIMEOUT_SEGUNDOS) as conexao:
        conexao.sendall((json.dumps(requisicao, ensure_ascii=False) + "\n").encode("utf-8"))
        texto = receber_linha(conexao)
    return json.loads(texto)


# ============================================================================
# FORMATAÇÃO
# ============================================================================
def formatar_preco(valor):
    """189.9 -> 'R$ 189,90' (padrão brasileiro)."""
    texto = "{:,.2f}".format(valor)
    return "R$ " + texto.replace(",", "X").replace(".", ",").replace("X", ".")


def formatar_duracao(minutos):
    """510 -> '8h30'."""
    return "{}h{:02d}".format(minutos // 60, minutos % 60)


def formatar_chegada(saida, chegada):
    """Acrescenta '(+1)' quando a chegada é no dia seguinte."""
    try:
        h1, m1 = saida.split(":")
        h2, m2 = chegada.split(":")
        if int(h2) * 60 + int(m2) < int(h1) * 60 + int(m1):
            return chegada + " (+1)"
    except ValueError:
        pass
    return chegada


def mesma_viagem(a, b):
    if not a or not b:
        return False
    return all(a.get(c) == b.get(c) for c in ("empresa", "saida", "preco"))


def exibir_resultado(resposta, tempo_cliente_ms):
    print()
    if resposta.get("status") == "erro":
        print("  ERRO: {}".format(resposta.get("mensagem", "erro desconhecido")))
        return

    print("=" * LARGURA)
    print("  {} -> {}  |  Data: {}".format(resposta.get("origem"), resposta.get("destino"),
                                          resposta.get("data")))
    print("=" * LARGURA)

    viagens = resposta.get("viagens", [])
    if viagens:
        cabecalho = "{:<16}| {:<6}| {:<12}| {:<8}| {:>12}".format(
            "EMPRESA", "SAÍDA", "CHEGADA", "DURAÇÃO", "PREÇO")
        print(cabecalho)
        print("-" * LARGURA)
        mais_economica = resposta.get("mais_economica")
        marcou = False
        for v in viagens:
            linha = "{:<16}| {:<6}| {:<12}| {:<8}| {:>12}".format(
                v["empresa"][:16], v["saida"], formatar_chegada(v["saida"], v["chegada"]),
                formatar_duracao(v["duracao_min"]), formatar_preco(v["preco"]))
            if not marcou and mesma_viagem(v, mais_economica):
                linha += "  <-- MAIS ECONÔMICA"
                marcou = True
            print(linha)
        print("-" * LARGURA)
        print("  {} viagem(ns) encontrada(s), ordenadas por preço crescente.".format(len(viagens)))
    else:
        print("  Nenhuma viagem encontrada para essa rota/data.")

    avisos = resposta.get("avisos", [])
    if avisos:
        print()
        for aviso in avisos:
            print("  AVISO: {}".format(aviso))

    print()
    print("  Tempo total: {:.0f} ms | Modo: {} | Serviços que responderam: {}/{}".format(
        resposta.get("tempo_total_ms", 0), resposta.get("modo_usado", "?"),
        resposta.get("servicos_responderam", 0), resposta.get("servicos_consultados", 0)))
    print("  (tempo de ida e volta medido no cliente: {:.0f} ms)".format(tempo_cliente_ms))
    print("=" * LARGURA)


# ============================================================================
# ENTRADA DE DADOS
# ============================================================================
def perguntar(texto, padrao=None):
    sufixo = " [{}]".format(padrao) if padrao else ""
    valor = input("  {}{}: ".format(texto, sufixo)).strip()
    return valor if valor else (padrao or "")


def data_valida(texto):
    try:
        time.strptime(texto, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def ler_consulta():
    """Pergunta os dados da viagem até que sejam válidos."""
    print()
    print("-" * LARGURA)
    print("  NOVA CONSULTA  (pressione Enter para usar o valor entre colchetes)")
    print("-" * LARGURA)

    origem = ""
    while not origem:
        origem = perguntar("Origem", PADRAO_ORIGEM)

    destino = ""
    while not destino or destino.lower() == origem.lower():
        destino = perguntar("Destino", PADRAO_DESTINO)
        if destino.lower() == origem.lower():
            print("  Destino deve ser diferente da origem.")

    data = ""
    while not data_valida(data):
        data = perguntar("Data (AAAA-MM-DD)", PADRAO_DATA)
        if not data_valida(data):
            print("  Data inválida. Exemplo: 2026-11-20")

    modo = ""
    while modo not in ("1", "2"):
        modo = perguntar("Modo (1 = sequencial, 2 = concorrente)", "2")
        if modo not in ("1", "2"):
            print("  Digite 1 ou 2.")

    return {
        "operacao": "consultar",
        "origem": origem,
        "destino": destino,
        "data": data,
        "modo": "sequencial" if modo == "1" else "concorrente",
    }


def executar_consulta():
    requisicao = ler_consulta()
    print()
    print("  Consultando o agregador em {}:{} (modo {})...".format(
        HOST_AGREGADOR, PORTA_AGREGADOR, requisicao["modo"]))
    inicio = time.perf_counter()
    try:
        resposta = consultar_agregador(requisicao)
    except ConnectionRefusedError:
        print("  ERRO: não foi possível conectar ao agregador. Ele está rodando na porta {}?".format(
            PORTA_AGREGADOR))
        return
    except socket.timeout:
        print("  ERRO: o agregador demorou mais de {} s para responder.".format(TIMEOUT_SEGUNDOS))
        return
    except (ConnectionError, OSError) as erro:
        print("  ERRO de comunicação com o agregador: {}".format(erro))
        return
    except ValueError:
        print("  ERRO: resposta inválida recebida do agregador.")
        return
    exibir_resultado(resposta, (time.perf_counter() - inicio) * 1000)


def menu():
    print("=" * LARGURA)
    print("        COMPARADOR DE PASSAGENS RODOVIÁRIAS - Sistemas Distribuídos")
    print("=" * LARGURA)
    while True:
        print()
        print("  [1] Nova consulta")
        print("  [0] Sair")
        opcao = input("  Escolha uma opção: ").strip()
        if opcao == "1":
            executar_consulta()
        elif opcao == "0":
            print("  Até a próxima viagem!")
            break
        else:
            print("  Opção inválida.")


def configurar_terminal():
    for fluxo in (sys.stdout, sys.stderr, sys.stdin):
        try:
            fluxo.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


if __name__ == "__main__":
    configurar_terminal()
    if len(sys.argv) > 1:
        HOST_AGREGADOR = sys.argv[1]
    try:
        menu()
    except (KeyboardInterrupt, EOFError):
        print("\n  Programa encerrado.")
