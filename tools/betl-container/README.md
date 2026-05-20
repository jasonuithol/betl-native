# betl container

Single-image bundle of the C engine, providers, the dtsx2yaml
converter, and the yaml-ui. Builds against pinned Debian bookworm
shared libraries so it's reproducible across hosts.

## Build

From the repo root:

```sh
podman build -t betl:dev -f Containerfile .
```

(`docker build …` works the same; the wrapper script auto-detects
either runtime.)

The first build downloads the .NET 8 SDK and apt packages — expect
3–5 minutes and ~1.5 GB of disk for the build layer. The runtime
image is ~600 MB.

## Run

Use the wrapper:

```sh
tools/betl-container/betl validate examples/01-csv-to-postgres/pipeline.betl.yml
tools/betl-container/betl run     examples/01-csv-to-postgres/pipeline.betl.yml
tools/betl-container/betl convert path/to/package.dtsx
tools/betl-container/betl ui      # http://127.0.0.1:8765
tools/betl-container/betl --version
```

The wrapper bind-mounts `$PWD` at `/workspace`, so paths passed to
betl are interpreted relative to wherever you ran the wrapper from.

### What `betl ui` does

The yaml-ui is a browser-based viewer + editor for `betl.yml` files
served on `http://127.0.0.1:8765`. Toolbar buttons:

- **browse…** — file picker rooted at `/workspace` (the bind-mounted CWD)
- **new** — empty `betl.yml` skeleton
- **save** — write the current buffer back to disk (Ctrl+S)
- **validate** — runs `betl validate` on the on-disk file
- **run…** — pops a parameter form pre-populated from the file's
  `parameters:` section (one widget per declared type), then runs
  `betl run` with the collected `--param` overrides
- **convert dtsx…** — file picker for `.dtsx`; runs dtsx2yaml and opens
  the resulting `.betl.yml`

The inspector (click any stage card / connection chip / parameter
chip) edits a single node's fields, including a **Test connection**
button on connection nodes that synthesizes a one-shot `SELECT 1`
pipeline against the chosen DSN. SQL fields get a CodeMirror overlay
on demand; DSN-style fields get a `key=value` pair editor.

### Environment overrides

- `BETL_IMAGE` — tag to run (default: `betl:dev`).
- `BETL_RUNTIME` — `podman` or `docker` (default: auto-detect).
- `BETL_UI_PORT` — host port for `betl ui` (default: `8765`).
- `BETL_DEV=1` — bind-mount `tools/betl-yaml-ui/` over the image's
  copy and pass `--reload` to uvicorn inside the container. Use this
  while iterating on UI code so changes to `server.py` / `index.html`
  on the host take effect without rebuilding the image:
  ```
  BETL_DEV=1 tools/betl-container/run-container.sh
  ```

### Without the wrapper

```sh
podman run --rm -v "$PWD:/workspace" --userns=keep-id \
    -p 8765:8765 betl:dev ui
```

## Layout inside the image

| Path                                           | What                       |
| ---------------------------------------------- | -------------------------- |
| `/opt/betl/bin/betl`                           | engine CLI                 |
| `/opt/betl/bin/betl-dtsx2yaml`                 | SSIS → betl YAML converter |
| `/opt/betl/bin/betl-ui`                        | viewer launcher            |
| `/opt/betl/lib/betl/providers/betl-*.so`       | dlopen'd providers         |
| `/opt/betl/libexec/dtsx2yaml/Betl.Dtsx2Yaml`   | self-contained .NET app    |
| `/opt/betl/share/yaml-ui/{server.py,index.html}` | UI assets                |
| `/opt/betl/share/betl/schemas/`                | YAML schemas               |
| `/opt/betl/include/betl/`                      | C headers                  |

`$BETL_PROVIDER_DIR` is set to `/opt/betl/lib/betl/providers/` so the
engine auto-loads every provider on startup; override with
`--provider <path>` on the engine command line for a single run.
