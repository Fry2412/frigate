# Rechercheprotokoll

Dieses Protokoll hält den ursprünglichen Recherchestand vor der Umsetzung
fest. Die inzwischen implementierten POC-Funktionen und durchgeführten
Trainings-/Containertests stehen in der [aktuellen Anleitung](README.md).

Stand und Abruf: **23.10.2026**. Primärquellen: offizielle Dokumentationen,
Originalquellcode und Dokumentation der jeweiligen Projektmaintainer.
Beobachtete Versionen sind eine Momentaufnahme. Vor Implementierung erneut
prüfen und tatsächlich kompatible Versionen in Lockfiles und Image-Digests
festhalten. „Neueste Version“ allein beweist keine Ende-zu-Ende-Kompatibilität.

## Lokale Ausgangslage

Untersuchter Commit: `9e7adb2a66f1cb4c27d613ba9ed44e6d8edb35cd`.
Zu Beginn keine lokalen Änderungen. Kein separates Trainingsportal oder
zugehöriger Plan im durchsuchten Checkout gefunden. Ein anderswo vorhandener
Ansatz lässt sich später einbeziehen; hier wird dessen Implementierung nicht
behauptet. Der Checkout ist ein angepasster Fork, kein unveränderter Release.

| Lokale Quelle | Beobachtung / Bedeutung |
| --- | --- |
| `frigate/detectors/plugins/edgetpu_tfl.py` | Coral unterstützt bereits `ssd` und `yolo-generic`; beim YOLO-Pfad besondere quantisierte Box-/Klassentensoren, DFL-Decodierung, NMS. Kein Austausch des Plugins nötig. |
| dieselbe Datei, Initialisierung und `detect_raw` | Bei 320×320 erwartet der Pfad 2100 Kandidaten, 64 DFL-Kanäle und separate Klassenlogits. Klassenzahl 64 ist mehrdeutig; Ein-Klassen-Modelle passen nicht sauber zur Formheuristik. Lokale Grenzen, keine allgemeine YOLO-Regel. |
| `frigate/detectors/detector_config.py` | Modellpfad, Labelmap, Tensorlayout, Pixelformat, Eingabedatentyp und `model_type` sind Teil des Integrationsvertrags. |
| `frigate/api/event.py` | Plus-Einreichung und False-Positive-Markierung hängen ausdrücklich an Plus. Kein allgemeiner Portal-Endpunkt. |
| `frigate/api/media.py`, `frigate/util/file.py` | `GET /events/{event_id}/snapshot-clean.webp`; Kamera-Zugriffsprüfung und saubere WebP-/ältere PNG-Snapshots vorhanden. Ein JPG mit möglichen Overlays ist kein sauberer Ersatz. |
| `web/package.json` | Bestehend: React `^19.2.4`, Vite `^6.4.1`, TypeScript `^5.9.3`, Konva `^10.2.3`, React-Konva `^19.2.3`, Vitest und Radix. Das sind deklarierte Bereiche, keine Aussage über aufgelöste Versionen. |
| `notebooks/README.md` | Vorhandenes Notebook exportiert vortrainiertes YOLO-NAS; kein allgemeines Coral-Trainingsportal. |
| `UPSTREAM_INTEGRATION.md` | Fork enthält ausgewählte Backports und eigene Auth-/Streaming-/Multikamera-Änderungen. Daher Release-Kompatibilität zusätzlich gezielt testen. |

Alle acht angehängten Referenzbilder wurden angesehen. Sichtbar: Dashboard,
Kameraverwaltung, Bildwarteschlangen, Vorschläge, Patches, Editor mit Boxen,
separate Speicher-/Verifizierungsaktion, rote Negativbox, Tastaturhilfe und
Modelltabellen mit Basisversion, Zielhardware und Auflösung. Die Bilder belegen
Oberflächenverhalten, keine interne Trainingsimplementierung von Frigate+.

## Quellen und belastbare Aussagen

### Frigate und Trainingsdaten

1. [Frigate: Object Detectors](https://docs.frigate.video/configuration/object_detectors/)
   dokumentiert Coral mit TFLite, quantisierte YOLOv9-Modelle und deren
   Konfiguration. Verlinkter öffentlicher Coral-Beispielexport nutzt nur 17
   COCO-Klassen. Andere Backend-/Modellkombinationen haben eigene Grenzen.
   320×320 ist eine sinnvolle erste Profilgröße. Der lokale Code ist für den
   Fork zusätzlich maßgeblich; aktuelle `dev`-Doku kann davon abweichen.
2. [Frigate: Annotation](https://docs.frigate.video/plus/annotating/)
   beschreibt vollständige Objektannotation, KI-Vorschläge, Patches und rote
   False-Positive-Boxen. Bei falscher Klasse zusätzlich die richtige positive
   Klasse annotieren. Daraus folgt keine öffentlich dokumentierte spezielle
   Negative-Loss-Implementierung von Frigate+.
3. [Frigate: Erstes Modell](https://docs.frigate.video/plus/first_model/)
   nennt abwechslungsreiche Lichtbedingungen und als Plus-Erfahrungswert
   mindestens etwa 100 verifizierte Bilder pro Kamera für gute Resultate.
   Dies ist keine Erfolgsgarantie oder Mindestmenge für unser eigenes Training.
4. [Frigate: Clean-Snapshot-API](https://docs.frigate.video/integrations/api/event-snapshot-clean-events-event-id-snapshot-clean-webp-get/)
   dokumentiert den Clean-WebP-Endpunkt und kameraabhängige Autorisierung.
5. [Frigate: Snapshots](https://docs.frigate.video/configuration/snapshots/)
   dokumentiert Snapshot-Konfiguration und saubere Kopien. Verfügbarkeit und
   Aufbewahrung müssen beim Import geprüft werden.
6. [Ultralytics: Detection-Datenformat](https://docs.ultralytics.com/datasets/detect/)
   beschreibt je Objekt Klasse und normalisierte XYWH-Box; objektlose Bilder
   brauchen keine Labeldatei. Das Standardformat enthält keine negative Box
   pro Klasse. Als Formatreferenz verwendet, keine Ultralytics-Abhängigkeit.
7. [Original YOLOv9: Loss-Quellcode](https://github.com/WongKinYiu/yolov9/blob/main/utils/loss_tal.py)
   verarbeitet positive Targets und Klassifikations-/Box-Loss; ein separates
   Portalformat für „nicht Katze in dieser Box“ ist dort nicht definiert.
8. [CVAT: Formate](https://docs.cvat.ai/docs/dataset_management/formats/)
   dokumentiert COCO-/YOLO-Austausch. [YOLO-Export](https://docs.cvat.ai/docs/dataset_management/formats/format-yolo/)
   unterstützt keine Attribute. Deshalb eigene verlustfreie Portal-Metadaten
   neben standardisiertem Trainingsexport behalten.

### Coral und konkreter YOLOv9-Pfad

9. [Coral: Modellanforderungen](https://coral.ai/docs/edgetpu/models-intro/)
   fordert quantisierte Parameter, feste Tensorgrößen und unterstützte
   Operatoren. Nicht unterstützte Operationen können CPU-Ausführung erzwingen.
   Kompilierbarkeit allein belegt weder Beschleunigungsgrad noch Genauigkeit.
10. [Coral: Compiler](https://coral.ai/docs/edgetpu/compiler/)
    verlangt Linux x86-64; ARM64-Compiler wird seit 2.1 nicht angeboten.
    `edgetpu_compiler -s` liefert die Zuordnung von Operationen. Runtime-Ziel
    und Compiler müssen zusammenpassen. Alte Installationsbeispiele sind
    kein Grund, veraltete Paketverwaltungspraktiken zu übernehmen.
11. [Google: Full Integer Quantization](https://developers.google.com/edge/litert/conversion/tensorflow/quantization/post_training_integer_quant)
    erklärt repräsentative Kalibrierungsdaten und vollständige Quantisierung
    einschließlich Integer-I/O. Quantisierte Modelle müssen erneut bewertet
    werden. Nur Gewichte auf INT8 zu setzen reicht nicht.
12. [dbro: Coral-YOLOv9-Integration](https://github.com/dbro/frigate-detector-edgetpu-yolo9)
    verweist ausdrücklich auf integrierten Support ab Frigate 0.17 und warnt
    vor Nutzung des alten Detektorcodes. Historische Geschwindigkeitswerte
    sind Messungen auf der dortigen Hardware, keine Projektzusage.
13. [dbro: Trainingsnotebook](https://github.com/dbro/frigate-detector-edgetpu-yolo9/blob/main/notebooks/Fine_tune_YOLOv9_s_for_EdgeTPU_use_ReLU6_and_17_COCO_classes.ipynb)
    beschreibt YOLOv9-s mit ReLU6 und angepasstem Head sowie 17 Klassen.
    Ansatz zur Reproduktion, kein gewartetes Produktions-Trainingsframework.
14. [dbro: Exportnotebook](https://github.com/dbro/frigate-detector-edgetpu-yolo9/blob/main/notebooks/Convert_YOLO_v9_ReLU6_PyTorch_format_to_EdgeTPU_for_Google_Coral.ipynb)
    trennt DFL- und Klassenlogits, begrenzt Logits, konvertiert über ONNX und
    onnx2tf und quantisiert mit TFLiteConverter. Aufgezeichnete Umgebung:
    Python 3.12.12, Torch 2.8.0+cu128, ONNX 1.19.1, onnx2tf 1.28.5,
    TensorFlow 2.19.0. Das ist ein historischer Reproduktionsanker, keine
    heute erneut getestete Kombination. Enthält überholte Plugin-Hinweise.
15. [onnx2tf: Maintainer-Repository](https://github.com/PINTO0309/onnx2tf)
    dokumentiert ONNX-Konvertierungen. Versionswechsel können Graphen und
    numerisches Verhalten ändern; deshalb Rezeptversionen und Paritätstests.
16. [Google libedgetpu](https://github.com/google-coral/libedgetpu)
    ist seit 14.10.2025 archiviert.
    [Google edgetpu](https://github.com/google-coral/edgetpu) ist seit
    19.04.2026 archiviert. Daraus lässt sich ein Wartungsrisiko ableiten,
    aber kein genereller Funktionsverlust vorhandener Coral-Hardware.

### Modernes Portal, getrennte Toolchains und weitere Ziele

17. [React-Versionen](https://react.dev/versions): aktuell dokumentiert React
    19.3; das bestehende Frigate-Web verwendet einen älteren Versionsbereich.
18. [Vite-Support](https://vite.dev/releases): regulär gepflegte Linie 8.3;
    6.4 erhält laut Supporttabelle noch Sicherheitskorrekturen. Empfehlung:
    eigenes Portal-Lockfile und Migrationstests statt Frigate mitzumigrieren.
19. [FastAPI-Releases](https://fastapi.tiangolo.com/release-notes/):
    0.156.4 vom 21.10.2026 sichtbar. Neue Anwendung mit Pydantic 2 und
    unterstütztem Python planen; Patchstand beim Aufbau erneut prüfen.
20. [SQLAlchemy aktuell](https://docs.sqlalchemy.org/en/21/): 2.1.6 vom
    21.10.2026 sichtbar. [SQLite WAL](https://www.sqlite.org/wal.html):
    keine WAL-Datenbank auf einem zwischen Hosts geteilten Netzlaufwerk.
21. [uv: Locking](https://docs.astral.sh/uv/concepts/projects/sync/)
    dokumentiert Lock-/Sync-Verhalten. Getrennte Abhängigkeiten für API,
    Training und Konvertierung sind unsere Architekturentscheidung.
22. [PyTorch: ONNX](https://docs.pytorch.org/docs/stable/onnx)
    empfiehlt den `torch.export`-basierten Export mit `dynamo=True`.
    Der dokumentierte aktuelle Stand ist 2.14. Das beweist nicht, dass die
    ältere YOLOv9-Coral-Rezeptur unverändert damit arbeitet.
23. [ONNX Runtime: Execution Providers](https://onnxruntime.ai/docs/execution-providers/)
    dokumentiert mehrere Hardware-Backends. Ein Provider allein garantiert
    keine Kompatibilität mit Frigates Modell-Postprocessing.
24. [OpenVINO: PyTorch-Konvertierung, 2026](https://docs.openvino.ai/2026/openvino-workflow/model-preparation/convert-model-pytorch.html)
    dokumentiert einen weiteren Konvertierungspfad. Als späteres Profil
    prüfen; nicht jede Intel-NPU unterstützt jeden exportierten Graphen.
25. [TensorRT-Supportmatrix](https://docs.nvidia.com/deeplearning/tensorrt/latest/getting-started/support-matrix.html)
    ist maßgeblich für Plattform-/Versionskompatibilität. Keine universell
    portable Engine-Datei versprechen; am passenden Ziel bauen und prüfen.
26. [Rockchip RKNN-Toolkit2](https://github.com/airockchip/rknn-toolkit2)
    ist eine eigene Toolchain. Frigates unterstützte Ausgabekonventionen
    zusätzlich prüfen. Hailo-SDK-Details wurden hier nicht hinreichend
    verifiziert; Hailo bleibt zunächst ein untersuchungsbedürftiges Ziel.
27. [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
    dokumentiert Hosttreiber und Container-GPU-Einrichtung. Die Coral TPU
    ersetzt keine Trainings-GPU für das geplante Detektor-Fine-Tuning.
28. [Cloudflare: Service Tokens](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/)
    ermöglicht maschinelle Access-Authentisierung, zusätzlich zu unserer
    Runner-Identität. Kein Browser-Login auf dem Runner nötig.
29. [Cloudflare: HTTP 413](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/4xx-client-error/error-413/)
    nennt Uploadlimits nach Tarif, z. B. 100 MB bei Free/Pro. Resumierbare,
    kleinere Requests planen; tatsächliche Zone und Proxy-Limits testen.
30. [Original YOLOv9](https://github.com/WongKinYiu/yolov9) trägt GPL-3.0;
    [Ultralytics-Lizenz](https://github.com/ultralytics/ultralytics/blob/main/LICENSE)
    trägt AGPL-3.0. Quellcode, Gewichte, Datensätze und Compiler separat
    inventarisieren. Containertrennung ist keine pauschale Lizenzfreistellung.

## Aussagegrenzen

- Keine Trainings-, Export- oder Hardwareversuche wurden durchgeführt.
- Kein Nachweis, dass aktuelle Torch-/TensorFlow-/onnx2tf-Versionen gemeinsam
  den geforderten Coral-Graphen erzeugen. Das ist das erste technische Gate.
- Keine Aussage über die interne Loss-Funktion oder Trainingsdaten von Plus.
- Keine nachgewiesene Genauigkeitsparität zu Plus und keine feste Bildzahl,
  VRAM-Anforderung oder Trainingsdauer für den späteren Nutzerdatensatz.
- Exakte Hailo-/sonstige proprietäre Compiler-Versionen, Weitergaberechte und
  Plattformmatrizen brauchen eigene Recherche vor einem Supportversprechen.
