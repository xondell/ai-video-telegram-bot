# AI Video Telegram Bot

Production-oriented Telegram bot for:

**voice/audio → Gemini understanding → scene plan → fal.ai PixVerse key scenes → FFmpeg hybrid edit → final MP4 → Telegram**

## Safety invariants

- paid media API hard cap: **$5.00/job**
- normal planner target: **$4.50/job**
- global initial paid-media budget: **$10.00**
- atomic Postgres reservations before paid requests
- unknown provider billing stays reserved rather than being assumed free
- database CHECK constraints enforce both hard caps as defense in depth

## Hosting

- **GitHub**: source repository / intermediate deployment step
- **Vercel**: FastAPI webhook runtime (no Telegram polling process)
- **Supabase**: Postgres + private Storage
- dedicated Supabase ref: `avpkxroflhlifjxfqbqi`

## Only five Vercel secrets

```text
TELEGRAM_BOT_TOKEN
GOOGLE_AI_API_KEY
FAL_KEY
SUPABASE_DATABASE_URL
SUPABASE_SERVICE_ROLE_KEY
```

No separate Telegram/fal webhook secrets or public base URL are required. Webhook path tokens are derived from existing API secrets.

## Deploy from Ubuntu

```bash
chmod +x deploy_all.sh
./deploy_all.sh
```

The script creates/pushes a private GitHub repository, links it to Vercel team `boris-llc`, sets the five Production secrets, deploys, health-checks the service and configures Telegram webhook automatically.

See [`DEPLOYMENT.md`](DEPLOYMENT.md) for details.

## Runtime architecture

Telegram sends updates to a secret-derived Vercel webhook path. Job/user/callback state lives in Supabase instead of process memory, so different Vercel Function instances can handle consecutive updates safely.

Paid fal requests use queue/webhooks. Before each paid request the app refreshes/validates PixVerse pricing, calculates a plan at or below `$4.50`, and atomically reserves the maximum request cost in both job and global ledgers.

The final video is assembled with `imageio-ffmpeg`, so the deployed Python package carries its own FFmpeg executable rather than assuming Vercel has a system FFmpeg installation.
