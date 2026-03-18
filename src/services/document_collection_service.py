"""
Document collection service - business logic for document collection.
"""
import json
import logging
from typing import Optional
from uuid import UUID

import asyncpg


# ─── Plan enrichment ─────────────────────────────────────────────────────────

async def enrich_plan_documents(pool: asyncpg.Pool, workspace_id: UUID, documents: list[dict]) -> list[dict]:
    """Enrich plan documents with metadata from ontology.types_documents.

    Stored collection plans may be missing scan_mode, verification_config, etc.
    This patches them in from the document types table so the collection agent
    has the full metadata it needs.
    """
    if not documents:
        return documents

    slugs = [d["slug"] for d in documents]
    rows = await pool.fetch(
        """SELECT slug, scan_mode, is_verifiable, verification_config, ai_hint, category
           FROM ontology.types_documents
           WHERE workspace_id = $1 AND slug = ANY($2)""",
        workspace_id, slugs
    )
    type_map = {r["slug"]: r for r in rows}

    for doc in documents:
        dt = type_map.get(doc["slug"])
        if dt:
            doc.setdefault("scan_mode", dt["scan_mode"] or "single")
            doc.setdefault("is_verifiable", dt["is_verifiable"])
            if dt["verification_config"]:
                vc = dt["verification_config"] if isinstance(dt["verification_config"], dict) else json.loads(dt["verification_config"])
                doc.setdefault("verification_config", vc)
            doc.setdefault("ai_hint", dt["ai_hint"])
            doc.setdefault("category", dt["category"])
        else:
            doc.setdefault("scan_mode", "single")

    return documents

from src.auth.exceptions import WorkspaceAccessDenied, InsufficientRoleError
from src.exceptions import NotFoundError, ValidationError
from src.repositories.document_type_repo import DocumentTypeRepository
from src.repositories.document_collection_repo import DocumentCollectionRepository
from src.repositories.membership_repo import WorkspaceMembershipRepository
from src.models.document_collection_v2 import (
    DocumentTypeResponse,
    ResolveDocumentsResponse,
    StartCollectionResponse,
    DocumentCollectionResponse,
    DocumentCollectionDetailResponse,
    DocumentCollectionFullDetailResponse,
    CollectionMessageResponse,
    CollectionUploadResponse,
    CollectionItemStatusResponse,
    WorkflowStepResponse,
)

logger = logging.getLogger(__name__)


class DocumentCollectionService:
    """Service for document collection operations."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.doc_type_repo = DocumentTypeRepository(pool)
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
    # Document Resolution
    # =========================================================================

    async def resolve_documents(
        self, workspace_id: UUID, user_id: UUID,
        vacancy_id: Optional[UUID] = None,
    ) -> ResolveDocumentsResponse:
        """Resolve which documents are needed — uses workspace default document types."""
        await self._check_read_access(workspace_id, user_id)
        default_rows = await self.doc_type_repo.get_defaults(workspace_id)
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

    async def get_collection_full_detail(
        self, workspace_id: UUID, user_id: UUID, collection_id: UUID
    ) -> DocumentCollectionFullDetailResponse:
        """Get enriched collection detail with plan, document statuses, and workflow progress."""
        await self._check_read_access(workspace_id, user_id)

        collection = await self.collection_repo.get_by_id(collection_id)
        if not collection or collection["workspace_id"] != workspace_id:
            raise NotFoundError("Document collection", str(collection_id))

        messages = await self.collection_repo.get_messages(collection_id)
        uploads = await self.collection_repo.get_uploads(collection_id)

        # Resolve documents_required to full document types
        # documents_required can be either ["slug1", "slug2"] or [{"slug": "...", "name": "..."}]
        raw = collection.get("documents_required") or []
        doc_slugs_raw = json.loads(raw) if isinstance(raw, str) else raw
        doc_slugs = []
        for item in doc_slugs_raw:
            if isinstance(item, str):
                doc_slugs.append(item)
            elif isinstance(item, dict) and "slug" in item:
                doc_slugs.append(item["slug"])
        if doc_slugs:
            doc_type_rows = await self.doc_type_repo.get_by_slugs(workspace_id, doc_slugs)
            doc_types = [self._build_doc_type_response(r) for r in doc_type_rows]
        else:
            doc_types = []

        # Parse collection_plan JSONB
        plan = self._parse_collection_plan(collection.get("collection_plan"))

        # Build unified collection items (documents + attributes)
        agent_state = collection.get("agent_state")
        if agent_state and isinstance(agent_state, str):
            agent_state = json.loads(agent_state)
        collection_items = await self._build_collection_items(plan, uploads, agent_state, workspace_id)

        # Compute document counts from collection items (not legacy documents_required)
        doc_items = [item for item in collection_items if item.type == "document"]
        documents_total = len(doc_items)
        documents_collected = sum(1 for item in doc_items if item.status == "verified")

        # Extract plan summary fields for the header
        raw_plan = collection.get("collection_plan")
        plan_dict = json.loads(raw_plan) if isinstance(raw_plan, str) else raw_plan
        summary = plan_dict.get("summary") if isinstance(plan_dict, dict) else None
        deadline_note = plan_dict.get("deadline_note") if isinstance(plan_dict, dict) else None

        # Build conversation step progress from plan + agent state
        conversation_steps = self._build_conversation_steps(plan, agent_state)

        # Look up workflow progress
        workflow_steps = await self._get_workflow_steps(str(collection_id))

        return DocumentCollectionFullDetailResponse(
            id=str(collection["id"]),
            config_id=str(collection["config_id"]) if collection["config_id"] else "",
            workspace_id=str(collection["workspace_id"]),
            vacancy_id=str(collection["vacancy_id"]) if collection["vacancy_id"] else None,
            vacancy_title=collection.get("vacancy_title"),
            application_id=str(collection["application_id"]) if collection.get("application_id") else None,
            candidacy_stage=collection.get("candidacy_stage"),
            goal=collection.get("goal", "collect_basic"),
            candidate_name=collection["candidate_name"],
            candidate_phone=collection.get("candidate_phone"),
            status=collection["status"],
            progress=self._compute_progress(collection),
            channel=collection["channel"],
            retry_count=collection["retry_count"],
            message_count=collection["message_count"],
            documents_collected=documents_collected,
            documents_total=documents_total,
            started_at=collection["started_at"],
            updated_at=collection["updated_at"],
            completed_at=collection.get("completed_at"),
            messages=[
                CollectionMessageResponse(role=m["role"], message=m["message"], created_at=m["created_at"])
                for m in messages
            ],
            uploads=[
                CollectionUploadResponse(
                    id=str(u["id"]),
                    document_type_id=str(u["document_type_id"]) if u["document_type_id"] else None,
                    document_side=u["document_side"],
                    verification_passed=u.get("verification_passed"),
                    status=u["status"],
                    uploaded_at=u["uploaded_at"],
                )
                for u in uploads
            ],
            documents_required=doc_types,
            summary=summary,
            deadline_note=deadline_note,
            collection_items=collection_items,
            conversation_steps=conversation_steps,
            candidacy_id=str(collection["candidacy_id"]) if collection.get("candidacy_id") else None,
            candidate_id=str(collection["candidate_id"]) if collection.get("candidate_id") else None,
            workflow_steps=workflow_steps,
        )

    @staticmethod
    def _parse_collection_plan(raw_plan) -> Optional[dict]:
        """Parse collection_plan JSONB into a dict."""
        if not raw_plan:
            return None
        plan = json.loads(raw_plan) if isinstance(raw_plan, str) else raw_plan
        if not isinstance(plan, dict):
            return None
        return plan

    async def _build_collection_items(
        self,
        plan: Optional[dict],
        upload_rows: list,
        agent_state: Optional[dict],
        workspace_id: UUID,
    ) -> list[CollectionItemStatusResponse]:
        """Build unified checklist from conversation_flow + agent state."""
        if not plan:
            return []

        conversation_flow = plan.get("conversation_flow", [])
        if not conversation_flow:
            return []

        # Collect all slugs that need display names
        all_slugs = set()
        for step in conversation_flow:
            for item in step.get("items", []):
                all_slugs.add(item.get("slug", ""))
        # Include attributes_from_documents slugs (extracted from ID)
        attrs_from_docs = plan.get("attributes_from_documents", [])
        for afd in attrs_from_docs:
            all_slugs.add(afd.get("slug", ""))
        # Include address-related slugs
        all_slugs.update({"domicile_address", "verblijfs_adres", "adres_gelijk_aan_domicilie"})

        name_map = await self._load_type_names(workspace_id, all_slugs)

        # Extract status from agent state
        collected_documents: dict = {}
        collected_attributes: dict = {}
        completed_steps: list = []
        skipped_items: list = []
        consent_given = False
        identity_phase = "ask_id"
        if agent_state and isinstance(agent_state, dict):
            collected_documents = agent_state.get("collected_documents", {})
            collected_attributes = agent_state.get("collected_attributes", {})
            completed_steps = agent_state.get("completed_steps", [])
            skipped_items = agent_state.get("skipped_items", [])
            consent_given = agent_state.get("consent_given", False)
            identity_phase = agent_state.get("identity_phase", "ask_id")

        skipped_slugs = {s.get("slug", "") for s in skipped_items}

        IDENTITY_SLUGS = {"id_card", "passport", "prato_5", "prato_9", "prato_20", "prato_101", "prato_102"}

        TASK_LABELS = {
            "contract_signing": "Contract ondertekening",
            "medical_screening": "Medisch onderzoek inplannen",
        }

        items = []

        for step in conversation_flow:
            step_type = step.get("type", "")
            step_completed = step_type in completed_steps

            if step_type == "greeting_and_consent":
                items.append(CollectionItemStatusResponse(
                    slug="greeting_and_consent",
                    name="Consent gegevensverwerking",
                    type="attribute",
                    priority="required",
                    status="verified" if consent_given or step_completed else "pending",
                ))

            elif step_type == "identity_verification":
                id_done = identity_phase == "done" or step_completed
                items.append(CollectionItemStatusResponse(
                    slug="identity_verification",
                    name="Identiteitsdocument",
                    type="document",
                    priority="required",
                    status="verified" if id_done else "pending",
                    group="identity",
                ))
                # Work eligibility — rendered as indented sub-item by frontend
                work_elig = agent_state.get("work_eligibility") if agent_state else None
                items.append(CollectionItemStatusResponse(
                    slug="prato_5",
                    name=name_map.get("work_eligibility", "Arbeidstoegang"),
                    type="document",
                    priority="required",
                    status="verified" if work_elig is True else "pending",
                    group="identity",
                ))
                # Attributes extracted from identity document
                for afd in attrs_from_docs:
                    afd_slug = afd.get("slug", "")
                    afd_info = collected_attributes.get(afd_slug)
                    items.append(CollectionItemStatusResponse(
                        slug=afd_slug,
                        name=name_map.get(afd_slug, afd_slug),
                        type="attribute",
                        priority="required",
                        status="verified" if afd_info else "pending",
                        value=self._format_attr_value(afd_info),
                    ))

            elif step_type == "address_collection":
                # Domicilie adres
                dom_collected = "domicile_address" in collected_attributes
                items.append(CollectionItemStatusResponse(
                    slug="domicile_address",
                    name=name_map.get("domicile_address", "Domicilie adres"),
                    type="attribute",
                    priority="required",
                    status="verified" if dom_collected else "pending",
                    value=self._format_attr_value(collected_attributes.get("domicile_address")),
                ))
                # Verblijfsadres gelijk aan domicilie
                same_flag = collected_attributes.get("adres_gelijk_aan_domicilie")
                items.append(CollectionItemStatusResponse(
                    slug="adres_gelijk_aan_domicilie",
                    name=name_map.get("adres_gelijk_aan_domicilie", "Verblijfsadres gelijk aan domicilie"),
                    type="attribute",
                    priority="required",
                    status="verified" if same_flag else "pending",
                    value=self._format_attr_value(same_flag),
                ))
                # Verblijfsadres
                verb_collected = "verblijfs_adres" in collected_attributes
                items.append(CollectionItemStatusResponse(
                    slug="verblijfs_adres",
                    name=name_map.get("verblijfs_adres", "Verblijfsadres"),
                    type="attribute",
                    priority="required",
                    status="verified" if verb_collected or (same_flag and same_flag.get("value")) else "pending",
                    value=self._format_attr_value(collected_attributes.get("verblijfs_adres")),
                ))

            elif step_type == "collect_documents":
                for item in step.get("items", []):
                    slug = item.get("slug", "")
                    doc_info = collected_documents.get(slug)
                    if doc_info and doc_info.get("status") == "verified":
                        status = "verified"
                    elif slug in skipped_slugs:
                        status = "skipped"
                    else:
                        status = "pending"

                    items.append(CollectionItemStatusResponse(
                        slug=slug,
                        name=name_map.get(slug, slug),
                        type="document",
                        priority=item.get("priority", "required"),
                        status=status,
                        group="identity" if slug in IDENTITY_SLUGS else None,
                    ))

            elif step_type == "collect_attributes":
                for item in step.get("items", []):
                    slug = item.get("slug", "")
                    attr_info = collected_attributes.get(slug)
                    if attr_info:
                        status = "verified"
                    elif slug in skipped_slugs:
                        status = "skipped"
                    else:
                        status = "pending"

                    items.append(CollectionItemStatusResponse(
                        slug=slug,
                        name=name_map.get(slug, slug),
                        type="attribute",
                        priority=item.get("priority", "required"),
                        status=status,
                        value=self._format_attr_value(attr_info),
                    ))

            elif step_type in ("medical_screening", "contract_signing"):
                items.append(CollectionItemStatusResponse(
                    slug=step_type,
                    name=TASK_LABELS.get(step_type, step.get("description", step_type)),
                    type="task",
                    priority="required",
                    status="verified" if step_completed else "pending",
                ))

        return items

    async def _load_type_names(self, workspace_id: UUID, slugs: set[str]) -> dict[str, str]:
        """Look up display names for document and attribute type slugs."""
        if not slugs:
            return {}

        slug_list = list(slugs)
        rows = await self.pool.fetch(
            """SELECT slug, name FROM ontology.types_documents
               WHERE workspace_id = $1 AND slug = ANY($2)
               UNION ALL
               SELECT slug, name FROM ontology.types_attributes
               WHERE workspace_id = $1 AND slug = ANY($2)""",
            workspace_id, slug_list
        )
        return {r["slug"]: r["name"] for r in rows}

    @staticmethod
    def _format_attr_value(attr_info: Optional[dict]):
        """Extract attribute value for display. Returns dict for structured, str for simple."""
        if not attr_info or not isinstance(attr_info, dict):
            return None
        value = attr_info.get("value")
        if value is None:
            return None
        return value

    @staticmethod
    def _build_conversation_steps(plan: Optional[dict], agent_state: Optional[dict]) -> list[dict]:
        """Build conversation step progress from plan + agent state."""
        if not plan:
            return []

        conversation_flow = plan.get("conversation_flow", [])
        if not conversation_flow:
            return []

        completed_steps = []
        current_step_index = 0
        if agent_state and isinstance(agent_state, dict):
            completed_steps = agent_state.get("completed_steps", [])
            current_step_index = agent_state.get("current_step_index", 0)

        steps = []
        for i, step in enumerate(conversation_flow):
            step_type = step.get("type", "")
            steps.append({
                "step": step.get("step", i + 1),
                "type": step_type,
                "description": step.get("description", ""),
                "completed": step_type in completed_steps,
                "current": i == current_step_index,
            })
        return steps

    async def _get_workflow_steps(self, collection_id: str) -> list[WorkflowStepResponse]:
        """Look up workflow progress for a document collection."""
        # Document collection workflow step sequence
        step_sequence = [
            ("generating_plan", "Plan genereren"),
            ("plan_generated", "Plan opgesteld"),
            ("collecting", "Documenten & contract (optioneel)"),
            ("complete", "Afgerond"),
        ]

        # Find workflow by context.collection_id
        row = await self.pool.fetchrow(
            """
            SELECT current_step, status FROM agents.workflows
            WHERE workflow_type = 'document_collection'
              AND context->>'collection_id' = $1
            ORDER BY created_at DESC LIMIT 1
            """,
            collection_id,
        )

        current_step = row["current_step"] if row else None
        workflow_status = row["status"] if row else None

        steps = []
        found_current = False
        for step_id, label in step_sequence:
            if step_id == current_step:
                found_current = True
                status = "current"
            elif not found_current:
                status = "completed"
            else:
                status = "pending"

            # If workflow is completed, all steps are completed
            if workflow_status == "completed":
                status = "completed"

            steps.append(WorkflowStepResponse(id=step_id, label=label, status=status))

        return steps

    async def abandon_collection(
        self, workspace_id: UUID, user_id: UUID, collection_id: UUID
    ) -> None:
        """Mark a document collection as abandoned."""
        await self._check_write_access(workspace_id, user_id)

        collection = await self.collection_repo.get_by_id(collection_id)
        if not collection or collection["workspace_id"] != workspace_id:
            raise NotFoundError("Document collection", str(collection_id))

        await self.collection_repo.update_status(collection_id, "abandoned")

    async def trigger_task_now(
        self, workspace_id: UUID, user_id: UUID, collection_id: UUID, task_slug: str
    ) -> None:
        """
        Trigger a scheduled task immediately.

        Updates the agent_state to clear scheduled_at and set status to 'triggered',
        signalling the agent to execute the task on next run.
        """
        await self._check_write_access(workspace_id, user_id)

        collection = await self.collection_repo.get_by_id(collection_id)
        if not collection or collection["workspace_id"] != workspace_id:
            raise NotFoundError("Document collection", str(collection_id))

        agent_state = collection.get("agent_state") or {}
        if isinstance(agent_state, str):
            agent_state = json.loads(agent_state)

        item_statuses = agent_state.get("item_statuses", {})
        task_status = item_statuses.get(task_slug, {})

        if isinstance(task_status, str):
            task_status = {"status": task_status}

        task_status["status"] = "triggered"
        task_status.pop("scheduled_at", None)

        item_statuses[task_slug] = task_status
        agent_state["item_statuses"] = item_statuses

        await self.pool.execute(
            "UPDATE agents.document_collections SET agent_state = $1, updated_at = now() WHERE id = $2",
            json.dumps(agent_state) if isinstance(agent_state, dict) else agent_state,
            collection_id,
        )

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

        full_name = f"{candidate_name} {candidate_lastname}"
        normalized_phone = whatsapp_number.lstrip("+")

        # Abandon previous active collections for this phone
        await self.collection_repo.abandon_active_for_phone(normalized_phone)

        # Create document collection
        doc_slugs = [d.slug for d in resolved.documents]
        collection = await self.collection_repo.create(
            config_id=None,
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
            config_id="",
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
            config_id=str(row["config_id"]) if row.get("config_id") else "",
            workspace_id=str(row["workspace_id"]),
            vacancy_id=str(row["vacancy_id"]) if row["vacancy_id"] else None,
            vacancy_title=row.get("vacancy_title"),
            application_id=str(row["application_id"]) if row["application_id"] else None,
            candidacy_stage=row.get("candidacy_stage"),
            goal=row.get("goal", "collect_basic"),
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
            config_id=str(row["config_id"]) if row.get("config_id") else "",
            workspace_id=str(row["workspace_id"]),
            vacancy_id=str(row["vacancy_id"]) if row["vacancy_id"] else None,
            vacancy_title=row.get("vacancy_title"),
            application_id=str(row["application_id"]) if row["application_id"] else None,
            candidacy_stage=row.get("candidacy_stage"),
            goal=row.get("goal", "collect_basic"),
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
