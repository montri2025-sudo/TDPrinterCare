# TDPrinter Care — Repair Ticketing System
# ---------------------------------------------------------------------------
# Pure Python (wsgiref) + Jinja2 app image. Talks to a MySQL database over
# the network (see docker-compose.yml for the paired mysql service + env
# vars: MYSQL_HOST/PORT/USER/PASSWORD/DATABASE).
#
# This Dockerfile expects the app source (app.py, db.py, schema.sql,
# templates/, static/, requirements.txt) as its BUILD CONTEXT. That context
# can come from a local checkout OR directly from the GitHub repo — Docker
# supports git URLs as a build context natively, so you don't need to
# `git clone` by hand:
#
#   # build straight from GitHub (private repo, needs local SSH access to it):
#   docker build -t tdprinter-care git@github.com:montri2025-sudo/TDPrinterCare.git
#
#   # or from a local clone/checkout:
#   git clone git@github.com:montri2025-sudo/TDPrinterCare.git
#   cd TDPrinterCare
#   docker build -t tdprinter-care .
#
# See DOCKER.md for full build/run instructions, volumes, and env vars.
# ---------------------------------------------------------------------------

FROM python:3.11-slim

LABEL maintainer="TDPrinter Care"
LABEL description="Repair ticketing system for TDPrinter Care"

WORKDIR /app

# Install Python deps first so Docker can cache this layer across rebuilds
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App source
COPY app.py db.py schema.sql ./
COPY templates ./templates
COPY static ./static

# Uploaded photos/videos live here — mount as a volume at runtime so they
# survive container restarts/rebuilds (the database itself lives in MySQL,
# not on this filesystem)
RUN mkdir -p uploads/parts

ENV PORT=8000
ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# uploads/ is meant to be bind-mounted from the host (see docker-compose.yml)
# so uploaded files aren't lost when the container is recreated.
VOLUME ["/app/uploads"]

CMD ["python", "app.py"]
