"""
Layer 1 classifier — hybrid rules-first, LLM-fallback-on-ambiguous-residue
(Spec Section 4).

One rule this file exists to enforce in code, not just in the doc: an
unclassifiable field defaults to NA, never to D. NA is the correct
low-confidence answer for "no signal found" — quietly defaulting to D would
inflate the Decision Register with content nobody actually decided anything
about, which is exactly the failure mode Section 1 rules out. If a future
pass decides this is too conservative, that's a threshold-tuning
conversation to have explicitly, not a default to flip silently.
"""
import json
from dataclasses import dataclass
from typing import List, Optional

from app.config import settings

# --- structured field deterministic map (Section 1) ---
# DETRM tagline framing: D = traceable owned acts, E = gates/rules/compliance,
# T = adoption/quality/velocity drift, R = governance currency/evolution.
STRUCTURED_FIELD_MAP = {
    "resolution": "D",
    "priority": "E",
    "component": "T",
    "fix_version": "T",
}

LABEL_MAP = {
    "policy": "E",
    "compliance": "E",
    "deprecated": "R",
    "stale": "R",
}

DECISION_MARKERS = ["decided", "decision", "going with", "selected", "signed off", "will ship", "approved"]
ENFORCEMENT_MARKERS = ["policy", "must not", "blocked by", "requires approval", "compliance", "gate", "not allowed"]
TREND_MARKERS = ["trending", "increasing", "recurring", "pattern", "velocity", "adoption", "growing"]
REVIEW_MARKERS = ["retire", "deprecate", "stale", "audit", "no longer needed", "revisit", "outdated"]

MARKER_SETS = {"D": DECISION_MARKERS, "E": ENFORCEMENT_MARKERS, "T": TREND_MARKERS, "R": REVIEW_MARKERS}


@dataclass
class ClassificationResult:
    classification: str   # "D" | "E" | "T" | "R" | "NA"
    confidence: float
    source: str            # "rule" | "llm"
    rationale: str


def classify_structured_field(field_name: str, value: Optional[str] = None) -> ClassificationResult:
    """Deterministic map for structured fields — always rule-sourced, confidence 1.0."""
    if field_name.lower() == "labels" and value:
        detrm = LABEL_MAP.get(value.lower())
        if detrm:
            return ClassificationResult(detrm, 1.0, "rule", f"Label '{value}' maps deterministically to {detrm}.")
        return ClassificationResult("NA", 1.0, "rule", f"Label '{value}' carries no DETRM signal by definition.")

    detrm = STRUCTURED_FIELD_MAP.get(field_name.lower())
    if detrm:
        return ClassificationResult(detrm, 1.0, "rule", f"Structured field '{field_name}' maps deterministically to {detrm}.")
    return ClassificationResult("NA", 1.0, "rule", f"Structured field '{field_name}' carries no DETRM signal by definition.")


def _keyword_score(text: str, markers: List[str]) -> float:
    text_l = text.lower()
    hits = sum(1 for m in markers if m in text_l)
    if hits == 0:
        return 0.0
    return min(0.5 + 0.15 * (hits - 1), 0.85)


def classify_free_text_fast(text: str) -> ClassificationResult:
    """Rule pass on free text (description/comments) — Section 4 rule layer."""
    if not text or not text.strip():
        return ClassificationResult("NA", 1.0, "rule", "Empty field — no content to classify.")

    scores = {k: _keyword_score(text, markers) for k, markers in MARKER_SETS.items()}
    best_type = max(scores, key=scores.get)
    best_score = scores[best_type]

    if best_score == 0.0:
        # No keyword signal on non-empty text. Deliberately below the LLM
        # fallback threshold — substantial free text with no rule-layer hit
        # is exactly the "ambiguous residue" Section 4 wants a second look
        # at, unlike a genuinely empty field.
        return ClassificationResult("NA", 0.5, "rule", "No DETRM-relevant keyword signal found on non-empty text.")

    return ClassificationResult(best_type, best_score, "rule", f"Keyword match on {best_type} markers.")


def classify_free_text_deep(text: str) -> ClassificationResult:
    """
    LLM fallback — only reached for ambiguous residue (Section 4). Falls
    back to the rule-layer result unchanged if no API key is configured, so
    this module works standalone in local dev and tests without a live key.
    """
    fast = classify_free_text_fast(text)
    if not settings.anthropic_api_key:
        return ClassificationResult(
            fast.classification, fast.confidence, fast.source,
            fast.rationale + " (LLM fallback skipped: no API key configured)",
        )

    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    prompt = (
        "Classify this text under the DETRM taxonomy. Respond with JSON only, "
        "no other text.\n"
        "D = Decision (traceable, owned act), E = Enforcement (gate/rule/compliance), "
        "T = Trend (adoption/quality/velocity drift), R = Review (governance currency/evolution), "
        "NA = no DETRM-relevant signal.\n\n"
        f"Text: {text}\n\n"
        '{"classification": "D|E|T|R|NA", "confidence": 0.0-1.0, "rationale": "one sentence"}'
    )
    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
    parsed = json.loads(raw)
    return ClassificationResult(parsed["classification"], float(parsed["confidence"]), "llm", parsed["rationale"])


def classify_free_text(text: str) -> ClassificationResult:
    """Entry point: rule pass first, LLM only on ambiguous residue (Section 4)."""
    result = classify_free_text_fast(text)
    if result.confidence < settings.llm_fallback_threshold:
        result = classify_free_text_deep(text)
    return result
