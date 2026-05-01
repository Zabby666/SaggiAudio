
import os
import json
import tempfile
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from openai import OpenAI

app = FastAPI(title="Telegram Voice Summary Bot")


def get_env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def require_env() -> None:
    missing = [
        name for name in [
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_WEBHOOK_SECRET",
            "OPENAI_API_KEY",
        ]
        if not get_env(name)
    ]
    if missing:
        raise RuntimeError(f"Missing env vars: {', '.join(missing)}")


def telegram_api_base() -> str:
    return f"https://api.telegram.org/bot{get_env('TELEGRAM_BOT_TOKEN')}"


def telegram_file_api_base() -> str:
    return f"https://api.telegram.org/file/bot{get_env('TELEGRAM_BOT_TOKEN')}"


def openai_client() -> OpenAI:
    return OpenAI(api_key=get_env("OPENAI_API_KEY"))


def max_file_mb() -> int:
    return int(get_env("MAX_FILE_MB", "20"))


def openai_transcribe_model() -> str:
    return get_env("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")


def openai_summary_model() -> str:
    return get_env("OPENAI_SUMMARY_MODEL", "gpt-4o-mini")


def is_group_chat(message: dict) -> bool:
    chat_type = message.get("chat", {}).get("type")
    return chat_type in {"group", "supergroup"}


async def tg_api(method: str, payload: Optional[dict] = None) -> dict:
    async with httpx.AsyncClient(timeout=60) as http:
        r = await http.post(f"{telegram_api_base()}/{method}", json=payload or {})
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error on {method}: {data}")
        return data["result"]


async def send_message(chat_id: int, text: str, reply_to_message_id: Optional[int] = None) -> None:
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if reply_to_message_id:
        payload["reply_parameters"] = {"message_id": reply_to_message_id}
    await tg_api("sendMessage", payload)


async def get_file_url(file_id: str) -> str:
    result = await tg_api("getFile", {"file_id": file_id})
    file_path = result["file_path"]
    return f"{telegram_file_api_base()}/{file_path}"


async def download_file(url: str) -> Path:
    async with httpx.AsyncClient(timeout=120) as http:
        r = await http.get(url)
        r.raise_for_status()
        suffix = Path(url).suffix or ".ogg"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(r.content)
        tmp.close()
        return Path(tmp.name)


def transcribe_audio(file_path: Path) -> str:
    client = openai_client()
    with file_path.open("rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            model=openai_transcribe_model(),
            file=audio_file,
        )
    text = getattr(transcript, "text", None)
    if not text:
        raise RuntimeError("Transcript text missing")
    return text.strip()


def summarize_transcript(transcript: str) -> dict:
    client = openai_client()
    prompt = f"""
Analizza questa trascrizione di un messaggio audio Telegram e restituisci SOLO JSON valido con questo schema:
{{
  "summary": "riassunto breve in italiano",
  "key_points": ["punto 1", "punto 2"],
  "actions": ["azione 1", "azione 2"],
  "entities": ["persona/data/importo/luogo 1", "..."]
}}
Regole:
- massimo 5 key_points
- massimo 5 actions
- massimo 6 entities
- se non ci sono actions o entities usa array vuoti
- non aggiungere markdown o testo extra

Trascrizione:
{transcript}
""".strip()

    response = client.responses.create(
        model=openai_summary_model(),
        input=prompt,
    )
    raw = response.output_text.strip()
    return json.loads(raw)


def format_reply(data: dict, transcript: str) -> str:
    key_points = data.get("key_points", [])

    lines = ["Trascrizione", transcript.strip() or "Trascrizione non disponibile."]

    if key_points:
        lines.extend(["", "Cose importanti"])
        lines.extend([f"- {point}" for point in key_points])

    return "\n".join(lines)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/debug-env")
async def debug_env():
    return {
        "TELEGRAM_BOT_TOKEN": bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip()),
        "TELEGRAM_WEBHOOK_SECRET": bool(os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()),
        "OPENAI_API_KEY": bool(os.getenv("OPENAI_API_KEY", "").strip()),
        "RAILWAY_ENVIRONMENT_NAME": os.getenv("RAILWAY_ENVIRONMENT_NAME", ""),
        "RAILWAY_SERVICE_NAME": os.getenv("RAILWAY_SERVICE_NAME", ""),
    }


@app.post("/webhook")
async def webhook(request: Request, x_telegram_bot_api_secret_token: Optional[str] = Header(default=None)):
    require_env()
    if x_telegram_bot_api_secret_token != get_env("TELEGRAM_WEBHOOK_SECRET"):
        raise HTTPException(status_code=403, detail="Invalid secret")

    update = await request.json()
    message = update.get("message") or update.get("edited_message")
    if not message:
        return JSONResponse({"ok": True})

    command_message_id = message.get("message_id")
    chat_id = message["chat"]["id"]
    text = (message.get("text") or "").strip()

    if is_group_chat(message):
        normalized_command = text.split()[0].split("@")[0].lower() if text else ""

        if normalized_command != "/riassumi":
            return JSONResponse({"ok": True})

        replied = message.get("reply_to_message") or {}
        if not replied:
            await send_message(
                chat_id,
                "Rispondi con /riassumi a un messaggio o a un vocale del gruppo.",
                command_message_id,
            )
            return JSONResponse({"ok": True})

        target_message = replied
    else:
        if text:
            normalized_command = text.split()[0].split("@")[0].lower()

            if normalized_command == "/start":
                await send_message(
                    chat_id,
                    "Mandami un messaggio vocale o inoltrami un audio da Telegram e ti restituisco trascrizione e cose importanti. Nei gruppi, usa /riassumi in risposta a un messaggio o a un vocale.",
                    command_message_id,
                )
                return JSONResponse({"ok": True})

            if normalized_command == "/help":
                await send_message(
                    chat_id,
                    "Comandi disponibili:\n/start\n/help\n\nIn chat privata: inviami un vocale o un file audio.\nNel gruppo: rispondi con /riassumi a un messaggio o a un vocale.",
                    command_message_id,
                )
                return JSONResponse({"ok": True})

        target_message = message

    voice = target_message.get("voice")
    audio = target_message.get("audio")
    document = target_message.get("document")
    media = voice or audio or document

    if not media:
        target_text = (target_message.get("text") or "").strip()
        if target_text:
            await send_message(chat_id, "Sto leggendo il messaggio e preparo il riassunto...", command_message_id)

            try:
                structured = summarize_transcript(target_text)
                reply = format_reply(structured, target_text)
                await send_message(chat_id, reply, command_message_id)
            except Exception as exc:
                await send_message(chat_id, f"Errore durante l'elaborazione: {str(exc)[:300]}", command_message_id)

            return JSONResponse({"ok": True})

        await send_message(
            chat_id,
            "Rispondi con /riassumi a un messaggio di testo, a un vocale o a un file audio.",
            command_message_id,
        )
        return JSONResponse({"ok": True})

    file_size = media.get("file_size", 0)
    if file_size > max_file_mb() * 1024 * 1024:
        await send_message(chat_id, f"File troppo grande. Limite attuale: {max_file_mb()} MB.", command_message_id)
        return JSONResponse({"ok": True})

    await send_message(chat_id, "Sto ascoltando il messaggio e preparo il riassunto...", command_message_id)

    temp_file: Optional[Path] = None
    try:
        file_id = media["file_id"]
        url = await get_file_url(file_id)
        temp_file = await download_file(url)
        transcript = transcribe_audio(temp_file)
        structured = summarize_transcript(transcript)
        reply = format_reply(structured, transcript)
        await send_message(chat_id, reply, command_message_id)
    except Exception as exc:
        await send_message(chat_id, f"Errore durante l'elaborazione: {str(exc)[:300]}", command_message_id)
    finally:
        if temp_file and temp_file.exists():
            temp_file.unlink(missing_ok=True)

    return JSONResponse({"ok": True})
