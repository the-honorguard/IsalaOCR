# Security- en privacynotities

## Runtimecontroles

- OCR-runtime heeft geen netwerkinterface.
- Training, datasetbouw en evaluatie hebben na setup geen netwerkinterface.
- Modeldownloads en officiële trainingsgewichten worden via afzonderlijke, expliciete setupservices opgehaald.
- Labelinterface wordt alleen gepubliceerd op `127.0.0.1:8088` en zit op een intern Docker-netwerk.
- Normale applicatiecontainer draait als niet-geprivilegieerde gebruiker.
- Rootfilesystem is read-only waar de service dat toestaat.
- Linux-capabilities zijn verwijderd en `no-new-privileges` is ingeschakeld.
- Input en modelcache zijn tijdens normale verwerking read-only.

## Privacy van trainingsartefacten

De collector bewaart alleen:

- ROI-crop;
- gehashte bron-ID;
- profiel- en veldsleutel;
- ROI-coördinaten;
- ruwe OCR-uitvoer en confidence;
- handmatig exact label en reviewstatus.

Niet bewaard in database en manifest:

- patiëntnaam;
- patiëntnummer;
- accession number;
- DICOM-UID's;
- oorspronkelijke bestandsnaam of volledig bronpad.

`training/workspace`, `training/registry`, `input`, `output` en `models` zijn uitgesloten van Git. Trainingsdata en modellen zijn uitgesloten van de Docker-buildcontext.

## Resterende risico's

- Pixels kunnen gebrande patiëntidentificatie bevatten.
- Een veldcrop kan op zichzelf klinische informatie zijn.
- Hostbeheerders en gebruikers met toegang tot Docker of de projectmap kunnen data lezen.
- SQLite, crops, modellen en evaluatierapporten vereisen ACL's, encryptie en retentiebeleid.
- Kwaadaardige of afwijkende DICOM's kunnen beelddecoders belasten.
- Containerimages, Pythonpakketten en basisgewichten blijven supply-chaincomponenten.
- Een model kan overfitten of trainingsbeelden memoriseren; publiceer modellen niet zonder beoordeling.
- Exact-match accuracy op een kleine of niet-representatieve dataset zegt onvoldoende over klinische betrouwbaarheid.

## Aanbevolen productieaanvullingen

- gesigneerde images en SBOM;
- private registry en vulnerability scanning;
- versleutelde lokale opslag en least-privilege ACL's;
- formeel retentie- en verwijderingsproces voor crops en datasets;
- audittrail voor labelwijzigingen en modelactivatie;
- minimaal twee-persoonsbeoordeling voor testlabels en modelpromotie;
- versievast validatieprotocol per scanner/softwareversie/layout;
- expliciete rollbackprocedure naar vorig actief model;
- DPIA, architectuurreview en klinische veiligheidsanalyse.
