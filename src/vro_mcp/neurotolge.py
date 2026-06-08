from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


VRO_TO_LANGS = {"eng", "est", "fin", "rus", "hun", "lav", "nor"}
LANGS_TO_VRO = {"eng", "est", "fin", "rus", "lav", "hun", "nor"}
SUPPORTED_VRO_PAIRS = {
    *(("vro", target) for target in VRO_TO_LANGS),
    *((source, "vro") for source in LANGS_TO_VRO),
}


class NeurotolgeClient:
    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def translate(self, text: str, source_lang: str | None = None, target_lang: str | None = None) -> dict[str, Any]:
        text = text.strip()
        if not text:
            return {"translated_text": "", "source_lang": source_lang, "target_lang": target_lang}

        source = source_lang or ("est" if target_lang == "vro" else "vro")
        target = target_lang or ("est" if source == "vro" else "vro")
        if (source, target) not in SUPPORTED_VRO_PAIRS:
            return {
                "error": "unsupported_translation_pair",
                "source_lang": source,
                "target_lang": target,
                "supported_from_vro": sorted(VRO_TO_LANGS),
                "supported_to_vro": sorted(LANGS_TO_VRO),
                "detail": (
                    "Use 3-letter API language codes. This MCP only exposes "
                    "currently available live API pairs where one side is vro."
                ),
            }
        payload = {
            "text": text,
            "src": source,
            "tgt": target,
            "source": source,
            "target": target,
        }
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base_url,
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return {
                "error": "translation_api_http_error",
                "status": exc.code,
                "detail": detail,
                "base_url": self.base_url,
            }
        except urllib.error.URLError as exc:
            return {
                "error": "translation_api_unavailable",
                "detail": str(exc.reason),
                "base_url": self.base_url,
            }

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw, "source_lang": source, "target_lang": target}

        translated = self._find_translation(data)
        return {
            "translated_text": translated,
            "source_lang": source,
            "target_lang": target,
            "raw": data,
        }

    @staticmethod
    def _find_translation(data: Any) -> str | None:
        if isinstance(data, str):
            return data
        if isinstance(data, list) and data:
            return NeurotolgeClient._find_translation(data[0])
        if not isinstance(data, dict):
            return None
        for key in ("result", "translation", "translated_text", "translatedText", "text"):
            value = data.get(key)
            if isinstance(value, str):
                return value
        for value in data.values():
            found = NeurotolgeClient._find_translation(value)
            if found:
                return found
        return None
