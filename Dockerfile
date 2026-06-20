FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY static/ ./static/
# cobertura.db é provido via volume externo — o touch cria o arquivo vazio
# para que o Docker monte o volume como arquivo (não como diretório)
RUN touch /app/cobertura.db

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
