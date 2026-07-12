from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse

from taxflow.middleware.auth import get_current_client
from taxflow.services.storage.r2 import get_source_pdf_url

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/source/{object_key}")
async def get_source_document(object_key: str, _client=Depends(get_current_client)):
    """Redirect to a signed URL for a stored original source PDF."""
    url = get_source_pdf_url(object_key)
    if not url:
        raise HTTPException(status_code=404, detail="Source document not available")
    return RedirectResponse(url)
