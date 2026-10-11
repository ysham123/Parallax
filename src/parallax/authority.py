"""Authenticated relay context, bound by the worker's private ASGI bearer."""
from contextvars import ContextVar
from fastapi import HTTPException

current = ContextVar("parallax_authority", default=None)

def context():
    return current.get()

def actor():
    return (context() or {}).get("actor", "local")

def require_project(path):
    value = context()
    if value and value.get("team") and path not in value["projects"]:
        raise HTTPException(403, "Project permission is required")

def require_scope(value):
    saved = value.get("authority")
    caller = context()
    if saved and saved.get("team"):
        if not caller or caller.get("workspace") != saved["workspace"]:
            raise KeyError(value["id"])
    elif caller and caller.get("team"):
        raise KeyError(value["id"])

def require_role(*roles):
    value = context()
    if value and value.get("team") and value["role"] not in roles:
        raise HTTPException(403, "This workspace role cannot perform that action")
