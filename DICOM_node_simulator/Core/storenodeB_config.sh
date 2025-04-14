#!/bin/bash

# Dynamisch de hoofdmap bepalen
BASE_DIR=$(dirname "$(dirname "$(realpath "$0")")")  # Bepaal de hoofdmap IsalaOCR
VENV_PYTHON="$BASE_DIR/venv/bin/python"  # Verwijs naar de Python-interpreter in de virtuele omgeving

# Laad configuratie uit mainconfig.ini
CONFIG_FILE="$BASE_DIR/config/mainconfig.ini"  # Correct pad naar de configuratie
if [ ! -f "$CONFIG_FILE" ]; then
    echo "[$(date)] Configuratiebestand niet gevonden: $CONFIG_FILE"
    exit 1
fi

# Functie om een configuratiewaarde op te halen
get_config_value() {
    local section=$1
    local key=$2
    awk -F '=' -v section="[$section]" -v key="$key" '
        $0 == section { in_section = 1; next }
        /^\[.*\]/ { in_section = 0 }
        in_section && $1 == key { gsub(/^[ \t]+|[ \t]+$/, "", $2); print $2; exit }
    ' "$CONFIG_FILE"
}

# Haal paden op uit de configuratie
WATCHDIR=$(get_config_value "paths" "dcm_in_folder")
QUEUE_DIR=$(get_config_value "paths" "queue_folder")
LOGDIR=$(get_config_value "paths" "log_folder")
PROCESS_SCRIPT=$(get_config_value "paths" "modules_folder")/processing_script.py

LOGFILE="$LOGDIR/storenodeB.log"

# Zet paden om naar absolute paden
WATCHDIR="$BASE_DIR/$WATCHDIR"
QUEUE_DIR="$BASE_DIR/$QUEUE_DIR"
LOGDIR="$BASE_DIR/$LOGDIR"
PROCESS_SCRIPT="$BASE_DIR/$PROCESS_SCRIPT"

# Controleer of de logmap bestaat, maak deze aan als dat niet zo is
if [ ! -d "$LOGDIR" ]; then
    mkdir -p "$LOGDIR"
    echo "[$(date)] Logmap aangemaakt: $LOGDIR"
fi

# Maak het logbestand aan of leeg het als het al bestaat
> "$LOGFILE"

# Maak de ontvangstmappen en wachtrijmap als ze nog niet bestaan
echo "[$(date)] Controleer of de ontvangstmappen en wachtrijmap bestaan..." | tee -a "$LOGFILE"
mkdir -p "$WATCHDIR"
mkdir -p "$QUEUE_DIR"
echo "[$(date)] Ontvangstmappen gecontroleerd: $WATCHDIR" | tee -a "$LOGFILE"
echo "[$(date)] Wachtrijmap gecontroleerd: $QUEUE_DIR" | tee -a "$LOGFILE"

# Controleer of het verwerkingsscript bestaat
if [ ! -f "$PROCESS_SCRIPT" ]; then
    echo "[$(date)] Verwerkingsscript niet gevonden: $PROCESS_SCRIPT" | tee -a "$LOGFILE"
    exit 1
else
    echo "[$(date)] Verwerkingsscript gevonden: $PROCESS_SCRIPT" | tee -a "$LOGFILE"
fi

# Start de DICOM-server met storescp
echo "[$(date)] Start de DICOM-server met storescp..." | tee -a "$LOGFILE"
nohup storescp --aetitle "StorenodeB" --output-directory "$WATCHDIR" 4242 >> "$LOGFILE" 2>&1 &
STORESCP_PID=$!
echo "[$(date)] DICOM-server gestart met PID: $STORESCP_PID" | tee -a "$LOGFILE"

# Controleer of storescp correct is gestart
sleep 2
if ps -p $STORESCP_PID > /dev/null; then
    echo "[$(date)] storescp draait correct op poort 4242" | tee -a "$LOGFILE"
else
    echo "[$(date)] Fout: storescp kon niet worden gestart" | tee -a "$LOGFILE"
    exit 1
fi

# Start een oneindige lus om bestanden te verwerken
echo "[$(date)] Start monitoring en verwerking..." | tee -a "$LOGFILE"
while true; do
    # Controleer of de Receive-map leeg is
    if [ "$(ls -A "$WATCHDIR")" ]; then
        echo "[$(date)] Bestanden gedetecteerd in $WATCHDIR, start verwerking..." | tee -a "$LOGFILE"
        for file in "$WATCHDIR"/*; do
            if [[ -f "$file" ]]; then
                echo "[$(date)] Nieuw bestand gedetecteerd: $file" | tee -a "$LOGFILE"
                
                # Log details over het bestand
                echo "[$(date)] Bestandsgrootte: $(stat -c%s "$file") bytes" | tee -a "$LOGFILE"
                echo "[$(date)] Bestandseigenaar: $(stat -c%U "$file")" | tee -a "$LOGFILE"
                echo "[$(date)] Bestandstype: $(file "$file")" | tee -a "$LOGFILE"

                LOCKFILE="$file.lock"

                # Controleer of er al een lock-bestand bestaat
                if [ -f "$LOCKFILE" ]; then
                    echo "[$(date)] Bestand is in gebruik, overslaan: $file" | tee -a "$LOGFILE"
                    continue
                fi

                # Maak een lock-bestand aan
                touch "$LOCKFILE"

                # Verwerk het bestand met de virtuele omgeving
                echo "[$(date)] Verwerken gestart: $file" | tee -a "$LOGFILE"
                "$VENV_PYTHON" "$PROCESS_SCRIPT" "$file" >> "$LOGFILE" 2>&1
                if [ $? -eq 0 ]; then
                    echo "[$(date)] Verwerking succesvol: $file" | tee -a "$LOGFILE"
                    rm -f "$file"
                else
                    echo "[$(date)] Verwerking mislukt, bestand verplaatst naar wachtrij: $file" | tee -a "$LOGFILE"
                    mv "$file" "$QUEUE_DIR/"
                fi

                # Verwijder het lock-bestand
                rm -f "$LOCKFILE"
            fi
        done
    else
        # Verplaats bestanden uit de wachtrij naar de Receive-map als deze leeg is
        if [ "$(ls -A "$QUEUE_DIR")" ]; then
            echo "[$(date)] Wachtrij bevat bestanden, verplaats naar $WATCHDIR..." | tee -a "$LOGFILE"
            mv "$QUEUE_DIR"/* "$WATCHDIR/"
        fi
    fi
    sleep 5  # Wacht 5 seconden voordat de lus opnieuw wordt uitgevoerd
done
