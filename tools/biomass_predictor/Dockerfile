FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY predictor ./predictor
RUN useradd -m app && chown -R app /app
USER app
EXPOSE 8001
# Needs ANTHROPIC_API_KEY in the environment. Never put the key in the image or the repo.
CMD ["uvicorn", "--factory", "predictor.app:create_app", "--host", "0.0.0.0", "--port", "8001"]
