# -*- coding: utf-8 -*-
"""
Agregador - Comparador de Passagens Rodoviárias
===============================================

Componente central do sistema. Ele:
  1. É um servidor TCP (porta 6000) que atende VÁRIOS clientes ao mesmo tempo,
     cada cliente em uma thread separada;
  2. Para cada consulta, atua como cliente TCP dos 4 serviços de empresas,
     consultando-os em modo SEQUENCIAL ou CONCORRENTE (uma thread por serviço);
  3. Aplica timeout de 2 segundos por serviço: serviço desligado ou lento é
     ignorado e gera um aviso, sem travar a consulta;
  4. Consolida as viagens, ordena por preço, identifica a mais econômica,
     mede o tempo total e devolve tudo em JSON ao cliente.

Como executar:
    python agregador.py

Protocolo: mensagens JSON em UTF-8, uma por linha (terminadas em "\\n").
"""

import socket
import threading
import json
import time
import sys

# ============================================================================
# CONFIGURAÇÕES
# ============================================================================
HOST = "0.0.0.0"
PORTA = 6000
TIMEOUT_SERVICO_SEGUNDOS = 2.0      # tempo máximo de espera por serviço
TIMEOUT_CLIENTE_OCIOSO = 300        # fecha conexões de clientes inativos (s)
TAMANHO_BUFFER = 4096
TAMANHO_MAXIMO_MENSAGEM = 1024 * 1024
MODOS_VALIDOS = ("sequencial", "concorrente")

# Serviços de empresas consultados pelo agregador
SERVICOS = [
    {"id": 1, "nome": "Viação Marabá",  "host": "127.0.0.1", "porta": 5001},
    {"id": 2, "nome": "TransBrasil",    "host": "127.0.0.1", "porta": 5002},
    {"id": 3, "nome": "Expresso Pará",  "host": "127.0.0.1", "porta": 5003},
    {"id": 4, "nome": "Rodoviária Sul", "host": "127.0.0.1", "porta": 5004},
]

trava_terminal = threading.Lock()
trava_contador = threading.Lock()
clientes_ativos = 0


# ============================================================================
# FUNÇÕES AUXILIARES
# ============================================================================
def log(mensagem):
    """Imprime com horário e nome da thread, sem misturar linhas."""
    with trava_terminal:
        print("[{}] [{}] {}".format(time.strftime("%H:%M:%S"),
                                   threading.current_thread().name, mensagem), flush=True)


def enviar_json(conexao, objeto):
    """Serializa o objeto em JSON e envia terminado por '\\n'."""
    conexao.sendall((json.dumps(objeto, ensure_ascii=False) + "\n").encode("utf-8"))


def receber_linha(conexao, prazo=None):
    """
    Lê do socket até encontrar '\\n'. Se 'prazo' (instante em perf_counter) for
    informado, garante que a leitura inteira não ultrapasse esse limite.
    Retorna None se a conexão foi fechada sem dados.
    """
    dados = b""
    while b"\n" not in dados:
        if prazo is not None:
            restante = prazo - time.perf_counter()
            if restante <= 0:
                raise socket.timeout("prazo esgotado")
            conexao.settimeout(restante)
        bloco = conexao.recv(TAMANHO_BUFFER)
        if not bloco:
            break
        dados += bloco
        if len(dados) > TAMANHO_MAXIMO_MENSAGEM:
            raise ValueError("mensagem muito grande")
    if not dados.strip():
        return None
    return dados.split(b"\n", 1)[0].decode("utf-8", errors="replace").strip()


# ============================================================================
# COMUNICAÇÃO COM OS SERVIÇOS
# ============================================================================
def consultar_servico(servico, consulta):
    """
    Abre uma conexão TCP com UM serviço, envia a consulta e lê a resposta.
    Nunca lança exceção: devolve um dicionário com 'ok' True/False.
    """
    inicio = time.perf_counter()
    prazo = inicio + TIMEOUT_SERVICO_SEGUNDOS
    resultado = {"servico": servico, "ok": False, "resposta": None, "erro": None, "tempo_ms": 0.0}
    try:
        with socket.create_connection((servico["host"], servico["porta"]),
                                      timeout=TIMEOUT_SERVICO_SEGUNDOS) as conexao:
            enviar_json(conexao, consulta)
            texto = receber_linha(conexao, prazo)
        if texto is None:
            raise ConnectionError("o serviço fechou a conexão sem responder")
        resposta = json.loads(texto)
        if not isinstance(resposta, dict):
            raise ValueError("resposta não é um objeto JSON")
        resultado["resposta"] = resposta
        resultado["ok"] = True
    except socket.timeout:
        resultado["erro"] = "tempo limite de {:.0f} s excedido".format(TIMEOUT_SERVICO_SEGUNDOS)
    except ConnectionRefusedError:
        resultado["erro"] = "conexão recusada (serviço desligado)"
    except ValueError as erro:
        resultado["erro"] = "resposta inválida ({})".format(erro)
    except (ConnectionError, OSError) as erro:
        resultado["erro"] = "falha de comunicação ({})".format(erro)
    resultado["tempo_ms"] = round((time.perf_counter() - inicio) * 1000, 1)
    return resultado


def consultar_sequencial(consulta):
    """MODO SEQUENCIAL: um serviço de cada vez, esperando cada resposta."""
    resultados = []
    for servico in SERVICOS:
        resultados.append(consultar_servico(servico, consulta))
    return resultados


def consultar_concorrente(consulta):
    """MODO CONCORRENTE: uma thread por serviço, todas disparadas juntas + join()."""
    resultados = [None] * len(SERVICOS)

    def tarefa(indice, servico):
        resultados[indice] = consultar_servico(servico, consulta)

    threads = []
    for indice, servico in enumerate(SERVICOS):
        t = threading.Thread(target=tarefa, args=(indice, servico),
                             name="Servico-{}".format(servico["id"]), daemon=True)
        threads.append(t)
        t.start()

    for t in threads:
        t.join(TIMEOUT_SERVICO_SEGUNDOS + 1.0)   # margem de segurança

    # Se alguma thread não terminou a tempo (não deveria acontecer), registra falha
    for indice, servico in enumerate(SERVICOS):
        if resultados[indice] is None:
            resultados[indice] = {"servico": servico, "ok": False, "resposta": None,
                                  "erro": "tempo limite excedido", "tempo_ms": 0.0}
    return resultados


# ============================================================================
# CONSOLIDAÇÃO
# ============================================================================
def viagem_valida(viagem):
    """Confere se a viagem recebida tem os campos e tipos esperados."""
    if not isinstance(viagem, dict):
        return False
    try:
        float(viagem["preco"])
        int(viagem["duracao_min"])
        return isinstance(viagem["saida"], str) and isinstance(viagem["chegada"], str)
    except (KeyError, TypeError, ValueError):
        return False


def consolidar(consulta, modo, resultados, inicio):
    """Junta as viagens de todos os serviços, ordena e monta a resposta final."""
    viagens = []
    avisos = []
    detalhes = []
    responderam = 0

    for r in resultados:
        servico = r["servico"]
        detalhe = {"id": servico["id"], "empresa": servico["nome"], "tempo_ms": r["tempo_ms"]}

        if not r["ok"]:
            detalhe["status"] = "indisponivel"
            avisos.append("Serviço {} ({}) indisponível: {}".format(
                servico["id"], servico["nome"], r["erro"]))
            detalhes.append(detalhe)
            continue

        resposta = r["resposta"]
        status = resposta.get("status", "erro")
        detalhe["status"] = status
        responderam += 1

        if status == "erro":
            avisos.append("Serviço {} ({}) retornou erro: {}".format(
                servico["id"], servico["nome"], resposta.get("mensagem", "sem detalhes")))
        else:
            empresa = resposta.get("fonte", servico["nome"])
            for v in resposta.get("viagens", []):
                if viagem_valida(v):
                    viagens.append({
                        "empresa": empresa,
                        "saida": v["saida"],
                        "chegada": v["chegada"],
                        "duracao_min": int(v["duracao_min"]),
                        "preco": round(float(v["preco"]), 2),
                        "assentos": v.get("assentos"),
                    })
        detalhes.append(detalhe)

    # Ordena por preço crescente (desempate pelo horário de saída)
    viagens.sort(key=lambda v: (v["preco"], v["saida"]))

    if responderam == 0:
        status_geral = "falha"
        avisos.append("Nenhum serviço respondeu à consulta")
    elif viagens:
        status_geral = "sucesso"
    else:
        status_geral = "sem_resultados"

    return {
        "status": status_geral,
        "origem": consulta["origem"],
        "destino": consulta["destino"],
        "data": consulta["data"],
        "modo_usado": modo,
        "viagens": viagens,
        "mais_economica": viagens[0] if viagens else None,
        "total_viagens": len(viagens),
        "servicos_consultados": len(SERVICOS),
        "servicos_responderam": responderam,
        "detalhes_servicos": detalhes,
        "avisos": avisos,
        "tempo_total_ms": round((time.perf_counter() - inicio) * 1000, 1),
    }


def resposta_erro(mensagem):
    return {"status": "erro", "mensagem": mensagem, "viagens": [], "avisos": [mensagem]}


def processar_requisicao(texto, endereco_txt):
    """Valida a requisição do cliente, consulta os serviços e consolida."""
    inicio = time.perf_counter()
    try:
        requisicao = json.loads(texto)
    except ValueError:
        return resposta_erro("JSON inválido")
    if not isinstance(requisicao, dict):
        return resposta_erro("A mensagem deve ser um objeto JSON")
    if requisicao.get("operacao") != "consultar":
        return resposta_erro("Operação desconhecida: {}".format(requisicao.get("operacao")))

    origem = str(requisicao.get("origem", "")).strip()
    destino = str(requisicao.get("destino", "")).strip()
    data = str(requisicao.get("data", "")).strip()
    modo = str(requisicao.get("modo", "concorrente")).strip().lower()

    if not origem or not destino or not data:
        return resposta_erro("Os campos origem, destino e data são obrigatórios")
    if modo not in MODOS_VALIDOS:
        return resposta_erro("Modo inválido '{}'. Use 'sequencial' ou 'concorrente'".format(modo))

    # Mensagem enviada a cada serviço (formato definido no protocolo)
    consulta = {"operacao": "consultar", "origem": origem, "destino": destino, "data": data}

    log("Consulta de {}: {} -> {} em {} | modo={}".format(endereco_txt, origem, destino, data, modo))
    if modo == "sequencial":
        resultados = consultar_sequencial(consulta)
    else:
        resultados = consultar_concorrente(consulta)

    resposta = consolidar(consulta, modo, resultados, inicio)

    for r in resultados:
        situacao = "OK" if r["ok"] else "FALHA ({})".format(r["erro"])
        log("   - Serviço {} {:<15} {:>8.1f} ms  {}".format(
            r["servico"]["id"], r["servico"]["nome"], r["tempo_ms"], situacao))
    log("Modo: {} | Tempo total: {:.1f} ms | Serviços que responderam: {}/{} | Viagens: {}".format(
        modo, resposta["tempo_total_ms"], resposta["servicos_responderam"],
        resposta["servicos_consultados"], resposta["total_viagens"]))
    return resposta


# ============================================================================
# ATENDIMENTO DOS CLIENTES (uma thread por cliente)
# ============================================================================
def atender_cliente(conexao, endereco):
    """Atende um cliente: processa requisições (uma por linha) até ele desconectar."""
    global clientes_ativos
    endereco_txt = "{}:{}".format(endereco[0], endereco[1])
    with trava_contador:
        clientes_ativos += 1
        ativos = clientes_ativos
    log("Cliente conectado: {} (clientes ativos: {})".format(endereco_txt, ativos))

    try:
        while True:
            conexao.settimeout(TIMEOUT_CLIENTE_OCIOSO)
            texto = receber_linha(conexao)
            if texto is None:
                break   # cliente encerrou a conexão
            resposta = processar_requisicao(texto, endereco_txt)
            enviar_json(conexao, resposta)
    except socket.timeout:
        log("Cliente {} inativo por muito tempo; conexão encerrada".format(endereco_txt))
    except (ConnectionError, OSError) as erro:
        log("Cliente {} desconectou inesperadamente: {}".format(endereco_txt, erro))
    except ValueError as erro:
        log("Mensagem rejeitada de {}: {}".format(endereco_txt, erro))
    except Exception as erro:   # proteção final: nunca derrubar o agregador
        log("Erro inesperado ao atender {}: {}".format(endereco_txt, erro))
    finally:
        try:
            conexao.close()
        except OSError:
            pass
        with trava_contador:
            clientes_ativos -= 1
            ativos = clientes_ativos
        log("Cliente desconectado: {} (clientes ativos: {})".format(endereco_txt, ativos))


def iniciar_servidor():
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if not sys.platform.startswith("win"):
        servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        servidor.bind((HOST, PORTA))
    except OSError as erro:
        print("ERRO: não foi possível usar a porta {} ({}).".format(PORTA, erro))
        print("Verifique se o agregador já não está rodando em outro terminal.")
        sys.exit(1)
    servidor.listen(50)
    servidor.settimeout(1.0)   # permite Ctrl+C também no Windows

    print("=" * 70)
    print("  AGREGADOR - COMPARADOR DE PASSAGENS RODOVIÁRIAS")
    print("  Porta TCP: {} | Timeout por serviço: {:.0f} s".format(PORTA, TIMEOUT_SERVICO_SEGUNDOS))
    print("  Serviços configurados:")
    for s in SERVICOS:
        print("    {} - {:<15} {}:{}".format(s["id"], s["nome"], s["host"], s["porta"]))
    print("  Aguardando clientes... (Ctrl+C para encerrar)")
    print("=" * 70, flush=True)

    contador = 0
    try:
        while True:
            try:
                conexao, endereco = servidor.accept()
            except socket.timeout:
                continue
            except OSError as erro:
                log("Falha ao aceitar conexão: {}".format(erro))
                continue
            contador += 1
            threading.Thread(target=atender_cliente, args=(conexao, endereco),
                             name="Cliente-{}".format(contador), daemon=True).start()
    except KeyboardInterrupt:
        print("\nEncerrando o agregador...")
    finally:
        servidor.close()


def configurar_terminal():
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


if __name__ == "__main__":
    configurar_terminal()
    iniciar_servidor()
