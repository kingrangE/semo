"""Local read-only collection browser. No collection, embedding, or schema writes."""

import logging
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from semo.admin import document_detail, document_inventory

router = APIRouter()
logger = logging.getLogger(__name__)
NO_CACHE = {"Cache-Control": "no-store"}


def repository():
    from semo.adapters.storage import PostgresDocumentRepository

    if not os.environ.get("DATABASE_URL"):
        raise RuntimeError("DATABASE_URL is required")
    return PostgresDocumentRepository(os.environ["DATABASE_URL"], Path("artifacts/daily"))


@router.get("/admin/documents", include_in_schema=False)
def admin_page():
    return FileResponse(Path(__file__).with_name("web") / "admin.html", headers=NO_CACHE)


@router.get("/api/admin/documents")
def list_documents():
    # shortcut: read all metadata for the current small corpus; paginate before large imports.
    try:
        documents = repository().load(initialize=False)
    except Exception as error:
        logger.exception("Could not read document inventory")
        raise HTTPException(503, "수집 자료에 연결하지 못했습니다. PostgreSQL 연결을 확인해 주세요.") from error
    entries = None
    try:
        from semo.adapters.chroma import ChromaVectorIndex

        entries = ChromaVectorIndex(
            os.environ.get("CHROMA_HOST", "localhost"),
            int(os.environ.get("CHROMA_PORT", "8000")), create=False,
        ).inventory()
    except Exception:
        logger.warning("Could not read search index inventory", exc_info=True)
    result = document_inventory(documents, entries)
    result["checked_at"] = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
    return JSONResponse(result, headers=NO_CACHE)


@router.get("/api/admin/document")
def get_document(id: str = Query(min_length=1, max_length=2048)):
    try:
        document = repository().get(id)
    except Exception as error:
        logger.exception("Could not read document")
        raise HTTPException(503, "자료를 가져오지 못했습니다. 잠시 후 다시 시도해 주세요.") from error
    if document is None:
        raise HTTPException(404, "자료가 삭제되었거나 없습니다. 목록을 새로고침해 주세요.")
    return JSONResponse(document_detail(document), headers=NO_CACHE)
