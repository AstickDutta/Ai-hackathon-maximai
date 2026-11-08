# Freshgate

Freshgate checks whether an LLM answer is still true. Prices, API versions, laws, and job titles change, and a gateway can keep serving the old sentence. Time-sensitive sentences are re-checked with Tavily against trusted sources, and each claim gets a freshness score. A gateway policy then decides whether to pass, warn, correct, or hold.

**Ask Bifrost** sends any question through the gateway, then scores that answer. You can type or hold the mic to speak. **Check an answer** scores text you paste. **Speak answer** turns the final answer into audio with OpenAI TTS. A score under `FRESHGATE_THRESHOLD` is flagged. Set `FRESHGATE_POLICY` to `warn`, `correct`, or `hold`.

The score follows the wording, not the model name. Change the model with `BIFROST_MODEL` in `.env` (`provider/model`, for example `gemini/gemini-3.1-flash-lite`) and restart the API.

## Why these technologies

| Technology | Why it is here |
| --- | --- |
| [Bifrost](https://github.com/maximhq/bifrost) | One OpenAI-compatible gateway in front of the model. It also lists the factual claims in the answer. Freshgate is the check Bifrost does not do on the way out: `X-Freshgate-Score` and `X-Freshgate-Flagged`. |
| Tavily | Live search for each claim. Reddit-style pages are filtered down; official and news domains are preferred. |
| Gemini | The chat model behind Bifrost. `gemini-3.1-flash-lite` is the default because it returns in about a second. |
| FastAPI | The API that proxies `/v1/chat` to Bifrost and exposes `/verify` for a pasted answer. |
| HTML, CSS, JavaScript | The demo page. No separate frontend build. |

## Run

You need Python 3.11+, Node.js, a Tavily API key, and a Gemini API key.

**Terminal 1, Bifrost.** Invent a setup token, start the gateway, then type that same token into the setup screen and create an admin account.

Git Bash:

```bash
export BIFROST_SETUP_TOKEN="your-setup-token"
npx -y @maximhq/bifrost
```

PowerShell:

```powershell
$env:BIFROST_SETUP_TOKEN = "your-setup-token"
npx -y @maximhq/bifrost
```

Open http://localhost:8080.

- Add the Gemini key under **Model Providers → Google Gemini**.
- Open http://localhost:8080/workspace/virtual-keys, create a key, and turn on **Allow all providers**.
- Leave **Enforce Virtual Keys on Inference** on. Copy the `sk-bf-...` key into `.env`.

**Terminal 2, this app.** From the repo root:

```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -r backend/requirements.txt
cp .env.example .env
```

On Windows Command Prompt, use `copy .env.example .env`. On macOS or Linux, activate with `source .venv/bin/activate`.

```env
TAVILY_API_KEY=tvly-your-key
BIFROST_URL=http://127.0.0.1:8080
BIFROST_MODEL=gemini/gemini-3.1-flash-lite
BIFROST_VK=sk-bf-your-virtual-key
FRESHGATE_THRESHOLD=60
FRESHGATE_POLICY=correct
OPENAI_STT_MODEL=openai/whisper-1
OPENAI_TTS_MODEL=openai/tts-1
OPENAI_TTS_VOICE=alloy
```

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

Open http://127.0.0.1:8000. Leave both terminals running. Do not commit `.env`.

```text
backend/app/routers/     /v1/chat, /verify, /api/transcribe, /api/speak, /api/health
backend/app/services/    Bifrost client and Tavily scoring
frontend/                Demo page
```
