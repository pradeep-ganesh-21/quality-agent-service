import yaml
from pathlib import Path
from typing import Dict, List, Any
from sqlalchemy import Integer, String, DateTime, Boolean


class ConfigService:
    def __init__(self, config_path: str = "config.yml"):
        self.config_path = Path(config_path)
        self.config = None

    def load_config(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")

        with open(self.config_path, 'r') as file:
            self.config = yaml.safe_load(file)

        self._validate_config()
        return self.config

    def _validate_config(self):
        if not self.config:
            raise ValueError("Configuration is empty")

        if 'database' not in self.config:
            raise ValueError("'database' section not found in configuration")

        db_config = self.config['database']
        if 'table_name' not in db_config:
            raise ValueError("'table_name' not found in database configuration")

        if 'columns' not in db_config or not isinstance(db_config['columns'], list):
            raise ValueError("'columns' must be a list in database configuration")

    def get_table_schema(self) -> Dict[str, Any]:
        if not self.config:
            self.load_config()

        return {
            'table_name': self.config['database']['table_name'],
            'columns': self.config['database']['columns']
        }

    def map_yaml_type_to_sqlalchemy(self, yaml_type: str):
        type_mapping = {
            'INTEGER': Integer,
            'VARCHAR': String,
            'TIMESTAMP': DateTime,
            'BOOLEAN': Boolean,
        }

        base_type = yaml_type.split('(')[0].upper()

        if base_type == 'VARCHAR':
            try:
                length = int(yaml_type.split('(')[1].split(')')[0])
                return String(length)
            except (IndexError, ValueError):
                return String(255)

        sql_type = type_mapping.get(base_type)
        if not sql_type:
            raise ValueError(f"Unsupported type: {yaml_type}")

        return sql_type
