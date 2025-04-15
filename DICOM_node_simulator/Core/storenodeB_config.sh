#!/bin/bash

# Configuratie
AETITLE_CALLING="ZendnodeA"
AETITLE_CALLED="StorenodeB"
HOST="127.0.0.1"
PORT="4242"
WATCHDIR="/home/isala/ocr/IsalaOCR/DICOM_node_simulator/Receive"
QUEUE_DIR="/home/isala/ocr/IsalaOCR/DICOM_node_simulator/Queue"
LOGDIR="/home/isala/ocr/IsalaOCR/DICOM_node_simulator/Logfiles"
LOGFILE="$LOGDIR/storenodeB.log"
PROCESS_SCRIPT="/home/isala/ocr/IsalaOCR/DICOM_node_simulator/Core/processing_script.py"

# Zorg dat log- en werkmappen bestaan
mkdir -p "$LOGDIR" "$WATCHDIR" "$QUEUE_DIR"
> "$LOGFILE"

# Check verwerkingsscript
if [ ! -f "$PROCESS_SCRIPT" ]; then
    echo "[$(date)] Verwerkingsscript niet gevonden: $PROCESS_SCRIPT" | tee -a "$LOGFILE"
    exit 1
else
    echo "[$(date)] Verwerkingsscript gevonden: $PROCESS_SCRIPT" | tee -a "$LOGFILE"
fi

# Start storescp
echo "[$(date)] Start de DICOM-server op poort $PORT..." | tee -a "$LOGFILE"
nohup storescp --aetitle "$AETITLE_CALLED" --output-directory "$WATCHDIR" "$PORT" >> "$LOGFILE" 2>&1 &
STORESCP_PID=$!
sleep 2

# Check of storescp draait
if ps -p $STORESCP_PID > /dev/null; then
    echo "[$(date)] storescp draait met PID $STORESCP_PID" | tee -a "$LOGFILE"
else
    echo "[$(date)] Fout: storescp kon niet worden gestart" | tee -a "$LOGFILE"
    exit 1
fi

# Start monitoring-loop
echo "[$(date)] Start monitoring van $WATCHDIR..." | tee -a "$LOGFILE"

while true; do
    # Verwerk bestanden in WATCHDIR
    for file in "$WATCHDIR"/*; do
        if [[ -f "$file" ]]; then
            echo "[$(date)] Verwerking van bestand: $file" | tee -a "$LOGFILE"
            
            # Bestand info
            echo "[$(date)] Grootte: $(stat -c%s "$file") bytes" | tee -a "$LOGFILE"
            echo "[$(date)] Eigenaar: $(stat -c%U "$file")" | tee -a "$LOGFILE"
            echo "[$(date)] Type: $(file "$file")" | tee -a "$LOGFILE"

            # DICOM check
            if head -c 132 "$file" | tail -c 4 | grep -q "DICM"; then
                echo "[$(date)] Geldig DICOM-bestand gedetecteerd." | tee -a "$LOGFILE"

                python3 "$PROCESS_SCRIPT" "$file" >> "$LOGFILE" 2>&1
                if [ $? -eq 0 ]; then
                    echo "[$(date)] Verwerking geslaagd. Bestand verwijderd: $file" | tee -a "$LOGFILE"
                    rm -f "$file"
                else
                    echo "[$(date)] Verwerking mislukt. Bestand verplaatst naar wachtrij: $file" | tee -a "$LOGFILE"
                    mv "$file" "$QUEUE_DIR/"
                fi
            else
                echo "[$(date)] Ongeldig DICOM-bestand. Bestand overgeslagen: $file" | tee -a "$LOGFILE"
            fi
        fi
    done

    # Als WATCHDIR leeg is, verplaats 1 bestand uit wachtrij
    if [ -z "$(ls -A "$WATCHDIR")" ]; then
        next_file=$(find "$QUEUE_DIR" -type f | head -n 1)
        if [ -n "$next_file" ]; then
            echo "[$(date)] WATCHDIR is leeg. Verplaats bestand uit wachtrij: $next_file" | tee -a "$LOGFILE"
            mv "$next_file" "$WATCHDIR/"
        fi
    fi

    sleep 5
done
