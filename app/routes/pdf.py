from datetime import datetime, timezone
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.process_history import ProcessHistory
from app.models.subscription import Subscription
from app.models.user import User
from app.services.pdf_service import process_pdf, PdfProcessError

router = APIRouter(prefix="/api/pdf", tags=["pdf"])

PROCESS_LIMITS = {
    "free": 10,
    "basico": 800,
    "pro": 1500,
    "business": 100000,
}


def _month_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def _monthly_usage(user_id: str, db: AsyncSession) -> int:
    result = await db.execute(
        select(func.coalesce(func.sum(ProcessHistory.pages_generated), 0)).where(
            ProcessHistory.user_id == user_id,
            ProcessHistory.status == "success",
            ProcessHistory.created_at >= _month_start(),
        )
    )
    return result.scalar() or 0


async def _get_plan(user_id: str, db: AsyncSession) -> tuple[str, bool]:
    result = await db.execute(select(Subscription).where(Subscription.user_id == user_id))
    sub = result.scalar_one_or_none()
    if sub and sub.id:
        return (sub.plan if sub.status == "active" else "free", bool(sub.unlimited))
    return "free", False


@router.post("/process")
async def upload_and_process(
    file: UploadFile = File(...),
    page_size: str = Query("100x150", pattern="^(100x150|auto|a4)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Somente arquivos PDF são aceitos")

    plan, unlimited = await _get_plan(user.id, db)
    limit = PROCESS_LIMITS.get(plan, PROCESS_LIMITS["free"])
    used = await _monthly_usage(user.id, db)

    if not unlimited and used >= limit:
        raise HTTPException(
            status_code=402,
            detail="Você atingiu o limite de processamentos do seu plano. "
                   "Faça upgrade para continuar.",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Arquivo vazio")

    try:
        result = process_pdf(data, page_size)
    except PdfProcessError as exc:
        history = ProcessHistory(
            user_id=user.id,
            filename=file.filename,
            status="error",
            error_message=str(exc),
        )
        db.add(history)
        await db.commit()
        raise HTTPException(status_code=400, detail=str(exc))

    history = ProcessHistory(
        user_id=user.id,
        filename=file.filename,
        status="success",
        result_size=len(result["output_data"]),
        pages_generated=result["pages_generated"],
    )
    db.add(history)
    await db.commit()

    out_name = file.filename.rsplit(".", 1)[0] + "_DANFE.pdf"

    return Response(
        content=result["output_data"],
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{out_name}"',
            "X-Warnings": "|".join(result["warnings"]),
            "X-Pages-Used": str(result["pages_used"]),
            "X-Pages-Generated": str(result["pages_generated"]),
            "X-Scale": str(round(result["scale"], 4)),
        },
    )


@router.get("/history")
async def get_history(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ProcessHistory)
        .where(ProcessHistory.user_id == user.id)
        .order_by(ProcessHistory.created_at.desc())
        .limit(50)
    )
    items = result.scalars().all()
    return [
        {
            "id": h.id,
            "filename": h.filename,
            "status": h.status,
            "error_message": h.error_message,
            "result_size": h.result_size,
            "created_at": h.created_at,
        }
        for h in items
    ]


@router.get("/usage")
async def get_usage(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    plan, unlimited = await _get_plan(user.id, db)
    used = await _monthly_usage(user.id, db)
    return {
        "plan": plan,
        "processed_month": used,
        "limit": None if unlimited else PROCESS_LIMITS.get(plan, PROCESS_LIMITS["free"]),
        "unlimited": unlimited,
    }