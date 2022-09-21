FROM ghcr.io/binkhq/python:3.10-poetry as build

WORKDIR /src
RUN poetry config virtualenvs.create false
RUN poetry self add poetry-dynamic-versioning[plugin]
ADD . .
RUN poetry build

FROM ghcr.io/binkhq/python:3.10

ENV PIP_INDEX_URL=https://269fdc63-af3d-4eca-8101-8bddc22d6f14:b694b5b1-f97e-49e4-959e-f3c202e3ab91@pypi.tools.uksouth.bink.sh/simple
WORKDIR /app
ARG wheel=vela-*-py3-none-any.whl
COPY --from=build /src/alembic/ ./alembic/
COPY --from=build /src/alembic.ini .
COPY --from=build /src/asgi.py .
COPY --from=build /src/dist/$wheel .
# gcc required for hiredis
RUN apt update && apt -y install gcc && pip install $wheel && rm $wheel && apt -y autoremove gcc
ENV PROMETHEUS_MULTIPROC_DIR=/dev/shm
ENTRYPOINT [ "linkerd-await", "--" ]
CMD [ "gunicorn", "--workers=2", "--error-logfile=-", "--access-logfile=-", \
    "--worker-class=uvicorn.workers.UvicornWorker", \
    "--bind=0.0.0.0:9000", "--bind=0.0.0.0:9100", "asgi:app" ]