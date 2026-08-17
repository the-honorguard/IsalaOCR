# IsalaOCR 3.13.10

## Canonieke GT-review blijft nu stabiel tussen modelruns

Na de eerste trainingsdataset wordt Stap 4 gebruikt als beheer van de canonieke Ground Truth. Tot v3.13.9 bleef de status **Afbeelding klaar** echter gekoppeld aan de actuele detector-run. Een nieuwe Stap-3-run kon daardoor alle bronnen opnieuw als onafgerond laten verschijnen, terwijl de bijbehorende nieuwe predictions in GT-modus bewust niet meer in Stap 4 werden getoond.

v3.13.10 scheidt die twee verantwoordelijkheden definitief:

- iedere canonieke GT-bron heeft een eigen persistente reviewstatus;
- Stap 4 toont in GT-modus **GT-afbeelding gecontroleerd**;
- een nieuwe detectie of modelactivatie verandert die GT-status niet;
- nieuwe predictions worden uitsluitend via Stap 7 tegen de canonieke GT beoordeeld;
- een echte GT-wijziging opent alleen de gewijzigde bron opnieuw;
- Stap 6 kan pas een nieuwe dataset bouwen als alle gewijzigde GT-bronnen opnieuw gecontroleerd zijn.

Voor bestaande projecten is geen handmatige herstelactie nodig. Canonieke GT-bestanden uit v3.13.1–v3.13.9 zonder het nieuwe reviewveld worden bij de upgrade als reeds gecontroleerd geïnterpreteerd. Dat past bij hun herkomst: canonieke GT kon in die versies alleen uit een eerder afgeronde dataset ontstaan.
