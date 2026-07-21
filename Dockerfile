FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default port is Streamlit's own convention (8501) to match the primary deployment path
# (GCP Compute Engine + Docker Compose, see GCP_Setyo_Guide.md — firewall rule opens 8501).
# $PORT still overrides it if this image is ever run on Cloud Run instead (see
# GCP_STREAMLIT_DEPLOY.md), which injects its own port (commonly 8080).
ENV STREAMLIT_SERVER_HEADLESS=true
EXPOSE 8501
CMD streamlit run app.py --server.port=${PORT:-8501} --server.address=0.0.0.0
