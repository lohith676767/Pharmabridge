"""Entry point — launches the PharmaBridge FastAPI backend + web frontend.

Locally this runs with auto-reload on port 8000. In production the host
platform supplies $PORT and sets ENV=production, which disables reload.

The legacy Streamlit prototype is still available via `streamlit run app.py`
if you prefer that quick-look UI, but the website (backend/api.py serving
frontend/index.html) is the primary way to run PharmaBridge now.
"""

import os

import uvicorn


def main():
    port = int(os.environ.get("PORT", 8000))
    is_dev = os.environ.get("ENV", "development").lower() != "production"
    uvicorn.run("backend.api:app", host="0.0.0.0", port=port, reload=is_dev)


if __name__ == "__main__":
    main()
