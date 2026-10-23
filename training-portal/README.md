# Eigenes Modell-Trainingsportal für Frigate

Planungsstand: 23. Oktober 2026. Arbeitsname: `training-portal`.

Ein eigenständig betreibbares Open-Source-Subprojekt für eigene Bildsammlungen,
Annotation, Vorannotation, Training und hardwareabhängige Frigate-Modellexporte.
Zuerst Google Coral mit YOLOv9; weitere Ziele über explizite, getestete Profile.
Frigate+ dient als Workflow-Inspiration. Dessen gemeinschaftlich trainierte
Basisgewichte, Daten oder Qualitätsniveau werden nicht vorausgesetzt.

Diese Dateien sind ein Forschungs- und Diskussionsentwurf, keine implementierte
Anwendung und keine bereits freigegebene technische Spezifikation.

- [Architektur, Produktumfang und Roadmap](tasks/plan.md)
- [Vorläufige Umsetzungsschritte mit Abnahmekriterien](tasks/todo.md)
- [Recherche und Quellen mit Einschränkungen](RESEARCH.md)

Die erste offene Hardwarefrage ist geklärt: Der Trainingsrechner steht noch
nicht fest; Linux x86-64 mit NVIDIA-GPU ist die vereinbarte Planungsannahme.
