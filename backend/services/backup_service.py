"""
Backup Service — scheduled database backups and retention management.
"""

import gzip
import logging
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

from backend.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class BackupService:
    """Handles database backup creation, listing, and retention cleanup."""

    def __init__(self) -> None:
        self.backup_dir = Path(settings.BACKUP_DIR)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def create_backup(self) -> dict:
        """
        Create a compressed backup of the SQLite database.
        For production PostgreSQL, this would invoke pg_dump.

        Returns:
            Dict with backup metadata.
        """
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"facevoiceauth_backup_{timestamp}.db.gz"
        backup_path = self.backup_dir / filename

        if settings.is_sqlite:
            db_file = settings.DATABASE_URL.replace("sqlite+aiosqlite:///", "")
            if os.path.exists(db_file):
                with open(db_file, "rb") as f_in:
                    with gzip.open(str(backup_path), "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
            else:
                backup_path.touch()
        else:
            backup_path.touch()
            logger.info(
                "PostgreSQL backup would be triggered via pg_dump in production"
            )

        size = backup_path.stat().st_size if backup_path.exists() else 0

        logger.info(f"Backup created: {filename} ({size} bytes)")
        return {
            "filename": filename,
            "path": str(backup_path),
            "size_bytes": size,
            "created_at": datetime.utcnow().isoformat(),
        }

    def list_backups(self) -> List[dict]:
        """List all existing backups with metadata."""
        backups = []
        for f in sorted(self.backup_dir.glob("facevoiceauth_backup_*.db.gz"), reverse=True):
            backups.append({
                "filename": f.name,
                "path": str(f),
                "size_bytes": f.stat().st_size,
                "created_at": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })
        return backups

    def cleanup_old_backups(self) -> int:
        """Remove backups older than BACKUP_RETENTION_DAYS."""
        cutoff = datetime.utcnow() - timedelta(days=settings.BACKUP_RETENTION_DAYS)
        removed = 0
        for f in self.backup_dir.glob("facevoiceauth_backup_*.db.gz"):
            file_time = datetime.fromtimestamp(f.stat().st_mtime)
            if file_time < cutoff:
                f.unlink()
                removed += 1
                logger.info(f"Removed old backup: {f.name}")
        return removed


backup_service = BackupService()
