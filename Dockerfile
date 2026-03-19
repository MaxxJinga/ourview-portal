FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies for WebSockets
RUN apt-get update && apt-get install -y gcc python3-dev

# Copy and install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your code
COPY . .

# Start the server (matching your SocketIO setup)
CMD ["gunicorn", "-k", "geventwebsocket.gunicorn.workers.GeventWebSocketWorker", "-w", "1", "--bind", "0.0.0.0:8080", "app:app"]