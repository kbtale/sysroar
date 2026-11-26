FROM rust:1.85-slim-bookworm AS builder

WORKDIR /src
COPY Cargo.toml Cargo.lock ./
COPY src ./src
RUN cargo build --release --locked

FROM debian:bookworm-slim AS runner

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    useradd --system --create-home --home-dir /var/lib/sysroar-agent --shell /usr/sbin/nologin sysroar

COPY --from=builder /src/target/release/sysroar-agent /usr/local/bin/sysroar-agent
USER sysroar
WORKDIR /var/lib/sysroar-agent
ENV SYSROAR_BUFFER_PATH=/var/lib/sysroar-agent/buffer.db

ENTRYPOINT ["/usr/local/bin/sysroar-agent"]
