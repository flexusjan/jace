# Changelog

## 1.1.0 - 2026-05-04

- Add clearer API endpoints for price history:
  - `/api/cards/{tracking_id}/price-history` for a tracked card entry.
  - `/api/collection/value-history` for collection-level value snapshots.
- Keep the previous `/api/cards/{tracking_id}/history` and `/api/value-history` endpoints available for compatibility.
- Add pagination metadata and `page` / `page_size` query parameters for card price history responses.
- Limit the frontend card detail panel to the latest 100 price snapshots by default and show a note when more snapshots exist.

## 1.0.6 - 2026-05-04

- Re-publish the Docker image release using the configured `GHCR_TOKEN` package write credentials.

## 1.0.5 - 2026-05-03

- Make the Docker image publish workflow compatible with a `GHCR_TOKEN` secret and attach repository metadata labels to published images.

## 1.0.4 - 2026-05-03

- Re-publish the 1.0.3 release contents after re-enabling GitHub Actions so the Docker image publish workflow can run.

## 1.0.3 - 2026-05-03

- Track card finish separately so foil and etched printings can use the correct Scryfall price fields.
- Add exchange-rate fallback pricing when requested EUR/USD prices are missing or foil EUR values are unreliable.
- Keep the collection table reachable after refreshes on short desktop viewports and show table-level load errors.
- Speed up reloads by calculating only the portfolio value points the frontend displays.
- Add collection count logging around startup, imports, deletes, and price refreshes.

## 1.0.2 - 2026-05-03

- Improve the smartphone layout by replacing the wide card table with compact mobile card rows that include card thumbnails and key price details.
- Allow the mobile page to scroll vertically so the collection list and card images remain reachable on small screens.

## 1.0.1 - 2026-05-03

- Treat browser or proxy disconnects during HTTP response writes as normal client disconnects instead of logging noisy `BrokenPipeError` tracebacks.

## 1.0.0 - 2026-05-03

Initial stable release.

- Track Magic: The Gathering card prices from Scryfall snapshots in Postgres.
- Import cards from text files, CSV files, single card entries, and Moxfield deck links.
- Use the browser frontend to add, search, sort, page through, select, and delete cards.
- Cache Scryfall artwork in Postgres and refresh stale prices automatically.
- Run as a CLI tool, local web server, Docker image, or Docker Compose stack.
- Configure runtime behavior through environment variables, including optional HTTP Basic Auth.
