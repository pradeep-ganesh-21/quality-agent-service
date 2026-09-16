from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from models.schemas import QualityRunCreate, QualityRunResponse
from services.database_service import DatabaseService

router = APIRouter(prefix="/api/v1", tags=["quality-runs"])

db_service: Optional[DatabaseService] = None


def set_database_service(service: DatabaseService):
    global db_service
    db_service = service


@router.post("/quality-runs", response_model=QualityRunResponse, status_code=201)
async def create_quality_run(quality_run: QualityRunCreate):
    try:
        data = quality_run.model_dump()
        record_id = db_service.insert_record(data)

        created_record = db_service.get_record_by_id(record_id)
        return QualityRunResponse(**created_record)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create quality run: {str(e)}")


@router.get("/quality-runs", response_model=List[QualityRunResponse])
async def get_quality_runs(
    limit: Optional[int] = Query(None, ge=1, le=1000, description="Maximum number of records to return"),
    offset: Optional[int] = Query(None, ge=0, description="Number of records to skip")
):
    try:
        records = db_service.get_all_records(limit=limit, offset=offset)
        return [QualityRunResponse(**record) for record in records]

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve quality runs: {str(e)}")


@router.get("/quality-runs/{record_id}", response_model=QualityRunResponse)
async def get_quality_run(record_id: int):
    try:
        record = db_service.get_record_by_id(record_id)

        if not record:
            raise HTTPException(status_code=404, detail=f"Quality run with id {record_id} not found")

        return QualityRunResponse(**record)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve quality run: {str(e)}")
