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

RUN mkdir -p /home/user/tmp /home/user/workspace
