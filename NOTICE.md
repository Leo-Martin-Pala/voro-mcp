## Project Code

The Python package, Modal app, shell scripts, tests, and documentation in this
repository are licensed under the MIT License unless a file says otherwise.
See `LICENSE`.

## Dataset

The SQLite datasets (`vro_dictionary.sqlite`, `vro_corpus.sqlite`,
`vro_word_bag.sqlite`) are not part of this repository. They are distributed as a
GitHub release archive that bundles the full dataset license and source
attribution; `scripts/fetch_data.sh` downloads and extracts them into `data/`.

The datasets are licensed CC-BY-SA-4.0 and aggregate sources released under
CC-BY-SA-4.0, CC-BY-SA-3.0, and CC-BY-4.0: Vikipeediä (Võro Wikipedia), the Võro
IDS wordlist (Cosgrove & Iva), the Võro/Seto ilukirjanduskorpus, and the
Võro–Estonian paralleelkorpus. Full per-source attribution ships in the
`NOTICE` inside the release archive.

This notice does not apply to generated runtime artifacts under
`data/giella-share/`.

## GiellaLT / Divvun Runtime Artifacts

The server optionally uses compiled GiellaLT/Divvun artifacts (analyzers,
generators, spellers, grammar checker) in `data/giella-share/`. These are not in
this repository. They are distributed as a separate GitHub release asset
(`scripts/fetch_giella.sh`), or can be built from source with
`scripts/install_giella_artifacts.sh` (`make giella-build`).

These artifacts are **GPL-3.0**. They are generated from upstream GiellaLT
sources: giella-core, shared-mul, and shared-smi (GPL-3.0), and lang-vro
(LGPL-3.0). Because GPL-3.0 material is incorporated, the combined artifacts are
licensed under GPL-3.0. The release archive bundles the GPL-3.0 license and a
NOTICE listing each upstream repository, its license, and the commit built from
(the corresponding source). This is independent of the project code (MIT) and
the dataset (CC-BY-SA-4.0).
