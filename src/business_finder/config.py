"""Configuration management."""

from pathlib import Path
from pydantic import BaseModel


class Config(BaseModel):
    """Application configuration."""

    # Project paths - config.py is at src/business_finder/config.py, so 3 parents up
    project_root: Path = Path(__file__).parent.parent.parent
    data_dir: Path = project_root / "data"
    db_path: Path = data_dir / "business_finder.db"

    # Scraping settings
    request_delay_seconds: float = 1.0
    max_retries: int = 3
    timeout_seconds: int = 30

    # Browser settings
    headless: bool = True
    slow_mo: int = 0  # milliseconds between actions

    def ensure_dirs(self) -> None:
        """Ensure required directories exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)


# Global config instance
config = Config()
