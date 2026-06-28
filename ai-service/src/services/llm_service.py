import logging
from openai import OpenAI
from ..config import settings
from .cost_tracker import record_cost

logger = logging.getLogger("llm")
logger.setLevel(logging.INFO)


class LlmService:
    """This class centralizes small and large model calls."""

    def __init__(self) -> None:
        self.client = OpenAI(api_key=settings.openai_api_key)

    def _chat(
        self,
        model: str,
        prompt: str,
        system_message: str,
        preferred_temperature: float | None,
        stage: str = "llm",
        document_id: str | None = None,
        session_id: str | None = None,
    ) -> str:
        """Generic chat-completion wrapper that retries without temperature if the model rejects it."""
        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt},
        ]
        kwargs: dict = {"model": model, "messages": messages}
        if preferred_temperature is not None:
            kwargs["temperature"] = preferred_temperature
        try:
            response = self.client.chat.completions.create(**kwargs)
        except Exception as error:
            # Some newer models (e.g. gpt-5.x reasoning) only allow the default temperature.
            # Retry once without it before giving up.
            if preferred_temperature is not None and "temperature" in str(error).lower():
                logger.warning(
                    "model=%s rejected temperature=%s, retrying without it (%s)",
                    model,
                    preferred_temperature,
                    error,
                )
                kwargs.pop("temperature", None)
                try:
                    response = self.client.chat.completions.create(**kwargs)
                except Exception as retry_error:
                    logger.exception("LLM call FAILED on retry model=%s error=%s", model, retry_error)
                    raise
            else:
                logger.exception("LLM call FAILED model=%s error=%s", model, error)
                raise
        content = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        if usage:
            record_cost(
                stage=stage,
                provider="openai",
                model=model,
                document_id=document_id,
                session_id=session_id,
                input_tokens=getattr(usage, "prompt_tokens", None),
                output_tokens=getattr(usage, "completion_tokens", None),
            )
        return content

    def small_model_call(
        self,
        prompt: str,
        system_message: str,
        stage: str = "llm_small",
        document_id: str | None = None,
    ) -> str:
        """This function calls the configured low-cost model for extraction tasks."""
        logger.info("LLM small call model=%s prompt_chars=%d", settings.small_model, len(prompt))
        content = self._chat(
            settings.small_model,
            prompt,
            system_message,
            preferred_temperature=0,
            stage=stage,
            document_id=document_id,
        )
        if not content:
            content = "{}"
        logger.info("LLM small call ok response_chars=%d", len(content))
        return content

    def large_model_call(
        self,
        prompt: str,
        system_message: str,
        stage: str = "llm_large",
        document_id: str | None = None,
        session_id: str | None = None,
    ) -> str:
        """This function calls the configured reasoning model for final responses."""
        logger.info("LLM large call model=%s prompt_chars=%d", settings.large_model, len(prompt))
        preferred_temperature = None if settings.large_model.startswith("gpt-5") else 0.1
        content = self._chat(
            settings.large_model,
            prompt,
            system_message,
            preferred_temperature=preferred_temperature,
            stage=stage,
            document_id=document_id,
            session_id=session_id,
        )
        logger.info("LLM large call ok response_chars=%d", len(content))
        return content
