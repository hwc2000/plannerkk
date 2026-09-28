"""Run the built React frontend and FastAPI together without browser automation."""
import os
from pathlib import Path
from dotenv import load_dotenv
import uvicorn

ROOT = Path(__file__).resolve().parent

if __name__ == "__main__":
    os.chdir(ROOT)
    load_dotenv(ROOT / ".env")
    if not (ROOT / "dist" / "index.html").is_file():
        raise SystemExit("Run npm install and npm run build first.")
    port = int(os.getenv("REPLAN_PORT", "8010"))
    print(f"re:plan: http://127.0.0.1:{port}", flush=True)
    uvicorn.run("server.app.main:app", host="127.0.0.1", port=port)
