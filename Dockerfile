FROM python:3.11-slim

WORKDIR /app

# Install dependencies first so this layer is cached on rebuilds
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py .
COPY discoverer/ discoverer/
COPY generators/ generators/
COPY utils/ utils/

# Output directory — mount a host volume here to retrieve generated files
RUN mkdir /output

ENTRYPOINT ["python", "main.py"]
