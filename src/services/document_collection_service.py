"""
Document collection service - business logic for document collection.
"""
import json
import logging
from typing import Optional
from uuid import UUID

import asyncpg

from src.auth.exceptions import WorkspaceAccessDenied, InsufficientRoleError
from src.exceptions import NotFoundError, ValidationError
from src.repositories.document_type_repo import DocumentTypeRepository
from src.repositories.document_collection_config_repo import DocumentCollectionConfigRepository
from src.repositories.document_collection_repo import DocumentCollectionRepository
from src.repositories.membership_repo import WorkspaceMembershipRepository
from src.models.document_collection_v2 import (
    DocumentTypeResponse,
    CollectionConfigResponse,
    CollectionConfigDetailResponse,
    CollectionRequirementResponse,
    ResolveDocumentsResponse,
    StartCollectionResponse,
    DocumentCollectionResponse,
    DocumentCollectionDetailResponse,
    CollectionMessageResponse,
    CollectionUploadResponse,
)

logger = logging.getLogger(__name__)


class DocumentCollectionService:
    """Service for document collection operations."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.doc_type_repo = DocumentTypeRepository(pool)
        self.config_repo = DocumentCollectionConfigRepository(pool)
        self.collection_repo = DocumentCollectionRepository(pool)
        self.membership_repo = WorkspaceMembershipRepository(pool)

    # =========================================================================
    # Access Control
    # =========================================================================

    async def _check_read_access(self, workspace_id: UUID, user_id: UUID) -> dict:
        """Verify user has read access (any workspace member)."""
        membership = await self.membership_repo.get_membership(user_id, workspace_id)
        if not membership:
            raise WorkspaceAccessDenied(str(workspace_id))
        return membership

    async def _check_write_access(self, workspace_id: UUID, user_id: UUID) -> dict:
        """Verify user has write access (owner or admin)."""
        membership = await self._check_read_access(workspace_id, user_id)
        if membership["role"] not in ("owner", "admin"):
            raise InsufficientRoleError("admin", membership["role"])
        return membership

    # =========================================================================
    # Document Types
    # =========================================================================

    async def list_document_types(
        self, workspace_id: UUID, user_id: UUID,
        category: Optional[str] = None,
        is_active: Optional[bool] = True,
    ) -> list[DocumentTypeResponse]:
        """List document types for a workspace."""
        await self._check_read_access(workspace_id, user_id)
        rows = await self.doc_type_repo.list_for_workspace(workspace_id, category, is_active)
        return [self._build_doc_type_response(r) for r in rows]

    async def create_document_type(
        self, workspace_id: UUID, user_id: UUID, **kwargs
    ) -> DocumentTypeResponse:
        """Create a new document type."""
        await self._check_write_access(workspace_id, user_id)

        existing = await self.doc_type_repo.get_by_slug(workspace_id, kwargs["slug"])
        if existing:
            raise ValidationError(f"Document type with slug '{kwargs['slug']}' already exists", field="slug")

        row = await self.doc_type_repo.create(workspace_id, **kwargs)
        return self._build_doc_type_response(row)

    async def update_document_type(
        self, workspace_id: UUID, user_id: UUID, doc_type_id: UUID, **kwargs
    ) -> DocumentTypeResponse:
        """Update a document type."""
        await self._check_write_access(workspace_id, user_id)

        existing = await self.doc_type_repo.get_by_id(doc_type_id)
        if not existing or existing["workspace_id"] != workspace_id:
            raise NotFoundError("Document type", str(doc_type_id))

        row = await self.doc_type_repo.update(doc_type_id, **kwargs)
        return self._build_doc_type_response(row)

    async def delete_document_type(
        self, workspace_id: UUID, user_id: UUID, doc_type_id: UUID
    ) -> None:
        """Soft-delete a document type."""
        await self._check_write_access(workspace_id, user_id)

        existing = await self.doc_type_repo.get_by_id(doc_type_id)
        if not existing or existing["workspace_id"] != workspace_id:
            raise NotFoundError("Document type", str(doc_type_id))

        await self.doc_type_repo.soft_delete(doc_type_id)

    # =========================================================================
    # Collection Configs
    # =========================================================================

    async def list_configs(
        self, workspace_id: UUID, user_id: UUID,
        vacancy_id: Optional[UUID] = None,
    ) -> list[CollectionConfigResponse]:
        """List collection configs."""
        await self._check_read_access(workspace_id, user_id)
        rows = await self.config_repo.list_for_workspace(workspace_id, vacancy_id)
        return [self._build_config_response(r) for r in rows]

    async def get_config(
        self, workspace_id: UUID, user_id: UUID, config_id: UUID
    ) -> CollectionConfigDetailResponse:
        """Get a config with its required documents."""
        await self._check_read_access(workspace_id, user_id)

        config = await self.config_repo.get_by_id(config_id)
        if not config or config["workspace_id"] != workspace_id:
            raise NotFoundError("Collection config", str(config_id))

        requirements = await self.config_repo.get_requirements(config_id)
        return self._build_config_detail_response(config, requirements)

    async def create_config(
        self, workspace_id: UUID, user_id: UUID,
        vacancy_id: Optional[UUID],
        name: Optional[str],
        intro_message: Optional[str],
        document_type_ids: list[UUID],
    ) -> CollectionConfigDetailResponse:
        """Create a collection config."""
        await self._check_write_access(workspace_id, user_id)

        # Check for duplicate
        if vacancy_id is not None:
            existing = await self.config_repo.get_for_vacancy(vacancy_id)
            if existing:
                raise ValidationError(
                    f"A collection config already exists for this vacancy",
                    field="vacancy_id",
                )
        else:
            existing = await self.config_repo.get_workspace_default(workspace_id)
            if existing:
                raise ValidationError(
                    "A default collection config already exists for this workspace",
                    field="vacancy_id",
                )

        row = await self.config_repo.create(
            workspace_id, vacancy_id, name, intro_message, document_type_ids,
        )
        requirements = await self.config_repo.get_requirements(row["id"])
        return self._build_config_detail_response(row, requirements)

    async def update_config(
        self, workspace_id: UUID, user_id: UUID, config_id: UUID, **kwargs
    ) -> CollectionConfigDetailResponse:
        """Update a config. If document_type_ids provided, replace requirements."""
        await self._check_write_access(workspace_id, user_id)

        existing = await self.config_repo.get_by_id(config_id)
        if not existing or existing["workspace_id"] != workspace_id:
            raise NotFoundError("Collection config", str(config_id))

        # Handle document_type_ids separately
        document_type_ids = kwargs.pop("document_type_ids", None)

        # Update config fields
        update_fields = {k: v for k, v in kwargs.items() if v is not None}
        if update_fields:
            row = await self.config_repo.update(config_id, **update_fields)
        else:
            row = existing

        # Replace requirements if provided
        if document_type_ids is not None:
            reqs = [
                {"document_type_id": str(dt_id), "position": i, "is_required": True}
                for i, dt_id in enumerate(document_type_ids)
            ]
            await self.config_repo.replace_requirements(config_id, reqs)

        requirements = await self.config_repo.get_requirements(config_id)
        return self._build_config_detail_response(row, requirements)

    async def delete_config(
        self, workspace_id: UUID, user_id: UUID, config_id: UUID
    ) -> None:
        """Delete a config (requirements cascade)."""
        await self._check_write_access(workspace_id, user_id)

        existing = await self.config_repo.get_by_id(config_id)
        if not existing or existing["workspace_id"] != workspace_id:
            raise NotFoundError("Collection config", str(config_id))

        await self.config_repo.delete(config_id)

    async def update_config_status(
        self, workspace_id: UUID, user_id: UUID, config_id: UUID,
        is_online: Optional[bool] = None,
        whatsapp_enabled: Optional[bool] = None,
    ) -> CollectionConfigResponse:
        """Toggle online/whatsapp flags."""
        await self._check_write_access(workspace_id, user_id)

        existing = await self.config_repo.get_by_id(config_id)
        if not existing or existing["workspace_id"] != workspace_id:
            raise NotFoundError("Collection config", str(config_id))

        updates = {}
        if is_online is not None:
            updates["is_online"] = is_online
        if whatsapp_enabled is not None:
            updates["whatsapp_enabled"] = whatsapp_enabled

        row = await self.config_repo.update(config_id, **updates) if updates else existing
        return self._build_config_response(row)

    # =========================================================================
    # Requirements
    # =========================================================================

    async def get_requirements(
        self, workspace_id: UUID, user_id: UUID, config_id: UUID
    ) -> list[CollectionRequirementResponse]:
        """Get requirements for a config."""
        await self._check_read_access(workspace_id, user_id)

        config = await self.config_repo.get_by_id(config_id)
        if not config or config["workspace_id"] != workspace_id:
            raise NotFoundError("Collection config", str(config_id))

        rows = await self.config_repo.get_requirements(config_id)
        return [self._build_requirement_response(r) for r in rows]

    async def replace_requirements(
        self, workspace_id: UUID, user_id: UUID, config_id: UUID,
        requirements: list[dict],
    ) -> list[CollectionRequirementResponse]:
        """Replace all requirements for a config."""
        await self._check_write_access(workspace_id, user_id)

        config = await self.config_repo.get_by_id(config_id)
        if not config or config["workspace_id"] != workspace_id:
            raise NotFoundError("Collection config", str(config_id))

        await self.config_repo.replace_requirements(config_id, requirements)

        rows = await self.config_repo.get_requirements(config_id)
        return [self._build_requirement_response(r) for r in rows]

    # =========================================================================
    # Document Resolution
    # =========================================================================

    async def resolve_documents(
        self, workspace_id: UUID, user_id: UUID,
        vacancy_id: Optional[UUID] = None,
    ) -> ResolveDocumentsResponse:
        """
        Resolve which documents are needed for a candidate.

        Algorithm:
        1. Get workspace default docs (document_types WHERE is_default=true)
        2. If vacancy_id:
           a. Look up config for that vacancy
           b. If found: get its requirements
           c. Merge: union of default + vacancy-specific (dedup by type_id)
        3. Else: use workspace default config or fallback to is_default types
        """
        await self._check_read_access(workspace_id, user_id)

        # Get default document types
        default_rows = await self.doc_type_repo.get_defaults(workspace_id)
        default_docs = {r["id"]: r for r in default_rows}

        if vacancy_id:
            vacancy_config = await self.config_repo.get_for_vacancy(vacancy_id)
            if vacancy_config:
                # Get vacancy-specific requirements
                reqs = await self.config_repo.get_requirements(vacancy_config["id"])
                vacancy_doc_ids = {r["document_type_id"] for r in reqs}

                # Get the full doc type records for vacancy requirements
                vacancy_type_rows = await self.doc_type_repo.get_by_ids(list(vacancy_doc_ids))
                vacancy_docs = {r["id"]: r for r in vacancy_type_rows}

                # Merge: defaults + vacancy-specific
                merged = {**default_docs}
                for doc_id, doc in vacancy_docs.items():
                    merged[doc_id] = doc

                source = "merged" if default_docs else "vacancy"
                return ResolveDocumentsResponse(
                    documents=[self._build_doc_type_response(r) for r in merged.values()],
                    source=source,
                )

        # No vacancy or no vacancy config: use workspace default config
        default_config = await self.config_repo.get_workspace_default(workspace_id)
        if default_config:
            reqs = await self.config_repo.get_requirements(default_config["id"])
            if reqs:
                req_doc_ids = [r["document_type_id"] for r in reqs]
                config_type_rows = await self.doc_type_repo.get_by_ids(req_doc_ids)
                return ResolveDocumentsResponse(
                    documents=[self._build_doc_type_response(r) for r in config_type_rows],
                    source="default",
                )

        # Fallback: use document_types where is_default=true
        return ResolveDocumentsResponse(
            documents=[self._build_doc_type_response(r) for r in default_rows],
            source="default",
        )

    # =========================================================================
    # Document Collections
    # =========================================================================

    async def list_collections(
        self, workspace_id: UUID, user_id: UUID,
        vacancy_id: Optional[UUID] = None,
        status: Optional[str] = None,
        limit: int = 50, offset: int = 0,
    ) -> tuple[list[DocumentCollectionResponse], int]:
        """List document collections with filtering."""
        await self._check_read_access(workspace_id, user_id)
        rows, total = await self.collection_repo.list_collections(
            workspace_id, vacancy_id, status, limit, offset,
        )
        return [self._build_collection_response(r) for r in rows], total

    async def get_collection(
        self, workspace_id: UUID, user_id: UUID, collection_id: UUID
    ) -> DocumentCollectionDetailResponse:
        """Get a document collection with messages, uploads, and required documents."""
        await self._check_read_access(workspace_id, user_id)

        collection = await self.collection_repo.get_by_id(collection_id)
        if not collection or collection["workspace_id"] != workspace_id:
            raise NotFoundError("Document collection", str(collection_id))

        messages = await self.collection_repo.get_messages(collection_id)
        uploads = await self.collection_repo.get_uploads(collection_id)

        # Resolve documents_required slugs to full document types
        raw = collection.get("documents_required") or []
        doc_slugs = json.loads(raw) if isinstance(raw, str) else raw
        if doc_slugs:
            doc_type_rows = await self.doc_type_repo.get_by_slugs(workspace_id, doc_slugs)
            doc_types = [self._build_doc_type_response(r) for r in doc_type_rows]
        else:
            doc_types = []

        return self._build_collection_detail_response(collection, messages, uploads, doc_types)

    async def abandon_collection(
        self, workspace_id: UUID, user_id: UUID, collection_id: UUID
    ) -> None:
        """Mark a document collection as abandoned."""
        await self._check_write_access(workspace_id, user_id)

        collection = await self.collection_repo.get_by_id(collection_id)
        if not collection or collection["workspace_id"] != workspace_id:
            raise NotFoundError("Document collection", str(collection_id))

        await self.collection_repo.update_status(collection_id, "abandoned")

    async def start_collection(
        self, workspace_id: UUID, user_id: UUID,
        candidate_name: str,
        candidate_lastname: str,
        whatsapp_number: str,
        vacancy_id: Optional[UUID] = None,
        application_id: Optional[UUID] = None,
        candidate_id: Optional[UUID] = None,
    ) -> StartCollectionResponse:
        """
        Start a document collection.

        Creates DB records and resolves documents. Does NOT send WhatsApp (agent phase).
        """
        await self._check_write_access(workspace_id, user_id)

        # Resolve documents
        resolved = await self.resolve_documents(workspace_id, user_id, vacancy_id)

        # Find or determine config
        config = None
        if vacancy_id:
            config = await self.config_repo.get_for_vacancy(vacancy_id)
        if not config:
            config = await self.config_repo.get_workspace_default(workspace_id)
        if not config:
            raise ValidationError("No document collection config found. Create a default config first.")

        full_name = f"{candidate_name} {candidate_lastname}"
        normalized_phone = whatsapp_number.lstrip("+")

        # Abandon previous active collections for this phone
        await self.collection_repo.abandon_active_for_phone(normalized_phone)

        # Create document collection
        doc_slugs = [d.slug for d in resolved.documents]
        collection = await self.collection_repo.create(
            config_id=config["id"],
            workspace_id=workspace_id,
            candidate_name=full_name,
            candidate_phone=normalized_phone,
            vacancy_id=vacancy_id,
            application_id=application_id,
            candidate_id=candidate_id,
            documents_required=doc_slugs,
            channel="whatsapp",
        )

        return StartCollectionResponse(
            collection_id=str(collection["id"]),
            config_id=str(config["id"]),
            candidate_name=full_name,
            whatsapp_number=whatsapp_number,
            documents_required=resolved.documents,
            source=resolved.source,
        )

    # =========================================================================
    # Response Builders
    # =========================================================================

    @staticmethod
    def _build_doc_type_response(row) -> DocumentTypeResponse:
        return DocumentTypeResponse(
            id=str(row["id"]),
            workspace_id=str(row["workspace_id"]),
            slug=row["slug"],
            name=row["name"],
            description=row.get("description"),
            category=row["category"],
            requires_front_back=row["requires_front_back"],
            is_verifiable=row["is_verifiable"],
            icon=row.get("icon"),
            is_default=row["is_default"],
            is_active=row["is_active"],
            sort_order=row["sort_order"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _build_config_response(row) -> CollectionConfigResponse:
        return CollectionConfigResponse(
            id=str(row["id"]),
            workspace_id=str(row["workspace_id"]),
            vacancy_id=str(row["vacancy_id"]) if row["vacancy_id"] else None,
            name=row.get("name"),
            intro_message=row.get("intro_message"),
            status=row["status"],
            is_online=row["is_online"],
            whatsapp_enabled=row["whatsapp_enabled"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _build_config_detail_response(
        self, config_row, requirement_rows
    ) -> CollectionConfigDetailResponse:
        base = self._build_config_response(config_row)
        documents = [self._build_requirement_response(r) for r in requirement_rows]
        return CollectionConfigDetailResponse(
            **base.model_dump(),
            documents=documents,
        )

    def _build_requirement_response(self, row) -> CollectionRequirementResponse:
        return CollectionRequirementResponse(
            id=str(row["id"]),
            document_type_id=str(row["document_type_id"]),
            document_type=DocumentTypeResponse(
                id=str(row["document_type_id"]),
                workspace_id=str(row["dt_workspace_id"]),
                slug=row["dt_slug"],
                name=row["dt_name"],
                description=row.get("dt_description"),
                category=row["dt_category"],
                requires_front_back=row["dt_requires_front_back"],
                is_verifiable=row["dt_is_verifiable"],
                icon=row.get("dt_icon"),
                is_default=row["dt_is_default"],
                is_active=row["dt_is_active"],
                sort_order=row["dt_sort_order"],
                created_at=row["dt_created_at"],
                updated_at=row["dt_updated_at"],
            ),
            position=row["position"],
            is_required=row["is_required"],
            notes=row.get("notes"),
        )

    @staticmethod
    def _compute_progress(row) -> str:
        """Derive progress from message data (only meaningful when status=active)."""
        message_count = row.get("message_count", 0)
        user_message_count = row.get("user_message_count", 0)
        if message_count == 0:
            return "pending"
        if user_message_count > 0:
            return "in_progress"
        return "started"

    @staticmethod
    def _build_collection_response(row) -> DocumentCollectionResponse:
        return DocumentCollectionResponse(
            id=str(row["id"]),
            config_id=str(row["config_id"]),
            workspace_id=str(row["workspace_id"]),
            vacancy_id=str(row["vacancy_id"]) if row["vacancy_id"] else None,
            vacancy_title=row.get("vacancy_title"),
            application_id=str(row["application_id"]) if row["application_id"] else None,
            candidate_name=row["candidate_name"],
            candidate_phone=row.get("candidate_phone"),
            status=row["status"],
            progress=DocumentCollectionService._compute_progress(row),
            channel=row["channel"],
            retry_count=row["retry_count"],
            message_count=row["message_count"],
            documents_collected=row.get("documents_collected", 0),
            documents_total=row.get("documents_total", 0),
            started_at=row["started_at"],
            updated_at=row["updated_at"],
            completed_at=row.get("completed_at"),
        )

    @staticmethod
    def _build_collection_detail_response(row, msg_rows, upload_rows, doc_types=None) -> DocumentCollectionDetailResponse:
        messages = [
            CollectionMessageResponse(
                role=m["role"],
                message=m["message"],
                created_at=m["created_at"],
            )
            for m in msg_rows
        ]
        uploads = [
            CollectionUploadResponse(
                id=str(u["id"]),
                document_type_id=str(u["document_type_id"]) if u["document_type_id"] else None,
                document_side=u["document_side"],
                verification_passed=u.get("verification_passed"),
                status=u["status"],
                uploaded_at=u["uploaded_at"],
            )
            for u in upload_rows
        ]
        return DocumentCollectionDetailResponse(
            id=str(row["id"]),
            config_id=str(row["config_id"]),
            workspace_id=str(row["workspace_id"]),
            vacancy_id=str(row["vacancy_id"]) if row["vacancy_id"] else None,
            vacancy_title=row.get("vacancy_title"),
            application_id=str(row["application_id"]) if row["application_id"] else None,
            candidate_name=row["candidate_name"],
            candidate_phone=row.get("candidate_phone"),
            status=row["status"],
            progress=DocumentCollectionService._compute_progress(row),
            channel=row["channel"],
            retry_count=row["retry_count"],
            message_count=row["message_count"],
            documents_collected=row.get("documents_collected", 0),
            documents_total=row.get("documents_total", 0),
            started_at=row["started_at"],
            updated_at=row["updated_at"],
            completed_at=row.get("completed_at"),
            messages=messages,
            uploads=uploads,
            documents_required=doc_types or [],
        )
