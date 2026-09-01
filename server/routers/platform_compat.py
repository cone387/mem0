"""Platform-compatible REST shim.

The official ``mem0`` Python SDK's ``MemoryClient`` targets the hosted
platform API (api.mem0.ai) with ``/v1/*`` and ``/v3/*`` paths. Our
self-hosted server exposes flat paths (``/memories``, ``/search``...).
This router translates the platform-shaped paths onto the local handlers
so the unmodified SDK works against a self-hosted instance.

Mounted explicitly in main.py — NOT included in ``routers/__init__.py``.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth import verify_auth as _verify_auth

logger = logging.getLogger(__name__)

router = APIRouter(tags=["platform-compat"])


class CompatAddRequest(BaseModel):
    messages: List[Dict[str, Any]]
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    filters: Optional[Dict[str, Any]] = None
    infer: bool = True
    prompt: Optional[str] = None


class CompatSearchRequest(BaseModel):
    query: str
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    filters: Optional[Dict[str, Any]] = None
    top_k: Optional[int] = None
    threshold: Optional[float] = None


class CompatUpdateRequest(BaseModel):
    text: Optional[str] = None
    data: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class CompatBatchDeleteRequest(BaseModel):
    memories: List[Dict[str, Any]] = []


def _memory():
    # Imported lazily to avoid circular import with main.py
    from server_state import get_memory_instance

    return get_memory_instance()


def _extract_scopes(payload: Dict[str, Any]) -> Dict[str, str]:
    scopes = {}
    filters = payload.get("filters") or {}
    for k in ("user_id", "agent_id", "run_id"):
        v = payload.get(k) or (filters.get(k) if isinstance(filters, dict) else None)
        if v:
            scopes[k] = v
    return scopes


# --- Ping / auth check -------------------------------------------------------


@router.get("/v1/ping/", include_in_schema=False)
@router.get("/v1/ping", include_in_schema=False)
def ping(_auth=Depends(_verify_auth)):
    # SDK validates the API key on init and expects user/org/project info back.
    return {
        "status": "ok",
        "message": "Self-hosted mem0 platform-compat shim",
        "user_email": "self-hosted@local",
        "org_id": "self-hosted",
        "project_id": "default",
    }


# --- Memories ----------------------------------------------------------------


@router.post("/v3/memories/add/", include_in_schema=False)
@router.post("/v3/memories/add", include_in_schema=False)
def platform_add(body: CompatAddRequest, _auth=Depends(_verify_auth)):
    params = _extract_scopes(body.model_dump())
    if body.metadata:
        params["metadata"] = body.metadata
    if body.infer is not None:
        params["infer"] = body.infer
    if body.prompt:
        params["prompt"] = body.prompt
    try:
        result = _memory().add(messages=body.messages, **params)
        return {"results": result.get("results", result) if isinstance(result, dict) else result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("platform_add failed")
        raise HTTPException(status_code=500, detail="add failed")


@router.post("/v3/memories/search/", include_in_schema=False)
@router.post("/v3/memories/search", include_in_schema=False)
def platform_search(body: CompatSearchRequest, _auth=Depends(_verify_auth)):
    filters = dict(body.filters or {})
    for k in ("user_id", "agent_id", "run_id"):
        v = getattr(body, k, None)
        if v:
            filters[k] = v
    params: Dict[str, Any] = {"query": body.query, "filters": filters}
    if body.top_k is not None:
        params["top_k"] = body.top_k
    if body.threshold is not None:
        params["threshold"] = body.threshold
    try:
        result = _memory().search(**params)
        return {"results": result.get("results", result) if isinstance(result, dict) else result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("platform_search failed")
        raise HTTPException(status_code=500, detail="search failed")


@router.post("/v3/memories/", include_in_schema=False)
@router.post("/v3/memories", include_in_schema=False)
def platform_get_all(body: Dict[str, Any], _auth=Depends(_verify_auth)):
    """SDK v2.x uses POST /v3/memories/ for get_all."""
    scopes = _extract_scopes(body)
    try:
        result = _memory().get_all(filters=scopes or None)
        return {"results": result.get("results", result) if isinstance(result, dict) else result}
    except Exception:
        logger.exception("platform_get_all failed")
        raise HTTPException(status_code=500, detail="get_all failed")


@router.get("/v1/memories/{memory_id}/", include_in_schema=False)
@router.get("/v1/memories/{memory_id}", include_in_schema=False)
def platform_get(memory_id: str, _auth=Depends(_verify_auth)):
    try:
        return _memory().get(memory_id)
    except Exception:
        raise HTTPException(status_code=404, detail="memory not found")


@router.put("/v1/memories/{memory_id}/", include_in_schema=False)
@router.put("/v1/memories/{memory_id}", include_in_schema=False)
def platform_update(memory_id: str, body: CompatUpdateRequest, _auth=Depends(_verify_auth)):
    data = body.text or body.data
    try:
        result = _memory().update(memory_id=memory_id, data=data, metadata=body.metadata)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/v1/memories/{memory_id}/", include_in_schema=False)
@router.delete("/v1/memories/{memory_id}", include_in_schema=False)
def platform_delete(memory_id: str, _auth=Depends(_verify_auth)):
    try:
        _memory().delete(memory_id=memory_id)
        return {"message": "Memory deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/v1/memories/", include_in_schema=False)
@router.delete("/v1/memories", include_in_schema=False)
def platform_delete_all(
    user_id: Optional[str] = Query(None),
    agent_id: Optional[str] = Query(None),
    run_id: Optional[str] = Query(None),
    _auth=Depends(_verify_auth),
):
    scopes = {k: v for k, v in {"user_id": user_id, "agent_id": agent_id, "run_id": run_id}.items() if v}
    if not scopes:
        raise HTTPException(status_code=400, detail="At least one scope (user_id/agent_id/run_id) is required.")
    try:
        _memory().delete_all(**scopes)
        return {"message": "Memories deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/v1/memories/{memory_id}/history/", include_in_schema=False)
@router.get("/v1/memories/{memory_id}/history", include_in_schema=False)
def platform_history(memory_id: str, _auth=Depends(_verify_auth)):
    try:
        return _memory().history(memory_id=memory_id)
    except Exception:
        raise HTTPException(status_code=404, detail="memory not found")


@router.put("/v1/batch/", include_in_schema=False)
@router.delete("/v1/batch/", include_in_schema=False)
def platform_batch(_auth=Depends(_verify_auth)):
    raise HTTPException(status_code=501, detail="batch operations not supported on self-hosted server")


@router.get("/v1/entities/", include_in_schema=False)
def platform_entities(_auth=Depends(_verify_auth)):
    raise HTTPException(status_code=501, detail="use GET /entities (dashboard router) on self-hosted server")
