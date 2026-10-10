from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db_name: str = "gymqueue"

    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    default_grace_period_seconds: int = 120
    default_rest_period_seconds: int = 300
    default_max_rests: int = 6

    scheduler_interval_seconds: float = 2.0

    cors_allowed_origins: str = "http://localhost:5173"

    # ---- vision service integration ----
    vision_url: str = ""                  # base URL of the vision service, e.g. http://localhost:8001
    vision_api_key: str = ""              # sent to vision's command API (== vision's own VISION_API_KEY)
    vision_events_api_key: str = ""       # expected on inbound events from vision (== vision's BACKEND_API_KEY)

    # ---- busy times / estimated wait ----
    gym_timezone: str = "America/New_York"
    stats_sample_interval_seconds: float = 60.0
    stats_turn_min_minutes: int = 10   # every turn on a machine is assumed to take 10-15 min
    stats_turn_max_minutes: int = 15

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]


settings = Settings()
