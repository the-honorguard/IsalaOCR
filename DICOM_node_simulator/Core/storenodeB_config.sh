#!/bin/bash

BASE_DIR=$(dirname "$(dirname "$(realpath "$0")")")
GRANDPARENT_DIR=$(dirname "$(dirname "$BASE_DIR")")
VENV_PYTHON="$GRANDPARENT_DIR/.venv/bin/python"

if [ ! -f "$VENV_PYTHON" ]; then
    echo "[$(date)] Virtuele omgeving niet gevonden: $VENV_PYTHON"
    exit 1
fi

echo "[$(date)] Gebruikte Python-interpreter: $VENV_PYTHON"

CONFIG_FILE="$GRANDPARENT_DIR/IsalaOCR/config/mainconfig.ini"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "[$(date)] Configuratiebestand niet gevonden: $CONFIG_FILE"
    exit 1
else
    echo "[$(date)] Configuratiebestand geladen: $CONFIG_FILE"
fi

get_config_value() {
    $VENV_PYTHON -c "import configparser; import sys; c=configparser.ConfigParser(); c.read('$CONFIG_FILE'); print(c.get('$1', '$2', fallback=''))" 2>/dev/null
}

WATCHDIR=$(get_config_value paths receive_folder)
QUEUE_DIR=$(get_config_value paths queue_folder)
LOGDIR=$(get_config_value paths log_folder)
PROCESS_SCRIPT="$BASE_DIR/Core/processing_script.py"
LOGFILE="$LOGDIR/storenodeB.log"

AETITLE_CALLING="ZendnodeA"
AETITLE_CALLED="StorenodeB"
HOST="127.0.0.1"
PORT="4242"

if [ ! -d "$LOGDIR" ]; then
    mkdir -p "$LOGDIR"
    echo "[$(date)] Logmap aangemaakt: $LOGDIR"
fi
> "$LOGFILE"

echo "[$(date)] Controleer mappen..." | tee -a "$LOGFILE"
mkdir -p "$WATCHDIR"
mkdir -p "$QUEUE_DIR"
echo "[$(date)] Ontvangstmappen: $WATCHDIR" | tee -a "$LOGFILE"
echo "[$(date)] Wachtrijmap: $QUEUE_DIR" | tee -a "$LOGFILE"

if [ ! -f "$PROCESS_SCRIPT" ]; then
    echo "[$(date)] Verwerkingsscript niet gevonden: $PROCESS_SCRIPT" | tee -a "$LOGFILE"
    exit 1
else
    echo "[$(date)] Verwerkingsscript gevonden: $PROCESS_SCRIPT" | tee -a "$LOGFILE"
fi

echo "[$(date)] Start storescp..." | tee -a "$LOGFILE"
nohup storescp --fork --aetitle "$AETITLE_CALLED" --output-directory "$WATCHDIR" "$PORT" >> "$LOGFILE" 2>&1 &
STORESCP_PID=$!
sleep 2

if ps -p $STORESCP_PID > /dev/null; then
    echo "[$(date)] storescp draait correct (PID: $STORESCP_PID)" | tee -a "$LOGFILE"
else
    echo "[$(date)] Fout bij starten storescp" | tee -a "$LOGFILE"
    tail -n 20 "$LOGFILE"
    exit 1
fi

echo "[$(date)] Start monitoring en verwerking..." | tee -a "$LOGFILE"
while true; do
    if [ "$(ls -A "$WATCHDIR" 2>/dev/null)" ]; then
        echo "[$(date)] Bestanden gedetecteerd in $WATCHDIR..." | tee -a "$LOGFILE"
        for file in "$WATCHDIR"/*; do
            if [[ -f "$file" ]]; then
                echo "[$(date)] Nieuw bestand: $file" | tee -a "$LOGFILE"
                echo "[$(date)] Grootte: $(stat -c%s "$file") bytes" | tee -a "$LOGFILE"
                echo "[$(date)] Eigenaar: $(stat -c%U "$file")" | tee -a "$LOGFILE"
                echo "[$(date)] Type: $(file "$file")" | tee -a "$LOGFILE"

                echo "[$(date)] Start verwerking met $VENV_PYTHON $PROCESS_SCRIPT $file" | tee -a "$LOGFILE"
                $VENV_PYTHON "$PROCESS_SCRIPT" "$file" >> "$LOGFILE" 2>&1
                if [ $? -eq 0 ]; then
                    echo "[$(date)] Verwerking succesvol: $file" | tee -a "$LOGFILE"
                    rm -f "$file"
                else
                    echo "[$(date)] Fout: bestand naar wachtrij verplaatst: $file" | tee -a "$LOGFILE"
                    mv "$file" "$QUEUE_DIR/"
                fi
            fi
        done
    elif [ "$(ls -A "$QUEUE_DIR" 2>/dev/null)" ]; then
        echo "[$(date)] Wachtrij bevat bestanden, verplaats naar $WATCHDIR..." | tee -a "$LOGFILE"
        mv "$QUEUE_DIR"/* "$WATCHDIR/"
    fi
    sleep 5
done
