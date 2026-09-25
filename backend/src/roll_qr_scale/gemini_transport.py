"""Gemini HTTP transport compatibility helpers."""


def prefer_httpx_transport() -> None:
    """Prevent Gemini from selecting a partial or incompatible aiohttp module.

    google-genai detects aiohttp by importing the package, but some packaged
    environments can contain an incomplete aiohttp module without
    ``ClientSession``. Selecting HTTPX explicitly avoids that path without
    storing an SSLContext-bearing transport object in HttpOptions.
    """
    try:
        from google.genai import _api_client
    except ImportError:
        return
    _api_client.has_aiohttp = False
