# IsalaOCR 3.13.5

## Stap 7 hover-highlight en in-place review

Afwijkingen in Stap 7 zijn nu direct gekoppeld aan hun overlay op de afbeelding. Hover of keyboard-focus op een issuekaart geeft het exacte prediction-/GT-kader een duidelijke always-on-top highlight.

Reviewacties zoals **Model fout**, **GT controleren**, **Wis oordeel** en **+ Toevoegen aan GT** worden via AJAX opgeslagen. De pagina refresht daarbij niet meer en de gebruiker blijft op dezelfde scrollpositie. De open/beoordeeld-tellers en oordeelstatus worden direct bijgewerkt.

## Worker-acties verversen na voltooiing

Worker-backed acties verversen de huidige pagina juist wel zodra de taak succesvol is afgerond. Daardoor worden vervolgknoppen na bijvoorbeeld datasetbouw, validatie, modeltraining en activatie meteen beschikbaar. De scrollpositie wordt over deze doelbewuste refresh heen bewaard. Een worker-form kan dit gedrag expliciet uitschakelen met `data-refresh-on-complete="0"`.
