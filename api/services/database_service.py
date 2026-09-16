import os
import time
from typing import Dict, List, Any, Optional
from sqlalchemy import create_engine, MetaData, Table, Column, select, insert
from sqlalchemy.exc import OperationalError
from services.config_service import ConfigService


class DatabaseService:
    def __init__(self, config_service: ConfigService):
        self.config_service = config_service
        self.engine = None
        self.metadata = MetaData()
        self.table = None
        self.table_name = None

    def _get_connection_string(self) -> str:
        user = os.getenv('POSTGRES_USER', 'postgres')
        password = os.getenv('POSTGRES_PASSWORD', 'postgres')
        host = os.getenv('POSTGRES_HOST', 'postgres')
        port = os.getenv('POSTGRES_PORT', '5432')
        database = os.getenv('POSTGRES_DB', 'quality_agent_db')

        return f"postgresql://{user}:{password}@{host}:{port}/{database}"

    def wait_for_db(self, max_retries: int = 30, retry_interval: int = 1):
        connection_string = self._get_connection_string()
        retries = 0

        while retries < max_retries:
            try:
                engine = create_engine(connection_string)
                with engine.connect() as conn:
                    conn.execute(select(1))
                print(f"Database connection established successfully")
                return
            except OperationalError as e:
                retries += 1
                if retries >= max_retries:
                    raise Exception(f"Failed to connect to database after {max_retries} attempts: {str(e)}")
                print(f"Database not ready, retrying... ({retries}/{max_retries})")
                time.sleep(retry_interval)

    def connect(self):
        connection_string = self._get_connection_string()
        self.engine = create_engine(
            connection_string,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10
        )
        print(f"Database engine created")

    def create_table_from_config(self):
        schema = self.config_service.get_table_schema()
        self.table_name = schema['table_name']

        columns = []
        for col_config in schema['columns']:
            col_name = col_config['name']
            col_type = self.config_service.map_yaml_type_to_sqlalchemy(col_config['type'])

            kwargs = {
                'nullable': col_config.get('nullable', True),
                'primary_key': col_config.get('primary_key', False),
                'autoincrement': col_config.get('auto_increment', False)
            }

            columns.append(Column(col_name, col_type, **kwargs))

        self.table = Table(self.table_name, self.metadata, *columns, extend_existing=True)
        self.metadata.create_all(self.engine)
        print(f"Table '{self.table_name}' created or verified")

    def insert_record(self, data: Dict[str, Any]) -> int:
        if not self.table or not self.engine:
            raise Exception("Database not initialized")

        with self.engine.connect() as conn:
            result = conn.execute(insert(self.table).values(**data))
            conn.commit()
            return result.inserted_primary_key[0]

    def get_all_records(self, limit: Optional[int] = None, offset: Optional[int] = None) -> List[Dict[str, Any]]:
        if not self.table or not self.engine:
            raise Exception("Database not initialized")

        with self.engine.connect() as conn:
            query = select(self.table)

            if offset:
                query = query.offset(offset)
            if limit:
                query = query.limit(limit)

            result = conn.execute(query)
            rows = result.fetchall()

            return [dict(row._mapping) for row in rows]

    def get_record_by_id(self, record_id: int) -> Optional[Dict[str, Any]]:
        if not self.table or not self.engine:
            raise Exception("Database not initialized")

        with self.engine.connect() as conn:
            query = select(self.table).where(self.table.c.id == record_id)
            result = conn.execute(query)
            row = result.fetchone()

            return dict(row._mapping) if row else None

    def close(self):
        if self.engine:
            self.engine.dispose()
            print("Database connection closed")
