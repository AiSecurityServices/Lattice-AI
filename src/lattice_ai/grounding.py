"""Evidence grounding verification for findings.

A finding claims facts; grounding checks those claims against the text of the
evidence the run actually recorded (PentestGPT-style exact alignment — no
semantic similarity, so every match/no-match is explainable). Outcomes:

- ``verified``: every claim sentence was found — verbatim modulo casing,
  width, spacing and line breaks, or within a single evidence line with at
  most 20% divergence (line-envelope match);
- ``unverified``: evidence was cited but none of the claims could be matched;
- ``missing_evidence``: the finding cites no evidence, or only ids that do
  not exist.

The policy (``enforce`` / ``mark`` / ``off``, default ``mark``) decides
whether a failed check blocks the finding or only labels it. It lives here
until it is wired to the project security settings page.
"""

import json
import re
import unicodedata
from dataclasses import dataclass, field

MIN_SENTENCE_CHARS = 12
ENVELOPE_THRESHOLD = 0.8
_MAX_SNIPPETS = 5
_REDACTED_MARKERS = ("[REDACTED]",)
_POLICIES = ("enforce", "mark", "off")

_policy = "mark"


@dataclass
class GroundingResult:
    status: str  # verified | unverified | missing_evidence
    detail: str = ""
    matched_snippets: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "detail": self.detail,
            "matched_snippets": list(self.matched_snippets),
        }


def get_policy() -> str:
    return _policy


def set_policy(value: str) -> None:
    global _policy
    if value not in _POLICIES:
        raise ValueError(f"invalid grounding_policy: {value}")
    _policy = value


def _get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _normalize(text: str) -> str:
    """Lowercase, fold full/half width, treat punctuation as separators and
    collapse whitespace so comparisons ignore formatting noise."""
    text = unicodedata.normalize("NFKC", str(text or "")).lower()
    text = "".join(ch if ch.isalnum() else " " for ch in text)
    return " ".join(text.split())


def _tight(text: str) -> str:
    return "".join(_normalize(text).split())


def _grams(tight: str, n: int = 4) -> set:
    if len(tight) <= n:
        return {tight} if tight else set()
    return {tight[i : i + n] for i in range(len(tight) - n + 1)}


def _evidence_text(evidence) -> str:
    result = _get(evidence, "result")
    if result is None:
        result = evidence
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False, default=str)


def _claim_sentences(finding) -> tuple[list[str], int]:
    lines = []
    for key in ("summary", "impact"):
        value = _get(finding, key)
        if isinstance(value, str):
            lines.extend(value.splitlines())
    steps = _get(finding, "repro_steps")
    if isinstance(steps, (list, tuple)):
        lines.extend(str(step) for step in steps)
    claims, skipped = [], 0
    for line in lines:
        line = line.strip().lstrip("-*• ").strip()
        if not line:
            continue
        if any(marker in line for marker in _REDACTED_MARKERS):
            # Redaction replaced the secret, so this sentence can never match
            # the evidence text; skip it and say so in the detail.
            skipped += 1
            continue
        if len(line) >= MIN_SENTENCE_CHARS:
            claims.append(line)
    return claims, skipped


def _window(text: str, needle: str, radius: int = 40) -> str:
    idx = text.find(needle)
    start = max(0, idx - radius)
    end = min(len(text), idx + len(needle) + radius)
    out = text[start:end]
    if start > 0:
        out = "…" + out
    if end < len(text):
        out = out + "…"
    return out


def _envelope_match(claim_grams: set, lines: list[tuple[str, set]]) -> str | None:
    """Line-envelope check: a claim line counts as matched when a single
    evidence line shares at least ENVELOPE_THRESHOLD of its n-grams, i.e. the
    claim appears inside that line with <=20% divergence."""
    if not claim_grams:
        return None
    for line, grams in lines:
        if grams and len(claim_grams & grams) / len(claim_grams) >= ENVELOPE_THRESHOLD:
            return line[:120] + ("…" if len(line) > 120 else "")
    return None


def verify_grounding(finding, evidence_map: dict | None) -> GroundingResult:
    ids = [str(i) for i in (_get(finding, "evidence_ids") or [])]
    if not ids:
        return GroundingResult("missing_evidence", "finding 未引用任何证据（evidence_ids 为空）")

    texts, missing = [], []
    for eid in ids:
        evidence = (evidence_map or {}).get(eid)
        if evidence is None:
            missing.append(eid)
        else:
            texts.append(_evidence_text(evidence))
    if not texts:
        return GroundingResult("missing_evidence", f"引用的证据不存在: {', '.join(missing)}")

    notes = []
    if missing:
        notes.append(f"{len(missing)} 条证据引用不存在: {', '.join(missing)}")

    claims, skipped = _claim_sentences(finding)
    if not claims:
        detail = "无可校验的事实句（句子过短或已脱敏）"
        if notes:
            detail += "；" + "；".join(notes)
        return GroundingResult("verified", detail)

    docs_space = [_normalize(t) for t in texts]
    docs_tight = ["".join(d.split()) for d in docs_space]
    docs_lines = []
    for text in texts:
        lines = [_tight(line) for line in str(text).splitlines() if line.strip()]
        docs_lines.append([(line, _grams(line)) for line in lines])

    matched, unmatched, snippets = 0, 0, []
    for claim in claims:
        claim_space = _normalize(claim)
        claim_tight = "".join(claim_space.split())
        hit = None
        for i, doc_space in enumerate(docs_space):
            if claim_space and claim_space in doc_space:
                hit = _window(doc_space, claim_space)
                break
            if claim_tight and claim_tight in docs_tight[i]:
                hit = _window(docs_tight[i], claim_tight)
                break
        if hit is None and claim_tight:
            for lines in docs_lines:
                hit = _envelope_match(_grams(claim_tight), lines)
                if hit:
                    break
        if hit:
            matched += 1
            snippets.append(hit)
        else:
            unmatched += 1

    if unmatched == 0:
        status = "verified"
        detail = f"{matched} 条事实句全部在证据中命中"
    elif matched:
        status = "unverified"
        detail = f"{unmatched}/{matched + unmatched} 条事实句未能在证据中找到"
    else:
        status = "unverified"
        detail = "所有事实句均未能在证据中找到"
    if skipped:
        notes.append(f"{skipped} 句含脱敏片段已跳过")
    if notes:
        detail += "（" + "；".join(notes) + "）"
    return GroundingResult(status, detail, snippets[:_MAX_SNIPPETS])
