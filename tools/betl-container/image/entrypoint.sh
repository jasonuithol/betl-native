#!/bin/sh
# In-image dispatch entrypoint. First arg picks the tool:
#
#   betl <args>        → C engine (validate / run / --version / ...)
#   ui                 → yaml-ui (HTTP server on 0.0.0.0:8765)
#   convert <dtsx>     → dtsx2yaml
#   dtsx2yaml <args>   → dtsx2yaml (verbose alias)
#   <anything-else>    → exec verbatim (escape hatch for shells / debugging)
set -e
if [ $# -eq 0 ]; then
    exec /opt/betl/bin/betl --help
fi
case "$1" in
    ui)        shift; exec /opt/betl/bin/betl-ui "$@" ;;
    convert)   shift; exec /opt/betl/bin/betl-dtsx2yaml "$@" ;;
    dtsx2yaml) shift; exec /opt/betl/bin/betl-dtsx2yaml "$@" ;;
    validate|run|--version|-V|--help|-h)
               exec /opt/betl/bin/betl "$@" ;;
    *)         exec "$@" ;;
esac
