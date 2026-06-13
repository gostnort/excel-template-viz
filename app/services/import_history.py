"""
Import History Management

Tracks processed IDs, trash IDs, and import history for each template.
History files are stored in: templates/{template_id}/{template_id}.history.json
"""
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Any
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path("templates")


@dataclass
class ImportHistoryConfig:
    """Import history configuration for a template"""
    template_id: str
    processed_ids: set[str]  # IDs that have been successfully imported
    trash_ids: set[str]      # IDs marked as trash/invalid
    last_import: str | None = None  # ISO timestamp of last import
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "template_id": self.template_id,
            "processed_ids": list(self.processed_ids),
            "trash_ids": list(self.trash_ids),
            "last_import": self.last_import
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ImportHistoryConfig":
        """Create from dictionary"""
        return cls(
            template_id=data.get("template_id", ""),
            processed_ids=set(data.get("processed_ids", [])),
            trash_ids=set(data.get("trash_ids", [])),
            last_import=data.get("last_import")
        )


def get_history_path(template_id: str) -> Path:
    """
    Get path to history file
    
    Returns: templates/{template_id}/{template_id}.history.json
    """
    return TEMPLATES_DIR / template_id / f"{template_id}.history.json"


def load_import_history(template_id: str) -> ImportHistoryConfig:
    """
    Load import history for a template
    
    Args:
        template_id: Template identifier
        
    Returns:
        ImportHistoryConfig (creates new one if not found)
    """
    history_file = get_history_path(template_id)
    
    if not history_file.exists():
        logger.info(f"No import history found for {template_id}, creating new")
        return ImportHistoryConfig(
            template_id=template_id,
            processed_ids=set(),
            trash_ids=set()
        )
    
    try:
        with open(history_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return ImportHistoryConfig.from_dict(data)
    
    except Exception as e:
        logger.error(f"Failed to load import history for {template_id}: {e}")
        return ImportHistoryConfig(
            template_id=template_id,
            processed_ids=set(),
            trash_ids=set()
        )


def save_import_history(history: ImportHistoryConfig) -> bool:
    """
    Save import history to disk
    
    Args:
        history: ImportHistoryConfig to save
        
    Returns:
        True if successful
    """
    history_file = get_history_path(history.template_id)
    
    # Ensure template directory exists
    history_file.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        with open(history_file, 'w', encoding='utf-8') as f:
            json.dump(history.to_dict(), f, indent=2, ensure_ascii=False)
        
        logger.info(f"Saved import history for {history.template_id}")
        return True
    
    except Exception as e:
        logger.error(f"Failed to save import history: {e}")
        return False


def mark_as_processed(template_id: str, id_values: list[str]) -> bool:
    """
    Mark IDs as processed
    
    Args:
        template_id: Template identifier
        id_values: List of ID values to mark as processed
        
    Returns:
        True if successful
    """
    history = load_import_history(template_id)
    history.processed_ids.update(id_values)
    history.last_import = datetime.now().isoformat()
    
    return save_import_history(history)


def mark_as_trash(template_id: str, id_values: list[str]) -> bool:
    """
    Mark IDs as trash (invalid/ignore)
    
    Args:
        template_id: Template identifier
        id_values: List of ID values to mark as trash
        
    Returns:
        True if successful
    """
    history = load_import_history(template_id)
    history.trash_ids.update(id_values)
    
    # Remove from processed if they were there
    history.processed_ids.difference_update(id_values)
    
    return save_import_history(history)


def unmark_trash(template_id: str, id_values: list[str]) -> bool:
    """
    Remove IDs from trash list
    
    Args:
        template_id: Template identifier
        id_values: List of ID values to remove from trash
        
    Returns:
        True if successful
    """
    history = load_import_history(template_id)
    history.trash_ids.difference_update(id_values)
    
    return save_import_history(history)


def unmark_processed(template_id: str, id_values: list[str]) -> bool:
    """
    Remove IDs from processed list
    
    Args:
        template_id: Template identifier
        id_values: List of ID values to remove from processed
        
    Returns:
        True if successful
    """
    history = load_import_history(template_id)
    history.processed_ids.difference_update(id_values)
    
    return save_import_history(history)


def unmark_ids(template_id: str, id_values: list[str]) -> bool:
    """
    Restore IDs to unprocessed state by removing from both processed and trash sets
    
    Args:
        template_id: Template identifier
        id_values: List of ID values to restore
        
    Returns:
        True if successful
    """
    history = load_import_history(template_id)
    history.processed_ids.difference_update(id_values)
    history.trash_ids.difference_update(id_values)
    
    return save_import_history(history)


def is_processed(template_id: str, id_value: str) -> bool:
    """Check if an ID has been processed"""
    history = load_import_history(template_id)
    return id_value in history.processed_ids


def is_trash(template_id: str, id_value: str) -> bool:
    """Check if an ID is marked as trash"""
    history = load_import_history(template_id)
    return id_value in history.trash_ids


def get_import_stats(template_id: str) -> dict[str, Any]:
    """
    Get import statistics for a template
    
    Returns:
        Dict with processed_count, trash_count, last_import
    """
    history = load_import_history(template_id)
    
    return {
        "processed_count": len(history.processed_ids),
        "trash_count": len(history.trash_ids),
        "last_import": history.last_import
    }


def clear_history(template_id: str) -> bool:
    """
    Clear all import history for a template
    
    Args:
        template_id: Template identifier
        
    Returns:
        True if successful
    """
    history_file = get_history_path(template_id)
    
    try:
        if history_file.exists():
            history_file.unlink()
            logger.info(f"Cleared import history for {template_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to clear history: {e}")
        return False
