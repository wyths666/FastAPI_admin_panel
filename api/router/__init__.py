from .auth import router as auth_router
from .main import router as main_router
from .claims import router as bot2_claims_router
from .support import router as supports_router
__all__ = ["auth_router", "main_router", "bot2_claims_router", "supports_router"]