#!/usr/bin/env bash
# Build the Wasm component and print its sha256.
#   scripts/build.sh            native toolchain (rustup 1.97.1 + cargo-component 0.21.1)
#   scripts/build.sh --docker   inside the pinned builder image (no host toolchain needed)
set -euo pipefail
cd "$(dirname "$0")/.."

PKG=serpapi_fdw
OUT="target/wasm32-unknown-unknown/release/${PKG}.wasm"

if [[ "${1:-}" == "--docker" ]]; then
  docker image inspect serpapi-fdw-builder:latest >/dev/null 2>&1 || docker build -f Dockerfile.build -t serpapi-fdw-builder:latest .
  docker run --rm -v "$PWD:/work" \
    -v serpapi-fdw-cargo:/usr/local/cargo/registry -v serpapi-fdw-rustup:/usr/local/rustup \
    -w /work serpapi-fdw-builder:latest \
    cargo component build --release --target wasm32-unknown-unknown
else
  export PATH="$HOME/.cargo/bin:$PATH"
  # macOS: the system linker needs an explicit SDK when Command Line Tools lag the OS.
  if [[ "$(uname)" == "Darwin" && -z "${SDKROOT:-}" ]]; then
    export SDKROOT="$(xcrun --show-sdk-path 2>/dev/null || echo /Library/Developer/CommandLineTools/SDKs/MacOSX.sdk)"
  fi
  cargo component build --release --target wasm32-unknown-unknown
fi

test -f "$OUT" || { echo "build did not produce $OUT" >&2; exit 1; }
SUM=$(shasum -a 256 "$OUT" | awk '{print $1}')
mkdir -p dist
cp "$OUT" "dist/${PKG}.wasm"
chmod 644 "dist/${PKG}.wasm"   # the db runs as another user; a 0600 file reads as "invalid WebAssembly component"
echo "$SUM  ${PKG}.wasm" > dist/checksum.txt
echo "built dist/${PKG}.wasm ($(du -h "dist/${PKG}.wasm" | cut -f1))"
echo "sha256 $SUM"
