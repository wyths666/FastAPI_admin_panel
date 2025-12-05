from .user.commands import router as commands
from .admin.reg import router as reg

routers = [
    reg,
    commands
]
