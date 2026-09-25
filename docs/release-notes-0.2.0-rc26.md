# Trạm Cân QR 0.2.0-rc26

- Gemini weight parsing now accepts a valid JSON object wrapped in Markdown or surrounding text.
- If Gemini returns malformed JSON, the app retries once with the same captured images. A second parse failure is treated as temporary so the API key is not quarantined for a bad model response.
- Captured images remain saved locally when AI weight recognition fails; operators can retry recognition or enter the displayed value manually.
