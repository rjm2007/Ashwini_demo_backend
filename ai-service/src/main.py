import asyncio
from fastapi import FastAPI
from .api.routes import router
from .api.voice_routes import router as voice_router
from .workers.sqs_consumer import start_sqs_consumer_loop
from .logging_config import setup_logging

setup_logging()

app = FastAPI(title="Warranty AI Service")
app.include_router(router)
app.include_router(voice_router)


@app.on_event("startup")
async def on_startup() -> None:
    """This function starts the SQS consumer loop in background."""
    asyncio.create_task(start_sqs_consumer_loop())
