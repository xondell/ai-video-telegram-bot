# Deployment: GitHub → Vercel + Supabase

The dedicated Supabase project already exists:

- project: `ai-video-telegram-bot`
- ref: `avpkxroflhlifjxfqbqi`
- region: `eu-west-1`
- Storage: private `bot-media`
- global paid-media budget: `$10.00`
- per-job hard cap: `$2.00`

## Vercel environment variables

This build intentionally requires only **five** manually configured Vercel Production secrets:

```text
TELEGRAM_BOT_TOKEN
GOOGLE_AI_API_KEY
FAL_KEY
SUPABASE_DATABASE_URL
SUPABASE_SERVICE_ROLE_KEY
```

Everything else is a safe code-level default. The public Supabase project URL/bucket are embedded for this dedicated project. Budget limits and model policy are not deploy-time variables, so an accidental Vercel configuration change cannot silently increase the `$2/job` or `$10/global` limits.

### What is no longer an env variable

- no `TELEGRAM_WEBHOOK_SECRET`
- no `FAL_WEBHOOK_SECRET`
- no `SETUP_SECRET`
- no `PUBLIC_BASE_URL`
- no model-name env vars
- no pricing/budget-limit env vars
- no Storage bucket env var

Telegram and fal webhook path tokens are derived at runtime from their existing API secrets with HMAC-SHA256. The current request origin is passed into the aiogram handler, so fal callback URLs do not need a separate base-URL setting.

## One-command Ubuntu deployment

From the project directory:

```bash
chmod +x deploy_all.sh
./deploy_all.sh
```

The script:

1. checks/installs Git, GitHub CLI, Node/npm, curl and Python;
2. authenticates `gh` if needed;
3. authenticates Vercel CLI if needed;
4. asks only for the five secrets above;
5. validates Telegram, Google AI, fal pricing and Supabase before deployment;
6. creates a **private GitHub repository** `ai-video-telegram-bot` if necessary;
7. commits and pushes `main`;
8. creates/links the Vercel project in team `boris-llc`;
9. connects the GitHub repo to Vercel where the account integration permits it;
10. uploads exactly five Production env vars as Sensitive variables;
11. deploys to Vercel production;
12. checks `/health`;
13. installs the Telegram webhook automatically;
14. verifies Telegram reports the expected webhook URL.

### Supabase database URL

For `SUPABASE_DATABASE_URL`, paste the **Transaction Pooler URI** from the Supabase project Connect screen. It should be the Postgres URI for project `avpkxroflhlifjxfqbqi`.

### Supabase service role

For `SUPABASE_SERVICE_ROLE_KEY`, use the server-side `service_role` / secret key from Supabase project API settings. Never use it in frontend code.

## Re-running

`deploy_all.sh` is designed to be re-runnable. It reuses the GitHub/Vercel projects, updates changed code, overwrites the five Production secrets, creates a fresh production deployment, and resets Telegram's webhook to the current production URL.
