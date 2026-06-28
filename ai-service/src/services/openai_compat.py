"""OpenAI Chat Completions kwargs for GPT-4 vs GPT-5 model families."""


def chat_create_kwargs(model: str, limit: int) -> dict:
    kw = completion_limit_kw(model, limit)
    if _supports_custom_temperature(model):
        kw["temperature"] = 0
    return kw


def _supports_custom_temperature(model: str) -> bool:
    m = (model or "").lower()
    return not m.startswith(("gpt-5", "o1", "o3", "o4"))


def completion_limit_kw(model: str, limit: int) -> dict:
    m = (model or "").lower()
    if m.startswith(("gpt-5", "o1", "o3", "o4")):
        return {"max_completion_tokens": limit}
    return {"max_tokens": limit}
