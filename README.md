# Telegram Voice Summary Bot

Bot Telegram che riceve vocali o file audio, li scarica via Bot API, li trascrive e restituisce:
- riassunto breve
- punti importanti
- azioni da fare
- persone/date/riferimenti
- anteprima della trascrizione

## Perché è la soluzione giusta
Funziona su qualsiasi cellulare perché l'interfaccia è Telegram stesso. L'utente manda o inoltra il vocale al bot e riceve il riassunto nella stessa chat.

## Come funziona
1. Crei il bot con BotFather.
2. Imposti un webhook HTTPS pubblico.
3. Quando arriva un messaggio con `voice`, `audio` o `document`, il bot usa `getFile` per ottenere `file_path` e scaricare il file.
4. Il file viene mandato al motore speech-to-text.
5. La trascrizione viene mandata a un modello che restituisce JSON strutturato.
6. Il bot invia la risposta su Telegram.

## Endpoint richiesti da Telegram
Telegram supporta due modi per ricevere update: `getUpdates` oppure `setWebhook`. In produzione conviene `setWebhook` con `secret_token`.

## Deploy rapido
### 1) Installa dipendenze
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) Variabili ambiente
```bash
cp .env.example .env
```
Compila i valori reali.

### 3) Avvio locale
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

### 4) Esporre il server
Usa un server pubblico con HTTPS, per esempio Railway, Render, Fly.io o VPS con Nginx.

### 5) Registrare webhook
```bash
curl -X POST "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://tuo-dominio.it/webhook",
    "secret_token": "IL_TUO_SECRET",
    "allowed_updates": ["message", "edited_message"],
    "drop_pending_updates": true
  }'
```

## Comandi utili
### Verificare webhook
```bash
curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getWebhookInfo"
```

### Rimuovere webhook
```bash
curl -X POST "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/deleteWebhook"
```

## Note pratiche
- `voice` copre le note vocali Telegram.
- `audio` copre file audio classici.
- `document` è utile quando l'audio arriva come allegato generico.
- Se vuoi trattare solo vocali veri, limita il parsing a `message.voice`.
- Il bot non legge i messaggi privati dell'utente dentro Telegram: riceve solo ciò che l'utente gli manda o inoltra.

## Stima costi
Il costo dipende da minuti audio + lunghezza della trascrizione + modello di sintesi. OpenAI pubblica prezzi API aggiornati per modelli testo/audio nella pagina pricing ufficiale.

## Migliorie consigliate
- Supporto multilingua automatico.
- JSON persistito in database.
- Tag automatici: lavoro, spesa, appuntamenti, persone.
- Pulsanti inline: "solo task", "solo riassunto", "traduci".
- Output in formato checklist.
