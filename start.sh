#!/usr/bin/env bash
# ============================================================================
#  Comparador de Passagens Rodoviárias - inicialização (Linux / macOS)
#  Abre os 4 serviços e o agregador, cada um em seu próprio terminal.
#  Uso:  ./start.sh      (ou: bash start.sh)
# ============================================================================

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 1

# Descobre o interpretador Python disponível
if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "ERRO: Python não encontrado. Instale o Python 3."
    exit 1
fi

MODO_FUNDO=0
mkdir -p "$DIR/logs" 2>/dev/null

# Abre um processo em um novo terminal (ou em segundo plano, se não houver terminal gráfico)
abrir() {
    local titulo="$1"
    local arquivo="$2"
    local comando="cd \"$DIR\" && $PY \"$arquivo\"; echo; echo 'Processo encerrado. Pressione Enter para fechar.'; read"

    if command -v gnome-terminal >/dev/null 2>&1; then
        gnome-terminal --title="$titulo" -- bash -c "$comando" >/dev/null 2>&1
    elif command -v konsole >/dev/null 2>&1; then
        konsole --new-tab -p tabtitle="$titulo" -e bash -c "$comando" >/dev/null 2>&1 &
    elif command -v xfce4-terminal >/dev/null 2>&1; then
        xfce4-terminal --title="$titulo" -x bash -c "$comando" >/dev/null 2>&1 &
    elif command -v mate-terminal >/dev/null 2>&1; then
        mate-terminal --title="$titulo" -- bash -c "$comando" >/dev/null 2>&1 &
    elif command -v x-terminal-emulator >/dev/null 2>&1; then
        x-terminal-emulator -T "$titulo" -e bash -c "$comando" >/dev/null 2>&1 &
    elif command -v xterm >/dev/null 2>&1; then
        xterm -T "$titulo" -e bash -c "$comando" >/dev/null 2>&1 &
    elif [ "$(uname)" = "Darwin" ]; then
        osascript -e "tell application \"Terminal\" to do script \"cd '$DIR' && $PY '$arquivo'\"" >/dev/null
    else
        # Sem terminal gráfico: roda em segundo plano gravando o log
        local log="$DIR/logs/$(basename "$arquivo" .py).log"
        nohup $PY "$arquivo" > "$log" 2>&1 &
        echo "  [segundo plano] $titulo  (PID $!, log em logs/$(basename "$log"))"
        MODO_FUNDO=1
    fi
}

echo "=============================================================="
echo "  Iniciando o Comparador de Passagens Rodoviárias"
echo "=============================================================="

abrir "Servico 1 - Viacao Maraba (5001)"  "servicos/servico_1_viacao_maraba.py"
abrir "Servico 2 - TransBrasil (5002)"    "servicos/servico_2_transbrasil.py"
abrir "Servico 3 - Expresso Para (5003)"  "servicos/servico_3_expresso_para.py"
abrir "Servico 4 - Rodoviaria Sul (5004)" "servicos/servico_4_rodoviaria_sul.py"

echo "Aguardando os serviços subirem..."
sleep 2

abrir "Agregador (6000)" "agregador/agregador.py"

echo
echo "Serviços (5001-5004) e agregador (6000) iniciados."
echo "Agora, em outro terminal, rode o cliente:"
echo "    $PY cliente/cliente.py"
echo "Ou os experimentos:"
echo "    $PY experimentos/experimento.py --latencia 0.8"
if [ "$MODO_FUNDO" = "1" ]; then
    echo
    echo "Para encerrar os processos em segundo plano:"
    echo "    pkill -f 'servicos/servico_' ; pkill -f 'agregador/agregador.py'"
fi
