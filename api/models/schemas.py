from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class QualityRunCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=255, description="Username of the person running the quality agent")
    github_repo: str = Field(..., min_length=1, max_length=500, description="GitHub repository in format 'org/repo'")
    run_date: datetime = Field(..., description="Date and time when the quality agent run occurred")
    number_of_issues_found: int = Field(..., ge=0, description="Number of issues found by the quality agent")

    class Config:
        json_schema_extra = {
            "example": {
                "username": "john_doe",
                "github_repo": "myorg/myrepo",
                "run_date": "2026-09-16T10:30:00",
                "number_of_issues_found": 5
            }
        }


class QualityRunResponse(QualityRunCreate):
    id: int = Field(..., description="Unique identifier for the quality run record")

    class Config:
        json_schema_extra = {
            "example": {
                "id": 1,
                "username": "john_doe",
                "github_repo": "myorg/myrepo",
                "run_date": "2026-09-16T10:30:00",
                "number_of_issues_found": 5
            }
        }
