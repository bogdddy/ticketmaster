# Dockerfile
FROM python:3.12-slim

# Evitar buffering de logs
ENV PYTHONUNBUFFERED=1

# Crear directorio de la app
WORKDIR /app

# Copiar dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código
COPY consumer.py .

# Definir comando por defecto
CMD ["python", "consumer.py"]