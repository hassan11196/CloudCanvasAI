FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TMPDIR=/home/user/tmp \
    NODE_PATH=/usr/lib/node_modules:/usr/local/lib/node_modules


RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    libreoffice \
    pandoc \
    poppler-utils \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    defusedxml \
    lxml \
    openpyxl \
    pandas \
    pdf2image \
    pdfplumber \
    pillow \
    pypdf \
    python-docx \
    python-pptx

RUN npm install -g \
    docx \
    pptxgenjs \
    && npm cache clean --force

# Create user and set up directories; tolerate rebuilds where user already exists
RUN if id -u user >/dev/null 2>&1; then \
        echo "user already exists"; \
    else \
        useradd -m -s /bin/bash user; \
    fi && \
    mkdir -p /home/user/tmp /home/user/workspace /home/user/workspace/skills /home/user/.claude /etc/claude-code/.claude && \
    chown -R user:user /home/user /etc/claude-code/.claude

COPY skills/ /home/user/workspace/skills/
RUN chown -R user:user /home/user/workspace/skills

USER user
WORKDIR /home/user/workspace
ENV CLAUDE_PROJECT_DIR=/home/user/workspace
ENV CLAUDE_SKILLS_DIRS=/home/user/workspace/skills
COPY --chown=user:user claude_config.json /etc/claude-code/.claude/claude_config.json
RUN mkdir -p /etc/claude-code/.claude/skills
COPY --chown=user:user skills/ /etc/claude-code/.claude/skills  