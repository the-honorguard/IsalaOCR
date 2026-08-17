# IsalaOCR 3.11.1

## Stap 1 verduidelijkt

- Stap 1 is nu primair een readiness-scherm in plaats van een installatie-dashboard.
- Bij een complete table-first voorbereiding staat duidelijk **TABLE PIPELINE · GEREED** met één vervolgactie naar Stap 2.
- Als iets ontbreekt toont Stap 1 één concrete herstelactie: status controleren, table-modellen downloaden, runtime installeren of offline valideren.
- Download/build/check-acties en technische details staan onder **Onderhoud / opnieuw installeren**.
- De table-first status telt alleen de werkelijk vereiste inference/table-component; geparkeerde detector-training stacks beïnvloeden de teller niet meer.
- Irrelevante training-image- en trainingsbestandmetrics zijn uit de normale Stap-1-weergave gehaald.
