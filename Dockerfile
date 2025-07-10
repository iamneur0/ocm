# Use official Python image
FROM python:3.11-slim

# Set work directory
WORKDIR /app

# Install dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY oracle_usage_bot.py ./

# Optionally copy README and env.sample.txt for reference
COPY README.md ./
COPY env.sample.txt ./

# The .env and key file should be mounted at runtime

# Run the bot
CMD ["python", "-u", "oracle_usage_bot.py"] 