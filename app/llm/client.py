# app/llm/client.py
import json
import logging
import os

from openai import AzureOpenAI, OpenAI
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 30

# Fixed answer used when LLM_PROVIDER=stub, so A1 and A2 can work offline.
STUB_RESPONSE = {
    "kind": "action",
    "resources": [
        {"type": "storage", "name": "shop", "region": "spaincentral", "sku": "Standard_LRS"},
    ],
    "missing_fields": [],
    "clarifying_question": None,
    "answer": None,
}


def _client():
    """Build the client from environment variables. Never log these values."""
    provider = os.getenv("LLM_PROVIDER", "azure")
    if provider == "azure":
        return AzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_KEY"],
            api_version=os.environ["AZURE_OPENAI_API_VERSION"],  # verify current
        )
    if provider == "openai_compatible":
        return OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"])
    raise ValueError(f"Unknown LLM_PROVIDER: {provider}")


def complete(system: str, user: str, schema: type[BaseModel], retries: int = 1):
    """Call the model, validate its JSON with `schema`, retry once on invalid output."""
    provider = os.getenv("LLM_PROVIDER", "azure")
    if provider == "stub":
        logger.info("LLM call: provider=stub")
        return schema.model_validate(STUB_RESPONSE)

    client, model = _client(), os.environ["LLM_MODEL"]
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user}]
    last_error = None
    for attempt in range(retries + 1):
        logger.info("LLM call: provider=%s model=%s attempt=%d", provider, model, attempt + 1)
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0,
            response_format={"type": "json_object"},
            timeout=TIMEOUT_SECONDS,
        )
        raw = resp.choices[0].message.content
        try:
            return schema.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValidationError) as e:
            last_error = e
            logger.warning("LLM output invalid on attempt %d: %s", attempt + 1, type(e).__name__)
            messages += [
                {"role": "assistant", "content": raw},
                {"role": "user",
                 "content": f"Your JSON was invalid: {e}. Return corrected JSON only."},
            ]
    raise ValueError(f"Model did not return valid JSON: {last_error}")