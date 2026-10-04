from frigate.record.multicam import MultiCamPlan
from pydantic import BaseModel, ConfigDict, Field


class MultiCamExportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="MultiCam", min_length=1, max_length=100)
    plan: MultiCamPlan
