FROM python:3.9-slim

# Install system dependencies (network tools + Docker CLI)
RUN apt update && \
    apt install -y iproute2 iputils-ping curl gnupg2 ca-certificates lsb-release && \
    curl -fsSL https://download.docker.com/linux/debian/gpg | apt-key add - && \
    echo "deb [arch=amd64] https://download.docker.com/linux/debian $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list && \
    apt update && \
    apt install -y docker-ce-cli && \
    apt clean

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5003

ENV FLASK_ENV=development

CMD ["python", "app.py"]