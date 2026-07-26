# Jace, the Price Tracker

Jace tracks Magic: The Gathering card prices. It reads card lists, fetches
current prices from the public Scryfall API, stores snapshots in Postgres, and
shows the price history in the browser or terminal.

## Features

- Import card lists from text, CSV, single card entries, and Moxfield collection CSV exports.
- Store price snapshots in Postgres, including history for archived cards.
- Persist EUR portfolio-value snapshots and inspect their chart from Total value.
- View, search, sort, page through, select, and archive cards in the browser.
- Cache Scryfall artwork in Postgres.
- Refresh stale prices automatically or manually from the frontend.
- Run as a Docker Compose stack, standalone container, local web server, or CLI.

## Quick Start With Docker Compose

Create a local `.env` file. This file is ignored by Git.

```bash
cp .env.example .env
```

Set at least `POSTGRES_PASSWORD` in `.env`:

```env
POSTGRES_PASSWORD=change-me
```

Start the stack:

```bash
docker compose up -d
```

Open the frontend:

```text
http://localhost:8180
```

The stack starts two containers:

- `jace-postgres` with Postgres
- `jace` with the web app

The app image defaults to `ghcr.io/flexusjan/jace:latest`. The Postgres image
defaults to `postgres:18-alpine`.

For Portainer, deploy the Compose stack and set the same environment variables
there. No local image build is required.

## Required Environment

Only `POSTGRES_PASSWORD` is required for the Docker Compose stack to start.

| Variable | Required | Purpose |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | yes | Password for the bundled Postgres database and the app connection |
| `JACE_AUTH_USERNAME` | no | Enables HTTP Basic Auth when set together with `JACE_AUTH_PASSWORD` |
| `JACE_AUTH_PASSWORD` | no | HTTP Basic Auth password |

To protect the browser frontend and API with HTTP Basic Auth, set both auth
variables:

```env
JACE_AUTH_USERNAME=jace
JACE_AUTH_PASSWORD=change-me-too
```

Use Basic Auth behind HTTPS when the app is reachable outside a trusted private
network.

## Configuration

Runtime settings can be overridden in `.env`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `POSTGRES_DB` | `jace` | Postgres database name |
| `POSTGRES_USER` | `jace` | Postgres database user |
| `POSTGRES_IMAGE` | `postgres:18-alpine` | Postgres container image |
| `APP_PORT` | `8180` | Host port exposed by Docker Compose |
| `JACE_IMAGE` | `ghcr.io/flexusjan/jace:latest` | App container image |
| `JACE_DEFAULT_CURRENCY` | `eur` | Default import currency (`eur`, `usd`, or `tix`) |
| `JACE_WEB_HOST` | `0.0.0.0` | Web server bind host |
| `JACE_WEB_PORT` | `8180` | Web server bind port inside the container |
| `JACE_DARK_THEME` | `true` | Use the dark frontend theme; set to `false` for light mode |
| `JACE_REFRESH_INTERVAL_SECONDS` | `3600` | Automatic stale price refresh interval |
| `JACE_SCRYFALL_BULK_SIZE` | `75` | Scryfall collection request size, max `75` |
| `JACE_SCRYFALL_REQUEST_INTERVAL_SECONDS` | `0.12` | Delay between regular Scryfall requests |
| `JACE_SCRYFALL_COLLECTION_REQUEST_INTERVAL_SECONDS` | `0.55` | Delay between collection/bulk Scryfall requests |
| `JACE_SCRYFALL_TIMEOUT_SECONDS` | `20` | Scryfall API request timeout |
| `JACE_IMAGE_FETCH_TIMEOUT_SECONDS` | `20` | Card image fetch timeout |
| `JACE_AUTH_USERNAME` | unset | Enables HTTP Basic Auth when set together with `JACE_AUTH_PASSWORD` |
| `JACE_AUTH_PASSWORD` | unset | HTTP Basic Auth password |
| `JACE_MAX_REQUEST_BODY_BYTES` | `1048576` | Maximum JSON request body size |
| `JACE_MAX_IMPORT_CARDS` | `10000` | Maximum cards per import request |
| `JACE_MAX_IMPORT_JOBS` | `4` | Maximum queued/running import jobs |
| `JACE_MAX_IMAGE_BYTES` | `10485760` | Maximum cached Scryfall image size |

When Basic Auth is enabled, mutating browser requests are accepted only from the
same origin. The web server also sends defensive browser headers, limits request
and image sizes, and only caches card images from HTTPS Scryfall image hosts.

## Import Formats

Text files support these formats:

```text
Card Name
2 Card Name (SET) CollectorNumber
Card Name [SET]
```

Example: [examples/cards.txt](examples/cards.txt)

The frontend also accepts single card entries, Moxfield collection CSV exports,
and CSV files. CSV import columns are matched by header name:

| CSV header | Required | Stored as | Notes |
| --- | --- | --- | --- |
| `Name` or `Card Name` | yes | `price_snapshots.tracked_name` | Used to find the card on Scryfall |
| `Count`, `Quantity`, or `Qty` | no | `price_snapshots.quantity` | Defaults to `1` |
| `Edition`, `Set`, or `Set Code` | no | `cards.set_code` | Stored as lowercase set code after Scryfall lookup |
| `Collector Number`, `collector_number`, or `Number` | no | `cards.collector_number` | Used together with the set code for exact Scryfall lookup |
| `Condition` | no | `price_snapshots.condition` | Defaults to `Near Mint`; aliases like `NM`, `LP`, `MP`, `HP`, and `DMG` are normalized |
| `Language` | no | `price_snapshots.language` | Defaults to `English` |
| `Finish`, `Foil`, or `Is Foil` | no | `price_snapshots.finish` | Defaults to `Non-Foil`; `Foil` and `Etched` are recognized |

Scryfall metadata is stored in the `cards` table (`scryfall_id`, `name`,
`set_code`, `collector_number`, `source_url`, and image fields). Tracking data
is stored in `price_snapshots` (`entry_id`, `tracked_name`, `quantity`,
`condition`, `language`, `currency`, `price`, and `captured_at`).

## Using The App

Import cards in the browser, then use the frontend to search, sort, page through,
select, and remove cards from the active collection. Removing a card archives it;
its price history and card metadata stay in Postgres. Prices can be missing
when Scryfall has no price data for a card in the selected currency.

### Portfolio Value History

Click `Total value` to open the EUR portfolio chart. Jace persists a portfolio
snapshot after a successful price refresh, import, Moxfield synchronization, or
manual archival. Portfolio snapshots are separate from individual card prices:
archived cards retain their full price history while they stop contributing to
new portfolio values. The first chart point is recorded after the next such
operation following an upgrade.

### Moxfield Collection Sync

In the Moxfield import tab, select an exported Moxfield collection CSV. A
successful first sync makes Moxfield the authoritative collection source. Later
uploads synchronize the collection: new cards are added, changed quantities and
attributes receive a new snapshot, and cards absent from the export are archived.
Archived cards no longer contribute to collection value or automatic price
refreshes, but their price history remains available in the database.

For safety, a Moxfield sync requires `Edition` and `Collector Number` on every
row. Jace aborts the whole sync before changing the collection if an export is
incomplete or any card cannot be resolved through Scryfall.

While Moxfield sync is active, Jace disables manual imports and removals. Use
`Switch to manual mode` in the UI to manage the active collection in Jace again.
It does not delete or reactivate archived cards.

### Upgrading To 1.3.0

Jace 1.3.0 performs an additive, idempotent database migration on startup. It
adds tracking metadata and backfills every existing snapshot entry as an active
manual entry; it does not delete or rewrite existing cards or price snapshots.

Before deploying a new production image, take a normal Postgres backup:

```bash
docker compose exec -T db pg_dump -U jace jace > jace-before-v1.3.0.sql
```

Replace `jace` with your configured `POSTGRES_USER` and `POSTGRES_DB` values if
they differ. Pin production deployments to a reviewed image tag such as
`ghcr.io/flexusjan/jace:1.3.0` rather than an unreviewed `latest` tag.

The web server automatically refreshes stale prices about once per hour by
default. A full refresh can also be started manually with `Update Prices` in the
frontend.

Show the terminal report:

```bash
docker compose run --rm jace report
```

Show the terminal report as CSV:

```bash
docker compose run --rm jace report --format csv
```

## Build The Container

Build a local image:

```bash
docker build -t jace:local .
```

Start the Compose stack with the local image:

```bash
JACE_IMAGE=jace:local docker compose up -d
```

The container can also be started directly. A Postgres database must be
reachable and `DATABASE_URL` must point to it:

```bash
docker run --rm \
  --add-host=host.docker.internal:host-gateway \
  -e DATABASE_URL='postgresql://jace:password@host.docker.internal:5432/jace' \
  -p 8180:8180 \
  ghcr.io/flexusjan/jace:latest
```

`--add-host=host.docker.internal:host-gateway` makes the host machine reachable
from the container on Linux. Docker Compose is usually simpler because the
database runs as the `db` service in the same Docker network.

## Run Locally

Postgres must be reachable and `DATABASE_URL` must be set.

```bash
python -m pip install -e .
export DATABASE_URL='postgresql://jace:password@localhost:5432/jace'
jace track examples/cards.txt --currency eur
jace report
jace web --host 127.0.0.1 --port 8180
```

`jace track` requires network access because it calls Scryfall.

## Tests

```bash
python -m unittest discover -s tests
```

## Dependency Updates

Renovate is configured in [renovate.json](renovate.json). Once the Renovate
GitHub App is enabled for this repository, it opens update PRs for Python
dependencies in `pyproject.toml`, container images in `Dockerfile` and
`docker-compose.yml`, and GitHub Actions.

Renovate also creates a Dependency Dashboard issue for manually tracking,
retrying, or approving dependency updates.

## License

MIT, see [LICENSE](LICENSE).
