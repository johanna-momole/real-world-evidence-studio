"""Application and study configuration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_DIR = _REPO_ROOT / "config"
_CONCEPT_FILE = _CONFIG_DIR / "concept_sets.yml"


class StudyConfig(BaseModel):
    """User-configurable study parameters."""

    follow_up_days: int = 180
    baseline_days: int = 365
    min_age_at_index: int = 18
    exclude_type1_diabetes: bool = True
    exclude_gestational_diabetes: bool = True
    exclude_pregnancy_at_index: bool = True
    exclude_missing_demographics: bool = False
    min_baseline_history_days: int = 365
    min_follow_up_days: int = 180

    @field_validator("follow_up_days")
    @classmethod
    def _valid_follow_up(cls, v: int) -> int:
        """Restrict to supported window lengths."""
        if v not in (30, 90, 180, 365):
            raise ValueError(f"follow_up_days must be 30, 90, 180, or 365; got {v}")
        return v

    @classmethod
    def from_yaml(cls, path: Optional[Path] = None) -> StudyConfig:
        """Load config from YAML, falling back to defaults if file is absent."""
        target = path or (_CONFIG_DIR / "study_defaults.yml")
        if not target.exists():
            logger.warning("Config file not found at %s; using defaults.", target)
            return cls()
        with target.open() as fh:
            data = yaml.safe_load(fh) or {}
        return cls(**data)

    def to_dict(self) -> dict:
        """Return JSON-serialisable representation for audit records."""
        return self.model_dump()


class AppConfig(BaseSettings):
    """Runtime environment configuration loaded from .env / environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    synthea_data_dir: Path = Path("data/raw")
    db_path: Path = Path("data/evidence_studio.duckdb")
    log_level: str = "INFO"

    # Resolved at startup so relative paths work from any working directory
    @property
    def resolved_synthea_dir(self) -> Path:
        """Return synthea_data_dir resolved relative to the repo root."""
        p = self.synthea_data_dir
        return p if p.is_absolute() else (_REPO_ROOT / p)

    @property
    def resolved_db_path(self) -> Path:
        """Return db_path resolved relative to the repo root."""
        p = self.db_path
        return p if p.is_absolute() else (_REPO_ROOT / p)

    @property
    def has_synthea_files(self) -> bool:
        """True when at least one .csv file exists in the configured data directory."""
        d = self.resolved_synthea_dir
        return d.is_dir() and any(d.glob("*.csv"))

    @property
    def required_files_present(self) -> dict[str, bool]:
        """Check presence of the five required Synthea source files."""
        required = ["patients", "encounters", "conditions", "medications", "observations"]
        d = self.resolved_synthea_dir
        return {name: (d / f"{name}.csv").exists() for name in required}


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger for the application."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
