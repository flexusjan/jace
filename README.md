# jace

A small tool that reads a list of Magic: The Gathering cards, fetches current
prices from the public Scryfall API, and stores snapshots in Postgres. Price
history can be viewed from the terminal or in the browser.

## Card List

Supported formats:

```text
Card Name
2 Card Name (SET) CollectorNumber
Card Name [SET]
```

Example: [examples/cards.txt](examples/cards.txt)

## Docker Compose / Portainer

Create a local `.env` file. This file is ignored by Git.

```bash
cp .env.example .env
```

Set your own `POSTGRES_PASSWORD` in `.env`, then start the stack:

```bash
docker compose up -d
```

The stack starts exactly two containers:

- `jace-postgres` with Postgres
- `jace` with the web app

Portainer does not need a local build. The app container uses the image from
`JACE_IMAGE`. Set it to the full image name that Portainer should deploy, for
example `registry.example.com/jace:latest`.

The Postgres container uses `postgres:18-alpine` by default. The Compose volume
is mounted at `/var/lib/postgresql` so it matches the data directory layout used
by the official Postgres 18 images.

Runtime settings can be overridden in `.env`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_PORT` | `8000` | Host port exposed by Docker Compose |
| `JACE_DEFAULT_CURRENCY` | `eur` | Default import currency (`eur`, `usd`, or `tix`) |
| `JACE_WEB_HOST` | `0.0.0.0` | Web server bind host |
| `JACE_WEB_PORT` | `8000` | Web server bind port inside the container |
| `JACE_REFRESH_INTERVAL_SECONDS` | `3600` | Automatic stale price refresh interval |
| `JACE_SCRYFALL_BULK_SIZE` | `75` | Scryfall collection request size, max `75` |
| `JACE_SCRYFALL_REQUEST_INTERVAL_SECONDS` | `0.12` | Delay between regular Scryfall requests |
| `JACE_SCRYFALL_COLLECTION_REQUEST_INTERVAL_SECONDS` | `0.55` | Delay between collection/bulk Scryfall requests |
| `JACE_SCRYFALL_TIMEOUT_SECONDS` | `20` | Scryfall API request timeout |
| `JACE_IMAGE_FETCH_TIMEOUT_SECONDS` | `20` | Card image fetch timeout |

Frontend:

```text
http://localhost:8000
```

In the frontend you can add, search, sort, select, and delete cards including
their price history. Supported import sources are single card lines, `.txt`
files in the same format as [examples/cards.txt](examples/cards.txt), CSV files
with columns such as `Count`, `Name`, `Edition`, `Collector Number`,
`Condition`, and `Language`, plus Moxfield deck links. The frontend displays
Scryfall artwork and caches it in Postgres.

The web server automatically refreshes prices for stale entries about once per
hour. A full refresh can also be started manually with `Update Prices` in the
frontend.

Show the terminal report:

```bash
docker compose run --rm jace report
```

## Build The Container

If Docker is installed, you can build the image without Docker Compose:

```bash
docker build -t jace:local .
```

Then start the Compose stack with the locally built image:

```bash
JACE_IMAGE=jace:local docker compose up -d
```

The container can also be started directly. A Postgres database must be
reachable and `DATABASE_URL` must point to it:

```bash
docker run --rm \
  --add-host=host.docker.internal:host-gateway \
  -e DATABASE_URL='postgresql://jace:password@host.docker.internal:5432/jace' \
  -p 8000:8000 \
  jace:local
```

`--add-host=host.docker.internal:host-gateway` makes the host machine reachable
from the container on Linux. Docker Compose is usually simpler because the
database runs as the `db` service in the same Docker network.

## Run Locally

Postgres must be reachable and `DATABASE_URL` must be set.

```bash
python -m pip install -e .
export DATABASE_URL='postgresql://jace@localhost:5432/jace'
jace track examples/cards.txt --currency eur
jace report
jace web --host 127.0.0.1 --port 8000
```

CLI output as CSV:

```bash
jace report --format csv
```

## Tests

```bash
python -m unittest discover -s tests
```

## Notes

- The data source is Scryfall. Prices can be missing when Scryfall has no price
  data for a card in the selected currency.
- `track` requires network access.
- Real passwords belong in local `.env` files or secret stores, not in the
  repository.
