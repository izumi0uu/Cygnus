from fastapi import APIRouter

from cygnus.runtime.routers.governance.audience_bindings import (
    router as audience_bindings_router,
)
from cygnus.runtime.routers.governance.audit import router as governance_audit_router  # fmt: skip
from cygnus.runtime.routers.governance.command_center import router as command_center_router  # fmt: skip
from cygnus.runtime.routers.governance.knowledge_graph import router as knowledge_graph_router  # fmt: skip
from cygnus.runtime.routers.governance.publish import router as publish_router
from cygnus.runtime.routers.governance.recovery import router as recovery_router
from cygnus.runtime.routers.governance.review import router as review_router
from cygnus.runtime.routers.governance.session_bridge import router as session_bridge_router  # fmt: skip
from cygnus.runtime.routers.governance.signals import router as signals_router

router = APIRouter(tags=["governance"])
router.include_router(audience_bindings_router, tags=["governance"])
router.include_router(governance_audit_router, tags=["governance"])
router.include_router(command_center_router, tags=["governance"])
router.include_router(review_router, tags=["governance"])
router.include_router(signals_router, tags=["governance"])
router.include_router(publish_router, tags=["governance"])
router.include_router(recovery_router, tags=["governance"])
router.include_router(session_bridge_router, tags=["governance"])
router.include_router(knowledge_graph_router, tags=["governance"])
