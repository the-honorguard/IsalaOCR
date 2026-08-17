# IsalaOCR 3.8.9 — gefaseerde voorbereiding

Stap 1 is opgesplitst in controleerbare fasen per component: bron/files, download, downloadcheck, install/build en installatie-/runtimecheck.

- Toon per component afzonderlijke status voor download en installatie/runtimevalidatie.
- Voeg losse knoppen toe voor Download, Install/build, Check install/runtime en Volledig proces.
- Voeg bulkacties toe voor Alle downloads, Alles installeren, Alles controleren en Alles voorbereiden.
- Voer onafhankelijke netwerkdownloads parallel uit; houd zware Docker-image-builds standaard sequentieel om BuildKit/PIP-cache- en schijfcontention te beperken.
- Sla validatiemarkers met Docker image-ID op zodat een rebuild een oude groene runtimecheck automatisch ongeldig maakt.
- Voeg offline checks toe voor reeds gedownloade inference- en localization-modelbestanden.
- Pin training-images op `setuptools<81` omdat PaddleDetection nog `pkg_resources` importeert; nieuwere setuptools-versies verwijderen die module.
- Behoud interne action-ID’s alleen voor worker/backwards compatibility; ze blijven verborgen in de workflow-UI.
