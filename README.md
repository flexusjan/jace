# Jace the Price Tracker

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

## Docker Compose

Lege lokal eine `.env` an. Die Datei wird von Git ignoriert.

```bash
cp .env.example .env
```

Setze in `.env` ein eigenes `POSTGRES_PASSWORD`. Danach:

```bash
docker compose up --build
```

Der Container wird dabei automatisch aus dem `Dockerfile` gebaut und unter dem
lokalen Image-Namen `jace-the-price-tracker:local` verwendet.

Frontend:

```text
http://localhost:8000
```

Preise als einmaligen Job abrufen:

```bash
docker compose --profile jobs run --rm tracker-job
```

Report im Terminal anzeigen:

```bash
docker compose run --rm tracker report
```

## Container bauen

Wenn Docker installiert ist, kannst du das Image auch ohne Docker Compose bauen:

```bash
docker build -t jace-the-price-tracker:local .
```

Danach kann der Container direkt gestartet werden. Dafür muss eine Postgres-
Datenbank erreichbar sein und `DATABASE_URL` auf diese Datenbank zeigen:

```bash
docker run --rm \
  -e DATABASE_URL='postgresql://mtg_tracker:password@host.docker.internal:5432/mtg_prices' \
  -p 8000:8000 \
  jace-the-price-tracker:local
```

Unter Linux funktioniert `host.docker.internal` je nach Docker-Version nicht
automatisch. In dem Fall ist Docker Compose meistens der einfachere Weg, weil
die Datenbank dort als Service `db` im gleichen Docker-Netzwerk läuft.

## Lokal ausführen

Postgres muss erreichbar sein und `DATABASE_URL` muss gesetzt sein.

```bash
python -m pip install -e .
export DATABASE_URL='postgresql://mtg_tracker@localhost:5432/mtg_prices'
mtg-price-tracker track examples/cards.txt --currency eur
mtg-price-tracker report
mtg-price-tracker web --host 127.0.0.1 --port 8000
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
