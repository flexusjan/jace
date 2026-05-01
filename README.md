# Jace the Price Tracker

Ein kleines CLI-Tool, das eine Liste von Magic: The Gathering Karten einliest,
aktuelle Preise über die öffentliche Scryfall-API abruft und Snapshots in SQLite
speichert. Wiederholte Läufe erzeugen eine Preishistorie.

## Kartenliste

Unterstützte Formate:

```text
Card Name
2 Card Name (SET) CollectorNumber
Card Name [SET]
```

Beispiel: [examples/cards.txt](examples/cards.txt)

## Lokal ausführen

```bash
python -m pip install -e .
mtg-price-tracker track examples/cards.txt --currency eur
mtg-price-tracker report
```

## Mit Docker

Image bauen:

```bash
docker build -t jace-the-price-tracker .
```

Preise tracken:

```bash
docker run --rm \
  -v "$PWD/data:/app/data" \
  -v "$PWD/examples:/app/examples:ro" \
  jace-the-price-tracker \
  track --db /app/data/prices.sqlite /app/examples/cards.txt --currency eur
```

Report anzeigen:

```bash
docker run --rm \
  -v "$PWD/data:/app/data" \
  jace-the-price-tracker \
  report --db /app/data/prices.sqlite
```

Alternativ:

```bash
docker compose up --build
```

## Tests

```bash
python -m unittest discover -s tests
```

## Hinweise

- Datenquelle ist Scryfall. Preise können fehlen, wenn Scryfall für eine Karte
  keine Preisdaten in der gewählten Währung liefert.
- `track` benötigt Netzwerkzugriff.
- Die SQLite-Datei liegt standardmäßig unter `data/prices.sqlite`.
