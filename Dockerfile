FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml config.yaml README.md ./
COPY kbindex ./kbindex
RUN pip install --no-cache-dir -e '.[embed]'
ENV HF_HOME=/data/hf
ENV PORT=43123
EXPOSE 43123
CMD ["kbindex-api"]
