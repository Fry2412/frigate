# Externe Trainingsdaten für das Frigate-Portal

Recherche vom 23.10.2026. Status: Vorschlag für den nächsten Ausbau, **kein
implementierter Dataset-Importer**. Geprüft wurden offizielle Dokumentationen,
Originalcode und die offizielle Open-Images-Liste der 600 Box-Klassen.

## Ergebnis

COCO 2017 ist die erste sinnvolle Quelle für einen breiten YOLO-Klassenumfang.
Open Images V7 eignet sich als gezielte Erweiterung. Eigene Kameraaufnahmen
bleiben für Perspektive, Nacht/IR und lokale Fehlalarme nötig. Klassenabdeckung
und Erkennungsqualität auf Überwachungskameras sind getrennte Abnahmeziele.

Zwei mögliche, versionierte Trainingsprofile:

- `coco80`: die 80 YOLO-COCO-Klassen in unveränderlicher Reihenfolge.
- `security-extended`: eine bewusst ausgewählte Sicherheitstaxonomie mit
  zusätzlichen Tierarten, gegebenenfalls Gesicht, Kennzeichen und Paket.
  Dies ist kein Versprechen vollständiger Frigate+-Klassenabdeckung.

Frigate unterstützt eigene Modelle mit passender Modellkonfiguration und
Labelmap. Seine Standardlabels und die Frigate+-Labels sind unterschiedliche
Vokabulare. `truck` wird standardmäßig als `car` angezeigt. Eine lange Labeldatei
beweist außerdem nicht, welche Klassen ein konkreter Modellcheckpoint gelernt
hat. Quellen: [Frigate-Objekte](https://docs.frigate.video/configuration/objects/),
[Frigate+-Klassen](https://docs.frigate.video/plus/#available-label-types).

## Geeignete Quellen

### COCO 2017: zuerst unterstützen

COCO hat 80 Objektkategorien. Das von unserem Runner verwendete Original-YOLOv9
enthält dafür eine Datenkonfiguration mit 118.287 Trainings- und 5.000
Validierungsbildern. Der große Jahrgangsunterschied ist kein Grund, die
Benchmarkdaten durch einen ungeprüften neueren Datensatz zu ersetzen.
Quellen: [COCO](https://cocodataset.org/),
[gepinntes YOLOv9-coco.yaml](https://github.com/WongKinYiu/yolov9/blob/5b1ea9a8b3f0ffe4fe0e203ec6232d788bb3fcff/data/coco.yaml).

Importweg: originale COCO-Instanzannotation (JSON) und Bilder einlesen, explizit
`category_id -> Profilklasse -> fortlaufende Trainings-ID` abbilden und nach
YOLO exportieren. Quelldateien, Original-IDs und Lizenzmetadaten behalten.
COCO-Kategorie-IDs und Frigates Standard-Labelmap dürfen nicht einfach als
YOLO-Indizes übernommen werden. Die
[offizielle COCO API](https://github.com/cocodataset/cocoapi) ist die
Formatreferenz. `iscrowd` benötigt eine bewusste Importregel.

Annotationen sind CC BY 4.0; Bildrechte sind davon getrennt und richten sich
nach den jeweiligen Flickr-Bedingungen. Nicht pauschal alle Bilder als
CC BY 4.0 deklarieren. Quelle:
[COCO-Nutzungsbedingungen](https://github.com/cocodataset/cocodataset.github.io/blob/master/dataset/termsofuse.htm).

### Open Images V7: gezielte Ergänzung

V7 ist weiterhin die offiziell ausgewiesene aktuelle Version. Die
Detektionsdaten umfassen 600 Box-Klassen auf rund 1,9 Mio. Bildern. Die größeren
Zahlen für Bildlabels und Punktlabels sind keine entsprechend großen
Bounding-Box-Klassenlisten. Quelle:
[offizielle Beschreibung](https://storage.googleapis.com/openimages/web/factsfigures_v7.html).

In der offiziellen
[Box-Klassenliste](https://storage.googleapis.com/openimages/v5/class-descriptions-boxable.csv)
wurden unter anderem folgende Kandidaten geprüft:

| Quellklasse | Mögliche Portal-Klasse | Mappingregel |
| --- | --- | --- |
| Deer, Fox, Raccoon | deer, fox, raccoon | Jeweils eigene Klasse |
| Squirrel, Rabbit, Skunk, Kangaroo, Goat | gleichnamige englische Klassen | Jeweils eigene Klasse |
| Human face | face | Gesichtserkennung als Detektionsklasse; keine Identität |
| Vehicle registration plate | license_plate | Box des Kennzeichens; keine OCR |
| Cattle | cow | Definition prüfen, kein blindes Umbenennen |
| Waste container | waste_bin | Quelle kann weiter gefasst sein; prüfen |
| Person, Man, Woman, Boy, Girl | person | Hierarchie auflösen, doppelte Instanzen verhindern |
| Box | keine automatische Zuordnung zu package | Eine beliebige Kiste ist kein zugestelltes Paket |

Die Beispiele belegen vorhandene Klassen, nicht ausreichende Anzahl oder
passende Kameraperspektiven. Pro Klasse müssen Box-/Bildzahlen, Größe und
Bildqualität vor der Aufnahme ins Profil ermittelt werden. Lieferdienstlogos,
Robotermäher oder bestimmte Fahrzeuguntertypen sind damit nicht automatisch
abgedeckt.

Annotationen: CC BY 4.0. Bilder werden als CC BY 2.0 ausgewiesen, aber Google
garantiert deren individuellen Lizenzstatus ausdrücklich nicht. Herkunft und
Attribution deshalb pro Bild mitführen. Quelle:
[Open-Images-Lizenzen](https://storage.googleapis.com/openimages/web/factsfigures_v7.html#licenses).

### Weitere Quellen: nachrangig

- **LVIS:** über 1.200 Kategorien; die API kennt explizit unvollständig
  annotierte und bestätigte negative Kategorien. Kein unkomplizierter
  Standard-YOLO-Import. [LVIS](https://www.lvisdataset.org/),
  [Original-Evaluationscode](https://github.com/lvis-dataset/lvis-api/blob/master/lvis/eval.py).
- **Objects365:** die offizielle Downloadseite beschränkt die Nutzung auf
  akademische Zwecke und untersagt das Weiterverteilen der Bilder. Deshalb
  keine allgemeine Standardquelle für unser Portal.
  [Originalbedingungen](https://www.objects365.org/download.html).
- **WIDER FACE:** spezialisierte Gesichtsdaten, offiziell CC BY-NC-ND.
  Keine pauschale Freigabe zum Bündeln mit dem Open-Source-Produkt ableiten.
  [Projektseite und Lizenz](https://mmlab.ie.cuhk.edu.hk/projects/WIDERFace/index.html).

## Wichtigste technische Einschränkung: fehlende Annotationen

Open Images unterscheidet bestätigte positive, bestätigte negative und
unbekannte Klassen pro Bild; Hierarchien und Gruppenboxen gehören ebenfalls
zum Format. Fehlende Labels sind keine bestätigten Negativbeispiele.
Quellen: [Annotationsverfahren](https://storage.googleapis.com/openimages/web/factsfigures_v7.html#bounding-boxes),
[Boxformat](https://storage.googleapis.com/openimages/web/download_v7.html#bounding-boxes).

Konkretes Problem unseres vorgeschlagenen erweiterten Profils: Ein COCO-Bild
kann korrekt als `person` annotiert sein, ohne eine `face`-Annotation zu haben.
Für ein Modell, das auch `face` lernen soll, ist diese Annotation unvollständig.
Bloßes Zusammenkopieren beider Datenquellen würde das nicht beheben.

Unser gepinntes Standard-YOLOv9-Rezept hat keine Schnittstelle für eine solche
Unbekannt-Maske pro Bild und Klasse. Diese Einschätzung folgt aus dem
[verwendeten Loss-Code](https://github.com/WongKinYiu/yolov9/blob/5b1ea9a8b3f0ffe4fe0e203ec6232d788bb3fcff/utils/loss_tal_dual.py).

Zulässige Integrationsstrategien:

1. Für das Profil vollständig geprüfte Bilder verwenden bzw. nachannotieren.
2. Alternativ das Trainingsrezept gezielt um Verlustmaskierung für unbekannte
   Klassen und eine passende Behandlung ignorierter Regionen erweitern.
3. Bei nicht unterstützten Crowd-/Gruppenregionen betroffene Bilder zunächst
   ausschließen, statt nur die Box zu löschen und das Bild als Hintergrund
   weiterzuverwenden.

Für den nächsten kleinen Implementierungsschritt ist Variante 1 mit `coco80`
am einfachsten überprüfbar. Eine automatische KI-Vorannotation kann später
Prüfarbeit reduzieren, ersetzt aber keine bestätigte Ground Truth.

## Training mit eigenen Bildern

Mit vertrauenswürdigen vortrainierten YOLOv9-Gewichten beginnen. Bei jeder
Anpassung öffentliche Referenzdaten und eigene geprüfte Kamerabilder gemeinsam
verwenden und die Mischung experimentell bestimmen. Keine feste optimale Quote
ist durch diese Recherche belegt.

Nur neue Klassen oder eigene Bilder nachzutrainieren kann bisherige Fähigkeiten
verschlechtern. Dies ist als Catastrophic Forgetting auch für Objektdetektoren
belegt: [Originalarbeit, ICCV 2017](https://arxiv.org/abs/1708.06977).

Wichtig: Die aktuelle POC-Klassenliste definiert die **gesamte** Ausgabe des
Trainingsmodells. `person,car` bedeutet kein unverändert fortbestehendes
80-Klassen-Modell. Der
[Originaltrainer](https://github.com/WongKinYiu/yolov9/blob/5b1ea9a8b3f0ffe4fe0e203ec6232d788bb3fcff/train_dual.py)
baut das Modell mit der Datensatz-Klassenzahl neu auf und übernimmt passende
Gewichtstensoren; er führt keine semantische Neuzuordnung nach Klassennamen aus.

Bewertung getrennt auf öffentlichen Referenzdaten und zurückgehaltenen eigenen
Aufnahmen: je Klasse Precision/Recall, kleine/entfernte Objekte und Tag/Nacht.
Splits vor dem Mischen festlegen; Duplikate und zeitliche Nachbaraufnahmen
dürfen nicht zwischen Training und Bewertung verteilt werden.

## Vorgeschlagene Einbindung in unsere zwei Dienste

1. **Manager:** Profile, Quellen, akzeptierte Nutzungsbedingungen, Mapping,
   Bild-/Klassenstatistik und Prüfstatus verwalten. Für externe Daten eigene
   Herkunfts- und Vollständigkeitsfelder vorsehen; nicht automatisch das
   bestehende manuelle `verified` setzen.
2. **Runner:** große öffentliche Datenbestände einmalig in einem persistenten
   Volume cachen. Nur freigegebene Quellen/Rezepte verwenden. Dateiprüfsummen,
   Quellversion, Auswahl-IDs und Mapping im unveränderlichen Jobmanifest fixieren.
3. **Job:** Referenz auf den versionierten Basisdatensatz plus Snapshot der
   eigenen Bilder. Keinen veränderlichen Ordnerinhalt unbemerkt nachladen.
4. **Export:** ein gemeinsames YOLO-Verzeichnis bzw. eine erzeugte Bildliste mit
   einheitlicher Klassenreihenfolge bereitstellen; Herkunftsmetadaten daneben
   verlustfrei speichern.

Das vorhandene Manager-Snapshotlimit von 5.000 Bildern und 256 MiB sowie der
512-MiB-Runnertransfer sind POC-Grenzen. Vollständiges COCO passt nicht in diesen
Pfad. Ein lokaler Runner-Datencache vermeidet außerdem, große Basisdatensätze
immer wieder durch den Frigate-Rechner und den Tunnel zu übertragen.

[FiftyOne](https://docs.voxel51.com/dataset_zoo/datasets/open_images_v7.html)
unterstützt selektive Open-Images-Downloads nach Klasse, Split und Samplelimit.
Es ist ein mögliches optionales Importwerkzeug, keine erforderliche weitere
Portalinstanz. Bei Auswahl nach Klassen alle relevanten Begleitlabels erhalten
(`only_matching=False`). `max_samples` ist keine garantierte Quote pro Klasse;
Klassenbalance gesondert prüfen. Für einen schlanken dauerhaften Importer sind
direkte COCO-JSON-/Open-Images-CSV-Adapter eine Alternative.

Der Datensatzimport kann architekturunabhängig sein. Die erfolgreiche
Coral-Konvertierung, unterstützte Klassenzahl und Latenz müssen anschließend
für jedes Modellprofil separat nachgewiesen werden. Eine breite Taxonomie
ist allein noch kein Coral-kompatibles Modell.
