"""CollabML's dependency-light Python client for notebook experiments."""

from .client import Client, CollabMLError, Run

__all__ = ["Client", "CollabMLError", "Run", "configure", "create_project", "start", "fork"]
__version__ = "0.1.0"

_default_client: Client | None = None


def configure(api_url: str, token: str) -> Client:
    """Configure the process-wide client used by module-level helpers."""
    global _default_client
    _default_client = Client(api_url=api_url, token=token)
    return _default_client


def _client() -> Client:
    global _default_client
    if _default_client is None:
        _default_client = Client.from_environment()
    return _default_client


def create_project(*args, **kwargs):
    return _client().create_project(*args, **kwargs)


def start(*args, **kwargs) -> Run:
    return _client().start(*args, **kwargs)


def fork(*args, **kwargs) -> Run:
    return _client().fork(*args, **kwargs)

