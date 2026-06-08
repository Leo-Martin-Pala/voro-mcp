from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _path_from_env(name: str, default: Path) -> Path:
    value = os.getenv(name)
    return Path(value).expanduser() if value else default


def _str_from_env(name: str, default: str) -> str:
    return os.getenv(name, default)


@dataclass(frozen=True)
class Settings:
    dictionary_db: Path
    corpus_db: Path
    word_bag_db: Path
    neurotolge_base_url: str
    analyzer_cmd: str
    generator_cmd: str
    speller_cmd: str
    grammar_cmd: str


def load_settings() -> Settings:
    giella_bin = REPO_ROOT / "tools" / "giella" / "bin"
    return Settings(
        dictionary_db=_path_from_env("VRO_DICTIONARY_DB", REPO_ROOT / "data" / "vro_dictionary.sqlite"),
        corpus_db=_path_from_env("VRO_CORPUS_DB", REPO_ROOT / "data" / "vro_corpus.sqlite"),
        word_bag_db=_path_from_env("VRO_WORD_BAG_DB", REPO_ROOT / "data" / "vro_word_bag.sqlite"),
        neurotolge_base_url=_str_from_env(
            "VRO_NEUROTOLGE_BASE_URL",
            "https://api.tartunlp.ai/translation/v2",
        ),
        analyzer_cmd=_str_from_env("VRO_ANALYZER_CMD", str(giella_bin / "analyze-vro")),
        generator_cmd=_str_from_env("VRO_GENERATOR_CMD", str(giella_bin / "generate-vro")),
        speller_cmd=_str_from_env("VRO_SPELLER_CMD", str(giella_bin / "spellcheck-vro")),
        grammar_cmd=_str_from_env("VRO_GRAMMAR_CMD", str(giella_bin / "grammar-check-vro")),
    )
