# --- Stage 1: base image ---
# We use a slim Python image to keep the final image small.
# "3.12-slim" means Python 3.12 on Debian, without the extra dev tools
# that the full image includes.
FROM python:3.12-slim

# Set the working directory inside the container.
# All subsequent commands run relative to this path.
WORKDIR /ghg-tracker

# Copy requirements first — before the app code.
# Docker caches each instruction as a "layer". By copying requirements.txt
# separately, Docker can reuse the pip install layer on rebuilds as long as
# requirements.txt hasn't changed (even if your app code has).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Now copy the rest of the app
COPY app/ ./app/

# Expose the port Uvicorn will listen on
EXPOSE 8000

# The command to start the server.
# --host 0.0.0.0 is important: by default Uvicorn binds to 127.0.0.1,
# which is only reachable inside the container. 0.0.0.0 makes it
# reachable from outside (i.e., from your host machine or other containers).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
