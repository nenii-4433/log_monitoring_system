import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_publishable_key: str
    supabase_secret_key: str


def get_settings() -> Settings:
    load_dotenv()

    supabase_url = os.getenv("SUPABASE_URL")
    publishable_key = os.getenv("SUPABASE_PUBLISHABLE_KEY")
    secret_key = os.getenv("SUPABASE_SECRET_KEY")

    missing = []
    if not supabase_url:
        missing.append("SUPABASE_URL")
    if not publishable_key:
        missing.append("SUPABASE_PUBLISHABLE_KEY")
    if not secret_key:
        missing.append("SUPABASE_SECRET_KEY")

    if missing:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(missing)
        )

    return Settings(
        supabase_url=supabase_url,
        supabase_publishable_key=publishable_key,
        supabase_secret_key=secret_key,
    )