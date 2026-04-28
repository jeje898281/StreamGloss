from __future__ import annotations

import json
import re
from typing import Optional


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)

_PREFIXES = [
    re.compile(r"(?is)^\s*here\s+is\s+(the\s+)?translation\s*[:：]?\s*"),
    re.compile(r"(?is)^\s*the\s+translation\s+is\s*[:：]?\s*"),
    re.compile(r"(?is)^\s*以下(?:為|是)翻譯\s*[:：]?\s*"),
    re.compile(r"(?is)^\s*翻譯(?:如下|結果)?\s*[:：]?\s*"),
    re.compile(r"(?is)^\s*好的[,，]?\s*"),
]


def strip_conversational_filler(text: str) -> str:
    t = text.strip()
    t = _FENCE.sub("", t).strip()
    for pat in _PREFIXES:
        t = pat.sub("", t).strip()
    return t


def _parse_json_translation(blob: str) -> Optional[str]:
    blob = blob.strip()
    try:
        obj = json.loads(blob)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    for key in ("translation", "translated_text", "tw", "zh", "text"):
        v = obj.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _regex_extract_translation_value(blob: str) -> Optional[str]:
    """
    處理模型吐出不合法 JSON（例如混用單雙引號）時，盡量抽出 translation 的值。
    """
    m = re.search(
        r'"translation"\s*:\s*"(.+)"\s*\}',
        blob,
        re.DOTALL,
    )
    if m:
        inner = m.group(1)
        inner = inner.replace('\\"', '"').replace("\\n", "\n").strip()
        if inner:
            return inner
    m2 = re.search(r'"translation"\s*:\s*\'(.+)\'\s*\}', blob, re.DOTALL)
    if m2:
        return m2.group(1).strip()
    m3 = re.search(r'"translation"\s*:\s*"\s*\'([^\']*)\'\s*"', blob)
    if m3:
        return m3.group(1).strip()
    return None


def _strip_wrapping_quotes(s: str) -> str:
    t = s.strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "'\"":
        return t[1:-1].strip()
    return t


def _strip_json_artifact_line(s: str) -> str:
    t = s.strip()
    if t.startswith("{") and "translation" in t:
        parsed = _parse_json_translation(t)
        if parsed is not None:
            return parsed
        rx = _regex_extract_translation_value(t)
        if rx is not None:
            return rx
    return t


def extract_translation(raw: str) -> str:
    """
    Prefer strict JSON from the model; fall back to regex cleanup of plain text.
    """
    cleaned = strip_conversational_filler(raw)

    parsed = _parse_json_translation(cleaned)
    if parsed is not None:
        return parsed

    m = re.search(r"\{[^{}]*\"(?:translation|translated_text)\"[^{}]*\}", cleaned, re.DOTALL)
    if m:
        parsed = _parse_json_translation(m.group(0))
        if parsed is not None:
            return parsed

    rx = _regex_extract_translation_value(cleaned)
    if rx is not None:
        return _strip_wrapping_quotes(rx)

    out = _strip_json_artifact_line(cleaned)
    return _strip_wrapping_quotes(out)
