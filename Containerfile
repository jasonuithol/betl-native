# betl — single image bundling the C engine, the .NET dtsx2yaml
# converter, and the browser-based YAML viewer.
#
# Build:   podman build -t betl:dev -f Containerfile .
# Run:     podman run --rm -v $PWD:/workspace betl:dev validate file.yml
# Wrapper: tools/betl-container/betl handles bind-mounts + port forwarding.
#
# Two stages: `build` compiles everything with full -dev packages,
# `runtime` is a slim image that only carries shared libs the binaries
# actually load at runtime. The final image is roughly 600–800 MB,
# dominated by the self-contained .NET runtime bundled with dtsx2yaml.

# ============================================================================
# 1) build — full toolchain + every optional library betl knows about
# ============================================================================
FROM debian:bookworm AS build

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        cmake \
        build-essential \
        pkg-config \
        curl \
        # C engine deps
        libyaml-dev \
        libpq-dev \
        unixodbc-dev \
        freetds-dev \
        libcurl4-openssl-dev \
        libxml2-dev \
        libicu-dev \
        # provider deps
        liblua5.4-dev \
    && rm -rf /var/lib/apt/lists/*

# .NET 8 SDK for dtsx2yaml. Installed to /opt/dotnet so it doesn't
# bleed into the runtime stage — we only need the published self-
# contained app there.
RUN curl -fsSL https://dot.net/v1/dotnet-install.sh -o /tmp/dotnet-install.sh \
    && bash /tmp/dotnet-install.sh --channel 8.0 --install-dir /opt/dotnet \
    && ln -s /opt/dotnet/dotnet /usr/local/bin/dotnet \
    && rm /tmp/dotnet-install.sh
ENV DOTNET_ROOT=/opt/dotnet

WORKDIR /src
COPY . .

# C engine + providers. CMake's install targets land at /opt/betl/{bin,
# include,lib,share}; providers go under lib/betl/providers/ flat.
RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build build -j \
    && cmake --install build --prefix /opt/betl

# .NET dtsx2yaml — self-contained linux-x64 so the runtime stage
# doesn't need a system-wide dotnet install.
RUN dotnet publish tools/betl-dtsx2yaml/Betl.Dtsx2Yaml.csproj \
        -c Release -r linux-x64 --self-contained \
        -o /opt/betl/libexec/dtsx2yaml

# UI assets
RUN mkdir -p /opt/betl/share/yaml-ui \
    && cp tools/betl-yaml-ui/server.py tools/betl-yaml-ui/index.html \
          /opt/betl/share/yaml-ui/

# Wrapper scripts on PATH. The dispatch entrypoint in the runtime
# stage routes `betl-dtsx2yaml` / `betl-ui` through these.
RUN printf '#!/bin/sh\nexec /opt/betl/libexec/dtsx2yaml/Betl.Dtsx2Yaml "$@"\n' \
        > /opt/betl/bin/betl-dtsx2yaml \
    && chmod +x /opt/betl/bin/betl-dtsx2yaml

# ============================================================================
# 2) runtime — slim base + only the shared libs betl actually loads
# ============================================================================
FROM debian:bookworm-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        # C engine runtime deps
        libyaml-0-2 \
        libpq5 \
        unixodbc \
        libsybdb5 \
        libcurl4 \
        libxml2 \
        libicu72 \
        # provider runtime deps
        liblua5.4-0 \
        # libldap is pulled in transitively by libpq / freetds — pin to
        # the exact major matching bookworm so betl resolves it at load.
        libldap-2.5-0 \
        # UI runtime
        python3 \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /opt/betl /opt/betl

# Pip venv for the UI so we sidestep PEP 668 + don't pollute system Python.
RUN python3 -m venv /opt/betl/venv \
    && /opt/betl/venv/bin/pip install --quiet --no-cache-dir fastapi uvicorn

# betl-ui wrapper: launches the UI server preconfigured to find the
# bundled betl + dtsx2yaml binaries.
RUN cat > /opt/betl/bin/betl-ui <<'EOF' && chmod +x /opt/betl/bin/betl-ui
#!/bin/sh
exec /opt/betl/venv/bin/python /opt/betl/share/yaml-ui/server.py \
    --host 0.0.0.0 \
    --root "${BETL_ROOT:-/workspace}" \
    --betl /opt/betl/bin/betl \
    --dtsx2yaml /opt/betl/libexec/dtsx2yaml/Betl.Dtsx2Yaml \
    "$@"
EOF

# Dispatch entrypoint: first arg picks the tool.
#   betl <args>       → C engine (validate / run / --version / ...)
#   ui                → yaml-ui (HTTP server on 0.0.0.0:8765)
#   convert <dtsx>    → dtsx2yaml
#   <anything-else>   → exec verbatim (escape hatch for shells / debugging)
RUN cat > /opt/betl/bin/entrypoint.sh <<'EOF' && chmod +x /opt/betl/bin/entrypoint.sh
#!/bin/sh
set -e
if [ $# -eq 0 ]; then
    exec /opt/betl/bin/betl --help
fi
case "$1" in
    ui)       shift; exec /opt/betl/bin/betl-ui "$@" ;;
    convert)  shift; exec /opt/betl/bin/betl-dtsx2yaml "$@" ;;
    dtsx2yaml) shift; exec /opt/betl/bin/betl-dtsx2yaml "$@" ;;
    validate|run|--version|-V|--help|-h)
              exec /opt/betl/bin/betl "$@" ;;
    *)        exec "$@" ;;
esac
EOF

ENV PATH=/opt/betl/bin:$PATH \
    BETL_PROVIDER_DIR=/opt/betl/lib/betl/providers \
    LD_LIBRARY_PATH=/opt/betl/lib

WORKDIR /workspace
EXPOSE 8765
ENTRYPOINT ["/opt/betl/bin/entrypoint.sh"]
CMD ["--help"]
