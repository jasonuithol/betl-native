#!/usr/bin/env bash
# tools/betl-container/run-container.sh — start the betl container.
#
# Defaults to `ui` (the yaml-ui on http://127.0.0.1:8765) which is the
# common case. Pass any other subcommand to override:
#
#   ./run-container.sh                                 # ui
#   ./run-container.sh validate examples/.../foo.yml   # one-shot validate
#   ./run-container.sh run      examples/.../foo.yml   # one-shot run
#   ./run-container.sh convert  path/to/pkg.dtsx       # one-shot convert
#   ./run-container.sh bash                            # interactive shell
#
# Shares overrides with build.sh + the `betl` wrapper:
#   BETL_IMAGE    image tag (default: betl:dev)
#   BETL_RUNTIME  podman | docker (auto-detected)
#   BETL_UI_PORT  host port for `ui` (default: 8765)

set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
exec "$here/betl" "${@:-ui}"
