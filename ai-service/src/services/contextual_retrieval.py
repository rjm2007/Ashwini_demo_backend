"""Contextual Retrieval — LLM context blurb prepended before embedding."""

import logging

from openai import OpenAI

from ..config import settings
from .cost_tracker import record_cost
from .openai_compat import chat_create_kwargs

logger = logging.getLogger("contextual_retrieval")

CONTEXT_PROMPT = """<document>
{document_text}
</document>

Here is the chunk we want to situate within the whole document:
<chunk>
{chunk_text}
</chunk>

Please give a short succinct context to situate this chunk within the overall document for the purposes of improving search retrieval of the chunk. The context should:
1. Identify which document this is from (manufacturer, model, year if visible)
2. State which section or topic area the chunk belongs to (coverage, exclusions, towing, components list, etc.)
3. Mention key terms, coverage codes, or component names referenced

Answer ONLY with the context (2-3 sentences). No preamble, no markdown."""


class ContextualRetrieval:
    def __init__(self) -> None:
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = settings.small_model

    def generate_context(
        self,
        full_doc_text: str,
        chunk_text: str,
        document_id: str | None = None,
    ) -> str:
        doc_truncated = full_doc_text[:6000]
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You generate short document context for search retrieval. Be concise and factual.",
                    },
                    {
                        "role": "user",
                        "content": CONTEXT_PROMPT.format(
                            document_text=doc_truncated,
                            chunk_text=chunk_text,
                        ),
                    },
                ],
                **chat_create_kwargs(self.model, 150),
            )
            content = (resp.choices[0].message.content or "").strip()
            usage = getattr(resp, "usage", None)
            if usage:
                record_cost(
                    stage="contextual_retrieval",
                    provider="openai",
                    model=self.model,
                    document_id=document_id,
                    input_tokens=getattr(usage, "prompt_tokens", None),
                    output_tokens=getattr(usage, "completion_tokens", None),
                )
            return content
        except Exception as error:
            logger.warning("Context generation failed: %s", error)
            return ""

    def contextualize_chunks(
        self,
        full_doc_text: str,
        chunks: list[dict],
        document_id: str | None = None,
    ) -> list[dict]:
        logger.info("Contextualizing %d chunks with %s", len(chunks), self.model)
        for i, chunk in enumerate(chunks):
            context = self.generate_context(full_doc_text, chunk["chunkText"], document_id=document_id)
            if context:
                chunk["contextualizedText"] = context + "\n\n" + chunk["chunkText"]
                chunk["contextBlurb"] = context
            else:
                chunk["contextualizedText"] = chunk["chunkText"]
                chunk["contextBlurb"] = ""
            if (i + 1) % 5 == 0 or (i + 1) == len(chunks):
                logger.info("  Contextualized %d/%d", i + 1, len(chunks))
        return chunks
