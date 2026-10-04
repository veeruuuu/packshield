FROM python:3.10-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    DO_NOT_TRACK=1

RUN apt-get update \
    && apt-get install --no-install-recommends -y git \
    && rm -rf /var/lib/apt/lists/*

COPY s2-requirements.txt /tmp/s2-requirements.txt
RUN python -m pip install --no-cache-dir --disable-pip-version-check \
    --requirement /tmp/s2-requirements.txt

RUN groupadd --gid 10001 s2worker \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin s2worker \
    && mkdir -p /opt/packshield/packshield/signals/s2_graphcodebert_parser \
       /opt/packshield/packshield/tools /inputs/npm /inputs/pypi /input /out \
       /hf-cache/hub \
    && chown -R 10001:10001 /opt/packshield /out /tmp

WORKDIR /opt/packshield
COPY __init__.py /opt/packshield/packshield/__init__.py
COPY signals/__init__.py /opt/packshield/packshield/signals/__init__.py
COPY signals/s2_git_source.py /opt/packshield/packshield/signals/s2_git_source.py
COPY signals/s2_graphcodebert_features.py /opt/packshield/packshield/signals/s2_graphcodebert_features.py
COPY signals/s2_graphcodebert_parser/ /opt/packshield/packshield/signals/s2_graphcodebert_parser/
COPY tools/__init__.py /opt/packshield/packshield/tools/__init__.py
COPY tools/prepare_s2_graphcodebert_features.py /opt/packshield/packshield/tools/prepare_s2_graphcodebert_features.py
COPY tools/pilot_s2_source_parse.py /opt/packshield/packshield/tools/pilot_s2_source_parse.py
COPY tools/s2_graphcodebert_worker.py /opt/packshield/packshield/tools/s2_graphcodebert_worker.py

USER 10001:10001
ENTRYPOINT ["python", "-m", "packshield.tools.pilot_s2_source_parse"]
