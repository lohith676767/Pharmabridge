"""Entry point — launches the PharmaBridge FastAPI backend + web frontend.

The legacy Streamlit prototype is still available via `streamlit run app.py`
if you prefer that quick-look UI, but the website (backend/api.py serving
frontend/index.html) is the primary way to run PharmaBridge now.
"""

import uvicorn


def main():
    uvicorn.run("backend.api:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
