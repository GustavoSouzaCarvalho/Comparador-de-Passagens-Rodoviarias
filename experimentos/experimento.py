# -*- coding: utf-8 -*-
"""
Experimentos automatizados - Comparador de Passagens Rodoviárias
================================================================

Pré-requisito: os 4 serviços e o agregador devem estar rodando.

Experimentos (numeração do enunciado do trabalho):
  1 e 2  Sequencial x concorrente: a mesma consulta (Marabá -> Belém,
         2026-11-20) N vezes em cada modo.            -> resultados.csv
  3      Simulação de latência: repete 1 e 2 para várias latências
         (0 a 1,5 s).                                   -> resultados_latencia.csv
  4      Múltiplos clientes: 1, 2, 4, 8, 16 e 32 clientes consultando
         ao mesmo tempo.                                -> resultados_multiplos_clientes.csv
  5      Indisponibilidade: serviço desligado, serviço lento (timeout)
         e dois serviços desligados.                    -> resultados_indisponibilidade.csv

Como executar (a partir da pasta do projeto):
    python experimentos/experimento.py                         -> experimentos 1 e 2
    python experimentos/experimento.py --latencia 0.8          -> 1 e 2 com 0,8 s em cada serviço
    python experimentos/experimento.py --latencia 0            -> 1 e 2 SEM latência
    python experimentos/experimento.py --experimento 3
    python experimentos/experimento.py --experimento 4
    python experimentos/experimento.py --experimento 5
    python experimentos/experimento.py --experimento todos     -> 1 a 5 (cerca de 6 minutos)

Opções:
    --experimento E    1, 2, 3, 4, 5 ou todos (padrão: 1 e 2)
    --latencia X       latência (s) aplicada aos serviços. Nos experimentos 1 e 2
                       o padrão é manter a latência atual; nos experimentos 4 e 5
                       e em "todos" o padrão é 0,8 s.
    --repeticoes N     repetições por modo/configuração (padrão: 5)
    --saida ARQUIVO    nome do CSV dos experimentos 1 e 2 (padrão: resultados.csv)

Ao final, a latência original de cada serviço é sempre restaurada.
Depois, gere os gráficos com:  python experimentos/gerar_graficos.py
"""

import socket
import threading
import json
import time
import sys
import csv

# ============================================================================
# CONFIGURAÇÕES
# ============================================================================
HOST_AGREGADOR = "127.0.0.1"
PORTA_AGREGADOR = 6000
SERVICOS = [
    (1, "Viação Marabá", "127.0.0.1", 5001),
    (2, "TransBrasil", "127.0.0.1", 5002),
    (3, "Expresso Pará", "127.0.0.1", 5003),
    (4, "Rodoviária Sul", "127.0.0.1", 5004),
]
CONSULTA = {"operacao": "consultar", "origem": "Marabá", "destino": "Belém", "data": "2026-11-20"}
MODOS = ("sequencial", "concorrente")

REPETICOES_PADRAO = 5
LATENCIA_PADRAO = 0.8
ARQUIVO_PADRAO = "resultados.csv"
TIMEOUT_SEGUNDOS = 60

# Experimento 3: latências testadas (todas abaixo do timeout de 2 s do agregador)
LATENCIAS_EXP3 = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5]

# Experimento 4: quantidades de clientes simultâneos
CLIENTES_EXP4 = [1, 2, 4, 8, 16, 32]

# Experimento 5: cenários de falha
#   (código, descrição, portas desligadas, {porta: latência do serviço lento})
LATENCIA_SERVICO_LENTO = 3.0
CENARIOS_EXP5 = [
    ("A", "Todos os serviços ativos", [], {}),
    ("B", "Serviço 2 desligado", [5002], {}),
    ("C", "Serviço 3 lento (3 s > timeout)", [], {5003: LATENCIA_SERVICO_LENTO}),
    ("D", "Serviços 2 e 4 desligados", [5002, 5004], {}),
]


# ============================================================================
# COMUNICAÇÃO
# ============================================================================
def pasta_do_script():
    """Diretório onde este arquivo está (sem usar o módulo os)."""
    caminho = __file__.replace("\\", "/")
    return caminho.rsplit("/", 1)[0] if "/" in caminho else "."


def caminho_saida(nome):
    if "/" in nome or "\\" in nome:
        return nome
    return pasta_do_script() + "/" + nome


def requisitar(host, porta, mensagem, timeout=TIMEOUT_SEGUNDOS):
    """Envia uma mensagem JSON via TCP e devolve a resposta JSON."""
    with socket.create_connection((host, porta), timeout=timeout) as conexao:
        conexao.sendall((json.dumps(mensagem, ensure_ascii=False) + "\n").encode("utf-8"))
        dados = b""
        while b"\n" not in dados:
            bloco = conexao.recv(4096)
            if not bloco:
                break
            dados += bloco
    if not dados.strip():
        raise ConnectionError("conexão encerrada sem resposta")
    return json.loads(dados.split(b"\n", 1)[0].decode("utf-8"))


def consultar(modo):
    """Faz a consulta padrão no agregador e devolve a resposta."""
    resposta = requisitar(HOST_AGREGADOR, PORTA_AGREGADOR, dict(CONSULTA, modo=modo))
    if resposta.get("status") == "erro":
        raise ValueError("agregador respondeu erro: {}".format(resposta.get("mensagem")))
    return resposta


def status_servico(host, porta):
    """Devolve o status do serviço, ou None se ele estiver fora do ar."""
    try:
        r = requisitar(host, porta, {"operacao": "status"}, timeout=3)
        return r if r.get("status") == "sucesso" else None
    except (OSError, ValueError):
        return None


def definir_latencia(porta, latencia):
    for _, _, host, p in SERVICOS:
        if p == porta:
            requisitar(host, porta, {"operacao": "configurar_latencia",
                                     "latencia_segundos": latencia}, timeout=3)


def definir_latencia_todos(latencia, silencioso=False):
    for sid, nome, host, porta in SERVICOS:
        try:
            definir_latencia(porta, latencia)
            if not silencioso:
                print("  Serviço {} {:<15} latência = {:.2f}s".format(sid, nome, latencia))
        except (OSError, ValueError) as erro:
            print("  Serviço {} {:<15} indisponível ({})".format(sid, nome, erro))


def aguardar(porta, no_ar, limite_segundos):
    """Espera até o serviço da porta ficar no ar (no_ar=True) ou fora do ar."""
    fim = time.time() + limite_segundos
    while time.time() < fim:
        if (status_servico("127.0.0.1", porta) is not None) == no_ar:
            return True
        time.sleep(0.3)
    return False


def salvar_csv(nome, colunas, linhas):
    caminho = caminho_saida(nome)
    with open(caminho, "w", newline="", encoding="utf-8") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=colunas)
        escritor.writeheader()
        escritor.writerows(linhas)
    print("  Resultados salvos em: {}".format(caminho))


def media(valores):
    return sum(valores) / len(valores) if valores else 0.0


def titulo(texto):
    print()
    print("=" * 70)
    print("  " + texto)
    print("=" * 70)


# ============================================================================
# EXPERIMENTOS 1 E 2 - SEQUENCIAL x CONCORRENTE
# ============================================================================
def experimentos_1_e_2(repeticoes, arquivo):
    titulo("EXPERIMENTOS 1 e 2: CONSULTA SEQUENCIAL x CONCORRENTE")
    print("  Rota: {} -> {} | Data: {} | Repetições por modo: {}".format(
        CONSULTA["origem"], CONSULTA["destino"], CONSULTA["data"], repeticoes))
    print()
    linhas = []
    tempos = {modo: [] for modo in MODOS}
    for modo in MODOS:
        print("  Modo {}:".format(modo.upper()))
        for rep in range(1, repeticoes + 1):
            r = consultar(modo)
            tempo = float(r["tempo_total_ms"])
            num = int(r["servicos_responderam"])
            tempos[modo].append(tempo)
            linhas.append({"modo": modo, "repeticao": rep, "tempo_ms": tempo, "num_servicos": num})
            print("    repetição {}: {:>9.1f} ms | serviços que responderam: {}/{}".format(
                rep, tempo, num, r["servicos_consultados"]))
    salvar_csv(arquivo, ["modo", "repeticao", "tempo_ms", "num_servicos"], linhas)

    m_seq, m_con = media(tempos["sequencial"]), media(tempos["concorrente"])
    print()
    print("  {:<12} {:>12} {:>12} {:>12}".format("Modo", "Média (ms)", "Mínimo", "Máximo"))
    for modo in MODOS:
        print("  {:<12} {:>12.1f} {:>12.1f} {:>12.1f}".format(
            modo, media(tempos[modo]), min(tempos[modo]), max(tempos[modo])))
    if m_con > 0:
        print("  Speedup (sequencial / concorrente): {:.2f}x".format(m_seq / m_con))
    if m_seq > 0:
        print("  Redução de tempo no modo concorrente: {:.1f}%".format((m_seq - m_con) / m_seq * 100))
    if m_con < m_seq:
        print("  Conclusão: o modo CONCORRENTE foi mais rápido.")
    else:
        print("  Conclusão: sem ganho do modo concorrente (latência baixa ou nula:")
        print("  o custo de criar threads se aproxima do tempo das consultas).")


# ============================================================================
# EXPERIMENTO 3 - EFEITO DA LATÊNCIA
# ============================================================================
def experimento_3(repeticoes):
    titulo("EXPERIMENTO 3: SIMULAÇÃO DE LATÊNCIA")
    print("  Latências testadas (s): {}".format(", ".join("{:g}".format(l) for l in LATENCIAS_EXP3)))
    print()
    print("  {:>9} | {:>16} | {:>16} | {:>8}".format("Latência", "Sequencial (ms)", "Concorrente (ms)", "Speedup"))
    print("  " + "-" * 58)
    linhas = []
    for latencia in LATENCIAS_EXP3:
        definir_latencia_todos(latencia, silencioso=True)
        medias = {}
        for modo in MODOS:
            tempos = []
            for rep in range(1, repeticoes + 1):
                r = consultar(modo)
                tempos.append(float(r["tempo_total_ms"]))
                linhas.append({"latencia_s": latencia, "modo": modo, "repeticao": rep,
                               "tempo_ms": float(r["tempo_total_ms"]),
                               "num_servicos": int(r["servicos_responderam"])})
            medias[modo] = media(tempos)
        speedup = medias["sequencial"] / medias["concorrente"] if medias["concorrente"] > 0 else 0
        print("  {:>8.2f}s | {:>16.1f} | {:>16.1f} | {:>7.2f}x".format(
            latencia, medias["sequencial"], medias["concorrente"], speedup))
    salvar_csv("resultados_latencia.csv",
               ["latencia_s", "modo", "repeticao", "tempo_ms", "num_servicos"], linhas)


# ============================================================================
# EXPERIMENTO 4 - MÚLTIPLOS CLIENTES SIMULTÂNEOS
# ============================================================================
def rodada_clientes(num_clientes, modo):
    """Dispara 'num_clientes' consultas ao mesmo tempo (uma thread por cliente)."""
    largada = threading.Barrier(num_clientes)
    resultados = [None] * num_clientes

    def cliente(indice):
        try:
            largada.wait(timeout=10)
        except threading.BrokenBarrierError:
            pass
        inicio = time.perf_counter()
        try:
            r = consultar(modo)
            resultados[indice] = {"ok": True, "inicio": inicio, "fim": time.perf_counter(),
                                  "tempo_ms": float(r["tempo_total_ms"]),
                                  "num_servicos": int(r["servicos_responderam"])}
        except (OSError, ValueError) as erro:
            resultados[indice] = {"ok": False, "inicio": inicio, "fim": time.perf_counter(),
                                  "tempo_ms": 0.0, "num_servicos": 0, "erro": str(erro)}

    threads = [threading.Thread(target=cliente, args=(i,)) for i in range(num_clientes)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    lote_ms = (max(r["fim"] for r in resultados) - min(r["inicio"] for r in resultados)) * 1000
    return resultados, lote_ms


def experimento_4(repeticoes):
    titulo("EXPERIMENTO 4: MÚLTIPLOS CLIENTES SIMULTÂNEOS")
    print("  Cada rodada dispara N clientes ao mesmo tempo (threading.Barrier).")
    print("  Rodadas por configuração: {}".format(repeticoes))
    print()
    print("  {:>8} | {:<12} | {:>14} | {:>12} | {:>14} | {:>6}".format(
        "Clientes", "Modo", "Média/cliente", "Lote (ms)", "Vazão (cons/s)", "Falhas"))
    print("  " + "-" * 82)
    linhas = []
    for num in CLIENTES_EXP4:
        for modo in MODOS:
            tempos, lotes, falhas = [], [], 0
            for rodada in range(1, repeticoes + 1):
                resultados, lote_ms = rodada_clientes(num, modo)
                lotes.append(lote_ms)
                for i, r in enumerate(resultados, start=1):
                    if r["ok"]:
                        tempos.append(r["tempo_ms"])
                    else:
                        falhas += 1
                    linhas.append({
                        "modo": modo, "num_clientes": num, "rodada": rodada, "cliente": i,
                        "status": "sucesso" if r["ok"] else "falha",
                        "tempo_ms": round(r["tempo_ms"], 1),
                        "tempo_ida_volta_ms": round((r["fim"] - r["inicio"]) * 1000, 1),
                        "num_servicos": r["num_servicos"],
                        "tempo_lote_ms": round(lote_ms, 1),
                    })
            vazao = num / (media(lotes) / 1000) if media(lotes) > 0 else 0
            print("  {:>8} | {:<12} | {:>11.1f} ms | {:>12.1f} | {:>14.2f} | {:>6}".format(
                num, modo, media(tempos), media(lotes), vazao, falhas))
    salvar_csv("resultados_multiplos_clientes.csv",
               ["modo", "num_clientes", "rodada", "cliente", "status", "tempo_ms",
                "tempo_ida_volta_ms", "num_servicos", "tempo_lote_ms"], linhas)


# ============================================================================
# EXPERIMENTO 5 - INDISPONIBILIDADE DE SERVIÇO
# ============================================================================
def experimento_5(repeticoes, latencia):
    titulo("EXPERIMENTO 5: INDISPONIBILIDADE DE SERVIÇO")
    print("  Serviços 'desligados' fecham a porta TCP de verdade (operação simular_queda)")
    print("  e voltam sozinhos ao fim do cenário. Latência base: {:.2f}s".format(latencia))
    linhas = []
    resumo = []
    for codigo, descricao, desligados, lentos in CENARIOS_EXP5:
        print()
        print("  Cenário {}: {}".format(codigo, descricao))
        definir_latencia_todos(latencia, silencioso=True)
        for porta, lat in lentos.items():
            definir_latencia(porta, lat)

        # Duração da queda: suficiente para todas as repetições dos dois modos
        duracao = repeticoes * (len(SERVICOS) + 1) * max(latencia, 0.2) + 4
        for porta in desligados:
            requisitar("127.0.0.1", porta, {"operacao": "simular_queda", "duracao_segundos": duracao}, timeout=3)
        for porta in desligados:
            if not aguardar(porta, no_ar=False, limite_segundos=5):
                print("    AVISO: o serviço da porta {} não saiu do ar a tempo".format(porta))

        for modo in MODOS:
            tempos, servicos, avisos = [], [], []
            for rep in range(1, repeticoes + 1):
                r = consultar(modo)
                tempos.append(float(r["tempo_total_ms"]))
                servicos.append(int(r["servicos_responderam"]))
                avisos = r.get("avisos", [])
                linhas.append({"cenario": codigo, "descricao": descricao, "modo": modo,
                               "repeticao": rep, "tempo_ms": float(r["tempo_total_ms"]),
                               "num_servicos": int(r["servicos_responderam"]),
                               "total_viagens": int(r.get("total_viagens", 0)),
                               "avisos": " | ".join(avisos)})
            print("    {:<12} média {:>8.1f} ms | serviços que responderam: {}/{}".format(
                modo, media(tempos), min(servicos), len(SERVICOS)))
            resumo.append((codigo, modo, media(tempos)))
        for aviso in avisos:
            print("    AVISO recebido: {}".format(aviso))

        # Restaura o cenário: latência normal e espera os serviços voltarem
        for porta in lentos:
            definir_latencia(porta, latencia)
        for porta in desligados:
            print("    Aguardando a porta {} voltar ao ar...".format(porta))
            if not aguardar(porta, no_ar=True, limite_segundos=duracao + 30):
                print("    ERRO: o serviço da porta {} não voltou. Reinicie-o manualmente.".format(porta))
                sys.exit(1)
    salvar_csv("resultados_indisponibilidade.csv",
               ["cenario", "descricao", "modo", "repeticao", "tempo_ms", "num_servicos",
                "total_viagens", "avisos"], linhas)


# ============================================================================
# PROGRAMA PRINCIPAL
# ============================================================================
def ler_argumentos(argv):
    opcoes = {"experimento": "12", "latencia": None, "repeticoes": REPETICOES_PADRAO,
              "saida": ARQUIVO_PADRAO}
    i = 0
    while i < len(argv):
        arg = argv[i]
        try:
            if arg == "--latencia":
                opcoes["latencia"] = float(argv[i + 1].replace(",", "."))
                i += 2
            elif arg == "--repeticoes":
                opcoes["repeticoes"] = max(1, int(argv[i + 1]))
                i += 2
            elif arg == "--saida":
                opcoes["saida"] = argv[i + 1]
                i += 2
            elif arg == "--experimento":
                valor = argv[i + 1].lower()
                if valor not in ("1", "2", "3", "4", "5", "todos"):
                    raise ValueError(valor)
                opcoes["experimento"] = "12" if valor in ("1", "2") else valor
                i += 2
            elif arg in ("-h", "--ajuda", "--help"):
                print(__doc__)
                sys.exit(0)
            else:
                opcoes["latencia"] = float(arg.replace(",", "."))
                i += 1
        except (IndexError, ValueError):
            print("Argumento inválido: {}".format(arg))
            print("Use: python experimento.py [--experimento 1|2|3|4|5|todos] [--latencia X] "
                  "[--repeticoes N] [--saida arquivo.csv]")
            sys.exit(1)
    if opcoes["latencia"] is not None and not 0 <= opcoes["latencia"] < 2:
        print("A latência deve ficar entre 0 e 2 s (o timeout do agregador é 2 s).")
        sys.exit(1)
    return opcoes


def verificar_ambiente():
    """Confere se agregador e serviços estão no ar e guarda as latências originais."""
    originais = {}
    faltando = []
    for sid, nome, host, porta in SERVICOS:
        st = status_servico(host, porta)
        if st is None:
            faltando.append("Serviço {} - {} (porta {})".format(sid, nome, porta))
        else:
            originais[porta] = float(st.get("latencia_segundos", LATENCIA_PADRAO))
    try:
        socket.create_connection((HOST_AGREGADOR, PORTA_AGREGADOR), timeout=3).close()
    except OSError:
        faltando.append("Agregador (porta {})".format(PORTA_AGREGADOR))
    return originais, faltando


def executar(opcoes):
    originais, faltando = verificar_ambiente()
    if faltando:
        print("ERRO: os seguintes processos não estão rodando:")
        for item in faltando:
            print("  - " + item)
        print("Suba os 4 serviços e o agregador (start.bat / start.sh) e tente novamente.")
        sys.exit(1)

    exp = opcoes["experimento"]
    latencia = opcoes["latencia"]
    inicio = time.time()
    try:
        if exp in ("12", "todos"):
            lat12 = latencia if latencia is not None else (LATENCIA_PADRAO if exp == "todos" else None)
            if lat12 is not None:
                print("Configurando latência de {:.2f}s nos serviços:".format(lat12))
                definir_latencia_todos(lat12)
            else:
                print("Usando a latência atual de cada serviço (LATENCIA_SEGUNDOS).")
            experimentos_1_e_2(opcoes["repeticoes"], opcoes["saida"])
        if exp in ("3", "todos"):
            experimento_3(opcoes["repeticoes"])
        if exp in ("4", "todos"):
            lat = latencia if latencia is not None else LATENCIA_PADRAO
            definir_latencia_todos(lat, silencioso=True)
            print("  Latência dos serviços: {:.2f}s".format(lat))
            experimento_4(opcoes["repeticoes"])
        if exp in ("5", "todos"):
            experimento_5(opcoes["repeticoes"], latencia if latencia is not None else LATENCIA_PADRAO)
    except ConnectionRefusedError:
        print("ERRO: o agregador parou de responder em {}:{}.".format(HOST_AGREGADOR, PORTA_AGREGADOR))
        sys.exit(1)
    except (OSError, ValueError) as erro:
        print("ERRO durante o experimento: {}".format(erro))
        sys.exit(1)
    finally:
        for _, _, host, porta in SERVICOS:
            if porta in originais:
                try:
                    definir_latencia(porta, originais[porta])
                except (OSError, ValueError):
                    pass
        print()
        print("Latências originais dos serviços restauradas.")

    print("Duração total: {:.0f} s".format(time.time() - inicio))
    print("Para gerar os gráficos: python experimentos/gerar_graficos.py")


if __name__ == "__main__":
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    executar(ler_argumentos(sys.argv[1:]))
