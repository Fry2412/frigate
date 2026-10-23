# Vorläufige Aufgaben

Stand 23.10.2026. Noch nicht zur Implementierung freigegeben. Diese Liste
konkretisiert den Planungsauftrag; nach Besprechung der Modulgrenzen jeweils
die nächste Modul-Spec ausarbeiten. Dateipfade bezeichnen geplante Bereiche,
keine bereits vorhandene Implementierung. M = ungefähr 3–5 Dateien je Slice;
größere Integrationsaufgaben beim Spezifizieren weiter zerlegen.

## P0 – Coral-Machbarkeit vor Portal-Ausbau

- [ ] **T01: Rezept und Eingabevertrag erfassen** (S; keine Abhängigkeit)
  - Ergebnis: Herkunft/Lizenz/Hash für Startgewichte und Toolchain; Tensor-/
    Labelmap-Vertrag dieses Forks sowie unterstützte Klassenanzahl dokumentiert.
  - Prüfen: Referenzmodell und Klassenliste gegen lokalen Decoder inspizieren;
    noch ungeklärte Weitergaberechte sichtbar lassen.
  - Geplant: `recipes/coral-yolov9/manifest`, `docs/compatibility.md`.
- [ ] **T02: Eigenes kurzes ReLU6-Fine-Tuning reproduzieren** (M; T01)
  - Ergebnis: fixierte Umgebung, kleiner lizenzierter Datensatz, eigener
    neuer Checkpoint, Seed, Logs und Float-Evaluation. Kein bloßer Modelldownload.
  - Prüfen: von leerem Cache wiederholen; Artefaktherkunft vollständig;
    Speicher/VRAM/Trainingszeit messen.
  - Geplant: `recipes/coral-yolov9/train`, zugehörige Lockdatei und Fixtures.
- [ ] **T03: Eigenen Checkpoint konvertieren und vergleichen** (M; T02)
  - Ergebnis: ONNX, quantisiertes TFLite und Compilerartefakt; korrekte
    Outputformen und Klassenreihenfolge; Float/INT8-Vergleich auf festen Bildern.
  - Prüfen: frischer Build, gültige Quantisierungsparameter, Compilerreport,
    verständlicher Fehler bei unpassendem Profil. Toleranzen vor Vergleich setzen.
  - Geplant: `recipes/coral-yolov9/export`, `tests/recipes/`.
- [ ] **T04: Reale Coral mit Frigate-Decoder prüfen** (M; T03)
  - Ergebnis: eigenes Modell liefert erwartete Detektionen auf realer Coral;
    vollständige Detektorzeit und Ressourcen dokumentiert.
  - Prüfen: reproduzierbare Bildsuite plus Start in diesem Fork; keine
    gleichzeitige Belegung einer produktiven Coral. Hardware fehlt → Gate offen.
  - Geplant: `tests/hardware/`, `docs/compatibility.md`.

**Checkpoint P0:** Pipeline belegt, Verträge und Lizenzfragen nachvollziehbar,
verbleibende Qualitätseinbußen sichtbar; Modul-Specs und Stack-Lock ableiten.

## P1 – Eigene Daten verwalten

- [ ] **T05: Zwei Dienste mit Speicherung und Anmeldung starten** (M; P0-Entscheidung)
  - Ergebnis: Web liefert UI/API, Runner erreicht Health-/Versionsvertrag;
    Metadaten/Dateien bleiben nach Neustart erhalten, fremder Zugriff scheitert.
  - Prüfen: Container-Smoke-Test, Migration leer/bestehend, Login/Logout und
    Rechteprüfung. Separate Hosts mit konfigurierbarer URL.
  - Geplant: `server/`, `runner/`, `docker/`, zwei Compose-Beispiele; bei Bedarf
    in Dienststart und Auth-Slice aufteilen.
- [ ] **T06: Bild aufnehmen und positive Box prüfen** (M; T05)
  - Ergebnis: Upload, Kamera-Zuordnung, Editor, positive Box, Entwurf und
    Verifizierung; Reload erhält Originalkoordinaten und Revision.
  - Prüfen: echte Browserbedienung bei Zoom, Bilddrehung und zwei Tabs;
    ungültiges Bild/Box wird abgelehnt.
  - Geplant: `web/`, `server/images/`, `server/annotations/`, passende Tests.
- [ ] **T07: Manuelle rote Beispiele samt Prüfregeln** (M; T06)
  - Ergebnis: negative Box ohne Frigate-Event; falsche Klasse mit korrektem
    Positivobjekt; ungeprüfter Rest verhindert Hintergrundexport.
  - Prüfen: Katze/Person-Verwechslung, leere Szene und Teilprüfung als
    getrennte Fixtures; Tastaturhilfe und Undo/Redo im Browser.
  - Geplant: Editor, Annotationsschema, Verifizierung, Semantiktests.
- [ ] **T08: Unveränderlichen Snapshot exportieren** (M; T07)
  - Ergebnis: gruppierter Split, Klassenmapping, YOLO/COCO plus eigenes
    Manifest; Snapshot nach späterer Boxänderung identisch.
  - Prüfen: Duplikate und Crops bleiben in einem Split; Bild/Box-Roundtrip;
    Negativbox ist kein positives Target, bewusst leere Targets bleiben leer.
  - Geplant: `server/datasets/`, `contracts/`, `tests/datasets/`.

**Checkpoint P1:** vollständiger Weg Upload → Korrektur → Review → Snapshot.

## P2 – Runner und Vorannotation

- [ ] **T09: Runner pairen und Aufträge sicher übernehmen** (M; T05)
  - Ergebnis: bestätigtes Pairing, passende Fähigkeiten, atomare Lease,
    widerrufbares Token; nur zugeordnete Bilddaten lesbar.
  - Prüfen: zwei konkurrierende Claims, falsches Token, Leaseablauf und
    Managerneustart. Alte Versuche dürfen nicht erfolgreich finalisieren.
  - Geplant: `server/jobs/`, `runner/agent/`, Vertrags-/Integrationstests.
- [ ] **T10: Transfer nach Netzabbruch fortsetzen** (M; T09)
  - Ergebnis: blockweiser Transfer, Hashprüfung, Cache und Größenlimits.
  - Prüfen: Unterbrechung und erneuter Request, falscher Hash, abgelaufene
    Lease während Upload; keine unvollständige Datei als Artefakt sichtbar.
  - Geplant: `server/artifacts/`, `runner/transfers/`, Netzwerk-Integrationstest.
- [ ] **T11: Weitere Objekte vorannotieren und prüfen** (M; T06, T09, T10)
  - Ergebnis: Predict-Job findet zusätzliche passende Klassen und speichert
    Modell/Score; manuelle Labels bleiben erhalten.
  - Prüfen: Mehrfachobjektbild, Crop-Koordinaten und Deduplizierung;
    Akzeptieren/Verwerfen getrennt, neue Vorschläge heben keine Prüfung auf.
  - Geplant: `runner/predict/`, `server/predictions/`, Editor-Vorschläge.

**Checkpoint P2:** zwei Rechner/Netzgrenze, Runner-Widerruf und Offlinefall.

## P3/P4 – Training bis nutzbares Paket

- [ ] **T12: Training aus eingefrorenem Snapshot starten** (M; T02, T08–T10)
  - Ergebnis: Run bindet Datensatz/Rezept/Parameter, erzeugt Kurven und
    Checkpoints; Abbruch und kompatibles Resume sind sichtbar.
  - Prüfen: kurzer echter Trainingslauf, Prozessausfall und Neustart;
    Wiederaufnahme mit falschem Snapshot wird abgelehnt.
  - Geplant: Runner-Trainingsadapter, Run-API, Trainingsansicht.
- [ ] **T13: Export bewerten und Modellpaket herunterladen** (M; T03, T04, T12)
  - Ergebnis: Modell/Labelmap/YAML/Hashes/Berichte; „Hardwaretest ausstehend“
    unterscheidbar von real bestanden. Download braucht Benutzerrechte.
  - Prüfen: Paket in Test-Frigate laden, Decodervergleich und Rückwechsel
    auf vorheriges Modell; Schwellen/Metriken nicht nach Ergebnis ändern.
  - Geplant: `server/models/`, Modellansicht, Paket-/Hardwaretests.
- [ ] **T14: Frigate-Ereignis mit sauberem Bild importieren** (M; T06)
  - Ergebnis: Ereignis/Kamera/Box-Herkunft, idempotenter Import ohne Plus-
    Abhängigkeit; fehlende Clean-Snapshots verständlich melden.
  - Prüfen: eingeschränkter Kamerazugriff, abgelaufenes Ereignis, doppelte
    Anfrage und ausgeschaltetes Frigate; Upload bleibt nutzbar.
  - Geplant: `connectors/frigate/`, Quellenansicht, Connector-Tests.
- [ ] **T15: Patches und Negativ-Sampling sichtbar machen** (M; T07, T08, T13)
  - Ergebnis: Crop-Raster nach Klasse/Polarität, nachvollziehbare Auswahl-
    gewichte; Elternbild und Split aller erzeugten Crops erhalten.
  - Prüfen: überlappendes echtes Objekt wird nicht aus Labels entfernt;
    vor/nach Sampling gleiche feste Testmenge und Recallvergleich.
  - Geplant: Patches-Ansicht, Dataset-Auswahl, Sampling-Tests.
- [ ] **T16: Wiederherstellung und Remote-Deployment abnehmen** (M; T10, T13)
  - Ergebnis: Backup auf leerer Installation wiederhergestellt; Remote-
    Runner über optionalen Tunnel, geschützte Downloads und Löschregeln.
  - Prüfen: konsistente DB/Blob-Wiederherstellung, großer resumierbarer
    Upload, 401/403 statt Login-HTML am Runner, Rechte und Token-Widerruf.
  - Geplant: Betriebsdoku, Backup-Werkzeug, Deployment-Testfälle.

**Checkpoint MVP:** eigene Bilder → manuelle/automatische Annotation →
Remote-Training → eigenes auf Coral geprüftes Frigate-Modell und Rückwechsel.
Erst danach zweites Hardwareprofil in eigener Spec und kleinen Slices.
