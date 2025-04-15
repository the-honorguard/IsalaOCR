#!/bin/bash

# Aangepaste configuratie voor ZendnodeA (verzender)
AETITLE_CALLING="ZendnodeA"
AETITLE_CALLED="StorenodeB"
HOST="127.0.0.1"
PORT="4242"
SENDDIR="/home/isala/ocr/IsalaOCR/DICOM_node_simulator/Send"
LOGDIR="/home/isala/ocr/IsalaOCR/DICOM_node_simulator/Logfiles"
LOGFILE="$LOGDIR/sendnodeA.log"

if [ ! -d "$LOGDIR" ]; then
    mkdir -p "$LOGDIR"
    echo "[$(date)] Logmap aangemaakt: $LOGDIR"
fi

> "$LOGFILE"

if [ ! -d "$SENDDIR" ]; then
    echo "[$(date)] Verzendmap niet gevonden: $SENDDIR" | tee -a "$LOGFILE"
    exit 1
fi

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

is_dicom_file() {
    if head -c 132 "$1" | tail -c 4 | grep -q "DICM"; then
        return 0
    else
        return 1
    fi
}

is_file_complete() {
    local file="$1"
    # Controleer of het bestand groter is dan 0 en niet in gebruik is
    if [ -f "$file" ] && [ $(stat -c%s "$file") -gt 0 ]; then
        # Controleer of het bestand niet in gebruik is
        lsof "$file" >/dev/null 2>&1
        if [ $? -ne 0 ]; then
            return 0  # Bestand is compleet en kan worden verwerkt
        else
            return 1  # Bestand is in gebruik
        fi
    fi
    return 1
}

echo "[$(date)] Monitoring map: $SENDDIR" | tee -a "$LOGFILE"
echo "[$(date)] inotifywait gestart, wacht op wijzigingen..." | tee -a "$LOGFILE"

inotifywait -m -e close_write "$SENDDIR" 2>&1 | while IFS= read -r line; do
    directory=$(echo "$line" | awk '{print $1}')
    events=$(echo "$line" | awk '{print $2}')
    filename=$(echo "$line" | cut -d ' ' -f3-)

    if [ -z "$filename" ]; then
        echo "[$(date)] Waarschuwing: geen geldig bestandsnaamveld gedetecteerd in regel: $line" | tee -a "$LOGFILE"
        continue
    fi

    file="${directory}${filename}"


    echo "[$(date)] Event gedetecteerd: $events op bestand: $filename in map: $directory" | tee -a "$LOGFILE"

    file="$directory$filename"
    if [ -f "$file" ]; then
        echo "[$(date)] Nieuw bestand gedetecteerd: $file" | tee -a "$LOGFILE"
        echo "[$(date)] Bestandsgrootte: $(stat -c%s "$file") bytes" | tee -a "$LOGFILE"
        echo "[$(date)] Bestandseigenaar: $(stat -c%U "$file")" | tee -a "$LOGFILE"
        echo "[$(date)] Bestandstype: $(file "$file")" | tee -a "$LOGFILE"

        if is_dicom_file "$file" && is_file_complete "$file"; then
            echo "[$(date)] Bestand is geldig DICOM-bestand en volledig." | tee -a "$LOGFILE"

            if check_receiver_online; then
                echo "[$(date)] Verzenden gestart: storescu --aetitle $AETITLE_CALLING --call $AETITLE_CALLED $HOST $PORT $file" | tee -a "$LOGFILE"
                storescu --aetitle "$AETITLE_CALLING" --call "$AETITLE_CALLED" "$HOST" "$PORT" "$file" >> "$LOGFILE" 2>&1
                if [ $? -eq 0 ]; then
                    echo "[$(date)] Succesvol verzonden: $file" | tee -a "$LOGFILE"
                    rm -f "$file"
                    echo "[$(date)] Bestand verwijderd: $file" | tee -a "$LOGFILE"
                else
                    echo "[$(date)] Fout bij verzenden: $file" | tee -a "$LOGFILE"
                fi
            else
                echo "[$(date)] Verzenden overgeslagen: Ontvangende node is niet online." | tee -a "$LOGFILE"
            fi
        else
            echo "[$(date)] Bestand is GEEN geldig DICOM-bestand of is niet compleet, wordt overgeslagen: $file" | tee -a "$LOGFILE"
        fi
    else
        echo "[$(date)] Geen geldig bestand om te verzenden: $file" | tee -a "$LOGFILE"
    fi
done
