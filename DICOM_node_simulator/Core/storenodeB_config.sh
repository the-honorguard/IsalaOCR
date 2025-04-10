#!/bin/bash

# Aangepaste configuratie voor StorenodeB (ontvanger)
AETITLE_CALLING="ZendnodeA"  # De zendnode
AETITLE_CALLED="StorenodeB"  # De ontvangende node (StorenodeB)
HOST="127.0.0.1"  # IP-adres van StorenodeB (zelfde machine)
PORT="4242"  # Poort waarop StorenodeB luistert
WATCHDIR="/home/isala/ocr/IsalaOCR/DICOM_node_simulator/Receive"  # Pad naar de ontvangstmappen voor de DICOM-bestanden
QUEUE_DIR="/home/isala/ocr/IsalaOCR/DICOM_node_simulator/Queue"  # Wachtrijmap voor bestanden
LOGDIR="/home/isala/ocr/IsalaOCR/DICOM_node_simulator/Logfiles"  # Map voor logbestanden
LOGFILE="$LOGDIR/storenodeB.log"  # Logbestand
PROCESS_SCRIPT="/home/isala/ocr/IsalaOCR/DICOM_node_simulator/Core/processing_script.py"  # Verwerkingsscript

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
nohup storescp --aetitle "$AETITLE_CALLED" --output-directory "$WATCHDIR" "$PORT" >> "$LOGFILE" 2>&1 &
STORESCP_PID=$!
echo "[$(date)] DICOM-server gestart met PID: $STORESCP_PID" | tee -a "$LOGFILE"

# Controleer of storescp correct is gestart
sleep 2
if ps -p $STORESCP_PID > /dev/null; then
    echo "[$(date)] storescp draait correct op poort $PORT" | tee -a "$LOGFILE"
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

                # Voer het verwerkingsscript uit
                echo "[$(date)] Start verwerkingsscript: python3 $PROCESS_SCRIPT $file" | tee -a "$LOGFILE"
                python3 "$PROCESS_SCRIPT" "$file" >> "$LOGFILE" 2>&1
                if [ $? -eq 0 ]; then
                    echo "[$(date)] Verwerkingsscript succesvol uitgevoerd voor: $file" | tee -a "$LOGFILE"
                    rm -f "$file"
                else
                    echo "[$(date)] Fout bij uitvoeren van verwerkingsscript voor: $file, bestand verplaatst naar wachtrij." | tee -a "$LOGFILE"
                    mv "$file" "$QUEUE_DIR/"
                fi
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
