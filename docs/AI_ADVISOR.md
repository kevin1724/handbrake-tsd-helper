# Size Wizard AI Advisor

The AI Advisor is an optional explanation layer for Size Wizard. It can explain why a plan was chosen and translate plain-language goals into safe wizard-option suggestions. The deterministic Size Wizard still calculates, validates, previews, and queues the final HandBrake plan.

You can use:

- Google Gemini Flash
- OpenAI
- The bundled local advisor, when the image includes a usable local model
- Planner-only mode, with no language model

Video, audio, subtitle content, and API keys are never included in an AI prompt.

## Fastest setup: web interface

Open **Settings > AI & API Keys**, or go directly to:

```text
http://YOUR-TSD-SERVER:5000/settings/ai
```

Then:

1. Select Gemini or OpenAI.
2. Create an API key using the official link shown beside that provider.
3. Paste the key into the clearly labeled API-key box.
4. Keep the recommended model, or enter another supported model ID.
5. Click **Save & test selected provider**.
6. Wait for the success message, then click **Open Size Wizard**.

The API-key input becomes blank after saving on purpose. The green status pill says whether the key is stored and whether it came from Settings or an environment variable.

## Google Gemini setup

1. Open [Google AI Studio API keys](https://aistudio.google.com/app/apikey).
2. Sign in and create or copy an API key.
3. In TSD, select **Google Gemini Flash**.
4. Paste the key into **Gemini API key**.
5. Use `gemini-3.6-flash`, the current recommended default, unless your Google account requires a different supported model.
6. Click **Save & test selected provider**.

Google documents API-key creation, restrictions, and server-side handling in its [Gemini API key guide](https://ai.google.dev/gemini-api/docs/api-key). Free-tier availability and quotas vary by model, account, and region; check the current [Gemini pricing and limits](https://ai.google.dev/gemini-api/docs/pricing).

## OpenAI setup

1. Open [OpenAI API keys](https://platform.openai.com/api-keys).
2. Create a new secret key and copy it. The full key is normally shown only once.
3. In TSD, select **OpenAI**.
4. Paste the key into **OpenAI API key**.
5. Keep `gpt-5.6-luna` for a cost-sensitive advisor, or choose another model supported by the Responses API.
6. Click **Save & test selected provider**.

See the official [OpenAI API quickstart](https://platform.openai.com/docs/quickstart) and [model catalog](https://developers.openai.com/api/docs/models). OpenAI API usage is separate from a ChatGPT subscription and may require API billing or credits.

## Docker Compose environment variables

The web form is the easiest option. For deployment-managed secrets, set one provider key as an environment variable. Environment variables override keys saved through Settings.

```yaml
services:
  handbrake-tsd-helper:
    image: kevina1724/handbrake-tsd-helper:latest
    environment:
      GEMINI_API_KEY: ${GEMINI_API_KEY}
      # Or use OpenAI instead:
      # OPENAI_API_KEY: ${OPENAI_API_KEY}
```

Create a `.env` file beside `compose.yaml`:

```dotenv
GEMINI_API_KEY=replace-with-your-real-gemini-key
# OPENAI_API_KEY=replace-with-your-real-openai-key
```

Do not commit `.env` or paste a real key into screenshots, issues, logs, or chat. Recreate the container after changing its environment:

```bash
docker compose up -d --force-recreate
```

Even when the key comes from an environment variable, open **Settings > AI & API Keys**, select the matching provider, and save the selection. The status pill will say `Key from environment`.

## Using the advisor in Size Wizard

1. Open a source from Jobs or Library, or select one in Size Wizard.
2. Choose your target size, quality goal, audio policy, and subtitle policy.
3. Wait for the plan to finish analyzing.
4. Use a suggested question or type your own in **Plan Assistant**.
5. Review any proposed changes and generate an accurate preview when visual quality matters.

Useful examples:

```text
Explain why this plan chose H.265.
```

```text
Prioritize quality but keep the result under 6 GB.
```

```text
Keep English and Spanish audio and subtitles.
```

```text
Keep surround sound; use E-AC3 5.1 only when passthrough is not possible.
```

```text
Keep the source at 4K and tell me how risky this target size is.
```

The advisor may suggest only supported Size Wizard fields. The normal planner recalculates the plan and remains authoritative.

## What is sent to a cloud provider

Only compact planning context is sent:

- Source filename, resolution, duration, size, HDR flag, and media type
- Selected goal, codec, encoder family, resolution, target size, audio mode, and subtitle mode
- A few planner decisions and warnings
- The question you type

The source filename is included to give the answer useful context. Media bytes, frames, audio samples, subtitle text, mapped-drive paths, raw HandBrake commands, and API keys are not put in the prompt. Requests are made from the TSD server, not from the browser or phone.

Keys saved through the UI are stored in the TSD data volume and masked in later API responses. Protect that volume and its backups like any other application secret. For stricter secret management, use Docker environment variables.

## Troubleshooting

### It says the provider needs setup

- Open **Settings > AI & API Keys**.
- Confirm the correct provider is selected.
- Paste the key, then click **Save & test selected provider**.
- If using Docker environment variables, recreate the container and look for `Key from environment`.

### The key box is empty after saving

That is expected. TSD never sends the saved secret back to the browser. Check the provider's status pill instead.

### HTTP 401 or invalid API key

Create a new key with the provider, paste it again, and save and test. Also check for an extra space or a revoked/restricted key.

### HTTP 429, quota, or billing error

The connection reached the provider, but that account has no available quota. Check the provider dashboard, model eligibility, current free-tier limits, or API billing.

### Model not found

Return to the recommended model shown in Settings, or copy a current compatible model ID from the provider's official model page. Model availability can differ by account and region.

### AI fails while building a plan

Encoding is not blocked. TSD falls back to its deterministic planner and marks the selected advisor as unavailable. Use **Save & test selected provider** to see the provider's direct error message.
