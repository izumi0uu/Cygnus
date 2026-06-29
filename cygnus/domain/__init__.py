"""Support-domain contracts and object vocabulary for Cygnus.

Ownership:
- answer/policy/troubleshooting/escalation object language lives here
- this package defines support-domain truth, not runtime wiring
"""

from cygnus.domain.audience import AudienceContext, AudienceFilter, Visibility
from cygnus.domain.lifecycle import LifecycleState
from cygnus.domain.objects import (
    AnswerCard,
    AudienceVariant,
    EscalationRoute,
    KnowledgeObject,
    KnownIssuePage,
    KnowledgeObjectType,
    PolicyRule,
    TroubleshootingFlow,
)

__all__ = [
    "AnswerCard",
    "AudienceContext",
    "AudienceFilter",
    "AudienceVariant",
    "EscalationRoute",
    "KnowledgeObject",
    "KnowledgeObjectType",
    "KnownIssuePage",
    "LifecycleState",
    "PolicyRule",
    "TroubleshootingFlow",
    "Visibility",
]
