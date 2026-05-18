# Email Approval Microservice
# Runs on Red Hat UBI9 Python 3.11 — compatible with OCP restricted SCC.
#
# Build:
#   podman build -t quay.io/YOUR_ORG/email-approver:latest .
#
# Push:
#   podman push quay.io/YOUR_ORG/email-approver:latest
#
# All runtime configuration is supplied via environment variables
# (injected from OCP Secret email-approver-secret).

FROM registry.access.redhat.com/ubi9/python-311:latest

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Run as non-root (required by OCP restricted SCC)
USER 1001

CMD ["python", "app.py"]
