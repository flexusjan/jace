# Changelog

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
