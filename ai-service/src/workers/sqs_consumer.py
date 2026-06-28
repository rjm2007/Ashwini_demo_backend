import asyncio
import json
import logging
import boto3
from ..config import settings
from .pipeline_orchestrator import run_act1_parse, run_act2_process

logger = logging.getLogger(__name__)


async def start_sqs_consumer_loop() -> None:
    """This function continuously reads SQS messages and starts document processing."""
    sqs = boto3.client(
        "sqs",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )
    while True:
        try:
            response = sqs.receive_message(
                QueueUrl=settings.sqs_queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20,
            )
            messages = response.get("Messages", [])
            if not messages:
                await asyncio.sleep(1)
                continue
            for message in messages:
                body = json.loads(message["Body"])
                stage = body.get("stage", "act1")
                if stage == "act2":
                    await run_act2_process(body["documentId"])
                else:
                    await run_act1_parse(body["documentId"], body.get("s3Path"))
                sqs.delete_message(
                    QueueUrl=settings.sqs_queue_url,
                    ReceiptHandle=message["ReceiptHandle"],
                )
        except Exception as error:  # pylint: disable=broad-except
            logger.exception("SQS loop error: %s", error)
            await asyncio.sleep(5)
