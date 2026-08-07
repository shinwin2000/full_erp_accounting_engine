#!/usr/bin/env python3

"""

Module: fastapi_document_router.py

Layer: Adapters (Primary API - v1)

Responsibility: Menyediakan REST API endpoint untuk manajemen dokumen:

               upload file (PDF, gambar, Excel), download, link ke entitas bisnis,

               metadata, verifikasi integritas (hash), retensi & hapus,

               versioning dokumen, dan workflow approval dokumen.



Method Standards (ERP):

- upload_document() / update_document() / delete_document() / get_document()

- download_document() / get_document_content()

- link_to_entity() / unlink_from_entity()

- verify_integrity() / get_document_hash()

- create_document_version() / get_document_versions()

- approve_document() / reject_document()

- archive_document() / restore_document() / lock_document() / unlock_document()

- get_document_status() / get_document_history()

- get_document_by_entity() / get_documents_by_tags()

- bulk_upload() / bulk_link() / bulk_delete()

- audit_trail_document() / can_transition_document()

- register_document_event() / get_document_events()

- version_document()

"""





from __future__ import annotations



import asyncio

import hashlib

import json

import logging

import mimetypes

import os

import tempfile

from datetime import datetime

from enum import Enum

from typing import Any

from uuid import UUID



import aiofiles  # <-- Tambahan untuk async file I/O

from fastapi import (

    APIRouter,

    Depends,

    File,

    Form,

    Header,

    HTTPException,

    Query,

    Request,

    UploadFile,

    status,

)

from fastapi.responses import FileResponse, Response

from pydantic import BaseModel, ConfigDict, Field



from adapters.primary_api.common.fastapi_auth_jwt_middleware import (

    TokenPayload,

    get_current_legal_entity,

    get_current_user,

    require_permission,

)



logger = logging.getLogger(__name__)



# ============================================================================

# IDEMPOTENCY MANAGER (for write operations)

# ============================================================================



class IdempotencyManager:

    """

    Simple in-memory idempotency manager untuk FastAPI endpoints.

    Menyimpan hasil operasi berdasarkan idempotency_key + method_name.

    TTL 24 jam.

    """



    def __init__(self):

        self._storage: dict[str, tuple[str, datetime]] = {}

        self._ttl_seconds = 86400



    def _get_key(self, idempotency_key: str, method_name: str) -> str:

        raw = f"{method_name}:{idempotency_key}"

        return hashlib.sha256(raw.encode()).hexdigest()



    def get_cached_result(self, idempotency_key: str, method_name: str) -> dict[str, Any] | None:

        storage_key = self._get_key(idempotency_key, method_name)

        entry = self._storage.get(storage_key)

        if entry is None:

            return None

        result_json, timestamp = entry

        if (datetime.now() - timestamp).total_seconds() > self._ttl_seconds:

            del self._storage[storage_key]

            return None

        try:

            return json.loads(result_json)

        except json.JSONDecodeError:

            return None



    def cache_result(self, idempotency_key: str, method_name: str, result: dict[str, Any]) -> None:

        storage_key = self._get_key(idempotency_key, method_name)

        try:

            result_json = json.dumps(result, default=str)

        except TypeError:

            result_json = json.dumps({"result": str(result)}, default=str)

        self._storage[storage_key] = (result_json, datetime.now())





# Global instance

_idempotency_manager = IdempotencyManager()





# ============================================================================

# CONSTANTS & ENUMS

# ============================================================================





class DocumentStatus(str, Enum):

    """Status dokumen."""



    DRAFT = "draft"

    PENDING = "pending"

    APPROVED = "approved"

    REJECTED = "rejected"

    ACTIVE = "active"

    ARCHIVED = "archived"

    DELETED = "deleted"

    LOCKED = "locked"

    EXPIRED = "expired"





class DocumentType(str, Enum):

    """Jenis dokumen."""



    INVOICE = "invoice"

    PURCHASE_ORDER = "purchase_order"

    SALES_ORDER = "sales_order"

    GOODS_RECEIPT = "goods_receipt"

    DELIVERY_ORDER = "delivery_order"

    CONTRACT = "contract"

    AGREEMENT = "agreement"

    TAX_INVOICE = "tax_invoice"

    BANK_STATEMENT = "bank_statement"

    FIXED_ASSET = "fixed_asset"

    EMPLOYEE = "employee"

    GENERAL = "general"

    REPORT = "report"

    ATTACHMENT = "attachment"





class DocumentMimeType(str, Enum):

    """MIME type yang didukung."""



    PDF = "application/pdf"

    JPEG = "image/jpeg"

    PNG = "image/png"

    GIF = "image/gif"

    EXCEL = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    EXCEL_OLD = "application/vnd.ms-excel"

    WORD = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    WORD_OLD = "application/msword"

    CSV = "text/csv"

    TXT = "text/plain"

    ZIP = "application/zip"

    XML = "application/xml"

    JSON = "application/json"





# Default document settings

MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB

ALLOWED_MIME_TYPES = [m.value for m in DocumentMimeType]

DEFAULT_RETENTION_DAYS = 365 * 7  # 7 years

DEFAULT_PAGE_SIZE = 20

MAX_PAGE_SIZE = 500





# ============================================================================

# PYDANTIC SCHEMAS

# ============================================================================





class DocumentUploadResponseSchema(BaseModel):

    """Response upload dokumen."""



    model_config = ConfigDict(from_attributes=True)



    id: UUID

    document_number: str

    original_filename: str

    file_size: int

    mime_type: str

    file_hash: str

    status: DocumentStatus

    download_url: str

    uploaded_at: datetime

    uploaded_by: UUID

    uploaded_by_name: str | None = None





class DocumentResponseSchema(BaseModel):

    """Response dokumen."""



    model_config = ConfigDict(from_attributes=True)



    id: UUID

    document_number: str

    original_filename: str

    file_size: int

    mime_type: str

    file_hash: str

    version: int

    entity_type: str | None

    entity_id: UUID | None

    entity_reference: str | None = None

    tags: list[str] | None

    description: str | None

    status: DocumentStatus

    is_locked: bool = False

    is_encrypted: bool = False

    retention_until: datetime | None

    expiry_date: datetime | None

    uploaded_by: UUID

    uploaded_by_name: str | None = None

    uploaded_at: datetime

    approved_by: UUID | None = None

    approved_by_name: str | None = None

    approved_at: datetime | None = None

    archived_by: UUID | None = None

    archived_at: datetime | None = None

    download_url: str | None = None

    preview_url: str | None = None

    version_of: UUID | None = None

    notes: str | None = None





class DocumentUpdateSchema(BaseModel):

    """Schema untuk update metadata dokumen."""



    model_config = ConfigDict(from_attributes=True)



    entity_type: str | None = Field(None, max_length=100)

    entity_id: UUID | None = None

    tags: list[str] | None = None

    description: str | None = Field(None, max_length=1000)

    notes: str | None = Field(None, max_length=500)

    retention_until: datetime | None = None

    expiry_date: datetime | None = None

    status: DocumentStatus | None = None





class DocumentBulkUploadSchema(BaseModel):

    """Schema untuk bulk upload dokumen."""



    model_config = ConfigDict(from_attributes=True)



    files: list[UploadFile]

    entity_type: str | None = None

    entity_id: UUID | None = None

    tags: list[str] | None = None

    description: str | None = None

    retention_days: int | None = None





class DocumentBulkLinkSchema(BaseModel):

    """Schema untuk bulk link dokumen ke entity."""



    model_config = ConfigDict(from_attributes=True)



    document_ids: list[UUID] = Field(..., min_length=1, max_length=100)

    entity_type: str = Field(..., max_length=100)

    entity_id: UUID = Field(...)





class DocumentSearchSchema(BaseModel):

    """Schema untuk pencarian dokumen."""



    model_config = ConfigDict(from_attributes=True)



    entity_type: str | None = None

    entity_id: UUID | None = None

    tag: str | None = None

    status: DocumentStatus | None = None

    start_date: datetime | None = None

    end_date: datetime | None = None

    filename_contains: str | None = None

    page: int = Field(1, ge=1)

    page_size: int = Field(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)





class DocumentVersionResponseSchema(BaseModel):

    """Response versi dokumen."""



    model_config = ConfigDict(from_attributes=True)



    id: UUID

    document_number: str

    version: int

    file_size: int

    file_hash: str

    created_at: datetime

    created_by: UUID

    created_by_name: str | None = None

    notes: str | None = None





class DocumentIntegrityResponseSchema(BaseModel):

    """Response verifikasi integritas dokumen."""



    model_config = ConfigDict(from_attributes=True)



    document_id: UUID

    document_number: str

    original_filename: str

    stored_hash: str

    computed_hash: str

    is_valid: bool

    file_size: int

    verified_at: datetime

    verified_by: UUID

    verified_by_name: str | None = None





# ============================================================================

# DEPENDENCY INJECTION

# ============================================================================





async def get_document_svc(request: Request) -> Any:

    """

    Get Document Service instance.

    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.

    """

    from application.service_layer.service_document import DocumentService



    container = request.app.state.container

    return await container.resolve_async(DocumentService)





# ============================================================================

# HELPER FUNCTIONS

# ============================================================================





def compute_file_hash(content: bytes) -> str:

    """Compute SHA-256 hash of file content."""

    return hashlib.sha256(content).hexdigest()





def validate_file_size(content: bytes) -> bool:

    """Validate file size does not exceed limit."""

    return len(content) <= MAX_FILE_SIZE_BYTES





def get_mime_type(filename: str) -> str:

    """Get MIME type from filename."""

    mime_type, _ = mimetypes.guess_type(filename)

    return mime_type or "application/octet-stream"





# ============================================================================

# ROUTER

# ============================================================================



router = APIRouter(prefix="/documents", tags=["Documents"])





# ----------------------------------------------------------------------------

# DOCUMENT UPLOAD

# ----------------------------------------------------------------------------





@router.post(

    "/upload",

    response_model=DocumentUploadResponseSchema,

    status_code=status.HTTP_201_CREATED,

    summary="Upload a document",

    operation_id="upload_document",

)

async def upload_document(

    file: UploadFile = File(..., description="File to upload"),

    entity_type: str | None = Form(None, description="Entity type (journal, ar_invoice, etc.)"),

    entity_id: UUID | None = Form(None, description="ID of the related entity"),

    tags: str | None = Form(None, description="Comma-separated tags"),

    description: str | None = Form(None, description="Document description"),

    retention_days: int | None = Form(None, description="Retention in days (optional)"),

    notes: str | None = Form(None, description="Internal notes"),

    _permission: None = Depends(require_permission("document:upload")),

    current_user: TokenPayload = Depends(get_current_user),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    doc_svc: Any = Depends(get_document_svc),

) -> DocumentUploadResponseSchema:

    """

    Upload file ke object storage (MinIO / S3).



    - File di-hash untuk integritas

    - Bisa langsung dikaitkan dengan entity tertentu

    - Support berbagai format file (PDF, gambar, Excel, Word, dll)

    - LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.

    """

    try:

        # Baca file content

        content = await file.read()



        # Validasi ukuran file

        if not validate_file_size(content):

            raise HTTPException(

                status_code=413,

                detail=f"File size exceeds {MAX_FILE_SIZE_BYTES / 1024 / 1024} MB limit",

            )



        # Hitung hash

        file_hash = compute_file_hash(content)



        # Parse tags

        tag_list = [t.strip() for t in tags.split(",")] if tags else None



        # Get MIME type

        mime_type = get_mime_type(file.filename)



        result = await doc_svc.upload_document(

            legal_entity_id=legal_entity_id,

            file_content=content,

            original_filename=file.filename,

            mime_type=mime_type,

            file_hash=file_hash,

            entity_type=entity_type,

            entity_id=entity_id,

            tags=tag_list,

            description=description,

            retention_days=retention_days,

            notes=notes,

            uploaded_by=current_user.user_id,

        )



        logger.info(

            f"Document uploaded: {result.document_number} by {current_user.username}"

        )



        return DocumentUploadResponseSchema(

            id=result.id,

            document_number=result.document_number,

            original_filename=result.original_filename,

            file_size=result.file_size,

            mime_type=result.mime_type,

            file_hash=result.file_hash,

            status=DocumentStatus(result.status),

            download_url=f"/api/v1/documents/{result.id}/download",

            uploaded_at=result.created_at,

            uploaded_by=result.uploaded_by,

            uploaded_by_name=result.uploaded_by_name,

        )

    except HTTPException:

        raise

    except ValueError as e:

        raise HTTPException(status_code=422, detail=str(e))

    except Exception as e:

        logger.exception("Failed to upload document: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





@router.post(

    "/upload/bulk",

    response_model=list[DocumentUploadResponseSchema],

    status_code=status.HTTP_207_MULTI_STATUS,

    summary="Bulk upload documents",

    operation_id="bulk_upload_documents",

)

async def bulk_upload_documents(

    files: list[UploadFile] = File(..., description="Files to upload"),

    entity_type: str | None = Form(None),

    entity_id: UUID | None = Form(None),

    tags: str | None = Form(None),

    description: str | None = Form(None),

    retention_days: int | None = Form(None),

    _permission: None = Depends(require_permission("document:upload")),

    current_user: TokenPayload = Depends(get_current_user),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    doc_svc: Any = Depends(get_document_svc),

) -> list[DocumentUploadResponseSchema]:

    """

    Upload multiple documents at once.

    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.

    """

    results = []

    tag_list = [t.strip() for t in tags.split(",")] if tags else None



    for file in files:

        try:

            content = await file.read()



            if not validate_file_size(content):

                results.append(

                    {

                        "error": f"File {file.filename} size exceeds limit",

                        "original_filename": file.filename,

                        "success": False,

                    }

                )

                continue



            file_hash = compute_file_hash(content)

            mime_type = get_mime_type(file.filename)



            result = await doc_svc.upload_document(

                legal_entity_id=legal_entity_id,

                file_content=content,

                original_filename=file.filename,

                mime_type=mime_type,

                file_hash=file_hash,

                entity_type=entity_type,

                entity_id=entity_id,

                tags=tag_list,

                description=description,

                retention_days=retention_days,

                notes=None,

                uploaded_by=current_user.user_id,

            )



            results.append(

                DocumentUploadResponseSchema(

                    id=result.id,

                    document_number=result.document_number,

                    original_filename=result.original_filename,

                    file_size=result.file_size,

                    mime_type=result.mime_type,

                    file_hash=result.file_hash,

                    status=DocumentStatus(result.status),

                    download_url=f"/api/v1/documents/{result.id}/download",

                    uploaded_at=result.created_at,

                    uploaded_by=result.uploaded_by,

                    uploaded_by_name=result.uploaded_by_name,

                )

            )

        except Exception as e:

            logger.error("Failed to upload %s: %s", file.filename, e)

            results.append({"error": str(e), "original_filename": file.filename, "success": False})



    return results





# ----------------------------------------------------------------------------

# DOCUMENT DOWNLOAD � DIPERBAIKI (aiofiles untuk file I/O)

# ----------------------------------------------------------------------------





@router.get(

    "/{document_id}/download",

    summary="Download a document",

    operation_id="download_document",

)

async def download_document(

    document_id: UUID,

    inline: bool = Query(False, description="Display inline instead of download"),

    _permission: None = Depends(require_permission("document:download")),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    doc_svc: Any = Depends(get_document_svc),

) -> FileResponse:

    """Download a document file."""

    try:

        doc = await doc_svc.get_document(document_id, legal_entity_id)



        if not doc:

            raise HTTPException(status_code=404, detail="Document not found")



        if doc.status == DocumentStatus.DELETED:

            raise HTTPException(status_code=410, detail="Document has been deleted")



        if doc.status == DocumentStatus.ARCHIVED:

            raise HTTPException(status_code=403, detail="Document is archived")



        # Get file content

        file_content = await doc_svc.get_file_content(document_id, legal_entity_id)



        if not file_content:

            raise HTTPException(status_code=404, detail="File not found in storage")



        # Create temporary file

        fd, temp_path = tempfile.mkstemp(suffix=f"_{doc.original_filename}")

        os.close(fd)



        try:

            # ===== PERBAIKAN: Gunakan aiofiles untuk menulis file =====

            async with aiofiles.open(temp_path, "wb") as f:

                await f.write(file_content)



            content_disposition = "inline" if inline else "attachment"



            return FileResponse(

                path=temp_path,

                filename=doc.original_filename,

                media_type=doc.mime_type,

                headers={

                    "Content-Disposition": f"{content_disposition}; filename={doc.original_filename}",

                    "X-Document-Hash": doc.file_hash,

                },

            )

        finally:

            # Bersihkan file setelah response (asinkron)

            # Gunakan background task untuk menghapus file setelah response dikirim

            # FastAPI mendukung BackgroundTasks, tapi di sini kita gunakan asyncio.to_thread

            # untuk menghapus file setelah 5 detik (memberi waktu client download)

            async def _cleanup():

                await asyncio.sleep(5)

                if os.path.exists(temp_path):

                    await asyncio.to_thread(os.unlink, temp_path)



            asyncio.create_task(_cleanup())



    except HTTPException:

        raise

    except Exception as e:

        logger.exception("Failed to download document: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





@router.get(

    "/{document_id}/preview",

    summary="Get document preview",

    operation_id="preview_document",

)

async def preview_document(

    document_id: UUID,

    _permission: None = Depends(require_permission("document:read")),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    doc_svc: Any = Depends(get_document_svc),

) -> Response:

    """Get document preview (for images and PDFs)."""

    try:

        doc = await doc_svc.get_document(document_id, legal_entity_id)



        if not doc:

            raise HTTPException(status_code=404, detail="Document not found")



        # Only allow preview for certain MIME types

        if doc.mime_type not in [

            DocumentMimeType.PDF,

            DocumentMimeType.JPEG,

            DocumentMimeType.PNG,

            DocumentMimeType.GIF,

        ]:

            raise HTTPException(

                status_code=400, detail=f"Preview not supported for {doc.mime_type}"

            )



        file_content = await doc_svc.get_file_content(document_id, legal_entity_id)



        if not file_content:

            raise HTTPException(status_code=404, detail="File not found")



        return Response(

            content=file_content,

            media_type=doc.mime_type,

            headers={

                "Content-Disposition": f"inline; filename={doc.original_filename}",

            },

        )

    except HTTPException:

        raise

    except Exception as e:

        logger.exception("Failed to preview document: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





# ----------------------------------------------------------------------------

# DOCUMENT METADATA CRUD

# ----------------------------------------------------------------------------





@router.get(

    "/{document_id}",

    response_model=DocumentResponseSchema,

    summary="Get document metadata",

    operation_id="get_document_metadata",

)

async def get_document_metadata(

    document_id: UUID,

    _permission: None = Depends(require_permission("document:read")),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    doc_svc: Any = Depends(get_document_svc),

) -> DocumentResponseSchema:

    """Get document metadata without downloading the file."""

    try:

        doc = await doc_svc.get_document(document_id, legal_entity_id)



        if not doc:

            raise HTTPException(status_code=404, detail="Document not found")



        return DocumentResponseSchema(

            id=doc.id,

            document_number=doc.document_number,

            original_filename=doc.original_filename,

            file_size=doc.file_size,

            mime_type=doc.mime_type,

            file_hash=doc.file_hash,

            version=doc.version,

            entity_type=doc.entity_type,

            entity_id=doc.entity_id,

            entity_reference=doc.entity_reference,

            tags=doc.tags,

            description=doc.description,

            status=DocumentStatus(doc.status),

            is_locked=doc.is_locked,

            is_encrypted=doc.is_encrypted,

            retention_until=doc.retention_until,

            expiry_date=doc.expiry_date,

            uploaded_by=doc.uploaded_by,

            uploaded_by_name=doc.uploaded_by_name,

            uploaded_at=doc.uploaded_at,

            approved_by=doc.approved_by,

            approved_by_name=doc.approved_by_name,

            approved_at=doc.approved_at,

            archived_by=doc.archived_by,

            archived_at=doc.archived_at,

            download_url=f"/api/v1/documents/{doc.id}/download",

            preview_url=f"/api/v1/documents/{doc.id}/preview"

            if doc.mime_type in [DocumentMimeType.PDF, DocumentMimeType.JPEG, DocumentMimeType.PNG]

            else None,

            version_of=doc.version_of,

            notes=doc.notes,

        )

    except HTTPException:

        raise

    except Exception as e:

        logger.exception("Failed to get document metadata: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





@router.put(

    "/{document_id}",

    response_model=DocumentResponseSchema,

    summary="Update document metadata",

    operation_id="update_document_metadata",

)

async def update_document_metadata(

    document_id: UUID,

    request: DocumentUpdateSchema,

    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),

    _permission: None = Depends(require_permission("document:update")),

    current_user: TokenPayload = Depends(get_current_user),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    doc_svc: Any = Depends(get_document_svc),

) -> DocumentResponseSchema:

    """

    Update document metadata (tags, description, entity link, etc.).

    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.

    """

    method_name = "update_document_metadata"

    if idempotency_key:

        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)

        if cached is not None:

            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")

            return DocumentResponseSchema(**cached)



    try:

        result = await doc_svc.update_document_metadata(

            document_id=document_id,

            legal_entity_id=legal_entity_id,

            entity_type=request.entity_type,

            entity_id=request.entity_id,

            tags=request.tags,

            description=request.description,

            notes=request.notes,

            retention_until=request.retention_until,

            expiry_date=request.expiry_date,

            status=request.status.value if request.status else None,

            updated_by=current_user.user_id,

        )



        if not result:

            raise HTTPException(status_code=404, detail="Document not found or cannot be updated")



        response = DocumentResponseSchema(

            id=result.id,

            document_number=result.document_number,

            original_filename=result.original_filename,

            file_size=result.file_size,

            mime_type=result.mime_type,

            file_hash=result.file_hash,

            version=result.version,

            entity_type=result.entity_type,

            entity_id=result.entity_id,

            entity_reference=result.entity_reference,

            tags=result.tags,

            description=result.description,

            status=DocumentStatus(result.status),

            is_locked=result.is_locked,

            is_encrypted=result.is_encrypted,

            retention_until=result.retention_until,

            expiry_date=result.expiry_date,

            uploaded_by=result.uploaded_by,

            uploaded_by_name=result.uploaded_by_name,

            uploaded_at=result.uploaded_at,

            approved_by=result.approved_by,

            approved_by_name=result.approved_by_name,

            approved_at=result.approved_at,

            archived_by=result.archived_by,

            archived_at=result.archived_at,

            download_url=f"/api/v1/documents/{result.id}/download",

            preview_url=f"/api/v1/documents/{result.id}/preview"

            if result.mime_type

            in [DocumentMimeType.PDF, DocumentMimeType.JPEG, DocumentMimeType.PNG]

            else None,

            version_of=result.version_of,

            notes=result.notes,

        )



        if idempotency_key:

            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())



        return response

    except ValueError as e:

        raise HTTPException(status_code=422, detail=str(e))

    except HTTPException:

        raise

    except Exception as e:

        logger.exception("Failed to update document metadata: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





@router.delete(

    "/{document_id}",

    response_model=dict[str, Any],

    summary="Delete document (soft delete)",

    operation_id="delete_document",

)

async def delete_document(

    document_id: UUID,

    reason: str = Query("", description="Deletion reason"),

    permanent: bool = Query(False, description="Permanent deletion"),

    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),

    _permission: None = Depends(require_permission("document:delete")),

    current_user: TokenPayload = Depends(get_current_user),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    doc_svc: Any = Depends(get_document_svc),

) -> dict[str, Any]:

    """

    Delete a document (soft delete by default, can be restored).

    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.

    """

    method_name = "delete_document"

    if idempotency_key:

        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)

        if cached is not None:

            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")

            return cached



    try:

        if permanent:

            result = await doc_svc.permanent_delete_document(

                document_id, legal_entity_id, current_user.user_id, reason

            )

            action = "permanently deleted"

        else:

            result = await doc_svc.delete_document(

                document_id, legal_entity_id, current_user.user_id, reason

            )

            action = "deleted"



        if not result:

            raise HTTPException(status_code=404, detail="Document not found")



        response = {

            "document_id": str(document_id),

            "document_number": result.document_number,

            "action": action,

            "status": result.status,

            "message": f"Document {action} successfully",

        }



        if idempotency_key:

            _idempotency_manager.cache_result(idempotency_key, method_name, response)



        return response

    except ValueError as e:

        raise HTTPException(status_code=422, detail=str(e))

    except Exception as e:

        logger.exception("Failed to delete document: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





@router.post(

    "/{document_id}/restore",

    response_model=DocumentResponseSchema,

    summary="Restore a deleted document",

    operation_id="restore_document",

)

async def restore_document(

    document_id: UUID,

    _permission: None = Depends(require_permission("document:update")),

    current_user: TokenPayload = Depends(get_current_user),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    doc_svc: Any = Depends(get_document_svc),

) -> DocumentResponseSchema:

    """

    Restore a soft-deleted document.

    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.

    """

    try:

        result = await doc_svc.restore_document(document_id, legal_entity_id, current_user.user_id)



        if not result:

            raise HTTPException(status_code=404, detail="Document not found or cannot be restored")



        return DocumentResponseSchema(

            id=result.id,

            document_number=result.document_number,

            original_filename=result.original_filename,

            file_size=result.file_size,

            mime_type=result.mime_type,

            file_hash=result.file_hash,

            version=result.version,

            entity_type=result.entity_type,

            entity_id=result.entity_id,

            entity_reference=result.entity_reference,

            tags=result.tags,

            description=result.description,

            status=DocumentStatus(result.status),

            is_locked=result.is_locked,

            is_encrypted=result.is_encrypted,

            retention_until=result.retention_until,

            expiry_date=result.expiry_date,

            uploaded_by=result.uploaded_by,

            uploaded_by_name=result.uploaded_by_name,

            uploaded_at=result.uploaded_at,

            approved_by=result.approved_by,

            approved_by_name=result.approved_by_name,

            approved_at=result.approved_at,

            archived_by=result.archived_by,

            archived_at=result.archived_at,

            download_url=f"/api/v1/documents/{result.id}/download",

            preview_url=f"/api/v1/documents/{result.id}/preview"

            if result.mime_type

            in [DocumentMimeType.PDF, DocumentMimeType.JPEG, DocumentMimeType.PNG]

            else None,

            version_of=result.version_of,

            notes=result.notes,

        )

    except ValueError as e:

        raise HTTPException(status_code=422, detail=str(e))

    except Exception as e:

        logger.exception("Failed to restore document: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





# ----------------------------------------------------------------------------

# DOCUMENT WORKFLOW (approve, lock, archive)

# ----------------------------------------------------------------------------





@router.post(

    "/{document_id}/approve",

    response_model=DocumentResponseSchema,

    summary="Approve document",

    operation_id="approve_document",

)

async def approve_document(

    document_id: UUID,

    notes: str = Query("", description="Approval notes"),

    _permission: None = Depends(require_permission("document:approve")),

    current_user: TokenPayload = Depends(get_current_user),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    doc_svc: Any = Depends(get_document_svc),

) -> DocumentResponseSchema:

    """

    Approve a document (for documents requiring approval).

    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.

    """

    try:

        result = await doc_svc.approve_document(

            document_id, legal_entity_id, current_user.user_id, notes

        )



        if not result:

            raise HTTPException(status_code=404, detail="Document not found or cannot be approved")



        return DocumentResponseSchema(

            id=result.id,

            document_number=result.document_number,

            original_filename=result.original_filename,

            file_size=result.file_size,

            mime_type=result.mime_type,

            file_hash=result.file_hash,

            version=result.version,

            entity_type=result.entity_type,

            entity_id=result.entity_id,

            entity_reference=result.entity_reference,

            tags=result.tags,

            description=result.description,

            status=DocumentStatus(result.status),

            is_locked=result.is_locked,

            is_encrypted=result.is_encrypted,

            retention_until=result.retention_until,

            expiry_date=result.expiry_date,

            uploaded_by=result.uploaded_by,

            uploaded_by_name=result.uploaded_by_name,

            uploaded_at=result.uploaded_at,

            approved_by=result.approved_by,

            approved_by_name=result.approved_by_name,

            approved_at=result.approved_at,

            archived_by=result.archived_by,

            archived_at=result.archived_at,

            download_url=f"/api/v1/documents/{result.id}/download",

            preview_url=f"/api/v1/documents/{result.id}/preview"

            if result.mime_type

            in [DocumentMimeType.PDF, DocumentMimeType.JPEG, DocumentMimeType.PNG]

            else None,

            version_of=result.version_of,

            notes=result.notes,

        )

    except ValueError as e:

        raise HTTPException(status_code=422, detail=str(e))

    except Exception as e:

        logger.exception("Failed to approve document: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





@router.post(

    "/{document_id}/reject",

    response_model=DocumentResponseSchema,

    summary="Reject document",

    operation_id="reject_document",

)

async def reject_document(

    document_id: UUID,

    reason: str = Query(..., min_length=5, description="Rejection reason"),

    _permission: None = Depends(require_permission("document:approve")),

    current_user: TokenPayload = Depends(get_current_user),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    doc_svc: Any = Depends(get_document_svc),

) -> DocumentResponseSchema:

    """

    Reject a document.

    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.

    """

    try:

        result = await doc_svc.reject_document(

            document_id, legal_entity_id, current_user.user_id, reason

        )



        if not result:

            raise HTTPException(status_code=404, detail="Document not found or cannot be rejected")



        return DocumentResponseSchema(

            id=result.id,

            document_number=result.document_number,

            original_filename=result.original_filename,

            file_size=result.file_size,

            mime_type=result.mime_type,

            file_hash=result.file_hash,

            version=result.version,

            entity_type=result.entity_type,

            entity_id=result.entity_id,

            entity_reference=result.entity_reference,

            tags=result.tags,

            description=result.description,

            status=DocumentStatus(result.status),

            is_locked=result.is_locked,

            is_encrypted=result.is_encrypted,

            retention_until=result.retention_until,

            expiry_date=result.expiry_date,

            uploaded_by=result.uploaded_by,

            uploaded_by_name=result.uploaded_by_name,

            uploaded_at=result.uploaded_at,

            approved_by=result.approved_by,

            approved_by_name=result.approved_by_name,

            approved_at=result.approved_at,

            archived_by=result.archived_by,

            archived_at=result.archived_at,

            download_url=f"/api/v1/documents/{result.id}/download",

            preview_url=f"/api/v1/documents/{result.id}/preview"

            if result.mime_type

            in [DocumentMimeType.PDF, DocumentMimeType.JPEG, DocumentMimeType.PNG]

            else None,

            version_of=result.version_of,

            notes=result.notes,

        )

    except ValueError as e:

        raise HTTPException(status_code=422, detail=str(e))

    except Exception as e:

        logger.exception("Failed to reject document: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





@router.post(

    "/{document_id}/archive",

    response_model=DocumentResponseSchema,

    summary="Archive document",

    operation_id="archive_document",

)

async def archive_document(

    document_id: UUID,

    reason: str = Query("", description="Archive reason"),

    _permission: None = Depends(require_permission("document:archive")),

    current_user: TokenPayload = Depends(get_current_user),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    doc_svc: Any = Depends(get_document_svc),

) -> DocumentResponseSchema:

    """

    Archive a document (move to cold storage).

    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.

    """

    try:

        result = await doc_svc.archive_document(

            document_id, legal_entity_id, current_user.user_id, reason

        )



        if not result:

            raise HTTPException(status_code=404, detail="Document not found")



        return DocumentResponseSchema(

            id=result.id,

            document_number=result.document_number,

            original_filename=result.original_filename,

            file_size=result.file_size,

            mime_type=result.mime_type,

            file_hash=result.file_hash,

            version=result.version,

            entity_type=result.entity_type,

            entity_id=result.entity_id,

            entity_reference=result.entity_reference,

            tags=result.tags,

            description=result.description,

            status=DocumentStatus(result.status),

            is_locked=result.is_locked,

            is_encrypted=result.is_encrypted,

            retention_until=result.retention_until,

            expiry_date=result.expiry_date,

            uploaded_by=result.uploaded_by,

            uploaded_by_name=result.uploaded_by_name,

            uploaded_at=result.uploaded_at,

            approved_by=result.approved_by,

            approved_by_name=result.approved_by_name,

            approved_at=result.approved_at,

            archived_by=result.archived_by,

            archived_at=result.archived_at,

            download_url=f"/api/v1/documents/{result.id}/download",

            preview_url=f"/api/v1/documents/{result.id}/preview"

            if result.mime_type

            in [DocumentMimeType.PDF, DocumentMimeType.JPEG, DocumentMimeType.PNG]

            else None,

            version_of=result.version_of,

            notes=result.notes,

        )

    except ValueError as e:

        raise HTTPException(status_code=422, detail=str(e))

    except Exception as e:

        logger.exception("Failed to archive document: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





@router.post(

    "/{document_id}/lock",

    response_model=DocumentResponseSchema,

    summary="Lock document",

    operation_id="lock_document",

)

async def lock_document(

    document_id: UUID,

    reason: str = Query("", description="Lock reason"),

    _permission: None = Depends(require_permission("document:lock")),

    current_user: TokenPayload = Depends(get_current_user),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    doc_svc: Any = Depends(get_document_svc),

) -> DocumentResponseSchema:

    """

    Lock a document to prevent modifications.

    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.

    """

    try:

        result = await doc_svc.lock_document(

            document_id, legal_entity_id, current_user.user_id, reason

        )



        if not result:

            raise HTTPException(status_code=404, detail="Document not found")



        return DocumentResponseSchema(

            id=result.id,

            document_number=result.document_number,

            original_filename=result.original_filename,

            file_size=result.file_size,

            mime_type=result.mime_type,

            file_hash=result.file_hash,

            version=result.version,

            entity_type=result.entity_type,

            entity_id=result.entity_id,

            entity_reference=result.entity_reference,

            tags=result.tags,

            description=result.description,

            status=DocumentStatus(result.status),

            is_locked=True,

            is_encrypted=result.is_encrypted,

            retention_until=result.retention_until,

            expiry_date=result.expiry_date,

            uploaded_by=result.uploaded_by,

            uploaded_by_name=result.uploaded_by_name,

            uploaded_at=result.uploaded_at,

            approved_by=result.approved_by,

            approved_by_name=result.approved_by_name,

            approved_at=result.approved_at,

            archived_by=result.archived_by,

            archived_at=result.archived_at,

            download_url=f"/api/v1/documents/{result.id}/download",

            preview_url=f"/api/v1/documents/{result.id}/preview"

            if result.mime_type

            in [DocumentMimeType.PDF, DocumentMimeType.JPEG, DocumentMimeType.PNG]

            else None,

            version_of=result.version_of,

            notes=result.notes,

        )

    except ValueError as e:

        raise HTTPException(status_code=422, detail=str(e))

    except Exception as e:

        logger.exception("Failed to lock document: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





@router.post(

    "/{document_id}/unlock",

    response_model=DocumentResponseSchema,

    summary="Unlock document",

    operation_id="unlock_document",

)

async def unlock_document(

    document_id: UUID,

    _permission: None = Depends(require_permission("document:lock")),

    current_user: TokenPayload = Depends(get_current_user),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    doc_svc: Any = Depends(get_document_svc),

) -> DocumentResponseSchema:

    """

    Unlock a locked document.

    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.

    """

    try:

        result = await doc_svc.unlock_document(document_id, legal_entity_id, current_user.user_id)



        if not result:

            raise HTTPException(status_code=404, detail="Document not found")



        return DocumentResponseSchema(

            id=result.id,

            document_number=result.document_number,

            original_filename=result.original_filename,

            file_size=result.file_size,

            mime_type=result.mime_type,

            file_hash=result.file_hash,

            version=result.version,

            entity_type=result.entity_type,

            entity_id=result.entity_id,

            entity_reference=result.entity_reference,

            tags=result.tags,

            description=result.description,

            status=DocumentStatus(result.status),

            is_locked=False,

            is_encrypted=result.is_encrypted,

            retention_until=result.retention_until,

            expiry_date=result.expiry_date,

            uploaded_by=result.uploaded_by,

            uploaded_by_name=result.uploaded_by_name,

            uploaded_at=result.uploaded_at,

            approved_by=result.approved_by,

            approved_by_name=result.approved_by_name,

            approved_at=result.approved_at,

            archived_by=result.archived_by,

            archived_at=result.archived_at,

            download_url=f"/api/v1/documents/{result.id}/download",

            preview_url=f"/api/v1/documents/{result.id}/preview"

            if result.mime_type

            in [DocumentMimeType.PDF, DocumentMimeType.JPEG, DocumentMimeType.PNG]

            else None,

            version_of=result.version_of,

            notes=result.notes,

        )

    except ValueError as e:

        raise HTTPException(status_code=422, detail=str(e))

    except Exception as e:

        logger.exception("Failed to unlock document: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





# ----------------------------------------------------------------------------

# DOCUMENT VERSIONING

# ----------------------------------------------------------------------------





@router.post(

    "/{document_id}/version",

    response_model=DocumentResponseSchema,

    status_code=status.HTTP_201_CREATED,

    summary="Create new document version",

    operation_id="create_document_version",

)

async def create_document_version(

    document_id: UUID,

    file: UploadFile = File(..., description="New version file"),

    notes: str = Form("", description="Version notes"),

    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),

    _permission: None = Depends(require_permission("document:update")),

    current_user: TokenPayload = Depends(get_current_user),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    doc_svc: Any = Depends(get_document_svc),

) -> DocumentResponseSchema:

    """

    Create a new version of an existing document.

    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.

    """

    method_name = "create_document_version"

    if idempotency_key:

        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)

        if cached is not None:

            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")

            return DocumentResponseSchema(**cached)



    try:

        content = await file.read()



        if not validate_file_size(content):

            raise HTTPException(

                status_code=413,

                detail=f"File size exceeds {MAX_FILE_SIZE_BYTES / 1024 / 1024} MB limit",

            )



        file_hash = compute_file_hash(content)

        mime_type = get_mime_type(file.filename)



        result = await doc_svc.create_document_version(

            document_id=document_id,

            legal_entity_id=legal_entity_id,

            file_content=content,

            original_filename=file.filename,

            mime_type=mime_type,

            file_hash=file_hash,

            notes=notes,

            created_by=current_user.user_id,

        )



        if not result:

            raise HTTPException(status_code=404, detail="Document not found")



        response = DocumentResponseSchema(

            id=result.id,

            document_number=result.document_number,

            original_filename=result.original_filename,

            file_size=result.file_size,

            mime_type=result.mime_type,

            file_hash=result.file_hash,

            version=result.version,

            entity_type=result.entity_type,

            entity_id=result.entity_id,

            entity_reference=result.entity_reference,

            tags=result.tags,

            description=result.description,

            status=DocumentStatus(result.status),

            is_locked=result.is_locked,

            is_encrypted=result.is_encrypted,

            retention_until=result.retention_until,

            expiry_date=result.expiry_date,

            uploaded_by=result.uploaded_by,

            uploaded_by_name=result.uploaded_by_name,

            uploaded_at=result.uploaded_at,

            approved_by=result.approved_by,

            approved_by_name=result.approved_by_name,

            approved_at=result.approved_at,

            archived_by=result.archived_by,

            archived_at=result.archived_at,

            download_url=f"/api/v1/documents/{result.id}/download",

            preview_url=f"/api/v1/documents/{result.id}/preview"

            if result.mime_type

            in [DocumentMimeType.PDF, DocumentMimeType.JPEG, DocumentMimeType.PNG]

            else None,

            version_of=result.version_of,

            notes=result.notes,

        )



        if idempotency_key:

            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())



        return response

    except HTTPException:

        raise

    except ValueError as e:

        raise HTTPException(status_code=422, detail=str(e))

    except Exception as e:

        logger.exception("Failed to create document version: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





@router.get(

    "/{document_id}/versions",

    response_model=list[DocumentVersionResponseSchema],

    summary="Get document versions",

    operation_id="get_document_versions",

)

async def get_document_versions(

    document_id: UUID,

    _permission: None = Depends(require_permission("document:read")),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    doc_svc: Any = Depends(get_document_svc),

) -> list[DocumentVersionResponseSchema]:

    """Get all versions of a document."""

    try:

        versions = await doc_svc.get_document_versions(document_id, legal_entity_id)



        return [

            DocumentVersionResponseSchema(

                id=v.id,

                document_number=v.document_number,

                version=v.version,

                file_size=v.file_size,

                file_hash=v.file_hash,

                created_at=v.created_at,

                created_by=v.created_by,

                created_by_name=v.created_by_name,

                notes=v.notes,

            )

            for v in versions

        ]

    except Exception as e:

        logger.exception("Failed to get document versions: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





# ----------------------------------------------------------------------------

# DOCUMENT INTEGRITY VERIFICATION

# ----------------------------------------------------------------------------





@router.post(

    "/{document_id}/verify",

    response_model=DocumentIntegrityResponseSchema,

    summary="Verify document integrity",

    operation_id="verify_document_integrity",

)

async def verify_document_integrity(

    document_id: UUID,

    _permission: None = Depends(require_permission("document:read")),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    current_user: TokenPayload = Depends(get_current_user),

    doc_svc: Any = Depends(get_document_svc),

) -> DocumentIntegrityResponseSchema:

    """Verify document integrity by comparing stored hash with computed hash."""

    try:

        result = await doc_svc.verify_document_integrity(

            document_id=document_id,

            legal_entity_id=legal_entity_id,

            verified_by=current_user.user_id,

        )



        if not result:

            raise HTTPException(status_code=404, detail="Document not found")



        return DocumentIntegrityResponseSchema(

            document_id=result.document_id,

            document_number=result.document_number,

            original_filename=result.original_filename,

            stored_hash=result.stored_hash,

            computed_hash=result.computed_hash,

            is_valid=result.is_valid,

            file_size=result.file_size,

            verified_at=result.verified_at,

            verified_by=result.verified_by,

            verified_by_name=result.verified_by_name,

        )

    except Exception as e:

        logger.exception("Failed to verify document integrity: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





# ----------------------------------------------------------------------------

# BULK OPERATIONS

# ----------------------------------------------------------------------------





@router.post(

    "/bulk-link",

    response_model=dict[str, Any],

    summary="Bulk link documents to entity",

    operation_id="bulk_link_documents",

)

async def bulk_link_documents(

    request: DocumentBulkLinkSchema,

    _permission: None = Depends(require_permission("document:update")),

    current_user: TokenPayload = Depends(get_current_user),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    doc_svc: Any = Depends(get_document_svc),

) -> dict[str, Any]:

    """

    Bulk link multiple documents to an entity.

    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.

    """

    try:

        result = await doc_svc.bulk_link_documents(

            document_ids=request.document_ids,

            legal_entity_id=legal_entity_id,

            entity_type=request.entity_type,

            entity_id=request.entity_id,

            updated_by=current_user.user_id,

        )



        return {

            "linked_count": result.linked_count,

            "skipped_count": result.skipped_count,

            "failed_count": result.failed_count,

            "failed_ids": [str(fid) for fid in result.failed_ids],

            "errors": result.errors,

        }

    except Exception as e:

        logger.exception("Failed to bulk link documents: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





@router.delete(

    "/bulk",

    response_model=dict[str, Any],

    summary="Bulk delete documents",

    operation_id="bulk_delete_documents",

)

async def bulk_delete_documents(

    document_ids: list[UUID] = Query(..., description="List of document IDs"),

    reason: str = Query("", description="Deletion reason"),

    permanent: bool = Query(False, description="Permanent deletion"),

    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),

    _permission: None = Depends(require_permission("document:delete")),

    current_user: TokenPayload = Depends(get_current_user),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    doc_svc: Any = Depends(get_document_svc),

) -> dict[str, Any]:

    """

    Bulk delete multiple documents.

    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.

    """

    method_name = "bulk_delete_documents"

    if idempotency_key:

        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)

        if cached is not None:

            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")

            return cached



    try:

        result = await doc_svc.bulk_delete_documents(

            document_ids=document_ids,

            legal_entity_id=legal_entity_id,

            reason=reason,

            permanent=permanent,

            deleted_by=current_user.user_id,

        )



        response = {

            "total": result.total,

            "deleted_count": result.deleted_count,

            "failed_count": result.failed_count,

            "failed_ids": [str(fid) for fid in result.failed_ids],

            "errors": result.errors,

        }



        if idempotency_key:

            _idempotency_manager.cache_result(idempotency_key, method_name, response)



        return response

    except Exception as e:

        logger.exception("Failed to bulk delete documents: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





# ----------------------------------------------------------------------------

# LIST AND SEARCH

# ----------------------------------------------------------------------------





@router.get(

    "/",

    response_model=list[DocumentResponseSchema],

    summary="List documents",

    operation_id="list_documents",

)

async def list_documents(

    entity_type: str | None = Query(None, description="Filter by entity type"),

    entity_id: UUID | None = Query(None, description="Filter by entity ID"),

    tag: str | None = Query(None, description="Filter by tag"),

    status: DocumentStatus | None = Query(None, description="Filter by status"),

    start_date: datetime | None = Query(None, description="Start date"),

    end_date: datetime | None = Query(None, description="End date"),

    filename_contains: str | None = Query(None, description="Search in filename"),

    page: int = Query(1, ge=1),

    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),

    _permission: None = Depends(require_permission("document:read")),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    doc_svc: Any = Depends(get_document_svc),

) -> list[DocumentResponseSchema]:

    """List documents with filters and pagination."""

    try:

        result = await doc_svc.list_documents(

            legal_entity_id=legal_entity_id,

            entity_type=entity_type,

            entity_id=entity_id,

            tag=tag,

            status=status.value if status else None,

            start_date=start_date,

            end_date=end_date,

            filename_contains=filename_contains,

            page=page,

            page_size=page_size,

        )



        return [

            DocumentResponseSchema(

                id=d.id,

                document_number=d.document_number,

                original_filename=d.original_filename,

                file_size=d.file_size,

                mime_type=d.mime_type,

                file_hash=d.file_hash,

                version=d.version,

                entity_type=d.entity_type,

                entity_id=d.entity_id,

                entity_reference=d.entity_reference,

                tags=d.tags,

                description=d.description,

                status=DocumentStatus(d.status),

                is_locked=d.is_locked,

                is_encrypted=d.is_encrypted,

                retention_until=d.retention_until,

                expiry_date=d.expiry_date,

                uploaded_by=d.uploaded_by,

                uploaded_by_name=d.uploaded_by_name,

                uploaded_at=d.uploaded_at,

                approved_by=d.approved_by,

                approved_by_name=d.approved_by_name,

                approved_at=d.approved_at,

                archived_by=d.archived_by,

                archived_at=d.archived_at,

                download_url=f"/api/v1/documents/{d.id}/download",

                preview_url=f"/api/v1/documents/{d.id}/preview"

                if d.mime_type

                in [DocumentMimeType.PDF, DocumentMimeType.JPEG, DocumentMimeType.PNG]

                else None,

                version_of=d.version_of,

                notes=d.notes,

            )

            for d in result.items

        ]

    except Exception as e:

        logger.exception("Failed to list documents: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





# ----------------------------------------------------------------------------

# GENERATE PRESIGNED URL (for direct S3 access)

# ----------------------------------------------------------------------------





@router.post(

    "/{document_id}/presigned-url",

    response_model=dict[str, str],

    summary="Generate pre-signed download URL",

    operation_id="generate_presigned_url",

)

async def generate_presigned_url(

    document_id: UUID,

    expires_in_seconds: int = Query(3600, ge=60, le=86400, description="URL expiry in seconds"),

    _permission: None = Depends(require_permission("document:download")),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    doc_svc: Any = Depends(get_document_svc),

) -> dict[str, str]:

    """Generate temporary pre-signed URL for direct S3/MinIO access."""

    try:

        url = await doc_svc.generate_presigned_url(

            document_id=document_id,

            legal_entity_id=legal_entity_id,

            expires_in_seconds=expires_in_seconds,

        )



        if not url:

            raise HTTPException(status_code=404, detail="Document not found")



        return {

            "url": url,

            "expires_in_seconds": str(expires_in_seconds),

            "document_id": str(document_id),

        }

    except Exception as e:

        logger.exception("Failed to generate presigned URL: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





# ----------------------------------------------------------------------------

# DOCUMENT HISTORY & AUDIT

# ----------------------------------------------------------------------------





@router.get(

    "/{document_id}/history",

    response_model=list[dict[str, Any]],

    summary="Get document history",

    operation_id="get_document_history",

)

async def get_document_history(

    document_id: UUID,

    _permission: None = Depends(require_permission("document:read")),

    legal_entity_id: UUID = Depends(get_current_legal_entity),

    doc_svc: Any = Depends(get_document_svc),

) -> list[dict[str, Any]]:

    """Get document change history (audit trail)."""

    try:

        history = await doc_svc.get_document_history(document_id, legal_entity_id)



        return [

            {

                "timestamp": h.timestamp.isoformat(),

                "action": h.action,

                "field": h.field,

                "old_value": h.old_value,

                "new_value": h.new_value,

                "actor_id": str(h.actor_id),

                "actor_name": h.actor_name,

                "reason": h.reason,

            }

            for h in history

        ]

    except Exception as e:

        logger.exception("Failed to get document history: %s", e)

        raise HTTPException(status_code=500, detail="Internal server error")





# ----------------------------------------------------------------------------

# EXPORTS

# ----------------------------------------------------------------------------



__all__ = ["router"]