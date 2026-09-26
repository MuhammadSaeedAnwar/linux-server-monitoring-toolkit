# Application container: runs the monitoring loop.
FROM python:3.12-slim

# ping/traceroute/systemctl-adjacent tooling for network diagnostics inside
# the container. systemctl itself isn't meaningful in a container (no init
# system), which is documented as a limitation in the README.
RUN apt-get update && apt-get install -y --no-install-recommends \
        iputils-ping \
        traceroute \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Least privilege: run as a non-root user.
RUN useradd --create-home --uid 1000 toolkit
WORKDIR /app

COPY pyproject.toml ./
COPY monitoring ./monitoring
COPY config ./config
COPY sql ./sql
COPY scripts/entrypoint.sh /entrypoint.sh

RUN pip install --no-cache-dir . && chmod +x /entrypoint.sh

USER toolkit
ENTRYPOINT ["/entrypoint.sh"]
