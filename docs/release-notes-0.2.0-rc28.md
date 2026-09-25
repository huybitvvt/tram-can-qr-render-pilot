# Trạm Cân QR 0.2.0-rc28

- Fixed a startup failure when the bundled Gemini SDK detects an incomplete `aiohttp` module.
- Gemini clients now use HTTPX explicitly for async transport, avoiding the optional `aiohttp.ClientSession` path.
- Applied the HTTPX transport to Gemini key validation and normal reading, including transient-request retries.
