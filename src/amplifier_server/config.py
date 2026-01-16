"""Server configuration."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class ServerConfig(BaseSettings):
    """Amplifier Server configuration.

    Can be set via environment variables with AMPLIFIER_SERVER_ prefix.
    """

    # Server settings
    host: str = Field(default="0.0.0.0", description="Host to bind to")
    port: int = Field(default=8420, description="Port to listen on")

    # Data settings
    data_dir: Path = Field(
        default=Path("~/.amplifier-server").expanduser(),
        description="Directory for server data",
    )

    # CORS settings
    cors_origins: list[str] = Field(
        default=["*"],
        description="Allowed CORS origins",
    )

    # Session defaults
    default_bundle: str = Field(
        default="foundation",
        description="Default bundle for new sessions",
    )

    # Startup sessions
    startup_bundles: list[str] = Field(
        default_factory=list,
        description="Bundles to create sessions for on startup",
    )

    # Security settings
    jwt_secret: str = Field(
        default="",  # Will be auto-generated if empty
        description="JWT signing secret (auto-generated if not set)",
    )
    jwt_expiry_minutes: int = Field(
        default=15,
        description="JWT access token expiry in minutes",
    )
    refresh_token_days: int = Field(
        default=30,
        description="Refresh token expiry in days",
    )
    require_auth: bool = Field(
        default=True,
        description="Require authentication for all endpoints (except /auth/*)",
    )

    class Config:
        env_prefix = "AMPLIFIER_SERVER_"
        env_file = ".env"


def load_config(config_path: Path | str | None = None) -> ServerConfig:
    """Load server configuration.

    Args:
        config_path: Optional path to a YAML config file

    Returns:
        ServerConfig instance
    """
    if config_path:
        import yaml

        config_path = Path(config_path)
        if config_path.exists():
            with open(config_path) as f:
                data = yaml.safe_load(f) or {}
            return ServerConfig(**data)

    return ServerConfig()
