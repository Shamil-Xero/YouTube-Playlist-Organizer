"""Builds the categorization prompt/schema and interprets the LLM's answer."""

CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}
NONE_SENTINEL = "none"


def build_prompt(video: dict, categories: list) -> str:
    cat_lines = "\n".join(
        f'- "{c["name"]}": {c.get("description", "")}' for c in categories
    )
    description = (video.get("description") or "")[:1000]
    tags = ", ".join(video.get("tags", [])[:15])

    return f"""You are sorting YouTube videos into playlists. Given the video details below, \
pick the single best-fitting category from this list, or "{NONE_SENTINEL}" if nothing fits well:

{cat_lines}

If you pick "{NONE_SENTINEL}", also suggest a short, descriptive new category name \
(1-2 words, Title Case) in the "suggested_category" field that would be a good fit \
for this video. If an existing category fits, leave "suggested_category" as an empty string.

Video details:
Title: {video.get('title', '')}
Channel: {video.get('channel', '')}
Tags: {tags}
Description (truncated): {description}
"""


def build_schema(categories: list) -> dict:
    """JSON schema handed to LM Studio's structured-output mode. Constraining
    "category" to this enum means the model literally cannot return a
    category name that isn't one of yours (or the none-of-the-above sentinel)."""
    names = [c["name"] for c in categories] + [NONE_SENTINEL]
    return {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": names},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "reason": {"type": "string"},
            "suggested_category": {"type": "string"},
        },
        "required": ["category", "confidence", "reason", "suggested_category"],
    }


def classify(video: dict, categories: list, llm_client, min_confidence: str = "medium"):
    """Returns (category_name_or_None, confidence, reason, suggested_category)."""
    prompt = build_prompt(video, categories)
    schema = build_schema(categories)
    result = llm_client.generate_json(prompt, schema, schema_name="video_category")

    if not result or "category" not in result:
        return None, "low", "model returned no usable answer", ""

    category = result.get("category")
    confidence = str(result.get("confidence", "low")).lower()
    reason = result.get("reason", "")
    suggested = result.get("suggested_category", "").strip()

    if category == NONE_SENTINEL:
        return None, confidence, reason or "no category judged a good fit", suggested

    valid_names = {c["name"] for c in categories}
    if category not in valid_names:
        return None, "low", reason or "category not in allowed list", suggested

    if CONFIDENCE_ORDER.get(confidence, 0) < CONFIDENCE_ORDER.get(min_confidence, 1):
        return None, confidence, reason or "confidence below threshold", suggested

    return category, confidence, reason, ""
