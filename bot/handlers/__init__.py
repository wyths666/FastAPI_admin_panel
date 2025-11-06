from .user.commands import router as commands
from .admin.commands import router as admin_commands
from .admin.chat_with_user import router as chat
from .admin.reg import router as reg
routers = [
    commands,
    admin_commands,
    reg,
    chat
]
