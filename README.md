# Quality Agent Service

A centralized Docker-containerized service for collecting and storing quality agent run outputs. Built with FastAPI and PostgreSQL, this service provides REST endpoints to track quality agent executions across different repositories.

## Overview

When quality agents run across different repositories, they report their results (username, GitHub repo, run date, number of issues found) to this centralized service. The database schema is configurable via YAML, allowing flexibility for future enhancements.

## Features

- REST API built with FastAPI
- PostgreSQL database for persistent storage
- Docker Compose for easy deployment
- YAML-driven database schema configuration
- Controller-Service architecture for clean separation of concerns
- Automatic API documentation (Swagger UI)
- Health check endpoint
- Pagination support for querying records

## Prerequisites

- Docker
- Docker Compose

## Quick Start

### 1. Clone and Navigate

```bash
cd quality-agent-service
```

### 2. Start the Services

```bash
docker-compose up --build
```

This will:
- Start PostgreSQL container on port 5432
- Start FastAPI application on port 8000
- Automatically create the database table based on `api/config.yml`

### 3. Access the API

- API Base URL: http://localhost:8000
- Interactive API Docs: http://localhost:8000/docs
- Health Check: http://localhost:8000/health

## API Endpoints

### Create Quality Run

**POST** `/api/v1/quality-runs`

Create a new quality agent run record.

```bash
curl -X POST http://localhost:8000/api/v1/quality-runs \
  -H "Content-Type: application/json" \
  -d '{
    "username": "john_doe",
    "github_repo": "myorg/myrepo",
    "run_date": "2026-09-16T10:30:00",
    "number_of_issues_found": 5
  }'
```

**Response:**
```json
{
  "id": 1,
  "username": "john_doe",
  "github_repo": "myorg/myrepo",
  "run_date": "2026-09-16T10:30:00",
  "number_of_issues_found": 5
}
```

### Get All Quality Runs

**GET** `/api/v1/quality-runs`

Retrieve all quality agent runs with optional pagination.

```bash
# Get all records
curl http://localhost:8000/api/v1/quality-runs

# With pagination
curl "http://localhost:8000/api/v1/quality-runs?limit=10&offset=0"
```

**Response:**
```json
[
  {
    "id": 1,
    "username": "john_doe",
    "github_repo": "myorg/myrepo",
    "run_date": "2026-09-16T10:30:00",
    "number_of_issues_found": 5
  }
]
```

### Get Quality Run by ID

**GET** `/api/v1/quality-runs/{id}`

Retrieve a specific quality agent run by its ID.

```bash
curl http://localhost:8000/api/v1/quality-runs/1
```

**Response:**
```json
{
  "id": 1,
  "username": "john_doe",
  "github_repo": "myorg/myrepo",
  "run_date": "2026-09-16T10:30:00",
  "number_of_issues_found": 5
}
```

### Health Check

**GET** `/health`

Check the health status of the service and database connection.

```bash
curl http://localhost:8000/health
```

**Response:**
```json
{
  "status": "healthy",
  "database": "connected"
}
```

## Configuration

### Database Schema

The database schema is defined in `api/config.yml`. The current schema includes:

```yaml
database:
  table_name: quality_agent_runs
  columns:
    - name: id
      type: INTEGER
      primary_key: true
      auto_increment: true
    - name: username
      type: VARCHAR(255)
      nullable: false
    - name: github_repo
      type: VARCHAR(500)
      nullable: false
    - name: run_date
      type: TIMESTAMP
      nullable: false
    - name: number_of_issues_found
      type: INTEGER
      nullable: false
```

### Supported Column Types

- `INTEGER`
- `VARCHAR(length)`
- `TIMESTAMP`
- `BOOLEAN`

### Modifying Schema

**Important:** The current implementation creates tables using `CREATE TABLE IF NOT EXISTS`, which means:

- New columns will NOT be automatically added to existing tables
- To modify the schema after deployment, you need to manually run SQL migrations or drop and recreate the table

**For future schema changes:**
1. Update `api/config.yml` with new schema
2. Update `api/models/schemas.py` Pydantic models to match
3. Either:
   - Manually run SQL `ALTER TABLE` commands
   - Drop the existing table (loses data)
   - Implement a migration tool like Alembic

## Project Structure

```
quality-agent-service/
├── docker-compose.yml       # Container orchestration
├── README.md               # This file
├── .gitignore
└── api/
    ├── Dockerfile          # API container definition
    ├── requirements.txt    # Python dependencies
    ├── config.yml          # Database schema configuration
    ├── main.py            # FastAPI application entry point
    ├── controllers/       # REST endpoint handlers
    │   ├── __init__.py
    │   └── quality_agent_controller.py
    ├── services/          # Business logic layer
    │   ├── __init__.py
    │   ├── config_service.py
    │   └── database_service.py
    └── models/            # Pydantic schemas
        ├── __init__.py
        └── schemas.py
```

## Development

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f api
docker-compose logs -f postgres
```

### Stop Services

```bash
docker-compose down
```

### Stop and Remove Data

```bash
docker-compose down -v
```

### Access PostgreSQL

```bash
docker exec -it quality-agent-postgres psql -U postgres -d quality_agent_db
```

**Useful PostgreSQL commands:**
```sql
-- List tables
\dt

-- Describe table structure
\d quality_agent_runs

-- Query all records
SELECT * FROM quality_agent_runs;

-- Count records
SELECT COUNT(*) FROM quality_agent_runs;
```

## Environment Variables

The following environment variables are configured in `docker-compose.yml`:

**PostgreSQL Container:**
- `POSTGRES_DB`: Database name (default: quality_agent_db)
- `POSTGRES_USER`: Database user (default: postgres)
- `POSTGRES_PASSWORD`: Database password (default: postgres)

**API Container:**
- `POSTGRES_DB`: Database name
- `POSTGRES_USER`: Database user
- `POSTGRES_PASSWORD`: Database password
- `POSTGRES_HOST`: Database host (default: postgres)
- `POSTGRES_PORT`: Database port (default: 5432)

## Troubleshooting

### API container fails to start

**Issue:** API cannot connect to PostgreSQL

**Solution:** The docker-compose.yml includes health checks. Ensure postgres is healthy:

```bash
docker-compose ps
```

If postgres is unhealthy, check logs:

```bash
docker-compose logs postgres
```

### Database connection errors

**Issue:** Connection refused or timeout

**Solution:** The API includes automatic retry logic (30 seconds). If it still fails:

1. Verify postgres container is running
2. Check environment variables match between services
3. Restart services: `docker-compose restart`

### Table not created

**Issue:** Table doesn't exist in database

**Solution:** Check API startup logs:

```bash
docker-compose logs api
```

Look for "Database table initialized" message.

### Port already in use

**Issue:** Port 8000 or 5432 already in use

**Solution:** Either stop the conflicting service or modify ports in `docker-compose.yml`:

```yaml
ports:
  - "8001:8000"  # Change host port
```

## Future Enhancements

- [ ] Database migration support with Alembic
- [ ] Authentication and authorization
- [ ] Batch record insertion
- [ ] Advanced filtering and search
- [ ] Audit timestamps (created_at, updated_at)
- [ ] Logging framework integration
- [ ] Metrics and monitoring
- [ ] Rate limiting

## License

MIT
