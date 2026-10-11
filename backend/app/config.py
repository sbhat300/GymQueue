from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db_name: str = "gymqueue"

    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    default_grace_period_seconds: int = 120           # turn-start: time to check in once it's your turn
    default_end_of_use_grace_seconds: int = 30         # end-of-use: time to resume after leaving the camera's view
    default_rest_period_seconds: int = 300
    max_rest_period_seconds: int = 300                 # hard cap, regardless of per-machine override
    default_max_rests: int = 6

    # ---- "working in" (sharing one queue slot/turn) ----
    default_max_group_size: int = 4   # how many people can share one slot: 1 owner + up to 3 who work in

    scheduler_interval_seconds: float = 2.0

    cors_allowed_origins: str = "http://localhost:5173"

    # ---- vision service integration ----
    vision_url: str = ""                  # base URL of the vision service, e.g. http://localhost:8001
    vision_api_key: str = ""              # sent to vision's command API (== vision's own VISION_API_KEY)
    vision_events_api_key: str = ""       # expected on inbound events from vision (== vision's BACKEND_API_KEY)

    # ---- voice announcements (ElevenLabs) ----
    elevenlabs_api_key: str = ""          # blank = voice announcements disabled
    elevenlabs_voice_id: str = ""         # blank = auto-pick the first voice on the account

    # ---- busy times / estimated wait ----
    gym_timezone: str = "America/New_York"
    stats_sample_interval_seconds: float = 60.0
    stats_turn_min_minutes: int = 10   # every turn on a machine is assumed to take 10-15 min
    stats_turn_max_minutes: int = 15
    stats_extra_minutes_per_partner: int = 5   # added per extra person sharing a turn (working in slows a set down a little, but a group doesn't take a whole separate turn each)

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]


settings = Settings()
