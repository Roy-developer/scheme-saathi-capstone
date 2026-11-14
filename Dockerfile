FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SCHEME_SAATHI_API_URL=http://127.0.0.1:8000 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_PORT=8501

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY data/schemes/passages ./data/schemes/passages
COPY data/schemes/document_checklists ./data/schemes/document_checklists
COPY data/schemes/document_evidence.json ./data/schemes/document_evidence.json
COPY data/schemes/mock_forms ./data/schemes/mock_forms

RUN pip install --no-cache-dir .

# Bake the local embedding model into the image. Search loads it with
# local_files_only=True, and a container has no cache of its own, so without
# this step every search fails on Azure. ACR builds have internet access.
ENV FASTEMBED_CACHE_PATH=/opt/fastembed_cache
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2', cache_dir='/opt/fastembed_cache')"

EXPOSE 8000 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)"

CMD ["python", "-m", "src.run_services"]
