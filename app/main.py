"""Campaign Manager - Main Application Entry Point"""

import logging
import uvicorn
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import APP_HOST, APP_PORT
from app.db.database import init_db, close_db
from app.routes import dashboard, campaigns, webhooks

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown."""
    # Startup
    logger.info("Starting Campaign Manager...")
    await init_db()
    logger.info("Database initialized")
    yield
    # Shutdown
    logger.info("Shutting down Campaign Manager...")
    await close_db()
    logger.info("Database connection closed")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Campaign Manager",
        description="Marketing campaign manager with auto-batching, retry logic, and n8n integration",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Mount static files
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    # Configure templates
    templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
    app.state.templates = templates

    # Include routers
    app.include_router(dashboard.router)
    app.include_router(campaigns.router)
    app.include_router(webhooks.router)

    return app


app = create_app()


def run():
    """Run the application with uvicorn."""
    uvicorn.run(
        "app.main:app",
        host=APP_HOST,
        port=APP_PORT,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    run()
