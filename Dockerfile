# Partner — Collaborative Memory Agent (All Things Agentic hackathon)
# Single image: python app + node runtime for heimdall (memory search) + graft (repo graph).
FROM python:3.12-bookworm

# Node 22 from NodeSource (heimdall requires >=22.5)
RUN apt-get update -qq && apt-get install -qq -y curl ca-certificates git \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -qq -y nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# heimdall + graft (memory search + repo graph), installed as npm deps
RUN npm init -y >/dev/null \
 && npm install --no-audit --no-fund @arihantdeva/heimdall@latest @nanonets/graft@latest >/dev/null
ENV PATH=/app/node_modules/.bin:$PATH
ENV HEIMDALL_BIN=/app/node_modules/.bin/heimdall

# App
COPY src/ src/
COPY memories/ memories/

# Memories AND sessions persist here; mount a volume to survive restarts
ENV MEMORIES_DIR=/data/memories
ENV SESSIONS_DIR=/data/sessions
RUN mkdir -p /data/memories /data/sessions
VOLUME /data/memories
VOLUME /data/sessions

# git identity needed if graft build runs in-container
RUN git config --global user.email partner@localhost && git config --global user.name partner

ENV PORT=8080
EXPOSE 8080
CMD ["python", "src/server.py"]
