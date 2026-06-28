from pydantic import BaseModel


class ProcessMessage(BaseModel):
    """This model defines processing queue payload."""

    documentId: str
    s3Path: str
    uploadedBy: str | None = None
