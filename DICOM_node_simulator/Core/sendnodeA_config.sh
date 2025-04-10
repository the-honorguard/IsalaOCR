#!/bin/bash

# Aangepaste configuratie voor ZendnodeA (verzender)
AETITLE_CALLING="ZendnodeA"  # De zendnode (ZendnodeA)
AETITLE_CALLED="StorenodeB"  # De ontvangende node (StorenodeB)
HOST="127.0.0.1"  # IP-adres van StorenodeB
PORT="4242"  # Poort waarop StorenodeB luistert
SENDDIR="/home/isala/ocr/IsalaOCR/DICOM_node_simulator/Send"  # Map met bestanden die verzonden moeten worden
LOGDIR="/home/isala/ocr/IsalaOCR/DICOM_node_simulator/Logfiles"  # Map voor logbestanden
LOGFILE="$LOGDIR/sendnodeA.log"  # Logbestand

# Controleer of de logmap bestaat, maak deze aan als dat niet zo is
if [ ! -d "$LOGDIR" ]; then
    mkdir -p "$LOGDIR"
    echo "[$(date)] Logmap aangemaakt: $LOGDIR"
fi

# Maak het logbestand aan of leeg het als het al bestaat
> "$LOGFILE"

# Controleer of de verzendmap bestaat
if [ ! -d "$SENDDIR" ]; then
    echo "[$(date)] Verzendmap niet gevonden: $SENDDIR" | tee -a "$LOGFILE"
    exit 1
fi

# Functie om te controleren of de ontvangende node online is
check_receiver_online() {
    echo "[$(date)] Controleer of $HOST:$PORT bereikbaar is..." | tee -a "$LOGFILE"
    nc -z -v -w5 "$HOST" "$PORT" >> "$LOGFILE" 2>&1
    if [ $? -eq 0 ]; then
        echo "[$(date)] Ontvangende node is online: $HOST:$PORT" | tee -a "$LOGFILE"
        return 0
    else
        echo "[$(date)] Ontvangende node is NIET bereikbaar: $HOST:$PORT" | tee -a "$LOGFILE"
        return 1
    fi
}

# Log dat het script is gestart
echo "[$(date)] Monitoring map: $SENDDIR" | tee -a "$LOGFILE"
echo "[$(date)] inotifywait gestart, wacht op wijzigingen..." | tee -a "$LOGFILE"

# Start inotifywait en log alles wat het detecteert
inotifywait -m -e close_write,create,delete,modify,move "$SENDDIR" 2>&1 | while read -r directory events filename; do
    echo "[$(date)] Event gedetecteerd: $events op bestand: $filename in map: $directory" | tee -a "$LOGFILE"
    
    # Controleer of het een bestand is dat moet worden verzonden
    file="$directory$filename"
    if [ -f "$file" ]; then
        echo "[$(date)] Nieuw bestand gedetecteerd: $file" | tee -a "$LOGFILE"
        
        # Log details over het bestand
        echo "[$(date)] Bestandsgrootte: $(stat -c%s "$file") bytes" | tee -a "$LOGFILE"
        echo "[$(date)] Bestandseigenaar: $(stat -c%U "$file")" | tee -a "$LOGFILE"
        echo "[$(date)] Bestandstype: $(file "$file")" | tee -a "$LOGFILE"

        # Controleer of de ontvangende node online is
        if check_receiver_online; then
            # Probeer het bestand te verzenden
            echo "[$(date)] Verzenden gestart: storescu --aetitle $AETITLE_CALLING --call $AETITLE_CALLED $HOST $PORT $file" | tee -a "$LOGFILE"
            storescu --aetitle "$AETITLE_CALLING" --call "$AETITLE_CALLED" "$HOST" "$PORT" "$file" >> "$LOGFILE" 2>&1
            if [ $? -eq 0 ]; then
                echo "[$(date)] Succesvol verzonden: $file" | tee -a "$LOGFILE"
                # Verwijder het bestand na succesvolle verzending
                rm -f "$file"
                echo "[$(date)] Bestand verwijderd: $file" | tee -a "$LOGFILE"
            else
                echo "[$(date)] Fout bij verzenden: $file" | tee -a "$LOGFILE"
                echo "[$(date)] Debug: storescu commando: storescu --aetitle $AETITLE_CALLING --call $AETITLE_CALLED $HOST $PORT $file" | tee -a "$LOGFILE"
            fi
        else
            echo "[$(date)] Verzenden overgeslagen: Ontvangende node is niet online." | tee -a "$LOGFILE"
        fi
    else
        echo "[$(date)] Geen geldig bestand om te verzenden: $file" | tee -a "$LOGFILE"
    fi
done