# Vorhandene Modelle als Ausgangspunkt für Refinement

Stand: 23.10.2026. Nutzerziel: das bereits mit den eigenen Kamerabildern
angepasste Frigate+-YOLOv9-EdgeTPU-Modell extern weitertrainieren.

## Aktueller Befund

Der POC unterstützt Refinement von im Portal trainierten und ausdrücklich
gespeicherten originalen YOLOv9-s-Trainingscheckpoints. Er importiert keine
Frigate+-Modelle und bietet keinen Rückkonverter für Inferenzmodelle an.

Die aktuellen [Frigate+-Bedingungen](https://plus.frigate.video/terms-and-conditions/)
(wirksam seit 18.07.2026) schließen unter „Output / No AI/ML Training“ die
direkte und indirekte Verwendung von Service-Outputs zur Erstellung, zum
Training, zum Testen oder zur Verbesserung anderer KI-/ML-Systeme aus.
Zu diesen Outputs gehören ausdrücklich die Modelle und deren Ergebnisse.
Dass das Modell mit eigenen Bildern angepasst wurde, ist in dieser Klausel
keine Ausnahme. Eine individuelle abweichende Erlaubnis ist hier nicht bekannt.
Auch Distillation oder Pseudolabels aus diesem Modell wären daher keine
unabhängige Alternative unter diesen veröffentlichten Bedingungen.

Technisch ist ein EdgeTPU-Export kein originaler PyTorch-Trainingscheckpoint.
Coral dokumentiert die Richtung Training → Checkpoint → TFLite → EdgeTPU-
Kompilierung; ein kompilierter Detektor lässt sich nicht direkt als `--weights`
an unseren `train_dual.py`-Runner übergeben. Die
[Coral-Dokumentation](https://coral.ai/docs/edgetpu/retrain-detection/#compile-the-model-for-the-edge-tpu)
belegt diese Trennung der Trainings- und Inferenzartefakte. Das dort gezeigte
alte TensorFlow-Rezept wird nicht als Toolchain für unseren YOLOv9-Runner
übernommen.

Die [Frigate+-Dokumentation](https://docs.frigate.video/plus/#yolov9-details)
bestätigt eine gesonderte `edgetpu`-Variante. Der Name YOLOv9 allein belegt
keine Kompatibilität mit dem originalen YOLOv9-s-Rezept unseres Runners.
Das konkrete Nutzermodell wurde nicht heruntergeladen oder untersucht.

## Voraussetzungen für einen zukünftigen Import

Ein Import braucht einen zum Weitertrainieren freigegebenen originalen
Trainingscheckpoint sowie die passende Architekturdefinition, geordnete
Klassenliste und Trainings-/Vorverarbeitungsdetails. Eine Dateiendung `.pt`
allein reicht nicht. Ein bloßes Umbenennen von `.tflite` oder `.onnx` ist keine
Konvertierung in einen Trainingscheckpoint.

Falls diese Voraussetzungen vorliegen, ist ein eigenes, geprüftes Inkrement
nötig: vertrauenswürdige Herkunft und Nutzungsrechte dokumentieren, Checkpoint
und Architektur im Runner validieren, einen echten kurzen Trainingslauf
ausführen und erst danach das Modell für die vorhandene Refinement-Auswahl
registrieren. Der Manager soll weiterhin niemals PyTorch-Pickle laden.
Bei einer anderen YOLOv9-Architektur ist ein expliziter Trainingsadapter nötig;
die feste YOLOv9-s-Konfiguration darf nicht stillschweigend verwendet werden.

Danach können bestehende Kamerafilter, unveränderliche Elternreferenz,
Herkunftsdaten und optionales Replay wiederverwendet werden. Ein anschließender
Coral-Export bleibt ein separates, noch nicht implementiertes Arbeitspaket.

Unabhängig davon bleiben eigene Originalbilder als Kameradatensatz mit einem
geeigneten offen lizenzierten Basismodell nutzbar. Dafür sollen Originaldateien
und selbst geprüfte Annotationen verwendet werden, ohne Frigate+-Modelloutputs
als Trainingsquelle vorauszusetzen.
