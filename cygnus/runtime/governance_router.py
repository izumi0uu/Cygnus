from fastapi import APIRouter

from cygnus.runtime.routers.governance.command_center import router as command_center_router
from cygnus.runtime.routers.governance.knowledge_graph import router as knowledge_graph_router
from cygnus.runtime.routers.governance.publish import router as publish_router
from cygnus.runtime.routers.governance.recovery import router as recovery_router
from cygnus.runtime.routers.governance.review import router as review_router

router = APIRouter(tags=["governance"])
router.include_router(command_center_router, tags=["governance"])
router.include_router(review_router, tags=["governance"])
router.include_router(publish_router, tags=["governance"])
router.include_router(recovery_router, tags=["governance"])
router.include_router(knowledge_graph_router, tags=["governance"])
