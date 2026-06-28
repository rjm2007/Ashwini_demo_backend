# AI Service (FastAPI)

This service runs two responsibilities:
- Async processing pipeline (`SQS -> OCR -> extraction -> chunk -> embed -> Qdrant`)
- Query answering pipeline (`intent -> certified retrieval -> reasoning -> confidence`)

## Internal endpoints

- `GET /health`
- `POST /internal/process/{document_id}`
- `POST /query/answer`
- `POST /internal/update-chunks`
