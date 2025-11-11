from .admin.commands import router as commands
from .user.user_messages import user_messages_router


routers = [commands, user_messages_router]