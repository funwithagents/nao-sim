# Rename the vendor folder to image data

**Status:** Done

Implements the naming of [specs/runtime/api.md](../specs/runtime/api.md) ("Files on disk"), [specs/container/container.md](../specs/container/container.md) and [specs/project.md](../specs/project.md): the folder holding what the images are built from and the record of the verified images is the **image data**, everywhere. It holds Aldebaran's suites and `animations.pkg` but also `hashes.json` and `images.json`, so "vendor" named only part of it. No behaviour changes but the names; nothing was published under the old ones, so no alias is kept.

## Scope

| Was | Becomes |
| --- | --- |
| `NAO_SIM_VENDOR` | `NAO_SIM_IMAGE_DATA` |
| `nao-sim fetch-and-build-images --vendor DIR` | `--image-data DIR` |
| `docker/vendor/` (checkout, gitignored) | `docker/image-data/` |
| `<user data>/nao-sim/vendor/` (installed) | `<user data>/nao-sim/image-data/` |
| build context `vendor` (`COPY --from=vendor`) | `image-data` |
| `files.VENDOR`, `vendor` arguments, `suite.VendorFile` | `files.IMAGE_DATA`, `image_data`, `suite.PinnedFile` |
| "vendor files", "vendor folder" in docs | "image data", "image data folder" |

Files: `src/nao_sim/{files,docker_images,suite,cli,errors}.py`, `docker/compose.yaml`, both Dockerfiles and their ignore files, `.gitignore`, `pyproject.toml`, `.github/workflows/ci.yml` (cache path), `tests/`, `tests-e2e/`, `README.md`, `AGENTS.md`, the specs. Done plans keep their wording: they record what was built then.

## Steps

1. Scripted renames of the identifiers and paths above, then the prose; review every remaining "vendor" by hand.
2. Move this machine's `docker/vendor/` to `docker/image-data/` (gitignored, so a plain `mv`; `images.json` and `hashes.json` stay valid, their keys are relative).
3. Specs: names only, statuses unchanged at the end (`Updated` while this plan runs, `Implemented` when it is `Done`).

## Verification

Lint, format, pyright, fast tier; the live tier on both versions (the Dockerfiles change, so the images rebuild once); CI green on main (one cold build per entry, the cache now holding `docker/image-data/images.json`).
