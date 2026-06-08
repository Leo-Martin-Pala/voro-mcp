"""
Modal deployment for the Võro MCP server (Tier 2: full, incl. GiellaLT tools).

Deploy with:   modal deploy modal_app.py
See DEPLOY.md for the full first-time setup (volume upload + secret).

Heavy data (SQLite DBs + Giella FST models) lives in the "vro-data" Modal
Volume, NOT in this image or in git. Only code + system binaries are baked in.
"""

import os
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path

import modal

APP_NAME = "vro-mcp"

# --- System binaries the Giella wrappers shell out to --------------------------
# hfst-optimized-lookup, hfst-ospell, and divvun-checker come from the Apertium/
# Divvun nightly apt repo. Use a Bookworm base because the Bullseye nightly
# metadata has pointed at removed .deb files.
image = (
    modal.Image.from_registry("python:3.11-slim-bookworm")
    .apt_install("curl", "ca-certificates", "gnupg", "perl", "gawk", "bash", "lsb-release")
    .run_commands(
        "curl -fsSL https://apertium.projectjj.com/apt/install-nightly.sh | bash",
        "apt-get update",
        "apt-get install -y --no-install-recommends "
        "hfst hfst-ospell cg3 divvun-gramcheck",
        "rm -rf /var/lib/apt/lists/*",
    )
    .pip_install("mcp>=1.0.0")
    # Point config + Giella wrappers at the Volume-mounted data (see /data below).
    .env(
        {
            "PYTHONPATH": "/app/src",
            "VRO_DICTIONARY_DB": "/data/dictionary.sqlite",
            "VRO_CORPUS_DB": "/data/corpus.sqlite",
            "VRO_WORD_BAG_DB": "/data/word_bag.sqlite",
            "VRO_ANALYZER_MODEL": "/data/giella-share/giella/vro/analyser-gt-desc.hfstol",
            "VRO_GENERATOR_MODEL": "/data/giella-share/giella/vro/generator-gt-norm.hfstol",
            "VRO_SPELLER_MODEL": "/data/giella-share/voikko/3/vro.zhfst",
            "VRO_GRAMMAR_MODEL": "/data/giella-share/voikko/4/vro.zcheck",
        }
    )
    # App code (small) is added last so Modal can mount it efficiently at startup.
    .add_local_dir("src", "/app/src")
    .add_local_dir("resources", "/app/resources")
    .add_local_dir("tools/giella/bin", "/app/tools/giella/bin")
)

app = modal.App(APP_NAME)

# Persistent storage for the big read-only data. Uploaded once from your laptop.
data = modal.Volume.from_name("vro-data", create_if_missing=True)


def _download_and_extract(url: str, destination: Path) -> None:
    with tempfile.NamedTemporaryFile(suffix=".tar.xz") as archive:
        print(f"Downloading {url}")
        urllib.request.urlretrieve(url, archive.name)
        with tarfile.open(archive.name, "r:xz") as tar:
            for member in tar.getmembers():
                target = (destination / member.name).resolve()
                if destination.resolve() not in target.parents and target != destination.resolve():
                    raise ValueError(f"archive member escapes destination: {member.name}")
            tar.extractall(destination)


@app.function(
    image=image,
    volumes={"/data": data},
    timeout=600,
)
def hydrate_release_data(
    *,
    force: bool = False,
    repo: str = "Leo-Martin-Pala/voro-mcp",
    data_tag: str = "data-v1",
    giella_tag: str = "giella-v1",
):
    data_root = Path("/data")
    db_paths = [
        data_root / "dictionary.sqlite",
        data_root / "corpus.sqlite",
        data_root / "word_bag.sqlite",
    ]
    giella_root = data_root / "giella-share"

    if force:
        for path in db_paths:
            path.unlink(missing_ok=True)
        shutil.rmtree(giella_root, ignore_errors=True)

    if force or not all(path.exists() for path in db_paths):
        url = f"https://github.com/{repo}/releases/download/{data_tag}/vro-data.tar.xz"
        with tempfile.TemporaryDirectory() as extracted:
            extracted_root = Path(extracted)
            _download_and_extract(url, extracted_root)
            mapping = {
                "vro_dictionary.sqlite": "dictionary.sqlite",
                "vro_corpus.sqlite": "corpus.sqlite",
                "vro_word_bag.sqlite": "word_bag.sqlite",
            }
            for source_name, target_name in mapping.items():
                shutil.copy2(extracted_root / source_name, data_root / target_name)
        print("SQLite datasets are present in the Modal Volume.")
    else:
        print("SQLite datasets already exist; skipping release download.")

    if force or not giella_root.exists():
        url = f"https://github.com/{repo}/releases/download/{giella_tag}/giella-share.tar.xz"
        giella_root.mkdir(parents=True, exist_ok=True)
        _download_and_extract(url, giella_root)
        print("Giella artifacts are present in the Modal Volume.")
    else:
        print("Giella artifacts already exist; skipping release download.")

    data.commit()


@app.local_entrypoint()
def hydrate_release():
    force = os.getenv("FORCE_DATA", "0") == "1"
    repo = os.getenv("VRO_DATA_REPO", "Leo-Martin-Pala/voro-mcp")
    data_tag = os.getenv("VRO_DATA_TAG", "data-v1")
    giella_tag = os.getenv("VRO_GIELLA_TAG", "giella-v1")
    hydrate_release_data.remote(
        force=force,
        repo=repo,
        data_tag=data_tag,
        giella_tag=giella_tag,
    )


@app.function(
    image=image,
    volumes={"/data": data},
    # Holds MCP_PATH=/<random>/mcp -> the unguessable secret URL segment.
    secrets=[modal.Secret.from_name("vro-mcp-secret")],
    min_containers=0,  # scale to zero when idle => effectively free
    timeout=120,
)
@modal.concurrent(max_inputs=50)
@modal.asgi_app()
def serve():
    from vro_mcp.server import create_server

    return create_server().streamable_http_app()
