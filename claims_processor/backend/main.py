"""
Claims Processing Service — Application Entry Point.

Run with:
    uvicorn main:app --reload --port 8000
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

from api.routes import init_pipeline, router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Plum Claims Processing API",
    description=(
        "Multi-agent health insurance claims processing system. "
        "Validates documents, extracts clinical data, evaluates policy rules, "
        "detects fraud signals, and produces explainable claim decisions."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


@app.on_event("startup")
async def startup() -> None:
    policy_path = Path(os.getenv("POLICY_PATH", "../../policy_terms.json")).resolve()
    if not policy_path.exists():
        # Try adjacent path for when running from the claims_processor/ root
        policy_path = Path(__file__).parent.parent.parent / "policy_terms.json"

    if not policy_path.exists():
        raise RuntimeError(f"policy_terms.json not found at {policy_path}")

    init_pipeline(policy_path)
    logger.info("Plum Claims Processing Service started")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "plum-claims-processor"}
