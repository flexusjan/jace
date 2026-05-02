FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY jace ./jace
COPY examples ./examples

RUN pip install --no-cache-dir .

ENTRYPOINT ["jace"]
CMD ["web", "--host", "0.0.0.0", "--port", "8000"]
