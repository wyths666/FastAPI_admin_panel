from .user.commands import router as commands

from .admin.commands import router as admin_commands


routers = [
    commands,
    admin_commands
]
