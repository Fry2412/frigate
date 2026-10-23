# Eigenes Modell-Trainingsportal für Frigate

Planungsstand: 23. Oktober 2026. Arbeitsname: `training-portal`.

Ein eigenständig betreibbares Open-Source-Subprojekt für eigene Bildsammlungen,
Annotation, Vorannotation, Training und hardwareabhängige Frigate-Modellexporte.
Zuerst Google Coral mit YOLOv9; weitere Ziele über explizite, getestete Profile.
Frigate+ dient als Workflow-Inspiration. Dessen gemeinschaftlich trainierte
Basisgewichte, Daten oder Qualitätsniveau werden nicht vorausgesetzt.

Der POC umfasst optionale Frigate-Einreichung, manuelle Bildprüfung,
COCO-Datensatzvorbereitung, YOLOv9-Basistraining und Kamerarefinement mit
einem explizit gespeicherten Elternmodell. Open Images kann nur als lokal
kuratierter COCO-Import eingebunden werden. Der POC erzeugt
Trainingscheckpoints, aber noch **kein Coral-kompatibles Inferenzmodell**.

- [Architektur, Produktumfang und Roadmap](tasks/plan.md)
- [Vorläufige Umsetzungsschritte mit Abnahmekriterien](tasks/todo.md)
- [Recherche und Quellen mit Einschränkungen](RESEARCH.md)
- [Vorhandene Frigate+-Modelle: Voraussetzungen und aktuelle Grenzen](EXTERNAL-MODELS.md)

Die erste offene Hardwarefrage ist geklärt: Der Trainingsrechner steht noch
nicht fest; Linux x86-64 mit NVIDIA-GPU ist die vereinbarte Planungsannahme.

## POC starten

### Manager-Rechner

Im Verzeichnis `training-portal` die `.env.example` nach `.env` kopieren.
Zwei unterschiedliche zufällige Tokens für `PORTAL_API_TOKEN` und
`PORTAL_RUNNER_TOKEN` eintragen. Beispielsweise zweimal
`python -c "import secrets; print(secrets.token_urlsafe(48))"` ausführen.
Das Admin-Token wird im Browser und in Frigate verwendet; der entfernte
Runner benötigt ausschließlich das Runner-Token.

Lokal bauen und starten:

```sh
docker compose --env-file .env -f compose.manager.yml up -d --build
```

Die Oberfläche ist unter `http://127.0.0.1:8080` erreichbar. Dort mit dem
Admin-Token verbinden. Der Token bleibt im Seitenspeicher und muss nach
Neuladen erneut eingegeben werden. Der Manager läuft als UID 10001 und
speichert Bilder, Datenbank und Ergebnisse im Docker-Volume `portal-data`.

Bei einer Installation auf einem anderen Rechner einen eigenen HTTPS-
Reverse-Proxy/Tunnel verwenden. `PORTAL_BIND_ADDRESS=0.0.0.0` ist eine
ausdrückliche Option für geschützte LAN-Tests. Cloudflare ist keine feste
Abhängigkeit. Ein Cloudflare-Access-Browserlogin kann den Runner blockieren;
Access-Service-Token-Header sind in diesem POC noch nicht implementiert.

### RTX-Rechner

Linux amd64 mit NVIDIA-Treiber für CUDA 12.8 und eingerichtetem NVIDIA
Container Toolkit verwenden. GPU-Zugriff des Containers vorher gemäß
[NVIDIA-Dokumentation](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/sample-workload.html)
prüfen. Der POC startet einen Trainingsprozess auf GPU `0`.

Auf diesem Rechner ebenfalls `training-portal` bereitstellen. In dessen
`.env` nur Runner-Einstellungen und das Runner-Token setzen:

```dotenv
PORTAL_URL=https://trainer.example.com
PORTAL_RUNNER_TOKEN=<dasselbe Runner-Token wie am Manager>
RUNNER_ID=rtx-runner-1
YOLO_WEIGHTS=/weights/yolov9-s.pt
```

Einen vertrauenswürdigen **originalen Trainingscheckpoint** `yolov9-s.pt`
aus dem [YOLOv9-Projekt](https://github.com/WongKinYiu/yolov9) unter
`training-portal/weights/yolov9-s.pt` ablegen. Keine `converted`-Inferenzgewichte
und kein TFLite als Trainingscheckpoint verwenden. Herkunft/Lizenz prüfen;
der POC lädt bewusst keine Gewichte zur Laufzeit herunter. `YOLO_WEIGHTS=`
ermöglicht ausdrücklich Training von Grund auf für einen Funktionstest;
damit ist bei wenigen eigenen Bildern keine brauchbare Genauigkeit zu erwarten.

```sh
docker compose --env-file .env -f compose.runner.yml up -d --build
docker compose --env-file .env -f compose.runner.yml logs -f runner
```

Der Runner öffnet keinen Serverport. `PORTAL_URL` muss aus seinem Container
erreichbar sein; `localhost` würde dort den Runner selbst bezeichnen. Die
Manager-Oberfläche muss für Training nicht im Browser geöffnet bleiben.
Fehlgeschlagene Versuche behalten ihre Dateien/Logs im Runner-Volume;
regelmäßig Speicher prüfen. Erfolgreiche Versuche werden nach bestätigter
Ergebnisübertragung lokal entfernt.

### Frigate optional umleiten

Im Frigate-Container `FRIGATE_MODEL_TRAINER_API_KEY` auf das Admin-Token des
Managers setzen. In der bisherigen YAML-Konfiguration ergänzen:

```yaml
model_trainer:
  enabled: true
  url: http://manager:8080  # nur bei gemeinsamem Docker-Netz; sonst erreichbare HTTPS-URL
  api_key: "{FRIGATE_MODEL_TRAINER_API_KEY}"
image_submission_api: model_trainer
```

Die bestehenden Einreichungsaktionen für Ereignisse, Fehlalarme und
Aufnahme-Snapshots verwenden dann den Manager. Bestehende UI-Texte heißen
im POC teilweise weiterhin Frigate+. Plus-Modellabfragen und `plus://`-
Downloads bleiben unabhängig davon. Das verwendete Token wird aus der
Konfigurationsantwort entfernt. Für den Rückwechsel
`image_submission_api: plus` setzen und Frigate neu starten. Bereits
eingereichte Ereignisse bleiben ihrem ursprünglichen Ziel zugeordnet;
ein Zielwechsel sendet sie nicht versehentlich zum anderen Dienst.

## Workflow: COCO-Basis und Kamerarefinement

Der Studio-Bereich im Manager führt durch drei Jobs. Eine COCO-Vorbereitung
lädt keine Gewichte herunter. Sie erfordert im Formular die Bestätigung der
COCO-Nutzungsbedingungen einschließlich der individuellen Bildrechte. Der
Runner lädt das offizielle COCO-2017-Annotationsarchiv und anschließend die
angeforderte Teilmenge von Trainings- und Validierungsbildern. Die Auswahl ist
seeded und deckt die 80 COCO-Klassen in beiden ursprünglichen Splits ab. Kann
die angeforderte Anzahl diese Abdeckung nicht erreichen, schlägt der Job
explizit fehl. Der Default ist 1.000 Trainings- und 200 Validierungsbilder;
zulässig sind 80–118.287 bzw. 80–5.000.

Der COCO-Annotationsdownload ist auf 512 MiB begrenzt; jedes COCO-JSON wird
beim Lesen auf 3 GiB begrenzt. Pro ausgewähltem Bild gilt ein Limit von 32 MiB.
Es werden nur die ausgewählten Bilder geladen, aber das vollständige
Annotationsarchiv wird benötigt. Runner behalten Downloads unter
`RUNNER_DATASETS_DIR/.downloads` und die veröffentlichte, nach Manifest-SHA256
adressierte Kopie im Cache. Der Cache benötigt daher ungefähr Platz für die
ausgewählten Bilder zweimal, zusätzlich zum Annotationsarchiv; unterschiedliche
Datasätze behalten jeweils ihre eigene veröffentlichte Kopie. Die Limits sind
Obergrenzen, keine Schätzung der tatsächlichen Downloadgröße. Verifizierte
Downloads werden bei erneuter Vorbereitung wiederverwendet und nicht automatisch
gelöscht. Cache und Downloadverzeichnis liegen standardmäßig unter
`RUNNER_WORK_DIR/datasets` und sollten auf einem persistenten Volume liegen.

1. **Datensatz vorbereiten:** COCO mit gewünschter Größe und Seed anfordern.
   Nach erfolgreichem Abschluss erscheint der Cache-Datensatz samt Klassen und
   Runnern im Manager. Es wird keine Kameraaufnahme an diesen Job angehängt.
2. **Basismodell trainieren:** den vorbereiteten Datensatz auswählen. Die
   Klassenreihenfolge stammt unveränderlich aus dessen Manifest. „Trusted local
   YOLOv9 weights“ nutzt den lokal montierten `YOLO_WEIGHTS`-Checkpoint;
   „Train from scratch“ übergibt dem Trainer leere Gewichte. Epochen, Batch und
   Bildgröße sind begrenzt; die UI startet mit 30 / 8 / 320.
3. **Ergebnis ausdrücklich speichern:** nach erfolgreichem Training kann ein
   Admin den Job mit einem Namen als Modell registrieren. Der Manager übernimmt
   nur `best.pt` aus dem Ergebnis-ZIP, speichert es unveränderlich mit SHA256
   und erhält Taxonomie, Datensatz und Elternlinie. Der Manager lädt den
   Checkpoint dabei nicht in Python oder PyTorch. Promotete Checkpoints stammen
   trotzdem von vertrauenswürdigen Runnern: Alle Runner mit dem gemeinsamen
   Runner-Token sind Operatoren, deren Artefakten der Admin vertrauen muss.
4. **Kamerarefinement:** ein gespeichertes Modell und nichtleere Kameras wählen.
   Nur geprüfte Bilder dieser Kameras gehen in den eigenen Trainingssnapshot.
   Prüfe die sichtbaren Objekte über die gesamte Taxonomie des Elternmodells.
   Die vollständige geordnete Elterntaxonomie bleibt im Modell erhalten; es ist
   kein positives Beispiel für jede Klasse in den Kameraaufnahmen erforderlich.
   Mindestens zwei unabhängige Bilder mit positiven Zielen und positive Bilder
   sowohl für Training als auch Validierung sind erforderlich. Positive Labels
   außerhalb der Eltern-Taxonomie werden abgewiesen. Die UI startet mit 5
   Epochen, Batchgröße 4, Bildgröße 320 und null Replaybildern.

Refinement lädt den gespeicherten Elterncheckpoint für die aktive Runner-Lease
und prüft seine SHA256. Bei `Public reference images = 0` braucht der Runner
keinen vollständigen öffentlichen Basisdatensatz; er benötigt nur den
Checkpoint und den eigenen geprüften Kamerasnapshot. Optionales Replay (0–5.000
Bilder) erfordert, dass der ursprüngliche Referenzdatensatz des Elternmodells
auf dem gewählten Runner vorhanden ist. Replay wird deterministisch nur aus
`images/train` genommen; öffentliche Validierungsbilder bleiben aus dem Training
ausgeschlossen. Das Rezept nutzt `lr0=0.001` und `--freeze 10`, startet den
Optimizer neu und bietet keine Garantie gegen Catastrophic Forgetting. Prüfe
nach dem Fine-Tuning weiterhin die Leistung früher gelernter Klassen.

Für einen ausdrücklich vollständig geprüften Open-Images-Import kann ein
Operator auf dem Runner die vorhandenen lokalen COCO-Formatdateien importieren.
Die Quellstruktur enthält `annotations/train.json`, `annotations/val.json`,
`images/train/` und `images/val/`; `classes.json` ist eine JSON-Liste in der
gewünschten Reihenfolge. Beispiel:

```sh
docker compose --env-file .env -f compose.runner.yml run --rm \
  -v /srv/openimages-reviewed:/import:ro runner \
  datasets import-reviewed-coco \
  --root /var/lib/portal-runner/datasets \
  --source-dir /import \
  --classes-json /import/classes.json \
  --confirm-all-classes-reviewed \
  --confirm-image-and-annotation-licenses
```

Das Kommando liest keine rohen Open-Images-CSV-Dateien und lädt keine Bilder
herunter. Es erstellt einen unveränderlichen lokalen Cacheeintrag. Der Runner
meldet den Eintrag bei seinem nächsten Poll an den Manager. Der Import setzt
voraus, dass jede im Klassenprofil verwendete Klasse und die individuellen
Bildrechte vorab geprüft wurden; Lizenzhinweise stehen im Datensatzmanifest.
Die CLI kann den Cache mit
`portal-runner datasets inventory --root /var/lib/portal-runner/datasets`
auflisten. Die vollständigen Flags stehen in
`portal-runner datasets import-reviewed-coco --help`.

Im manuellen Kameraworkflow Boxen zeichnen, Klasse angeben, bei Bedarf „False
positive“ auswählen und speichern. Falsch klassifizierte echte Objekte
zusätzlich mit der richtigen positiven Klasse annotieren. Erst nach vollständiger
Prüfung „Mark reviewed“ wählen; Annotationen ändern setzt den Status zurück.
Der Snapshot enthält nur explizit geprüfte Bilder. Negative Boxen bleiben im
Manifest erhalten und werden nicht als positive YOLO-Targets ausgegeben.
Geprüfte reine Hintergrundbilder erhalten leere Targets. Der POC hat keine
direkte klassenbezogene negative Loss. `difficult`-Positivboxen werden als
gewöhnliche positive Targets exportiert und zusätzlich im Manifest markiert.

Trainingsartefakte enthalten `best.pt`, `last.pt`, `metrics.csv`,
`training.log` und `provenance.json`. Sie sind die Grundlage für spätere
Konvertierung und Deployment, können aber noch nicht direkt auf Coral oder als
`plus://`-Modell geladen werden.

## GitHub Actions und ladbare Images

Der Workflow **Training portal POC** führt Paket-/Integrationstests aus und
baut/publiziert auf Push nach `main`, `feat/**` und `codex/training-portal-poc`
sowie bei manuellem Start diese Images für Linux amd64:

```text
ghcr.io/fry2412/frigate/training-manager:sha-<vollständiger Commit>
ghcr.io/fry2412/frigate/training-runner:sha-<vollständiger Commit>
```

Zusätzlich gibt es einen Branch-Tag, für diesen Arbeitsbranch
`codex-training-portal-poc`. Pull Requests bauen ohne Registry-Push. Der
bestehende Workflow **Fork image** baut Frigate auch für diesen Arbeitsbranch:

```text
ghcr.io/fry2412/frigate:feature-<erste 7 Zeichen des Commits>
```

Nach erfolgreichem Workflow die veröffentlichten Manager-/Runner-Tags als
`PORTAL_MANAGER_IMAGE` bzw. `PORTAL_RUNNER_IMAGE` in die lokale `.env` eintragen:

```sh
docker compose --env-file .env -f compose.manager.yml pull
docker compose --env-file .env -f compose.manager.yml up -d --no-build
# Auf dem RTX-Rechner entsprechend compose.runner.yml verwenden.
```

Private GHCR-Pakete benötigen vorher `docker login ghcr.io` mit einer passenden
Leseberechtigung. Registry-Sichtbarkeit wird durch diesen POC nicht geändert.
Frigate mit dem neuen Image über die vorhandene eigene Compose-Konfiguration
betreiben; diese Beispiele ersetzen keine Kamera-/Geräte-Konfiguration.

## Prüfung und bewusste POC-Grenzen

```sh
python -m pip install -e './manager[test]' -e './runner[test]' ruff
python -m pytest manager/tests runner/tests tests -q
ruff check manager runner tests
ruff format --check manager runner tests
```

Lokal geprüft: Manager- und GPU-Runner-Image gebaut, Browser-Verbindung,
manuelle rote Box und Verifizierung; echte HTTP-Auftrags-/Transferkette mit
ersetztem Trainer; zusätzlich echte YOLOv9-CPU-Läufe im CUDA-Image:
Basistraining, Speichern des Checkpoints und anschließendes Kamerarefinement
ohne öffentlichen Cache oder lokale Startgewichte. Beide Läufe nutzten je
eine Epoche auf synthetischen Bildern und erzeugten Checkpoints, Metriken und
Herkunftsdaten. COCO-Vorbereitung wurde mit kontrollierten Download-Fixtures
geprüft; ein vollständiger öffentlicher Download wurde nicht gestartet.
Auf RTX wurde hier noch kein Lauf gemessen.

Noch offen: automatische Vorannotation, Coral-ReLU6/INT8-Export, Modell-
Deployment/Rollback in Frigate, Konten/Rollen, per Runner getrennte Tokens,
Pairing-UI, Live-Trainingskurven, UI-Abbruch/Resume und resumierbare Transfers.
Der POC nutzt einen gemeinsamen administrativ vergebenen Runner-Token.
Alle Runner damit sind Vertrauenspersonen derselben Installation.

Maximal 10 MiB pro Bild, 40 Megapixel, 5.000 geprüfte Bilder und 256 MiB
Bilddaten pro Snapshot; Artefakte maximal 512 MiB. Große Uploads können an
Proxy-/Tunnel-Limits scheitern. Dataset-ZIPs werden beim Manager im Speicher
erstellt, deshalb ist dieser POC für kleine Testdatensätze vorgesehen.

Der Split ist beim Auftrag eingefroren und gruppiert nach Kamera, sofern
mehrere Kameras positive Daten haben, sonst nach Bild. Zeitliche Nachbarbilder
und Duplikate werden noch nicht automatisch erkannt. Resultierende Metriken
sind deshalb keine belastbare Aussage über Generalisierung. Keine Gleichheit
mit Frigate+-Qualität ableiten. Lokaler Docker-Build und CPU-Smoke ersetzen
keine Abnahme auf der späteren RTX-/Coral-Hardware.
