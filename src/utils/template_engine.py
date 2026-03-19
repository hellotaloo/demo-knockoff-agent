"""
Template engine for integration field mapping.

Resolves N8N-style {{field_name}} placeholders against external system records.
Supports dot-path traversal for relationship fields (e.g. Owner.Email).
"""
import re

TEMPLATE_PATTERN = re.compile(r"\{\{([\w.]+)\}\}")


def resolve_template(template: str, record: dict) -> str | None:
    """Resolve {{field}} placeholders against a record dict.

    Returns None if the template is empty or all referenced fields are None.
    """
    if not template or not template.strip():
        return None

    resolved_any = False

    def _replace(match: re.Match) -> str:
        nonlocal resolved_any
        path = match.group(1)
        value = _resolve_dot_path(record, path)
        if value is not None:
            resolved_any = True
            return str(value)
        return ""

    result = TEMPLATE_PATTERN.sub(_replace, template)
    return result if resolved_any else None


def _resolve_dot_path(obj: dict, path: str):
    """Traverse nested dicts via dot notation (e.g. 'Owner.Email')."""
    parts = path.split(".")
    current = obj
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
        if current is None:
            return None
    return current


def extract_referenced_fields(template: str) -> list[str]:
    """Extract all {{field}} references from a template string."""
    return TEMPLATE_PATTERN.findall(template)


def resolve_mapping(mappings: dict, record: dict) -> dict:
    """Apply all field mappings to a record, returning Taloo field values.

    Args:
        mappings: dict of {taloo_field: {"template": "..."}}
        record: Salesforce record dict
    Returns:
        dict of {taloo_field: resolved_value}
    """
    result = {}
    for taloo_field, config in mappings.items():
        template = config.get("template", "")
        if template:
            result[taloo_field] = resolve_template(template, record)
    return result


def build_soql_fields(mappings: dict) -> list[str]:
    """Collect all unique Salesforce fields referenced across all mappings.

    Used to dynamically build SOQL SELECT clauses.
    """
    fields = set()
    for config in mappings.values():
        template = config.get("template", "")
        fields.update(extract_referenced_fields(template))
    return sorted(fields)
