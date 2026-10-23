# Eigenes Modell-Trainingsportal für Frigate

Planungsstand: 23. Oktober 2026. Arbeitsname: `training-portal`.

Ein eigenständig betreibbares Open-Source-Subprojekt für eigene Bildsammlungen,
Annotation, Vorannotation, Training und hardwareabhängige Frigate-Modellexporte.
Zuerst Google Coral mit YOLOv9; weitere Ziele über explizite, getestete Profile.
Frigate+ dient als Workflow-Inspiration. Dessen gemeinschaftlich trainierte
Basisgewichte, Daten oder Qualitätsniveau werden nicht vorausgesetzt.

Der erste POC ist implementiert: optionale Frigate-Einreichung, Web-Manager
mit manueller Bildprüfung und positiven/negativen Boxen, eingefrorene
Trainingsdatensätze und ein entfernter YOLOv9-Runner. Die detaillierte Roadmap
enthält weiterhin spätere Funktionen. Der POC erzeugt Trainingscheckpoints;
er erzeugt noch **kein Coral-kompatibles Inferenzmodell**.

- [Architektur, Produktumfang und Roadmap](tasks/plan.md)
- [Vorläufige Umsetzungsschritte mit Abnahmekriterien](tasks/todo.md)
- [Recherche und Quellen mit Einschränkungen](RESEARCH.md)

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

## Erster Trainingsdurchlauf

1. Bilder manuell hochladen oder über Frigate einreichen.
2. Im Manager Box zeichnen, Klasse angeben, bei Bedarf „False positive“
   auswählen und speichern. Falsch klassifizierte echte Objekte zusätzlich
   mit der richtigen positiven Klasse annotieren.
3. Alle Objekte der gewünschten Trainingsklassen prüfen, erst dann
   „Mark reviewed“ wählen. Annotationen ändern setzt diesen Status zurück.
4. Gewünschte Klassen kommasepariert angeben und zunächst 1 Epoche,
   Batchgröße 2 und 320 Pixel einstellen. Der POC benötigt mindestens zwei
   unabhängige positiv annotierte Bilder. Jede gewählte Klasse muss im
   Trainingssplit vorkommen; mehr Daten je Kamera sind sinnvoll.
5. Auftrag erstellen. Der Runner übernimmt ihn automatisch. Im Browser
   „Refresh“ aktualisiert den Status; nach Erfolg Ergebnis herunterladen.

Der Snapshot enthält nur explizit geprüfte Bilder. Rote Boxen bleiben im
Manifest erhalten, erscheinen aber niemals als positive YOLO-Targets.
Geprüfte reine Hintergrundbilder erhalten leere Targets. Der POC hat keine
direkte klassenbezogene negative Loss. `difficult`-Positivboxen werden als
gewöhnliche positive Targets exportiert und zusätzlich im Manifest markiert.

Ergebnisse: `best.pt`, `last.pt`, `metrics.csv`, `training.log` und
`provenance.json`. Die Checkpoints sind die Grundlage für späteren Export.
Sie können noch nicht direkt auf Coral oder als `plus://`-Modell geladen werden.

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
ersetztem Trainer; zusätzlich echter YOLOv9-CPU-Trainingslauf über eine Epoche
auf synthetischen Bildern im CUDA-Image einschließlich Checkpoints und
Validierung. Auf RTX wurde hier noch kein Lauf gemessen.

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
