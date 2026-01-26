FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Create an unprivileged user and the Claude skills directories up front
RUN useradd -m -s /bin/bash appuser \
    && mkdir -p /etc/claude-code/.claude/skills /home/appuser/.claude/skills

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Make skills available in the path expected by the Claude CLI and fix ownership
RUN mkdir -p /etc/claude-code/.claude/skills \
    && cp -r /app/skills/. /etc/claude-code/.claude/skills/ \
    && chown -R appuser:appuser /app /etc/claude-code/.claude /home/appuser/.claude

USER appuser
ENV CLAUDE_PROJECT_DIR=/app \
    CLAUDE_SKILLS_DIRS=/app/skills

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
