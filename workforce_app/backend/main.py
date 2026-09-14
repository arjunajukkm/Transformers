"""
main.py
───────
FastAPI application entry point for Workforce Intelligence.
Configures CORS, registers API routers, and exposes the app instance.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from workforce_app.backend.api import health, workforce

app = FastAPI(
    title="Workforce Intelligence API",
    description="Local analytical backend for enterprise workforce process health and compliance monitoring.",
    version="1.0.0",
)

# Enable CORS for local Vite dev server and desktop web clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API routers
app.include_router(health.router, prefix="/api", tags=["Health"])
app.include_router(workforce.router, prefix="/api", tags=["Workforce Intelligence"])


@app.get("/")
def root():
    return {
        "app": "Workforce Intelligence API",
        "status": "online",
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("workforce_app.backend.main:app", host="127.0.0.1", port=8000, reload=True)
