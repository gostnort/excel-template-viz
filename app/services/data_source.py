"""
Data Source Configuration Management

Handles loading and saving data source configurations for templates.
Each template's data source config is stored in its own directory:
templates/{template_id}/{template_id}.datasource.json
"""
import json
import logging
from pathlib import Path
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path("templates")


@dataclass
class DataSourceConfig:
    """Data source configuration for a template"""
    template_id: str
    sheet_url: str
    worksheet_name: str
    id_column: str


def get_data_source_path(template_id: str) -> Path:
    """
    Get path to data source config file
    
    New location: templates/{template_id}/{template_id}.datasource.json
    """
    return TEMPLATES_DIR / template_id / f"{template_id}.datasource.json"


def load_template_data_source(template_id: str) -> DataSourceConfig | None:
    """
    Load data source configuration for a template
    
    Args:
        template_id: Template identifier
        
    Returns:
        DataSourceConfig if found, None otherwise
    """
    config_path = get_data_source_path(template_id)
    
    if not config_path.exists():
        logger.info(f"No data source config found for template: {template_id}")
        return None
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        config = DataSourceConfig(
            template_id=data['template_id'],
            sheet_url=data['sheet_url'],
            worksheet_name=data['worksheet_name'],
            id_column=data['id_column']
        )
        
        logger.info(f"Loaded data source config for template: {template_id}")
        return config
        
    except Exception as e:
        logger.error(f"Failed to load data source config: {e}")
        return None


def save_template_data_source(config: DataSourceConfig) -> None:
    """
    Save data source configuration for a template
    
    Args:
        config: Data source configuration
    """
    config_path = get_data_source_path(config.template_id)
    
    # Ensure template directory exists
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(asdict(config), f, indent=2, ensure_ascii=False)
        
        logger.info(f"Saved data source config for template: {config.template_id}")
        
    except Exception as e:
        logger.error(f"Failed to save data source config: {e}")
        raise


def delete_template_data_source(template_id: str) -> None:
    """
    Delete data source configuration for a template
    
    Args:
        template_id: Template identifier
    """
    config_path = get_data_source_path(template_id)
    
    if config_path.exists():
        try:
            config_path.unlink()
            logger.info(f"Deleted data source config for template: {template_id}")
        except Exception as e:
            logger.error(f"Failed to delete data source config: {e}")
            raise
