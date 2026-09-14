"""
run_workforce_app.py
────────────────────
Simple local runner for Workforce Intelligence FastAPI backend.

Usage:
    python run_workforce_app.py

Backend will listen at: http://127.0.0.1:8000
Frontend can be launched with:
    cd workforce_app/frontend
    npm run dev
"""

import sys
import uvicorn

def main():
    print("=" * 60)
    print("  Starting Workforce Intelligence Backend Service")
    print("  API Docs: http://127.0.0.1:8000/docs")
    print("  Health:   http://127.0.0.1:8000/api/health")
    print("=" * 60)
    print("\nTo launch the UI:")
    print("  cd workforce_app/frontend")
    print("  npm run dev\n")

    uvicorn.run("workforce_app.backend.main:app", host="127.0.0.1", port=8000, reload=True)

if __name__ == "__main__":
    main()
