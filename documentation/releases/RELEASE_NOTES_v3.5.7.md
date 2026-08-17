# IsalaOCR 3.5.7

- Het tabblad **Activatie** heet voortaan **Models**.
- Officiële `PP-OCRv6_small_rec` en `PP-OCRv6_medium_rec` modellen kunnen vanuit dezelfde pagina worden geselecteerd.
- Eigen geregistreerde modellen blijven op dezelfde pagina beschikbaar.
- Modelselectie is transactioneel: het gekozen model wordt eerst naar `active-recognition.new` gekopieerd en vervangt pas daarna het actieve model.
- De Windows PowerShell-worker wacht nu expliciet op het kindproces en leest daarna pas de exitcode. Een geslaagde activatie wordt daardoor niet meer onterecht als mislukt gemarkeerd.
- `/activation` verwijst door naar `/models` voor bestaande bookmarks.
