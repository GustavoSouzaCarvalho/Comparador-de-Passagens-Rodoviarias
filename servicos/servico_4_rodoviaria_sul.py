# -*- coding: utf-8 -*-
"""
Serviço 4 - Rodoviária Sul
==========================

Serviço independente (processo próprio) que simula o sistema de vendas de
passagens de uma empresa de ônibus. Ele abre um servidor TCP, recebe
consultas em JSON (uma mensagem por linha) e responde com as viagens
disponíveis para a rota e a data informadas.

Como executar:
    python servico_4_rodoviaria_sul.py          -> usa LATENCIA_SEGUNDOS
    python servico_4_rodoviaria_sul.py 0.0      -> latência personalizada (segundos)

Operações aceitas (protocolo JSON terminado em "\\n"):
    {"operacao": "consultar", "origem": "...", "destino": "...", "data": "AAAA-MM-DD"}
    {"operacao": "configurar_latencia", "latencia_segundos": 0.8}   (experimentos)
    {"operacao": "status"}                                           (experimentos)
    {"operacao": "simular_queda", "duracao_segundos": 20}            (experimento 5)

A operação "simular_queda" FECHA de verdade o socket servidor pelo tempo pedido
(novas conexões recebem "conexão recusada", como em um serviço desligado) e
depois reabre a porta automaticamente.
"""

import socket
import threading
import json
import time
import sys

# ============================================================================
# CONFIGURAÇÕES GERAIS
# ============================================================================
HOST = "0.0.0.0"            # escuta em todas as interfaces
LATENCIA_SEGUNDOS = 0.8     # latência simulada (altere aqui para os experimentos)
TAMANHO_BUFFER = 4096
TAMANHO_MAXIMO_MENSAGEM = 1024 * 1024   # 1 MB: protege contra mensagens gigantes
TIMEOUT_CONEXAO_SEGUNDOS = 10           # tempo máximo esperando o cliente enviar dados

# >>> DADOS DA EMPRESA (cada serviço tem os seus)
PORTA = 5004
NOME_EMPRESA = "Rodoviária Sul"

# Rotas conhecidas: (origem_normalizada, destino_normalizado) -> lista de viagens
# Cada viagem: (horário de saída, duração em minutos, preço em R$, assentos livres)
ROTAS = {
    ("maraba", "belem"): [
        ("07:30", 540, 165.00, 5),
        ("14:00", 515, 182.75, 16),
        ("22:00", 535, 199.00, 22),
    ],
    ("maraba", "parauapebas"): [
        ("09:00", 165, 45.90, 33),
        ("16:00", 160, 48.50, 17),
    ],
    ("belem", "maraba"): [
        ("08:30", 545, 180.00, 26),
        ("19:30", 540, 166.70, 12),
    ],
}

# Parâmetros usados para gerar viagens de rotas não cadastradas
HORARIOS_GENERICOS = ["08:00", "18:30", "23:30"]
FATOR_PRECO_GENERICO = 0.95
# <<< FIM DOS DADOS DA EMPRESA

# Trava para que as mensagens de threads diferentes não se misturem no terminal
trava_terminal = threading.Lock()

# Instante (time.time) até o qual o serviço deve ficar fora do ar (experimento 5)
queda_ate = 0.0

# Tabela para remover acentos sem bibliotecas externas
_ACENTUADOS = "áàâãäéèêëíìîïóòôõöúùûüçñÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ"
_SEM_ACENTO = "aaaaaeeeeiiiiooooouuuucnAAAAAEEEEIIIIOOOOOUUUUCN"
_TABELA_ACENTOS = str.maketrans(_ACENTUADOS, _SEM_ACENTO)


# ============================================================================
# FUNÇÕES AUXILIARES
# ============================================================================
def log(mensagem):
    """Imprime uma mensagem com horário, de forma segura entre threads."""
    with trava_terminal:
        print("[{}] {}".format(time.strftime("%H:%M:%S"), mensagem), flush=True)


def normalizar(texto):
    """Normaliza nomes de cidades: minúsculas, sem acentos e sem espaços extras."""
    return " ".join(str(texto).translate(_TABELA_ACENTOS).lower().split())


def data_valida(texto):
    """Verifica se a data está no formato AAAA-MM-DD e é uma data real."""
    try:
        time.strptime(str(texto), "%Y-%m-%d")
        return True
    except ValueError:
        return False


def somar_minutos(horario, minutos):
    """Soma minutos a um horário 'HH:MM' e devolve o horário de chegada (24h)."""
    horas, mins = horario.split(":")
    total = (int(horas) * 60 + int(mins) + minutos) % (24 * 60)
    return "{:02d}:{:02d}".format(total // 60, total % 60)


def gerar_viagens_genericas(origem, destino):
    """
    Gera viagens para rotas não cadastradas. Os valores são derivados do nome
    da rota (sempre iguais para a mesma rota) e do fator de preço da empresa.
    """
    semente = sum(ord(c) for c in normalizar(origem) + "->" + normalizar(destino))
    duracao_base = 120 + (semente * 7) % 480          # entre 2h e 10h
    viagens = []
    for indice, saida in enumerate(HORARIOS_GENERICOS):
        duracao = duracao_base + indice * 10
        preco = round((duracao * 0.33 + 15 + indice * 7.5) * FATOR_PRECO_GENERICO, 2)
        assentos = (semente + indice * 11 + PORTA) % 35 + 3
        viagens.append((saida, duracao, preco, assentos))
    return viagens


def montar_viagens(origem, destino, data):
    """Retorna a lista de viagens (dicionários) para a rota e data pedidas."""
    chave = (normalizar(origem), normalizar(destino))
    dados = ROTAS.get(chave)
    if dados is None:
        dados = gerar_viagens_genericas(origem, destino)

    # Os assentos variam um pouco conforme o dia, para parecer mais real
    dia = time.strptime(data, "%Y-%m-%d").tm_mday
    viagens = []
    for saida, duracao, preco, assentos in dados:
        viagens.append({
            "saida": saida,
            "chegada": somar_minutos(saida, duracao),
            "duracao_min": duracao,
            "preco": preco,
            "assentos": max(0, assentos - (dia % 4)),
        })
    return viagens


def resposta_erro(mensagem, requisicao=None, inicio=None):
    """Monta uma resposta de erro padronizada."""
    requisicao = requisicao if isinstance(requisicao, dict) else {}
    tempo_ms = round((time.perf_counter() - inicio) * 1000, 1) if inicio else 0
    return {
        "fonte": NOME_EMPRESA,
        "origem": requisicao.get("origem", ""),
        "destino": requisicao.get("destino", ""),
        "data": requisicao.get("data", ""),
        "viagens": [],
        "status": "erro",
        "mensagem": mensagem,
        "tempo_resposta_ms": tempo_ms,
    }


# ============================================================================
# PROCESSAMENTO DAS OPERAÇÕES
# ============================================================================
def operacao_consultar(requisicao, inicio):
    """Valida a consulta, simula a latência e devolve as viagens encontradas."""
    origem = str(requisicao.get("origem", "")).strip()
    destino = str(requisicao.get("destino", "")).strip()
    data = str(requisicao.get("data", "")).strip()

    if not origem or not destino:
        return resposta_erro("Origem e destino são obrigatórios", requisicao, inicio)
    if normalizar(origem) == normalizar(destino):
        return resposta_erro("Origem e destino não podem ser iguais", requisicao, inicio)
    if not data_valida(data):
        return resposta_erro("Data inválida. Use o formato AAAA-MM-DD", requisicao, inicio)

    # Simula o tempo de processamento/rede de um sistema real
    if LATENCIA_SEGUNDOS > 0:
        time.sleep(LATENCIA_SEGUNDOS)

    viagens = montar_viagens(origem, destino, data)
    return {
        "fonte": NOME_EMPRESA,
        "origem": origem,
        "destino": destino,
        "data": data,
        "viagens": viagens,
        "status": "sucesso" if viagens else "sem_resultados",
        "tempo_resposta_ms": round((time.perf_counter() - inicio) * 1000, 1),
    }


def operacao_configurar_latencia(requisicao, inicio):
    """Altera a latência simulada em tempo de execução (usado pelos experimentos)."""
    global LATENCIA_SEGUNDOS
    try:
        nova = float(requisicao.get("latencia_segundos"))
    except (TypeError, ValueError):
        return resposta_erro("Campo 'latencia_segundos' inválido", requisicao, inicio)
    if nova < 0 or nova > 30:
        return resposta_erro("A latência deve estar entre 0 e 30 segundos", requisicao, inicio)

    anterior = LATENCIA_SEGUNDOS
    LATENCIA_SEGUNDOS = nova
    log("Latência alterada: {:.2f}s -> {:.2f}s".format(anterior, nova))
    return {
        "fonte": NOME_EMPRESA,
        "status": "sucesso",
        "latencia_anterior": anterior,
        "latencia_segundos": nova,
    }


def operacao_status(requisicao, inicio):
    """Informa que o serviço está no ar e qual a latência atual."""
    return {
        "fonte": NOME_EMPRESA,
        "status": "sucesso",
        "porta": PORTA,
        "latencia_segundos": LATENCIA_SEGUNDOS,
    }


def operacao_simular_queda(requisicao, inicio):
    """Agenda o fechamento do socket servidor por alguns segundos (experimento 5)."""
    global queda_ate
    try:
        duracao = float(requisicao.get("duracao_segundos"))
    except (TypeError, ValueError):
        return resposta_erro("Campo 'duracao_segundos' inválido", requisicao, inicio)
    if duracao <= 0 or duracao > 600:
        return resposta_erro("A duração deve estar entre 0 e 600 segundos", requisicao, inicio)

    queda_ate = time.time() + duracao
    log("QUEDA SIMULADA solicitada: o serviço ficará fora do ar por {:.1f}s".format(duracao))
    return {
        "fonte": NOME_EMPRESA,
        "status": "sucesso",
        "mensagem": "Serviço ficará fora do ar por {:.1f}s".format(duracao),
        "duracao_segundos": duracao,
    }


def processar_mensagem(texto):
    """Interpreta o JSON recebido e encaminha para a operação correta."""
    inicio = time.perf_counter()
    try:
        requisicao = json.loads(texto)
    except ValueError:
        return resposta_erro("JSON inválido", None, inicio)

    if not isinstance(requisicao, dict):
        return resposta_erro("A mensagem deve ser um objeto JSON", None, inicio)

    operacao = requisicao.get("operacao")
    if operacao == "consultar":
        return operacao_consultar(requisicao, inicio)
    if operacao == "configurar_latencia":
        return operacao_configurar_latencia(requisicao, inicio)
    if operacao == "status":
        return operacao_status(requisicao, inicio)
    if operacao == "simular_queda":
        return operacao_simular_queda(requisicao, inicio)
    return resposta_erro("Operação desconhecida: {}".format(operacao), requisicao, inicio)


# ============================================================================
# COMUNICAÇÃO TCP
# ============================================================================
def receber_linha(conexao):
    """Lê bytes do socket até encontrar '\\n' (fim da mensagem) ou o fechamento."""
    dados = b""
    while b"\n" not in dados:
        bloco = conexao.recv(TAMANHO_BUFFER)
        if not bloco:
            break
        dados += bloco
        if len(dados) > TAMANHO_MAXIMO_MENSAGEM:
            raise ValueError("mensagem muito grande")
    return dados.split(b"\n", 1)[0].decode("utf-8", errors="replace").strip()


def atender_conexao(conexao, endereco):
    """Atende uma conexão: lê uma requisição, responde e fecha."""
    origem_txt = "{}:{}".format(endereco[0], endereco[1])
    try:
        conexao.settimeout(TIMEOUT_CONEXAO_SEGUNDOS)
        texto = receber_linha(conexao)
        if not texto:
            log("Conexão de {} encerrada sem dados".format(origem_txt))
            return

        log("Requisição recebida de {}: {}".format(origem_txt, texto))
        resposta = processar_mensagem(texto)
        conexao.sendall((json.dumps(resposta, ensure_ascii=False) + "\n").encode("utf-8"))

        if resposta.get("status") == "erro":
            log("Respondido com ERRO: {}".format(resposta.get("mensagem")))
        elif "viagens" in resposta:
            log("Respondido: status={} | {} viagem(ns) | {} ms".format(
                resposta["status"], len(resposta["viagens"]), resposta["tempo_resposta_ms"]))
        else:
            log("Respondido: status={}".format(resposta.get("status")))
    except socket.timeout:
        log("Tempo esgotado aguardando dados de {}".format(origem_txt))
    except (ConnectionError, OSError) as erro:
        log("Conexão com {} perdida: {}".format(origem_txt, erro))
    except ValueError as erro:
        log("Mensagem rejeitada de {}: {}".format(origem_txt, erro))
    finally:
        try:
            conexao.close()
        except OSError:
            pass


def criar_socket_servidor():
    """Cria o socket servidor TCP, faz bind na porta e começa a escutar."""
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if not sys.platform.startswith("win"):
        # Permite reabrir a porta logo após fechá-la (Linux/macOS)
        servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        servidor.bind((HOST, PORTA))
    except OSError:
        servidor.close()
        raise
    servidor.listen(50)
    # Timeout no accept permite encerrar com Ctrl+C também no Windows
    servidor.settimeout(1.0)
    return servidor


def ficar_fora_do_ar(servidor):
    """Fecha a porta até 'queda_ate' e depois a reabre (queda simulada)."""
    servidor.close()
    log("SERVIÇO FORA DO AR: porta {} fechada (novas conexões serão recusadas)".format(PORTA))
    while time.time() < queda_ate:
        time.sleep(0.2)
    for _ in range(60):   # tenta reabrir a porta por até ~30 s
        try:
            novo = criar_socket_servidor()
            log("SERVIÇO DE VOLTA AO AR na porta {}".format(PORTA))
            return novo
        except OSError:
            time.sleep(0.5)
    log("ERRO: não foi possível reabrir a porta {}. Encerrando.".format(PORTA))
    sys.exit(1)


def iniciar_servidor():
    """Cria o socket servidor e fica em loop aceitando conexões."""
    try:
        servidor = criar_socket_servidor()
    except OSError as erro:
        print("ERRO: não foi possível usar a porta {} ({}).".format(PORTA, erro))
        print("Verifique se o serviço já não está rodando em outro terminal.")
        sys.exit(1)

    print("=" * 64)
    print("  SERVIÇO: {}".format(NOME_EMPRESA))
    print("  Porta TCP: {} | Latência simulada: {:.2f}s".format(PORTA, LATENCIA_SEGUNDOS))
    print("  Aguardando conexões... (Ctrl+C para encerrar)")
    print("=" * 64, flush=True)

    try:
        while True:
            if queda_ate > time.time():
                servidor = ficar_fora_do_ar(servidor)
                continue
            try:
                conexao, endereco = servidor.accept()
            except socket.timeout:
                continue
            except OSError as erro:
                log("Falha ao aceitar conexão: {}".format(erro))
                continue
            # Cada conexão é atendida em sua própria thread
            threading.Thread(target=atender_conexao, args=(conexao, endereco), daemon=True).start()
    except KeyboardInterrupt:
        print("\nEncerrando o serviço {}...".format(NOME_EMPRESA))
    finally:
        servidor.close()


def configurar_terminal():
    """Garante saída em UTF-8 (acentos) mesmo em terminais antigos do Windows."""
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


if __name__ == "__main__":
    configurar_terminal()
    if len(sys.argv) > 1:
        try:
            LATENCIA_SEGUNDOS = max(0.0, float(sys.argv[1].replace(",", ".")))
        except ValueError:
            print("Latência inválida '{}'. Usando {:.2f}s.".format(sys.argv[1], LATENCIA_SEGUNDOS))
    iniciar_servidor()
