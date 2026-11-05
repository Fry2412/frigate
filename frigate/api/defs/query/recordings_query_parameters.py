from typing import Optional, Union

from pydantic import BaseModel, Field
from pydantic.json_schema import SkipJsonSchema


class MediaRecordingsSummaryQueryParams(BaseModel):
    timezone: str = "utc"
    cameras: Optional[str] = "all"


class MediaRecordingsAvailabilityQueryParams(BaseModel):
    cameras: str = "all"
    before: Union[float, SkipJsonSchema[None]] = None
    after: Union[float, SkipJsonSchema[None]] = None
    scale: int = Field(default=30, ge=1)


class RecordingsDeleteQueryParams(BaseModel):
    keep: Optional[str] = None
    cameras: Optional[str] = "all"
