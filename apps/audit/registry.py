"""
Registry of models that opt in to audit recording.

Maps a model class to its stable ``entity_type`` string -- the value stored
in ``audit_logs.entity_type`` -- plus the human ``label`` shown in the
Settings audit trail UI. Registration happens in ``audit.apps.AuditConfig.ready``
so every model is registered exactly once per process and startup ordering
never matters.
"""

AUDITABLE_MODELS = {}


def register(model, entity_type, label, category=None):
    """Opt ``model`` into audit recording under a stable ``entity_type``.

    ``category`` is an optional UI grouping hint (e.g. "Settings",
    "Documents", "Money") surfaced by the /api/audit/entities/ endpoint so the
    frontend can present an optgroup instead of one long flat list.
    """
    AUDITABLE_MODELS[model] = {
        'entity_type': entity_type,
        'label': label,
        'category': category,
    }


def entity_type_for(model):
    info = AUDITABLE_MODELS.get(model)
    return info['entity_type'] if info else None


def label_for(entity_type):
    for info in AUDITABLE_MODELS.values():
        if info['entity_type'] == entity_type:
            return info['label']
    return entity_type.replace('_', ' ').title()