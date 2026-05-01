FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY mtg_price_tracker ./mtg_price_tracker
COPY examples ./examples

RUN pip install --no-cache-dir .

ENTRYPOINT ["mtg-price-tracker"]
CMD ["web", "--host", "0.0.0.0", "--port", "8000"]
