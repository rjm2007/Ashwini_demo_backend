# Review Module

Supports reviewer metadata corrections, reviewer approval, admin final approval, and rejection flow.

## Endpoints
- `GET /review/pending`
- `PATCH /review/:documentId/metadata`
- `POST /review/:documentId/reviewer-approve`
- `POST /review/:documentId/admin-approve`
- `POST /review/:documentId/reject`
