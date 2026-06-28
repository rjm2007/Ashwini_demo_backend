# Backend Service (NestJS)

This service provides authentication, document upload, review workflow, query session APIs, and dashboard stats.

## Role hierarchy

- `admin` can access all endpoints.
- `reviewer` can access reviewer and user endpoints.
- `user` can access user-level endpoints only.

## Core endpoints

- `POST /auth/login`
- `GET /auth/me`
- `POST /documents/upload`
- `GET /documents`
- `GET /review/pending`
- `POST /query/sessions`
- `POST /query/sessions/:id/messages`
- `GET /dashboard/stats`

## Test login with curl

```bash
curl -X POST http://localhost:3001/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@demo.com","password":"admin123"}'
```
