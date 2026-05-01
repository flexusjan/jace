# Jace, the Price Tracker

Ein kleines Tool, das eine Liste von Magic: The Gathering Karten einliest,
aktuelle Preise über die öffentliche Scryfall-API abruft und Snapshots in
Postgres speichert. Die Preisentwicklung kann im Terminal und im Browser
angezeigt werden.

## Kartenliste

Unterstützte Formate:

```text
Card Name
2 Card Name (SET) CollectorNumber
Card Name [SET]
```

Beispiel: [examples/cards.txt](examples/cards.txt)

## Docker Compose / Portainer

Lege lokal eine `.env` an. Die Datei wird von Git ignoriert.

```bash
cp .env.example .env
```

Setze in `.env` ein eigenes `POSTGRES_PASSWORD`. Danach:

```bash
docker compose up -d
```

Der Stack startet genau zwei Container:

- `jace-postgres` mit Postgres
- `jace` mit der Web-App

Für Portainer wird kein lokaler Build benötigt. Der App-Container verwendet
das Image aus `JACE_IMAGE`. Setze dort den vollständigen Namen des Images, das
Portainer deployen soll, zum Beispiel `registry.example.com/jace-the-price-tracker:latest`.

Der Postgres-Container nutzt standardmäßig `postgres:18-alpine`. Das Compose-
Volume wird dafür auf `/var/lib/postgresql` gemountet, damit die
Datenverzeichnis-Struktur der offiziellen Postgres-18-Images passt.

Frontend:

```text
http://localhost:8000
```

Im Frontend kannst du Karten hinzufügen, suchen, sortieren, auswählen und
inklusive Preisverlauf wieder löschen. Unterstützt werden einzelne Kartenzeilen,
`.txt`-Dateien im gleichen Format wie [examples/cards.txt](examples/cards.txt),
CSV-Dateien mit Spalten wie `Count`, `Name`, `Edition`, `Collector Number`,
`Condition` und `Language` sowie Moxfield-Decklinks. Das Frontend zeigt
Scryfall-Artworks an und cached sie in Postgres.

Der Webserver aktualisiert Preise automatisch etwa einmal pro Stunde für stale
Einträge. Über `Update Prices` im Frontend kann ein vollständiger Refresh auch
manuell gestartet werden.

Report im Terminal anzeigen:

```bash
docker compose run --rm jace report
```

## Container bauen

Wenn Docker installiert ist, kannst du das Image auch ohne Docker Compose bauen:

```bash
docker build -t jace-the-price-tracker:local .
```

Danach kannst du den Compose-Stack mit dem lokal gebauten Image starten:

```bash
JACE_IMAGE=jace-the-price-tracker:local docker compose up -d
```

Danach kann der Container direkt gestartet werden. Dafür muss eine Postgres-
Datenbank erreichbar sein und `DATABASE_URL` auf diese Datenbank zeigen:

```bash
docker run --rm \
  --add-host=host.docker.internal:host-gateway \
  -e DATABASE_URL='postgresql://mtg_tracker:password@host.docker.internal:5432/mtg_prices' \
  -p 8000:8000 \
  jace-the-price-tracker:local
```

`--add-host=host.docker.internal:host-gateway` macht den Host-Rechner unter
Linux aus dem Container erreichbar. Docker Compose ist trotzdem meistens der
einfachere Weg, weil die Datenbank dort als Service `db` im gleichen
Docker-Netzwerk läuft.

## Lokal ausführen

Postgres muss erreichbar sein und `DATABASE_URL` muss gesetzt sein.

```bash
python -m pip install -e .
export DATABASE_URL='postgresql://mtg_tracker@localhost:5432/mtg_prices'
mtg-price-tracker track examples/cards.txt --currency eur
mtg-price-tracker report
mtg-price-tracker web --host 127.0.0.1 --port 8000
```

CLI-Ausgabe als CSV:

```bash
mtg-price-tracker report --format csv
```

## Tests

```bash
python -m unittest discover -s tests
```

## Hinweise

- Datenquelle ist Scryfall. Preise können fehlen, wenn Scryfall für eine Karte
  keine Preisdaten in der gewählten Währung liefert.
- `track` benötigt Netzwerkzugriff.
- Echte Passwörter gehören nur in lokale `.env`-Dateien oder Secret Stores,
  nicht ins Repository.
