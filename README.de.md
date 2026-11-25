# Star Gazing Control Center by TheSkyCoder

> **Testversion** – nach 10 Starts gesperrt (Hinweis ab Start 8).  
> Vollversion auf Anfrage: Facebook-Profil **„Bönn Ingstedt“** – am einfachsten über die Suche nach **„TheSkyCoder“**.

PC-Steuerung für ZWO Seestar S30, S30 Pro, S50 und S50 Pro. © 2026 TheSkyCoder.

Inoffizielle Desktop-App (Windows, macOS, Linux) zur Steuerung aller aktuellen Seestar-Modelle über **WLAN** (gleiches Netzwerk) und **Bluetooth LE**. Nicht von ZWO – Nutzung auf eigenes Risiko.

*English version: [README.md](README.md)* · **📖 Bedienungsanleitung (englisch): [MANUAL.md](MANUAL.md)**

## Installation (Windows)

1. Python 3.10 oder neuer von python.org installieren (Haken bei „Add Python to PATH“ setzen).
2. Ordner entpacken, `start.bat` doppelklicken. Beim ersten Start werden die Pakete automatisch installiert.

Manuell: `pip install -r requirements.txt` und dann `python star_gazing_control_center.py`.

## Erste Schritte

Beim ersten Start öffnet sich ein **Einrichtungsassistent** mit drei Schritten:

1. **Standort** – automatisch ermitteln lassen (mit deinem Einverständnis, siehe unten) oder Breite/Länge eintippen.
2. **Seestar hinzufügen** – im Netzwerk suchen oder IP-Adresse eintragen; beliebig viele Geräte.
3. **Anmeldeschlüssel** – nur bei neuerer Firmware nötig (siehe unten), kann auch später eingetragen werden.

Danach „Verbinden“: Die App verbindet alle Geräte und erkennt das Modell selbst. Es ist nichts vorbelegt – kein Filter, kein Gerät, kein Plan. Einen externen 2"-Filter trägst du nur ein, wenn du einen benutzt (Tab „Fokus & Filter“).

Den Assistenten kannst du jederzeit im Tab „WLAN“ erneut öffnen. Dort gibt es auch **„Alles zurücksetzen …“**: löscht Geräteliste, Standort, Filter, gemerkte Fokuspositionen, Zeitpläne und eigene Filter – die App startet danach wie frisch installiert.

## Funktionen

| Tab | Was geht |
|---|---|
| Übersicht | Mehrere Seestars per IP-Adresse verwalten, hinter jedem Gerät ein Verbinden/Trennen-Knopf, Status/Modell/Frames/Akku (⚡ beim Laden)/freier Speicher je Gerät, Gruppensteuerung für alle markierten Geräte gleichzeitig, Vorschau-Fenster je Gerät |
| Standort | Position automatisch ermitteln (Windows-Standortdienst, Seestar, optional Internet) mit einmaligem, widerrufbarem Einverständnis – oder manuell eingeben; Zeit + Standort an Seestar senden |
| Wetter & Tipps | Wolken- (tief/mittel/hoch) und Regenvorhersage für 48 h, Dunkelheit und Mond, Bewertung der Nacht und Vorschläge, was sich an deinem Standort heute am besten lohnt – auf Wunsch gleich als Zeitplan |
| Steuerung | Arm öffnen, parken, Not-Stopp, Joystick (auch Pfeiltasten), Fokus ±, Autofokus, GoTo mit Katalog oder RA/Dec, Plate Solve, aktuelle Position |
| Fokus & Filter | Externen Filter je Gerät eintragen, Präzisions-Autofokus (App) mit Schärfekurve, gemerkte Positionen je Gerät und Filter, Arm-Schutz |
| Einstellungen & Aufnahme | Alle Geräteeinstellungen wie in der Seestar-App, pro Gerät (siehe unten) · Stacking starten/stoppen · Frame-Zähler |
| EQ-Modus | Umschalten Alt-Az ↔ EQ, Live-Libelle (Neigungssensor), Wedge-Winkel aus dem Breitengrad, 3-Punkt-Polausrichtung mit Zielscheibe und automatischem Nachmessen, Ampel-Checkliste, Nachführ-/Belichtungstest mit Frame-Quote |
| GoTo | Objektkatalog (alle Messier, Nebel, helle NGC/IC, deutsche Namen; per Suche zusätzlich alle NGC/IC, Sh2, LDN) mit Suche, aktueller Höhe, Richtung, Kulmination und Bildfeld-Check; GoTo für das aktive Gerät oder alle markierten |
| Mosaik | Raster-Mosaik (Spalten × Zeilen, Überlappung, Zeit pro Panel, Autofokus je Panel) und Framing-Mosaik (Seestar-intern, Größe und Drehung) – pro Gerät, mit Planansicht und Fortschritt |
| Zeitpläne | Abläufe aus Zielen, Mosaiks, Wartezeiten und Autofokus; Mindesthöhe je Ziel; Startzeit; Endaktion; speichern/laden; pro Gerät oder Gruppe; fortsetzbar |
| Vorschau | Live-Vorschau und aktuelles Stack-Bild mit Auto-Stretch (Stärke einstellbar), automatische Aktualisierung bei jedem neuen Stack-Frame, PNG speichern |
| WLAN | Seestar per UDP-Broadcast finden, verbinden, Anmeldung, Zeit + Standort senden, Gerätestatus |
| Bluetooth | Seestar per BLE finden, hinter jedem gefundenen Gerät verbinden/trennen, alle Dienste/Characteristics anzeigen, lesen, schreiben, Benachrichtigungen mitschneiden |
| Konsole | Beliebigen JSON-RPC-Befehl senden |

Alles, was du einstellst (Geräteliste, Standort, PEM-Pfad, Filter, Fokuspositionen, Zeitpläne), wird in `%USERPROFILE%\.star_gazing_control_center.json` gespeichert. Einstellungen einer früheren Version (`.seestar_control.json`) werden beim ersten Start übernommen.

## Aussehen, Sprache, Fenster

**Design:** Oben rechts unter „Design“ wählst du *Blau* (Standard, Tasten in einem helleren Blau abgesetzt), *Dunkel* oder *Nacht (rot)* für die Beobachtung am Teleskop. „Größe“ skaliert die ganze Oberfläche (wirkt nach einem Neustart).

**Sprache:** Beim ersten Start nimmt die App die Sprache deines Systems. Umstellen kannst du jederzeit über das Auswahlfeld **„Sprache“** – oben in der App-Leiste und oben in jedem weiteren Fenster (Vorschau, Einstellungen, Assistent …). Der Wechsel wirkt sofort, ohne Neustart.

Mitgeliefert: Deutsch, English, Français, Español, Italiano, Nederlands, Polski, Português, 中文（简体）, 日本語. Fehlt in einer Sprache ein Text, erscheint er auf Englisch.

*Weitere Sprache hinzufügen:* Tab „WLAN“ → **„Neue Sprache hinzufügen …“** speichert eine Vorlage mit allen Texten (deutsch und englisch als Hilfe). Übersetzungen eintragen, die erste Zeile `# name: …` anpassen und die Datei als `<Sprachkürzel>.txt` (z. B. `fi.txt`, `sv.txt`, `tr.txt`) in den Ordner `lang` neben der App legen. Beim nächsten Start steht sie in der Auswahl; mit dem Kürzel der Systemsprache wird sie auch automatisch gewählt.

**Fenster:** Alle Fenster lassen sich frei in der Größe ändern; Position und Größe werden gemerkt, auch über mehrere Monitore. **F11** schaltet auf Vollbild. Die **Vorschaubilder** jedes Teleskops öffnen sich in eigenen Fenstern (Übersicht → „Vorschau“ oder Doppelklick), die du z. B. auf einen zweiten Monitor schieben kannst – mit „Immer im Vordergrund“ und Vollbild. Beim nächsten Start gehen sie an derselben Stelle wieder auf.

**Seite zurücksetzen:** Der Knopf **„↺ Seite zurücksetzen“** oben rechts setzt nur die gerade sichtbare Seite auf Grundeinstellung (vorher wird angezeigt, was genau zurückgesetzt wird). Gespeicherte Pläne, Filter und Fokuspositionen bleiben dabei erhalten; alles auf einmal löscht „Alles zurücksetzen …“ im Tab „WLAN“.

## Wetter & Tipps

Der Tab zeigt für deinen Standort die nächsten 48 Stunden: Bewölkung gesamt und getrennt nach tiefen, mittleren und hohen Wolken, Regenwahrscheinlichkeit, Taupunkt (Hinweis auf die Anti-Tau-Heizung), Böen, dazu Dämmerung/Dunkelheit und Mondhöhe. Daraus bewertet die App die kommende Nacht (gut / teilweise / eher nicht) und nennt die beste Phase.

**Was lohnt sich heute?** Aus dem Objektkatalog rechnet die App für dein aktives Gerät aus, welche Objekte heute Nacht lange genug über der Mindesthöhe stehen, wann sie am höchsten sind, wie weit der Mond entfernt ist, ob sie ins Bildfeld passen (sonst Mosaik-Hinweis) und ob dein externer Filter passt (mit Schmalbandfilter werden Emissionsnebel bevorzugt, bei hellem Mond ebenfalls). Wenn Wetterdaten da sind, zählen nur klare Stunden. Ein Klick auf „Plan für heute Nacht erstellen“ macht daraus einen Zeitplan, den du im Tab „Zeitpläne“ prüfen und starten kannst; einzelne Objekte gehen direkt zu GoTo, Zeitplan oder Mosaik.

**Datenschutz:** Wetterdaten kommen vom kostenlosen Dienst **Open-Meteo.com** (Daten unter CC BY 4.0). Abgerufen wird erst, nachdem du einmal zugestimmt hast; dabei wird nur dein Standort, auf ca. 1 km gerundet, gesendet – ohne Konto und ohne weitere Daten. Das Häkchen „Wetterdaten abrufen“ schaltet es jederzeit wieder aus. Sonne und Mond rechnet die App selbst, dafür geht nichts ins Internet.

## Standort

Der Standort wird für die Uhrzeit und Nachführung am Seestar, die Objekthöhen und Kulmination im GoTo-Tab, die Mindesthöhe in Zeitplänen und den Wedge-Winkel im EQ-Modus gebraucht.

**Automatisch – nur mit deinem Einverständnis.** Beim ersten Bedarf fragt die App **einmal**, ob sie den Standort selbst ermitteln darf, und welche Quellen sie dafür nutzen darf:

| Quelle | Genauigkeit | Was passiert mit den Daten |
|---|---|---|
| Windows-Standortdienst | meist Meter bis wenige km | bleibt auf deinem PC. Dafür muss in Windows unter *Einstellungen › Datenschutz › Standort* der Zugriff für Desktop-Apps erlaubt sein. |
| Standort aus dem Seestar | wie in der Seestar-App gesetzt | wird nur aus deinem eigenen Teleskop gelesen |
| Ungefähr über die Internet-Adresse | Stadt/Region, ca. 5–50 km | deine öffentliche IP-Adresse geht an freeipapi.com bzw. ipwho.is – **standardmäßig aus** |

Die Quellen werden in dieser Reihenfolge probiert, die erste erfolgreiche gewinnt. Mit Einverständnis wird der Standort bei jedem Start aktualisiert; eine ungenaue (Internet-)Position wird automatisch durch die des Seestar ersetzt, sobald eines verbunden ist.

**Widerrufen** kannst du jederzeit im Tab **„Standort“**: Häkchen „Standort automatisch ermitteln“ entfernen. Die App fragt, ob die letzte Position als manuelle Eingabe bleiben oder gelöscht werden soll, und ermittelt danach nichts mehr selbst.

**Manuell eingeben** (Tab „Standort“, sobald die automatische Ermittlung aus ist): Breite und Länge als Dezimalgrad (`52,52` oder `52.52`) oder in Grad/Minuten/Sekunden (`52°31'12" N`, `13° 24′ O`); Süden und Westen mit „-“ oder S/W. Optional ein Ortsname. Die Werte findest du in jeder Karten-App.

Die Zeitzone für das Seestar nimmt die App aus den Einstellungen deines PCs.

## Zeit und Standort

Bei jedem Verbinden schickt die App wie die Seestar-App automatisch Uhrzeit, Zeitzone und Standort an das Seestar – wichtig für genaue GoTos. Abschaltbar im Tab „WLAN“ unter „Initialisierung“. Läuft auf dem Gerät gerade ein Ablauf (Zeitplan/Mosaik), wird beim Neuverbinden nichts gesendet. Ist noch kein Standort festgelegt, geht nur die Uhrzeit hinaus.

## Mehrere Seestars gleichzeitig

Im Tab **Übersicht** trägst du jedes Seestar mit Name und IP-Adresse ein (oder „Netzwerk durchsuchen“ fügt alle gefundenen hinzu). Die Liste wird gespeichert.

- **Klick auf eine Zeile** macht das Gerät zum *aktiven Gerät*. Die Tabs Steuerung, Einstellungen, Vorschau und Konsole beziehen sich darauf.
- **Kästchen vorn in der Zeile** nimmt das Gerät in die Gruppe auf oder heraus.
- **Verbinden / Trennen** hinter jedem Gerät: Der Knopf wechselt je nach Zustand (grün „Verbinden“, rot „Trennen“, während des Aufbaus „Abbrechen“). Im Tab „Bluetooth“ gibt es dasselbe für jedes gefundene BLE-Gerät.
- **Oben bei „Befehle an“** stellst du um: *aktives Gerät* oder *alle markierten*. Mit „alle markierten“ gehen Joystick, GoTo, Fokus, Einstellungen usw. aus allen Tabs gleichzeitig an die ganze Gruppe.
- Die Knöpfe im Kasten **Gruppe** wirken immer auf alle markierten Geräte, egal was oben eingestellt ist: verbinden, Arm öffnen, GoTo, Stacking starten/stoppen, Autofokus, parken, Not-Stopp.
- **Doppelklick** auf ein Gerät (oder „Alle Vorschauen öffnen“) öffnet ein eigenes Vorschau-Fenster pro Seestar mit eigener Stretch-Einstellung und eigenem PNG-Export.

Jedes Gerät hat seine eigene Verbindung; alle nutzen denselben PEM-Schlüssel aus dem Tab „WLAN“.

## Einstellungen pro Gerät

Jedes Seestar hat seine eigenen Einstellungen. Im Tab „Einstellungen & Aufnahme“ siehst du die des aktiven Geräts; über „⚙ Einstellungen“ in der Übersicht öffnet sich für jedes Gerät ein eigenes Fenster. Beim Verbinden liest die App die aktuellen Werte aus dem Gerät, jede Änderung geht sofort an genau dieses Gerät.

| Bereich | Einstellungen |
|---|---|
| Stacking | Belichtung (2/5/10/20/30 s, 60 s nur im EQ-Modus = Maximum), Gain, LP- bzw. Duo-Band-Filter, Filter automatisch wählen, Dithering (an/aus, Abstand, Intervall), Dark-Kalibrierung, Einzelframes speichern (nein / nur gute / alle), Serienaufnahme (ohne Stacken), 4K-Modus (Drizzle 2×), Hintergrund-Extraktion, Sternkorrektur, Flugzeug-/Satellitenspuren entfernen, nach GoTo automatisch stacken |
| Fokus | Smart-AF (nach GoTo / bei Temperaturdrift), Autofokus vor jedem Ziel |
| Gerät | Anti-Tau-Heizung (An/Aus – die Firmware kennt keine Stufen), automatisch ausschalten, Temperatureinheit, EQ-Polausrichtung kalibrieren, Expertenmodus |
| Live-Ansicht | Zoom 1× / 2× / 4× (Sonne, Mond, Planeten), Belichtung des Live-Bildes |
| Weitwinkel (S30, S30 Pro, S50 Pro) | Weitwinkelkamera verwenden, Weitwinkel in 4K, Weitwinkel-Entrauschen |

„–“ heißt: Das Gerät meldet diesen Wert nicht (z. B. Gain, oder die Funktion gibt es in deiner Firmware noch nicht). „Auf alle markierten übertragen“ kopiert die Einstellungen eines Geräts auf die ganze Gruppe; Weitwinkel-Optionen nur dort, wo es eine Weitwinkelkamera gibt.

- **Befehle an „alle markierten“:** Eine Änderung im Tab „Einstellungen“ geht dann an alle markierten Geräte; Optionen, die ein Modell nicht hat, werden dort übersprungen. Im eigenen Einstellungsfenster eines Geräts gilt die Änderung immer nur für dieses Gerät.
- **Gerät nicht verbunden:** Die Änderung wird gemerkt (auch über einen Neustart der App) und beim nächsten Verbinden gesendet; im Protokoll steht, wie viele Einstellungen nachgereicht wurden.
- **Alle Ansichten gleich:** Tab „Einstellungen“ und das eigene Einstellungsfenster zeigen immer denselben Stand. Ändert jemand in der Seestar-App auf dem Handy etwas, liest die App die Einstellungen automatisch neu.
- **Handy-App zeigt alte Werte:** Die Seestar-App auf dem Handy aktualisiert sich nicht von selbst, wenn du am PC etwas änderst. Bei der Hintergrund-Extraktion (DBE) die Einstellungsseite in der Handy-App schließen und wieder öffnen; bei der Tauheizung die Handy-App ganz schließen und neu verbinden.
- **Nicht angenommen:** Lehnt das Seestar einen Wert ab, zeigt die App wieder den echten Stand des Geräts. Nach jeder Änderung liest die App den Wert außerdem zurück und sagt im Protokoll Bescheid, wenn das Gerät ihn nicht übernommen hat.
- **Nachlesen:** Solange der Tab „Einstellungen“ oder ein Einstellungsfenster offen ist, liest die App die Werte alle 30 s neu – auch Änderungen aus der Handy-App, die das Seestar nicht von selbst meldet.
- **Arm-Schutz:** „Automatisch ausschalten“ und „Nach Seestar-Plan Arm schließen“ lassen sich bei aktivem Arm-Schutz nicht einschalten – auch nicht über „Auf alle markierten übertragen“. Mit eingetragenem Filter gilt das auch für Smart-AF und „Autofokus vor jedem Ziel“.

## Mosaik

Beim ersten Öffnen des Tabs erklärt ein kurzer Hinweis die Zeichnung (Felder, Reihenfolge, Überlappungsstreifen). Mit „Nicht wieder anzeigen“ bleibt er weg; im Tab „WLAN“ holt **„Hinweise wieder anzeigen“** ihn zurück.

Im Tab „Mosaik“ wählst du den Mittelpunkt (Katalog, RA/Dec oder aus „Steuerung“) und eine der beiden Arten:

- **Raster-Mosaik:** Spalten × Zeilen (bis 6 × 6), Überlappung, Zeit pro Panel, optional Autofokus vor jedem Panel. Das Seestar fährt die Panels in Schlangenlinie ab und speichert jedes als eigenes Ziel (`Name_R1C1`, `Name_R1C2` …). Zusammensetzen dann z. B. in Siril oder Astro Pixel Processor.
- **Framing-Mosaik:** die Mosaik-Funktion der Seestar-Firmware – Größe 1,5× bis 4× des Bildfelds, Drehung −90° bis +90°, eine Gesamtzeit. Ergebnis ist ein einziger Stack.

Jedes Gerät rechnet mit seinem eigenen Bildfeld, ein S30 Pro deckt mit 2 × 2 also eine viel größere Fläche ab als ein S50. Der Fortschritt steht in der Übersicht in der Spalte „Auftrag“. Starten geht an das Ziel aus „Befehle an“ oder an alle markierten Geräte; jedes läuft unabhängig. Die Planansicht zeigt das Bildfeld des aktiven Geräts (Norden oben, Osten links). Die Bildfeldmaße sind Näherungen; im Alt-Az-Modus dreht sich das Feld im Lauf der Nacht.

### PC/Laptop nicht in den Standby

Solange auf mindestens einem Gerät ein Mosaik läuft, verhindert die App, dass PC oder Laptop wegen Untätigkeit in den Standby oder Ruhezustand gehen – sonst würde die Steuerung mitten im Mosaik einschlafen. Das gilt **nur für Mosaiks** (nicht für normale Zeitpläne oder Einzelaufnahmen). Ist das letzte Mosaik fertig, abgebrochen oder pausiert, gibt die App die Sperre sofort wieder frei, ebenso beim Beenden. Der Bildschirm darf dabei dunkel werden.

Abschalten kannst du das im Tab „Mosaik“ unter **„PC / Laptop“**; dort steht auch, ob die Sperre gerade aktiv ist. Technisch: Windows `SetThreadExecutionState`, macOS `caffeinate`, Linux `systemd-inhibit`.

Grenzen: Zuklappen des Laptops, der Ein-/Aus-Knopf oder ein fast leerer Akku lösen den Standby trotzdem aus. Laptop also aufgeklappt lassen und ans Netzteil hängen (oder in den Windows-Energieoptionen „Beim Zuklappen: Nichts unternehmen“ wählen).

### Verbindungsabbrüche und Fortsetzen

Die App steuert den Ablauf (Panel anfahren, stacken, nach der Zeit weiter), deshalb sollte sie während eines Mosaiks laufen. Sie ist aber gegen Abbrüche abgesichert:

- **Automatisch neu verbinden** (Schalter im Tab „WLAN“, standardmäßig an): Reißt die Verbindung ab – auch „still“, z. B. nach dem Ruhezustand des Laptops (nach 45 s ohne Antwort) –, verbindet die App jedes Gerät selbst neu, mit wachsendem Abstand bis 1 Minute.
- **Mosaik läuft weiter:** Während der Unterbrechung wartet der Ablauf bis zu einer Stunde. Danach prüft er, ob das Seestar noch stackt. Wenn ja, geht es nahtlos weiter; wenn nicht (z. B. nach einem Neustart des Seestar), wird das Panel erneut angefahren und das Stacking fortgesetzt, ohne den bisherigen Stack zu verwerfen. Die Zeit läuft nach der Uhr weiter, ein Abbruch verlängert das Mosaik also nicht.
- **Fortsetzen nach Neustart der App:** Der Stand (Panel, Endzeit) wird laufend gespeichert. Schließt du die App mitten im Mosaik oder stürzt der PC ab, fragt die App beim nächsten Verbinden: „Mosaik fortsetzen?“. Pausierte Mosaiks stehen in der Übersicht in der Spalte „Auftrag“.
- **„Trennen“** pausiert ein laufendes Mosaik ebenfalls (fortsetzbar). **„Mosaik abbrechen“** beendet es endgültig und stoppt das Stacking.

Trotzdem empfehlenswert: Laptop ans Netzteil und den Ruhezustand während der Nacht abschalten – sonst stackt das Seestar während der Pause zwar weiter, wechselt aber nicht zum nächsten Panel.

## GoTo und Objektkatalog

Der Tab **„GoTo“** enthält rund 1100 Objekte: alle Messier-Objekte, alle Nebel, Sternhaufen und Galaxien bis etwa 11 mag sowie benannte Objekte (Pferdekopf, Doppelhaufen, Stephans Quintett …), die bekannten mit deutschem Namen – dazu der **Südhimmel** (Omega Centauri, 47 Tucanae, Magellansche Wolken, Carina- und Tarantelnebel …) für Reisen in den Süden. Mit Standort (Tab „Standort“) zeigt die Liste Höhe und Richtung jetzt, die Kulmination und ob das Objekt ins Bildfeld des aktiven Geräts passt oder ein Mosaik braucht. Doppelklick oder „GoTo + Live“ fährt es an – das aktive Gerät oder alle markierten.

**Passt sich dem Standort an:** Objekte, die an deinem Standort nie über 10° steigen, blendet die Liste aus – nach einem Ortswechsel (z. B. im Urlaub) erscheinen automatisch die Objekte, die dort zu sehen sind. Die Spalte **„beste Monate“** zeigt, wann ein Objekt an deinem Standort nachts am längsten hoch genug steht; mit **„nur jetzt in Saison (sortiert)“** siehst du nur die Objekte, die gerade Saison haben – die besten zuerst. Alles wird offline gerechnet.

Meldet ein verbundenes Seestar (meist von der Handy-App) oder die automatische Ortung einen Standort mehr als 20 km vom eingestellten entfernt, fragt die App, ob sie den neuen Ort übernehmen soll.

Wichtig: Kataloge sind in J2000 angegeben, das Seestar erwartet aber Koordinaten zum heutigen Datum. Die App rechnet das jetzt bei **jedem** GoTo um (Präzession; 2026 macht das rund 0,3° aus – ein knappes halbes S50-Bildfeld). Vorher lagen GoTos aus der App leicht daneben.

Objektdaten: [OpenNGC](https://github.com/mattiaverga/OpenNGC) von Mattia Verga, Lizenz CC-BY-SA 4.0. Die Datei `catalog.json` ist daraus abgeleitet und steht unter derselben Lizenz.

**Erweiterter Katalog (über die Suche):** Zusätzlich zu den gut machbaren Zielen kennt die App rund 12.500 weitere Objekte – alle NGC/IC-Objekte (Typ, Helligkeit und Größe aus OpenNGC), die Sharpless-Emissionsnebel (Sh2) und die Lynds-Dunkelnebel (LDN), zusammengestellt nach den Objektlisten von Siril. Sie erscheinen nur, wenn du danach suchst (z. B. „Sh2-101“, „LDN 1235“, „Tulpennebel“), damit Listen und Empfehlungen übersichtlich bleiben. In „Steuerung“ und „Mosaik“ kannst du ins Auswahlfeld tippen und aus dem ganzen Katalog wählen (Enter übernimmt).

## Externe Filter & Fokus

**Warum es keinen festen Fokuswert pro Filter gibt:** Ein 2"-Filter vor dem Objektiv sitzt im parallelen Strahlengang und verschiebt den Fokus praktisch nicht. Die richtige Fokusposition hängt vom einzelnen Seestar (Motorschritte) und von der Temperatur ab. Das eigentliche Problem: Der Seestar-Autofokus belichtet sehr kurz – hinter einem Schmalbandfilter (z. B. Dual-Band mit 3–7 nm) sieht er zu wenige Sterne und scheitert oder liegt daneben.

Darum hat die App im Tab **„Fokus & Filter“** einen eigenen **Präzisions-Autofokus**:

1. Filter für das Gerät auswählen (Marke und Modell aus der Filterdatenbank oder ein eigener Filter, siehe unten). Die App stellt passende Werte ein: Belichtung der Live-Bilder 1–5 s und 1–6 gemittelte Bilder pro Fokusposition, je nachdem wie dunkel der Filter ist.
2. Sternfeld anfahren, „Autofokus starten“. Die App fährt den Fokus in Schritten durch, mittelt pro Position mehrere Live-Bilder (das senkt das Rauschen um √n), misst die Sternschärfe (HFR) und macht danach eine Feinsuche mit halber Schrittweite um das Optimum. Gefahren wird immer von unten an die Position heran, um Getriebespiel auszugleichen. Die Schärfekurve wird live gezeichnet.
3. Das Ergebnis wird **pro Gerät und Filter** gemerkt (mit Temperatur). „Gemerkte Position anfahren“ stellt sie später direkt ein; weicht die Temperatur um mehr als 4 °C ab, empfiehlt die App einen neuen Autofokus.

Alternativ: „Seestar-Autofokus (ohne Filter) + als Referenz merken“, dann Filter aufsetzen und die gemerkte Position anfahren.

In Simulationen mit realistisch dunklen Sternfeldern traf der App-Autofokus das Optimum im Mittel auf 1–2 Motorschritte; ohne Mittelung mehrerer Bilder fand er hinter 3–7-nm-Filtern gar keine Sterne. Am echten Gerät ist das noch nicht geprüft.

## Zeitpläne

Im Tab **„Zeitpläne“** baust du einen Ablauf aus Schritten:

- **Aufnahme:** Ziel aus dem GoTo-Tab, Dauer, Mindesthöhe (der Plan wartet, bis das Ziel hoch genug steht, höchstens 3 h, sonst wird es übersprungen; sinkt es während der Aufnahme darunter, endet die Aufnahme und der Plan macht mit dem nächsten Schritt weiter – die Spalte „voraussichtlich“ zeigt das schon vorher an), Fokus und LP-Filter.
- **Mosaik:** übernimmt die Einstellungen aus dem Tab „Mosaik“; jedes Gerät rechnet die Panels mit seinem eigenen Bildfeld.
- **Warten bis Uhrzeit** und **Autofokus** als eigene Schritte.

Fokus pro Schritt: *automatisch* (mit externem Filter App-Autofokus, ohne Filter Seestar-Autofokus), Seestar-Autofokus, App-Autofokus, gemerkte Position oder kein Fokus. Die Liste zeigt für jeden Schritt die voraussichtliche Uhrzeit und die Höhe des Ziels. Pläne lassen sich speichern („Speichern“, „Speichern unter …“) und über **„Laden …“** wieder öffnen, mit „sofort“ oder einer Startzeit starten – vor dem Start fragt die App immer nach (Name, Schritte, Endaktion), damit kein Plan aus Versehen losläuft – auf dem aktiven Gerät oder allen markierten. Fortschritt, Wiederverbindung und Fortsetzen nach einem App-Neustart funktionieren wie beim Mosaik.

**Am Ende:** frei wählbar – „Stacking stoppen, Arm bleibt offen“ (Voreinstellung), „Parken (Arm schließen)“ oder „Parken und ausschalten“. Die App merkt sich deine letzte Wahl auch für neue Pläne. Geräte mit Arm-Schutz (Filter oder Taukappe, siehe unten) enden immer mit offenem Arm, egal was gewählt ist. Mosaiks enden immer mit offenem Arm.

## Fokus während der Aufnahme

**Nachfokussieren über die Nacht:** Wenn es abkühlt, verschiebt sich der Fokus. In den Tabs „Zeitpläne“ (unter „Ausführen“) und „Mosaik“ (Raster) stellst du ein, wann die App automatisch nachfokussiert: ab 2 °C oder 3 °C Temperaturänderung (Voreinstellung 2 °C), alle 60/90/120 Minuten, eine Kombination oder „Aus“. Dann hält sie das Stacking kurz an, fokussiert wie beim Schritt eingestellt (mit externem Filter der App-Autofokus, sonst der Seestar-Autofokus) und macht **im selben Stack weiter** – wie „Weitermachen“ in der Seestar-App. Die Pause zählt nicht zur Belichtungszeit. In den letzten 4 Minuten eines Schritts und bei Schritten mit „kein Fokus“ wird nicht nachfokussiert, ebenso nicht beim Framing-Mosaik (das steuert das Seestar selbst).

**Mit externem Filter** sucht der App-Autofokus beim Nachfokussieren nur in einem engen Bereich (± 30 Schritte) um die aktuelle Position, weil sich der Fokus über die Nacht nur wenig verschiebt. Das halbiert ungefähr die Pause – wichtig bei dunklen Schmalbandfiltern mit langen Live-Belichtungen. Liegt das Optimum am Rand dieses Bereichs oder findet sich keins, sucht die App automatisch noch einmal im vollen Bereich (± 80). Bleibt auch das ohne Ergebnis (z. B. Wolken), fährt sie die zuletzt gemerkte Position für diesen Filter an. Der erste Fokus beim Start eines Ziels nutzt immer den vollen Bereich.

**Fokus von Hand ändern, während das Seestar stackt:** Wie die Seestar-App fragt die App vorher, ob es danach **weitergehen** (gleicher Stack) oder **neu starten** soll – auch beim Autofokus-Knopf. Das Stacking wird angehalten; wenige Sekunden nach der letzten Fokusänderung (bzw. nach dem Autofokus) läuft es wie gewählt wieder an. Weitere Klicks in dieser Zeit fragen nicht erneut.

Neue Dark-Frames nimmt die App dabei nicht eigens auf: Das Seestar macht seine Darks selbst mit dem internen Dunkelfilter (der Arm bewegt sich dabei nicht), und bei 10–30-s-Belichtungen bringt ein Nachholen wenig. Dithering und Einzelframes für Siril sind die wirksameren Mittel.

## Filterdatenbank (2")

Im Tab „Fokus & Filter“ wählst du **Marke** und **Modell** – 185 Filter von 19 Marken, die in 2"-Fassung erhältlich sind und mit einem 2"-Filterhalter vor jedes Seestar passen (S30, S30 Pro, S50, S50 Pro): Breitband, UHC, Dual/Tri/Quad-Band, Schmalband, Luminanz, Klarglas, R/G/B, IR-Pass, Mond/ND, Photometrie und Spezialfilter. Fehlt deiner, legst du ihn mit **„Eigener Filter …“** an (Marke, Modell, Art, engste Bandbreite) – er wird gespeichert und genauso behandelt.

Aus Art und Bandbreite leitet die App die **Helligkeit** ab und stellt danach den App-Autofokus ein (Belichtung der Live-Bilder × gemittelte Bilder): hell 1 s × 1 · mittel 2 s × 2 · dunkel 3 s × 3 · sehr dunkel 5 s × 6.

Gut zu wissen für den Seestar (Farbsensor):
- **Dual-, Tri- und Quad-Band-Filter** sind die richtige Wahl für Nebel: Jeder Farbkanal bekommt Licht.
- **Einzellinien-Filter** (nur Hα, OIII oder SII) lassen nur einen Teil der Farbpixel arbeiten – das Bild wird einfarbig und deutlich dunkler. Sie sind darum eine Stufe dunkler eingestuft.
- **Visuelle Nebelfilter** (Lumicon, Explore Scientific, Orion UltraBlock …) funktionieren, sind fotografisch aber oft zu breit und können Reflexe zeigen.
- Bei Schmalbandfiltern empfiehlt die App, den **internen LP-/Duo-Band-Filter auszuschalten** – doppelt filtern kostet nur Licht.
- **S50 / S50 Pro:** 2"-Filter haben meist eine freie Öffnung um 46–48 mm und blenden die 50-mm-Öffnung minimal ab. **S30 / S30 Pro:** vollständig abgedeckt.

„Daten: Hersteller“ heißt, die Bandbreite stammt aus einer geprüften Herstellerangabe. „Handel“ ist die übliche Typangabe – Sortimente und Werte ändern sich, im Zweifel gilt das Datenblatt deines Filters. Sonnenfilter gehören nicht hierher: Für die Sonne immer den passenden Objektiv-Sonnenfilter des Seestar verwenden.

<details><summary>Auswahl der Filter anzeigen</summary>

| Marke | Modell | Art | Durchlass | Helligkeit | Daten |
|---|---|---|---|---|---|
| Optolong | L-Pro | Breitband-LP | breitbandig, dämpft Natrium-/Quecksilberlinien | hell | Handel |
| Optolong | L-eNhance | Tri-Band | Hα 10 nm · Hβ+OIII ca. 24 nm | dunkel | Handel |
| Optolong | L-eXtreme | Dual-Band | Hα 656,3 + OIII 500,7 nm, je 7 nm | dunkel | Hersteller |
| Optolong | L-eXtreme F2 | Dual-Band | Hα + OIII je 7 nm, für sehr schnelle Optik | dunkel | Hersteller |
| Optolong | L-Ultimate | Dual-Band | Hα + OIII je 3 nm | sehr dunkel | Hersteller |
| Optolong | L-Synergy | Dual-Band | SII + OIII je 7 nm | dunkel | Hersteller |
| Optolong | L-Para | Dual-Band | Hα + OIII je 10 nm | dunkel | Hersteller |
| Optolong | L-QEF (L-Quad Enhance) | Quad-Band | Hβ, OIII, Hα, SII – breite Bänder | mittel | Hersteller |
| Optolong | CLS | Breitband-LP | City Light Suppression | hell | Handel |
| Optolong | CLS-CCD | Breitband-LP | City Light Suppression mit IR-Sperre | hell | Handel |
| Optolong | UHC | Nebelfilter (UHC) | Hβ+OIII und Hα | mittel | Handel |
| Optolong | Moon & Skyglow | Breitband-LP | Neodym-Typ, dämpft Natriumlicht | hell | Handel |
| Optolong | UV/IR-Cut | UV/IR-Sperrfilter | sperrt UV und IR | hell | Hersteller |
| Optolong | H-Alpha 7 nm | Einzel-Linie | Hα 7 nm | sehr dunkel | Handel |
| Optolong | H-Alpha 3 nm | Einzel-Linie | Hα 3 nm | sehr dunkel | Hersteller |
| Optolong | OIII 6,5 nm | Einzel-Linie | OIII 6,5 nm | sehr dunkel | Handel |
| Optolong | OIII 3 nm | Einzel-Linie | OIII 3 nm | sehr dunkel | Hersteller |
| Optolong | SII 6,5 nm | Einzel-Linie | SII 6,5 nm | sehr dunkel | Handel |
| Optolong | SII 3 nm | Einzel-Linie | SII 3 nm | sehr dunkel | Hersteller |
| Optolong | H-Beta | Einzel-Linie | Hβ (eher visuell) | sehr dunkel | Handel |
| Svbony | SV220 Hα/OIII 7 nm | Dual-Band | Hα 656 + OIII 501 nm, je 7 nm | dunkel | Hersteller |
| Svbony | SV220 Hα/OIII 3 nm | Dual-Band | Hα + OIII je 3 nm | sehr dunkel | Hersteller |
| Svbony | SV220 SII/OIII 7 nm | Dual-Band | SII + OIII je 7 nm | dunkel | Hersteller |
| Svbony | UHC | Nebelfilter (UHC) | Hβ+OIII und Hα | mittel | Handel |
| Svbony | CLS | Breitband-LP | City Light Suppression | hell | Handel |
| Antlia | ALP-T Dual Band 5 nm | Dual-Band | Hα + OIII je 5 nm | dunkel | Hersteller |
| Antlia | ALP-T Dual Band 3 nm | Dual-Band | Hα + OIII je 3 nm | sehr dunkel | Hersteller |
| Antlia | Triband RGB Ultra (II) | Tri-Band | Hα+NII, SII, OIII | mittel | Hersteller |
| Antlia | Quad Band Anti-Light-Pollution | Quad-Band | vier Nebellinien, breit | mittel | Hersteller |
| Antlia | V-Pro | Breitband-LP | Breitband-Lichtverschmutzungsfilter | hell | Handel |
| Antlia | H-Alpha 3 nm Pro | Einzel-Linie | Hα 3 nm | sehr dunkel | Handel |
| Antlia | OIII 3 nm Pro | Einzel-Linie | OIII 3 nm | sehr dunkel | Handel |
| Antlia | SII 3 nm Pro | Einzel-Linie | SII 3 nm | sehr dunkel | Handel |
| Antlia | H-Beta 3 nm Pro | Einzel-Linie | Hβ 3 nm | sehr dunkel | Hersteller |
| Antlia | H-Alpha 2,5 nm Ultra | Einzel-Linie | Hα 2,5 nm | sehr dunkel | Hersteller |
| Antlia | OIII 2,5 nm Ultra | Einzel-Linie | OIII 2,5 nm | sehr dunkel | Hersteller |
| ZWO | Duo-Band | Dual-Band | Hα 15 nm + OIII 35 nm | mittel | Hersteller |
| ZWO | H-Alpha 7 nm | Einzel-Linie | Hα 7 nm | sehr dunkel | Handel |
| ZWO | OIII 7 nm | Einzel-Linie | OIII 7 nm | sehr dunkel | Handel |
| ZWO | SII 7 nm | Einzel-Linie | SII 7 nm | sehr dunkel | Handel |
| ZWO | UV/IR-Cut | UV/IR-Sperrfilter | sperrt UV und IR | hell | Handel |
| ZWO | IR-Cut | UV/IR-Sperrfilter | sperrt IR | hell | Handel |
| IDAS | LPS-D1 | Breitband-LP | Breitband-LP, IR-Sperre | hell | Hersteller |
| IDAS | LPS-D2 | Breitband-LP | Breitband-LP für LED-Licht, IR-Sperre | hell | Hersteller |
| IDAS | LPS-D3 (NGS1) | Breitband-LP | Breitband-LP, IR-Sperre | hell | Hersteller |
| IDAS | LPS-P2 | Breitband-LP | Breitband-LP | hell | Hersteller |
| IDAS | LPS-V4 | Nebelfilter (UHC) | Nebelfilter, IR-Sperre | mittel | Hersteller |
| IDAS | NB1 | Tri-Band | Hα, Hβ, OIII | mittel | Hersteller |
| IDAS | NB2 | Dual-Band | Hα + OIII, 20 nm | mittel | Hersteller |
| IDAS | NB3 | Dual-Band | OIII + SII, 20 nm | mittel | Hersteller |
| IDAS | NBZ | Dual-Band | Hα + OIII/Hβ, 12 nm | dunkel | Hersteller |
| STC | Astro Duo-Narrowband | Dual-Band | Hα + OIII, 7–12 nm | dunkel | Hersteller |
| STC | Astro-Multispectra | Breitband-LP | Breitband-LP | hell | Handel |
| Altair | DualBand Hα/OIII 6 nm | Dual-Band | Hα + OIII je 6 nm | dunkel | Hersteller |
| Altair | DualBand 4,5 nm | Dual-Band | Hα + OIII je 4,5 nm | sehr dunkel | Hersteller |
| Altair | DualBand Ultra SII/OIII 4 nm | Dual-Band | SII + OIII je 4 nm | sehr dunkel | Hersteller |
| Altair | TriBand V2 | Tri-Band | Hα · Hβ+OIII | mittel | Hersteller |
| Altair | QuadBand V2 | Quad-Band | 495 nm und 660 nm, je 35 nm | mittel | Hersteller |
| Radian | Triad Ultra | Quad-Band | Hβ 5 nm, OIII 4 nm, Hα 4 nm, SII 4 nm | dunkel | Hersteller |
| Askar | Colour Magic C1 (Hα+OIII) | Dual-Band | Hα + OIII, breit | mittel | Hersteller |
| Askar | Colour Magic C2 (SII+OIII) | Dual-Band | SII 15 nm + OIII 35 nm | mittel | Hersteller |
| Askar | Colour Magic D1 (Hα+OIII) | Dual-Band | OIII 6,5 nm + Hα 8,5 nm | dunkel | Hersteller |
| Askar | Colour Magic D2 (SII+OIII) | Dual-Band | OIII 6,5 nm + SII 8,5 nm | dunkel | Hersteller |
| Askar | Colour Magic Ultra E1 (Hα+OIII) | Dual-Band | Hα + OIII je 3 nm | sehr dunkel | Hersteller |
| Askar | Colour Magic Ultra E2 (SII+OIII) | Dual-Band | SII + OIII je 3 nm | sehr dunkel | Hersteller |
| Baader | UHC-S | Nebelfilter (UHC) | Nebelfilter, recht breit | mittel | Handel |
| Baader | Moon & Skyglow | Breitband-LP | Neodym, dämpft Natriumlicht | hell | Handel |
| Baader | Neodymium | Breitband-LP | Neodym, dämpft Natriumlicht | hell | Handel |
| Baader | UV/IR-Cut L | UV/IR-Sperrfilter | sperrt UV und IR | hell | Hersteller |
| Baader | H-Alpha 6,5 nm CMOS | Einzel-Linie | Hα 6,5 nm | sehr dunkel | Handel |
| Baader | OIII 6,5 nm CMOS | Einzel-Linie | OIII 6,5 nm | sehr dunkel | Handel |
| Baader | SII 6,5 nm CMOS | Einzel-Linie | SII 6,5 nm | sehr dunkel | Handel |
| Baader | H-Alpha Ultra-Narrowband CMOS | Einzel-Linie | Hα 656,3 nm, 3,5–4 nm | sehr dunkel | Hersteller |
| Baader | OIII Ultra-Narrowband CMOS | Einzel-Linie | OIII 500,7 nm, 3,5–4 nm | sehr dunkel | Hersteller |
| Baader | SII Ultra-Narrowband CMOS | Einzel-Linie | SII 671,7 nm, 3,5–4 nm | sehr dunkel | Hersteller |
| Astronomik | CLS | Breitband-LP | City Light Suppression | hell | Hersteller |
| Astronomik | CLS-CCD | Breitband-LP | City Light Suppression mit IR-Sperre | hell | Hersteller |
| Astronomik | UHC | Nebelfilter (UHC) | Nebelfilter | mittel | Hersteller |
| Astronomik | UHC-E | Nebelfilter (UHC) | Nebelfilter, etwas breiter | mittel | Hersteller |
| Astronomik | L-1 UV-IR Block | UV/IR-Sperrfilter | sperrt UV und IR | hell | Handel |
| Astronomik | L-2 UV-IR Block | UV/IR-Sperrfilter | sperrt UV und IR | hell | Handel |
| Astronomik | L-3 UV-IR Block | UV/IR-Sperrfilter | sperrt UV und IR | hell | Handel |
| Astronomik | H-Alpha 6 nm (auch MaxFR) | Einzel-Linie | Hα 6 nm | sehr dunkel | Hersteller |
| Astronomik | OIII 6 nm (auch MaxFR) | Einzel-Linie | OIII 6 nm | sehr dunkel | Hersteller |
| Astronomik | SII 6 nm (auch MaxFR) | Einzel-Linie | SII 6 nm | sehr dunkel | Hersteller |
| Astronomik | H-Alpha 12 nm (auch MaxFR) | Einzel-Linie | Hα 12 nm | sehr dunkel | Hersteller |
| Astronomik | OIII 12 nm (auch MaxFR) | Einzel-Linie | OIII 12 nm | sehr dunkel | Hersteller |
| Astronomik | SII 12 nm (auch MaxFR) | Einzel-Linie | SII 12 nm | sehr dunkel | Hersteller |
| Lumicon | UHC | Nebelfilter (UHC) | Nebelfilter (visuell) | mittel | Handel |
| Lumicon | OIII | Einzel-Linie | OIII, breit (visuell) | sehr dunkel | Handel |
| Lumicon | H-Beta | Einzel-Linie | Hβ, breit (visuell) | sehr dunkel | Handel |
| Explore Scientific | UHC | Nebelfilter (UHC) | Nebelfilter (visuell) | mittel | Handel |
| Explore Scientific | OIII | Einzel-Linie | OIII, breit (visuell) | sehr dunkel | Handel |
| Celestron | UHC/LPR | Nebelfilter (UHC) | Nebelfilter | mittel | Handel |
| Orion | UltraBlock | Nebelfilter (UHC) | Nebelfilter (visuell) | mittel | Handel |
| Orion | SkyGlow | Breitband-LP | Breitband-LP | hell | Handel |
| Omegon | UHC | Nebelfilter (UHC) | Nebelfilter | mittel | Handel |
| Omegon | CLS | Breitband-LP | City Light Suppression | hell | Handel |
| TS-Optics | UHC | Nebelfilter (UHC) | Nebelfilter | mittel | Handel |
| TS-Optics | CLS | Breitband-LP | City Light Suppression | hell | Handel |

</details>

## Arm-Schutz bei externem Filter oder Taukappe

Mit einem 2"-Filterhalter oder einer Taukappe vor dem Objektiv kann das Seestar den Arm nicht schließen – der Motor würde dagegen fahren. Sobald du im Tab „Fokus & Filter“ einen Filter einträgst oder **„Taukappe montiert“** bzw. **„Anderes Zubehör vor dem Objektiv“** ankreuzt, schaltet sich der **Arm-Schutz** für dieses Gerät ein (das geht pro Gerät, auch ganz ohne Filter):

- Parken, Ausschalten, Neustart und der Wechsel Alt-Az ↔ EQ (der parkt) werden **direkt in der Verbindung blockiert** – egal ob aus einem Tab, einem Plan, einem Mosaik oder der Konsole. Wer es trotzdem auslöst, wird gefragt, ob der Filter abgenommen ist.
- Zeitpläne enden auf diesem Gerät immer mit offenem Arm, auch wenn „Parken“ eingestellt ist; andere Geräte parken wie gewählt.
- Am Gerät werden ausgeschaltet: *Automatisch ausschalten* und *Nach Seestar-Plan Arm schließen* (für Pläne aus der Seestar-App); mit Filter zusätzlich *Smart-AF* und *Autofokus vor dem Stacking* (scheitern hinter Schmalbandfiltern). Bei Taukappe oder anderem Zubehör ohne Filter bleibt der Autofokus unverändert. Solange der Schutz aktiv ist, lassen sich *Automatisch ausschalten* und *Nach Seestar-Plan Arm schließen* nicht wieder einschalten – und solange ein Filter eingetragen ist, auch der Seestar-Autofokus nicht (die App verweist dann auf ihren eigenen Autofokus).
- Bei 20 % und 10 % Akku warnt die App: Schaltet sich das Seestar wegen leerem Akku selbst ab, kann es den Arm schließen – das kann keine App verhindern.

In der Übersicht steht bei geschützten Geräten „[Arm-Schutz]“. Filter oder Taukappe abgenommen? Im Tab „Fokus & Filter“ „Kein externer Filter“ wählen bzw. das Häkchen „Taukappe montiert“ entfernen – die App fragt dann, ob der Arm-Schutz aus soll.

## EQ-Modus (Wedge)

Im EQ-Modus kann das Seestar bis zu **60 s pro Frame** belichten – mehr geht nicht. Im Alt-Az-Modus sind es höchstens 30 s; die App lässt 60 s dort gar nicht erst zu (auch nicht beim Übertragen von Einstellungen auf andere Geräte).

Der Tab **„EQ-Modus“** führt dich in drei Schritten durch Aufbau und Kontrolle, jeweils für das aktive Gerät:

1. **Nivellieren & Wedge:** „Live-Messung“ zeigt den eingebauten Neigungssensor als Libelle (grün < 0,5°, gelb < 1°). Darunter steht der Wedge-Winkel aus deinem Breitengrad (Tab „Standort“) – für Skalen ab Horizont und ab Senkrechte, weil Wedges das unterschiedlich beschriften. Der Moduswechsel Alt-Az ↔ EQ geht über die Knöpfe oben; das Seestar fährt dafür in die Parkposition.
2. **Polausrichtung (3-Punkt):** Startposition wählen (1 = nah, 5 = fern; 3 ist Standard, bei Hindernissen eine andere nehmen), „Abweichung messen“. Die Zielscheibe zeigt den Fehler in Höhe und Azimut, der Verlauf der letzten Messungen ist gestrichelt verbunden. Mit „automatisch neu messen“ misst die App nach jeder Messung erneut, während du an Höhe/Azimut drehst – bis beide Achsen unter 0,5° liegen. Die Seestar-App akzeptiert schon < 1°.
3. **Kontrolle & Tests:** Ampel-Checkliste (EQ-Modus, Neigung, Polausrichtung, Belichtung) und ein **Nachführtest**: Ziel anfahren, Belichtung (20/30/60 s) und Dauer wählen, starten. Die App zählt gestackte und verworfene Frames und sagt dir, ob die Belichtung passt (≥ 90 % gute Frames), grenzwertig ist oder du kürzer belichten bzw. besser ausrichten solltest. Danach wird die vorherige Belichtung wiederhergestellt.

Hinweis: Die Bedeutung der Rohwerte des Neigungssensors (X/Y in Grad) stammt aus Community-Analysen der Firmware. Vergleiche beim ersten Mal kurz mit einer Wasserwaage. Zeigt die Libelle bei genau waagerechtem Seestar einen kleinen festen Versatz, merkt sich **„Nullpunkt setzen“** den aktuellen Wert als Null (pro Gerät; „Nullpunkt löschen“ nimmt ihn zurück).

## Modellauswahl

Oben rechts wählst du das Modell des aktiven Geräts (S30, S30 Pro, S50, S50 Pro). Mit „beim Verbinden erkennen“ liest die App das Modell automatisch aus dem Seestar aus und stellt Dropdowns, Filterbezeichnung und Modelldaten (Optik, Sensor, Bildfeld) passend ein. Gleichzeitig werden die aktuellen Einstellungen vom Gerät übernommen.

Die „empfohlenen Werte“ sind Startwerte (10 s, Gain 80, Standard-Dithering, interner Filter aus). 60 s Belichtung funktionieren nur im EQ-Modus mit Polausrichtung.

## Vorschaubild

Der Tab „Vorschau“ verbindet sich mit dem Bildkanal des Seestar (TCP-Port 4800). „Live-Vorschau“ zeigt die laufenden Einzelbilder (in halber Auflösung entbayert), „Stack-Bild holen“ das aktuell gestapelte Bild. Bei aktivem Haken wird das Stack-Bild nach jedem neuen Frame automatisch nachgeladen. Die Darstellung wird nur für den Bildschirm gestreckt – die Rohdaten auf dem Seestar bleiben unberührt. Läuft auf dem Seestar gerade keine Ansicht (z. B. nach dem Ende eines Plans), startet „Live“ den Sternenmodus selbst (bei geschlossenem Arm nach Rückfrage); kommt eine Weile kein neues Bild, fordert die App es selbst neu an und zeigt „warte auf ein neues Bild …“.

## WLAN: Seestar ins Heimnetz bringen

Am einfachsten im **Stationsmodus**: In der Seestar-App unter WLAN-Einstellungen das Heimnetz eintragen. Danach hängt das Seestar im selben Netz wie der PC; die IP siehst du im Router oder in der App. Alternativ verbindet sich der PC direkt mit dem Seestar-Hotspot (dann meist `10.0.0.1`).

Die Steuerung läuft über JSON-RPC auf TCP-Port 4700, die Bilder über TCP-Port 4800, die Suche über UDP-Port 4720. Ggf. in der Windows-Firewall freigeben.

## Zugangsdaten je Seestar (WLAN-Name und Passwort)

Jedes Seestar hat ein eigenes WLAN mit Namen wie `S50_1a2b3c4d` (bzw. `S30_…`) und Passwort – ab Werk `12345678`, in der Seestar-App unter dem Gerät änderbar. In der Übersicht öffnet **„Zugangsdaten …“** (Kasten „Aktives Gerät“) für jedes Gerät:

- **Gerätename** in der App und **IP-Adresse**
- **Verbindung:** *Heimnetz* (Seestar und PC im selben WLAN, empfohlen und nötig für mehrere Geräte gleichzeitig) oder *Direkt* (PC verbindet sich mit dem WLAN des Seestar, Adresse dann meist `10.0.0.1`; geht immer nur mit einem Seestar zugleich, weil ein PC nur in einem WLAN sein kann)
- **WLAN-Name** und **WLAN-Passwort** des Seestar

Bei „Direkt“ verbindet die App den PC (Windows) beim Verbinden automatisch mit dem Seestar-WLAN, auch beim automatischen Neuverbinden; „PC jetzt mit diesem WLAN verbinden“ macht das sofort. Ist ein Gerät verbunden, liest die App WLAN-Name und Passwort selbst aus dem Seestar (`pi_get_ap`) und zeigt an, in welchem Heimnetz es hängt (`pi_station_state`).

Das Passwort wird unter Windows mit der Windows-Datenverschlüsselung (DPAPI) gespeichert – lesbar nur für dein Windows-Benutzerkonto. Hinweis: Neuere Windows-11-Versionen verlangen für WLAN-Befehle die Standortfreigabe für Desktop-Apps; die App sagt Bescheid, wenn das fehlt.

Das Seestar ins Heimnetz bringen (Stationsmodus) geht weiterhin nur in der Seestar-App.

## Wichtig: Anmeldung bei neuerer Firmware

Ab Firmware 6.45 bzw. verbindlich ab ca. 7.18 verlangt das Seestar eine Challenge-Response-Anmeldung mit einem RSA-Schlüssel aus der offiziellen Seestar-Android-App. Diesen Schlüssel liefere ich **nicht** mit – er gehört ZWO.

So bekommst du ihn: Das Projekt **seestar_alp** (github.com/smart-underworld/seestar_alp) hat ein „Seestar tool“ mit der Funktion **Extract PEM**, das den Schlüssel aus der APK deiner Seestar-App extrahiert. Die `.pem`-Datei wählst du dann im Feld „PEM-Schlüssel“ aus.

Ohne Schlüssel verbindet die App trotzdem, aber neuere Firmware lehnt dann die meisten Befehle ab.

## Bluetooth: was realistisch ist

Das Seestar nutzt BLE nur zum Aufwecken und zur WLAN-Ersteinrichtung. ZWO hat dieses Protokoll nicht veröffentlicht, und es gibt bislang keine öffentliche Dokumentation dazu. Der Bluetooth-Tab ist deshalb ein Explorer: Verbinden, alle Characteristics auflisten, lesen, schreiben, Benachrichtigungen protokollieren. Die eigentliche Teleskopsteuerung (GoTo, Stacking usw.) läuft über WLAN.

Unter Windows braucht Bluetooth Windows 10 (Version 1709) oder neuer und einen BLE-fähigen Adapter.

## Hinweise

- Die Richtungen des Joysticks (0° = rechts, 90° = hoch …) entsprechen der Community-Konvention. Falls sie bei dir vertauscht sind, sag Bescheid, dann passe ich die Winkel an.
- Bei externem Filter (z. B. Ha/OIII) den internen LP-Filter beim GoTo ausgeschaltet lassen.
- ZWO ändert das Protokoll bei Firmware-Updates gelegentlich. Wenn nach einem Update etwas nicht mehr geht, zuerst im Protokollfenster nach Fehlercodes schauen.

## Programmname & Echtheit

Der Name **„Star Gazing Control Center by TheSkyCoder“** gehört zum Programm und darf nicht verändert werden (siehe `LICENSE.md`).

Jede vom Urheber freigegebene Fassung ist digital signiert (Datei `SIGNATUR.txt`). Beim Start prüft das Programm, ob Programmcode, Objektkatalog und mitgelieferte Sprachdateien unverändert sind. Passt die Signatur nicht – weil etwas geändert, der Name umbenannt oder eine Datei entfernt wurde –, erscheint hinter dem Namen überall der Zusatz **„(modifiziert)“** in der eingestellten Sprache (z. B. „(modified)“, „(modifié)“). Ohne Zusatz erscheint der Name nur in Fassungen, die mit dem privaten Schlüssel des Urhebers signiert wurden.

Eine selbst hinzugefügte Sprachdatei im Ordner `lang` gilt nicht als Veränderung.

Hinweis: Die Prüfung macht Veränderungen sichtbar, sie kann aber jemanden, der den Programmcode gezielt umschreibt, nicht technisch aufhalten. Rechtlich gilt die Lizenz.
