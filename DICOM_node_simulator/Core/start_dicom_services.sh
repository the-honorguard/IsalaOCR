#!/bin/bash

# Configuratie
STORENODE_SCRIPT="/home/isala/ocr/IsalaOCR/DICOM_node_simulator/Core/storenodeB_config.sh"
SENDNODE_SCRIPT="/home/isala/ocr/IsalaOCR/DICOM_node_simulator/Core/sendnodeA_config.sh"
LOGDIR="/home/isala/ocr/IsalaOCR/DICOM_node_simulator/Logfiles"
STARTUP_LOG="$LOGDIR/startup.log"

# Controleer of de logmap bestaat, maak deze aan als dat niet zo is
if [ ! -d "$LOGDIR" ]; then
    mkdir -p "$LOGDIR"
    echo "[$(date)] Logmap aangemaakt: $LOGDIR"
fi

# Maak het startup-logbestand aan of leeg het als dat al bestaat
> "$STARTUP_LOG"

# Start storenodeB_config.sh
if [ -f "$STORENODE_SCRIPT" ]; then
    echo "[$(date)] Start storenodeB_config.sh..." | tee -a "$STARTUP_LOG"
    nohup "$STORENODE_SCRIPT" >> "$STARTUP_LOG" 2>&1 &
    echo "[$(date)] storenodeB_config.sh gestart." | tee -a "$STARTUP_LOG"
else
    echo "[$(date)] Fout: storenodeB_config.sh niet gevonden op $STORENODE_SCRIPT" | tee -a "$STARTUP_LOG"
fi

# Start sendnodeA_config.sh
if [ -f "$SENDNODE_SCRIPT" ]; then
    echo "[$(date)] Start sendnodeA_config.sh..." | tee -a "$STARTUP_LOG"
    nohup "$SENDNODE_SCRIPT" >> "$STARTUP_LOG" 2>&1 &
    echo "[$(date)] sendnodeA_config.sh gestart." | tee -a "$STARTUP_LOG"
else
    echo "[$(date)] Fout: sendnodeA_config.sh niet gevonden op $SENDNODE_SCRIPT" | tee -a "$STARTUP_LOG"
fi

echo "[$(date)] Alle DICOM-services zijn gestart." | tee -a "$STARTUP_LOG"

# Voeg deze regel toe aan het einde van start_dicom_services.sh
while true; do sleep 60; done