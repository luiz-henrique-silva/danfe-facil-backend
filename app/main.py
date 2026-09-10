import time
import logging
import stripe
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.config import get_settings
from app.database import engine, Base
from app.models import user, subscription, process_history
from app.routes import auth, user as user_routes, subscription as sub_routes, webhook, pdf

settings = get_settings()
logging.basicConfig(level=logging.INFO)

if settings.STRIPE_SECRET_KEY:
    stripe.api_key = settings.STRIPE_SECRET_KEY

# CORS: permite origem configurada + localhost
cors_origins = []
for origin in [settings.APP_URL, "http://localhost:3000", "https://localhost:3000"]:
    if origin:
        cors_origins.append(origin)

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    docs_url="/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    process_time = time.time() - start
    response.headers["X-Process-Time"] = str(process_time)
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logging.error(f"Unhandled error: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Erro interno do servidor"})


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": settings.APP_NAME, "version": "1.0.0"}


app.include_router(auth.router)
app.include_router(user_routes.router)
app.include_router(sub_routes.router)
app.include_router(webhook.router)
app.include_router(pdf.router)