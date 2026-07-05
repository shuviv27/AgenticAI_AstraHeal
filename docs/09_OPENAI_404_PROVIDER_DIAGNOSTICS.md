# OpenAI Provider 404 Diagnostics

If AstraHeal AI shows:

```text
openai is configured, but backend live validation failed: HTTPError: HTTP Error 404: Not Found
```

then provider routing is working and AstraHeal is checking OpenAI, not Codex. A 404 normally means the configured OpenAI base URL, endpoint style, Azure/public OpenAI style, or model name is wrong.

## Correct public OpenAI settings

```env
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4.1-mini
OPENAI_API_KEY=<your key>
```

Do not use these as the base URL:

```text
https://api.openai.com
https://api.openai.com/v1/chat/completions
https://api.openai.com/v1/responses
https://api.openai.com/v1/models
https://<resource>.openai.azure.com/...
```

The public OpenAI provider expects the API base URL only. AstraHeal appends `/models` and `/chat/completions` internally.

## VM diagnostics

From VM177:

```powershell
Test-NetConnection api.openai.com -Port 443
curl.exe -v https://api.openai.com/v1/models -H "Authorization: Bearer %OPENAI_API_KEY%"
```

PowerShell syntax using environment variable:

```powershell
$headers = @{ Authorization = "Bearer $env:OPENAI_API_KEY" }
Invoke-RestMethod -Uri "https://api.openai.com/v1/models" -Headers $headers -Method Get
```

## Azure OpenAI note

Azure OpenAI uses deployment-specific URLs and API versions. Do not configure an Azure deployment URL inside the public OpenAI provider field. Use public OpenAI settings, or add/use a dedicated Azure OpenAI provider mode.

## What changed in this build

AstraHeal now:

1. Normalizes accidental endpoint URLs back to the base URL where safe.
2. Adds `/v1` automatically if the user enters `https://api.openai.com`.
3. Detects Azure OpenAI endpoints and gives a clear message.
4. Validates `/models` first to separate base URL/API-key problems from model problems.
5. Shows clearer messages for 401, 403 and 404.
