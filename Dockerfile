# One container serves the built React app and the FastAPI API from the same URL.
# server/app/main.py mounts dist/ when it exists, so no separate web server is needed.

FROM node:22-slim AS web
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html vite.config.ts tsconfig*.json ./
COPY src ./src
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY server ./server
COPY --from=web /app/dist ./dist
# SQLite lives here. On a free host it resets when the container restarts;
# mount a persistent disk at /app/data to keep it.
RUN mkdir -p /app/data
ENV REPLAN_DB_PATH=/app/data/replan.sqlite3
EXPOSE 8000
CMD ["sh", "-c", "uvicorn server.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
