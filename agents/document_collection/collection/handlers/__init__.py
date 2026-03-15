"""
Step handlers for the document collection agent.

Each handler module implements two functions:
- enter_<type>(agent, step) -> str  — generate the opening message for a step
- handle_<type>(agent, message, has_image, step) -> str  — process user message
"""

from agents.document_collection.collection.handlers.consent import enter_consent, handle_consent
from agents.document_collection.collection.handlers.identity import enter_identity, handle_identity
from agents.document_collection.collection.handlers.address import enter_address, handle_address
from agents.document_collection.collection.handlers.attributes import enter_attributes, handle_attributes
from agents.document_collection.collection.handlers.documents import enter_documents, handle_documents
from agents.document_collection.collection.handlers.tasks import enter_task, handle_task
from agents.document_collection.collection.handlers.closing import enter_closing, handle_closing

# Registry: step_type -> (enter_handler, message_handler)
STEP_HANDLERS: dict[str, tuple] = {
    "greeting_and_consent": (enter_consent, handle_consent),
    "identity_verification": (enter_identity, handle_identity),
    "address_collection": (enter_address, handle_address),
    "collect_attributes": (enter_attributes, handle_attributes),
    "collect_documents": (enter_documents, handle_documents),
    "medical_screening": (enter_task, handle_task),
    "contract_signing": (enter_task, handle_task),
    "closing": (enter_closing, handle_closing),
}
