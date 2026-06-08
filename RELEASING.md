# Publishing releases (maintainer)

Nothing under `data/` is in git. The SQLite datasets and the compiled GiellaLT
models ship as separate GitHub release assets; `scripts/fetch_data.sh` and
`scripts/fetch_giella.sh` pull them back down.

Tracked in git: `src/`, `resources/`, `tools/giella/bin/`, `scripts/`,
`pyproject.toml`, `modal_app.py`, and the docs. The whole `data/` folder is
ignored (datasets are released separately; Giella models are generated).

## The dataset

The databases ship as one asset with the dataset `LICENSE` and `NOTICE` bundled
alongside them, so the CC-BY-SA-4.0 attribution travels with the data. Once your
local `data/` holds all five files (after `make data`), publish with:

```sh
make release-data DATA_TAG=data-v1
```

That builds `vro-data.tar.xz` and creates the GitHub release. For later updates
bump the tag (`DATA_TAG=data-v2`) and set the matching `VRO_DATA_TAG` default in
`scripts/fetch_data.sh` so downloads point at the new archive.

## The GiellaLT artifacts

The compiled GiellaLT models ship as a separate asset, since they are GPL-3.0
(the dataset is CC-BY-SA-4.0). Build them once with `make giella-build` (this
also writes the GPL-3.0 `LICENSE` and a provenance `NOTICE` into
`data/giella-share/`), then publish:

```sh
make release-giella GIELLA_TAG=giella-v1
```

That archives `data/giella-share/` (license + notice included) and creates the
release. Bump `GIELLA_TAG` and the matching `VRO_GIELLA_TAG` default in
`scripts/fetch_giella.sh` when you rebuild.
