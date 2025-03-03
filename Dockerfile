FROM python:3.9-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directories for persistent storage
RUN mkdir -p /app/logs

# Set environment variables
ENV PYTHONUNBUFFERED=1

# No default entrypoint - we'll specify what to run in docker-compose.yml
CMD ["python", "cl_job_scheduler.py"]