FROM node:22-bookworm-slim AS node_runtime

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Seoul

COPY --from=node_runtime /usr/local/ /usr/local/

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        git \
        libxml2-dev \
        libxmlsec1-dev \
        libxmlsec1-openssl \
        pkg-config \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/stock8-requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /tmp/stock8-requirements.txt \
    && rm /tmp/stock8-requirements.txt

# Create the WIZ workspace first. Stock8 itself is the workspace's main project.
WORKDIR /opt
RUN wiz create app

COPY . /opt/app/project/main/
COPY deploy/boot.py /opt/app/config/boot.py
COPY deploy/docker-entrypoint.sh /usr/local/bin/stock8-entrypoint

WORKDIR /opt/app
RUN chmod 0755 /usr/local/bin/stock8-entrypoint \
    && wiz project build --project=main --clean

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3000/access', timeout=4)" || exit 1

ENTRYPOINT ["stock8-entrypoint"]
CMD ["wiz", "run", "--host=0.0.0.0", "--port=3000"]

