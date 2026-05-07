# Changelog

## 1.1.8 - 2026-05-07

- Restore the desktop card detail panel to a larger artwork-first layout with compact details below.
- Keep the desktop detail panel non-scrollable while preserving the mobile side-by-side overlay layout.

## 1.1.7 - 2026-05-07

- Defer collection value history loading so initial page refreshes are not blocked by the secondary graph request.
- Cache static frontend assets and short-lived collection value history responses.
- Add an entry/id snapshot index for faster first/latest entry-bound queries.
- Improve the non-mobile detail panel layout and compact the mobile card list.

## 1.1.6 - 2026-05-07

- Speed up card listing and collection value history by reducing snapshot scans to first/latest entry bounds.
- Use short-lived database connections for web read requests so expensive reads do not share the scheduler store connection.
- Match the desktop card detail panel layout to the mobile overlay with artwork on the left and details on the right.

## 1.1.5 - 2026-05-07

- Fix the optimized card listing SQL query by restoring the missing CTE separator.
- Roll back failed read transactions so one SQL error does not leave subsequent API requests in an aborted transaction.

## 1.1.4 - 2026-05-07

- Make the desktop card detail panel more compact and remove duplicated detail values.
- Keep the price history chart fill while removing individual point markers.
- Speed up card listing responses by sharing page and summary data through one query.
- Speed up collection value history by avoiding per-point lateral snapshot scans and adding snapshot indexes.

## 1.1.3 - 2026-05-07

- Restore the desktop card detail view as a right-side panel while keeping the mobile detail view as an overlay.
- Improve the mobile detail overlay layout with a larger card image and denser card metadata.
- Redesign the price history chart to match the app theme and show latest, change, low, high, price axis, and date labels.
- Keep card detail copy consistently in English.

## 1.1.2 - 2026-05-07

- Replace the inline card detail panel with a modal overlay on all viewport sizes.
- Remove the mobile detail panel that appeared below the collection list.
- Show card details with artwork, edition, quantity, tracked metadata, Scryfall link, and a chart-only price history.

## 1.1.1 - 2026-05-05

- Add Renovate configuration for Python dependencies, container images, Docker Compose defaults, and GitHub Actions.
- Add a GitHub Actions test workflow and run the Python test suite before publishing Docker images.
- Update Python container and GitHub Actions versions used by CI and image publishing.
- Bump the psycopg dependency lower bound to `3.3.4`.
- Expand test coverage for exchange-rate conversion and price refresh behavior.
- Refresh README wording and dependency update documentation.

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
