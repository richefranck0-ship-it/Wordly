import os

def env(key, default=""):
    return os.getenv(key, default)

ENV = env("FLASK_ENV", "production")
IS_PROD = ENV == "production"
SECRET_KEY = env("SECRET_KEY") or ("dev-secret-change-me" if not IS_PROD else "")
DATABASE_URL = env("DATABASE_URL")           # Supabase PostgreSQL (connection string)
SQLITE_PATH = env("SQLITE_PATH", "worldly_dev.db")  # dev local seulement
ADMIN_PATH = "/" + env("ADMIN_PATH", "gestion-wl").strip("/")
ADMIN_USER = env("ADMIN_USER", "admin")
ADMIN_PASSWORD_HASH = env("ADMIN_PASSWORD_HASH")
ADMIN_PASSWORD = env("ADMIN_PASSWORD")       # alternative simple (déconseillé en prod)
VAPID_PUBLIC_KEY = env("VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY = env("VAPID_PRIVATE_KEY")  # clé privée VAPID (base64url) ou chemin PEM
VAPID_SUBJECT = env("VAPID_SUBJECT", "mailto:contact@example.com")
CRON_TOKEN = env("CRON_TOKEN")
SITE_URL = env("SITE_URL", "").rstrip("/")
MYMEMORY_EMAIL = env("MYMEMORY_EMAIL")       # augmente le quota gratuit
TRANSLATE_PROVIDER = env("TRANSLATE_PROVIDER", "mymemory")  # mymemory | libretranslate
LIBRETRANSLATE_URL = env("LIBRETRANSLATE_URL")
LIBRETRANSLATE_KEY = env("LIBRETRANSLATE_KEY")
PUSH_HOST_SUFFIXES = tuple(env("PUSH_HOST_SUFFIXES",
    "googleapis.com,mozilla.com,apple.com,windows.com,microsoft.com").split(","))
