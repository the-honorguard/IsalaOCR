#!/bin/bash
# Send node configuratie voor Test
IP_ADDRESS="127.0.0.1"
PORT_NUMBER="4243"
AE_TITLE="Test"

# DCMTK send command
storescu -v -aec Test 127.0.0.1 4243 /path/to/dicom/files

# Path to start_dicom_services.sh
/home/isalaocrsandbox/isala/ocr/IsalaOCR/DICOM_node_simulator/Core/start_dicom_services.sh
