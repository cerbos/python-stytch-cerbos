# syntax=docker/dockerfile:1
FROM python:3.11.0-slim-bullseye AS builder
WORKDIR /app
RUN pip install -U pip setuptools wheel
RUN pip install pdm
COPY ["pyproject.toml", "pdm.lock", "./"]
RUN mkdir __pypackages__ && pdm install --prod --no-lock --no-editable

FROM python:3.11.0-slim-bullseye
WORKDIR /app
ENV PYTHONPATH=/pkgs
COPY --from=builder ["app/__pypackages__/3.11/lib", "/pkgs"]
COPY ["main.py", "./"]
COPY ["templates", "templates/"]
CMD ["python", "main.py"]
