"""Photo recognition of water meter readings using a vision model.

Supports two providers:
- anthropic  (Claude vision via Anthropic SDK)
- openrouter (OpenAI-compatible, free models e.g. google/gemini-flash-1.5)

Extracts integer reading value and confidence from uploaded meter photo.
Photo is not stored after processing.
"""
from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from home_bills_agent.config import settings

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

VISION_PROMPT = (
    "Ты — система распознавания показаний водяного счётчика. "
    "На фото изображен счётчик с цифровым табло. "
    "Верни строго JSON в формате: "
    '{"value": <целое число показания>, "confidence": <уверенность 0.0-1.0>}. '
    "Если цифры неразборчивы или фото не содержит счётчик, верни "
    '{"value": null, "confidence": 0.0}. '
    "Показание — всегда целое число (счётчик не показывает дробные значения). "
    "Не добавляй никакого текста кроме JSON."
)


@dataclass
class VisionResult:
    """Result of meter reading recognition."""
    value: int | None
    confidence: float
    raw_response: str


def _parse_result(text: str) -> VisionResult:
    """Parse model text output into VisionResult."""
    text = text.strip()
    try:
        data = json.loads(text)
        value = data.get("value")
        confidence = float(data.get("confidence", 0.0))
        if value is not None:
            value = int(value)
        return VisionResult(value=value, confidence=confidence, raw_response=text)
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.warning("Failed to parse vision response: %s, raw: %s", e, text)
        return VisionResult(value=None, confidence=0.0, raw_response=text)


async def _recognize_anthropic(image_bytes: bytes, mime_type: str) -> VisionResult:
    client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    b64 = base64.b64encode(image_bytes).decode("ascii")
    resp = await client.messages.create(
        model=settings.VISION_MODEL,
        max_tokens=200,
        temperature=0,
        system=VISION_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime_type,
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": "Распознай показание счётчика."},
                ],
            }
        ],
    )
    text = ""
    for block in resp.content:
        if block.type == "text":
            text += block.text
    return _parse_result(text)


async def _recognize_openrouter(image_bytes: bytes, mime_type: str) -> VisionResult:
    client = AsyncOpenAI(
        api_key=settings.OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
        default_headers={"HTTP-Referer": "https://github.com/home-bills-agent", "X-Title": "Anapa Water Agent"},
    )
    b64 = base64.b64encode(image_bytes).decode("ascii")
    resp = await client.chat.completions.create(
        model=settings.VISION_MODEL,
        temperature=0,
        max_tokens=200,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{b64}"},
                    },
                    {"type": "text", "text": VISION_PROMPT},
                ],
            }
        ],
    )
    text = resp.choices[0].message.content or ""
    return _parse_result(text)


async def recognize_reading(image_bytes: bytes, mime_type: str = "image/jpeg") -> VisionResult:
    """Send photo to configured vision provider and parse result."""
    provider = (settings.VISION_PROVIDER or "anthropic").lower()

    if provider == "openrouter":
        if not settings.OPENROUTER_API_KEY:
            logger.warning("OPENROUTER_API_KEY not set, returning zero confidence")
            return VisionResult(value=None, confidence=0.0, raw_response="no_api_key")
        try:
            return await _recognize_openrouter(image_bytes, mime_type)
        except Exception as e:
            logger.exception("OpenRouter vision call failed")
            return VisionResult(value=None, confidence=0.0, raw_response=f"api_error: {e}")

    # default: anthropic
    if not settings.ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not set, returning zero confidence")
        return VisionResult(value=None, confidence=0.0, raw_response="no_api_key")
    try:
        return await _recognize_anthropic(image_bytes, mime_type)
    except Exception as e:
        logger.exception("Anthropic vision call failed")
        return VisionResult(value=None, confidence=0.0, raw_response=f"api_error: {e}")


def is_confident(result: VisionResult) -> bool:
    """Check if confidence meets threshold for auto-accept."""
    return result.confidence >= settings.CONFIDENCE_MIN


def prepare_for_logging(result: VisionResult) -> str:
    """Prepare result for logging (mask raw response if needed)."""
    return f"value={result.value}, confidence={result.confidence:.2f}"