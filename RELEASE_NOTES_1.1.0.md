# Release 1.1.0

## Highlights

- Added clearer API endpoint names for price history data:
  - `/api/cards/{tracking_id}/price-history`
  - `/api/collection/value-history`
- Kept the existing `/api/cards/{tracking_id}/history` and `/api/value-history` endpoints for compatibility.
- Added `page` and `page_size` query parameters plus pagination metadata for card price history.
- Updated the frontend to request the latest 100 card price snapshots by default and show when more snapshots are available.

## Compatibility

This release is backward compatible with existing clients using the previous history endpoints.

## Verification

- `python -m pytest`
- `node --check jace/static/app.js`
