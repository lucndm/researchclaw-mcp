FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    texlive-latex-base \
    texlive-latex-extra \
    texlive-fonts-recommended \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "researchclaw[all] @ git+https://github.com/aiming-lab/AutoResearchClaw.git" || \
    pip install --no-cache-dir git+https://github.com/aiming-lab/AutoResearchClaw.git

RUN pip install --no-cache-dir "mcp[cli]" httpx loguru

WORKDIR /workspace
RUN mkdir -p /workspace/runs

COPY server.py /workspace/server.py

RUN git config --global user.name "ResearchClaw Bot" && \
    git config --global user.email "bot@nanobot.local"

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

LABEL io.docker.server.metadata="{\"name\":\"researchclaw\",\"description\":\"ResearchClaw MCP Server — autonomous research pipeline for generating academic papers with verified references\",\"remote\":{\"transport_type\":\"sse\",\"url\":\"http://localhost:8000/sse\"},\"env\":[{\"name\":\"OPENAI_API_KEY\",\"required\":true},{\"name\":\"ANTHROPIC_API_KEY\",\"required\":false},{\"name\":\"OUTPUT_REPO_URL\",\"required\":false}]}"

ENTRYPOINT ["/entrypoint.sh"]
