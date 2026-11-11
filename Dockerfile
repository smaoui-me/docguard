# Build and runtime share a pinned base; deliberately update this digest when
# reviewing Python/OS updates. A build argument permits testing a replacement.
ARG PYTHON_IMAGE=python:3.11-slim-bookworm@sha256:a83ba18aef0f865b1a4a611c2cf460fe446f2795673bbb9fe43be570439e3b39
FROM ${PYTHON_IMAGE} AS builder
WORKDIR /build
COPY pyproject.toml MANIFEST.in README.md ./
COPY src/docguard ./src/docguard
RUN python -m pip wheel --no-cache-dir --no-deps --wheel-dir /wheels .

FROM ${PYTHON_IMAGE} AS runtime
LABEL org.opencontainers.image.source="https://github.com/smaoui-me/docguard"
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 docguard \
    && useradd --uid 10001 --gid 10001 --create-home docguard \
    && mkdir /work /output /workspace \
    && chown docguard:docguard /work /output \
    && git config --system --add safe.directory /workspace
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index --no-deps /wheels/*.whl \
    && rm -rf /wheels
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001
WORKDIR /work
ENTRYPOINT ["docguard"]
CMD ["--help"]
