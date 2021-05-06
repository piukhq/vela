FROM binkhq/python:3.9

WORKDIR /app
ADD . .
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ && \
    pip install --no-cache-dir pipenv && \
    pipenv install --deploy --system --ignore-pipfile && \
    apt-get autoremove -y gcc g++ && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists

ENV PROMETHEUS_MULTIPROC_DIR=/dev/shm
CMD [ "gunicorn", "--workers=1", "--error-logfile=-", "--access-logfile=-", \
    "--worker-class=uvicorn.workers.UvicornWorker", \
    "--bind=0.0.0.0:9000", "asgi:app" ]
