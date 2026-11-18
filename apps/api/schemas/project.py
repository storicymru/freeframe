from pydantic import BaseModel, Field, field_validator
import uuid
from datetime import datetime
from ..models.project import ProjectType, ProjectRole

class ProjectCreate(BaseModel):
    name: str = Field(max_length=255)
    description: str | None = None
    project_type: ProjectType = ProjectType.personal

class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    is_public: bool | None = None

class ProjectResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    project_type: ProjectType
    created_by: uuid.UUID
    created_at: datetime
    poster_url: str | None = None
    is_public: bool = False
    asset_count: int = 0
    storage_bytes: int = 0
    member_count: int = 0
    role: ProjectRole | None = None
    # The client's branding for this project (set here, or sent across by
    # Cylch): shown on the project's card and page as well as on review pages.
    brand_logo_url: str | None = None
    brand_primary_color: str | None = None
    brand_secondary_color: str | None = None
    model_config = {"from_attributes": True}

    @field_validator("brand_logo_url", "brand_primary_color", "brand_secondary_color", mode="before")
    @classmethod
    def _branding_is_set_by_the_route(cls, v):
        # These are not columns of a project: the route fills them in from the
        # project's branding. Whatever the object being read happens to offer
        # under these names is not branding.
        return v if isinstance(v, str) else None

class ProjectMemberResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    user_id: uuid.UUID
    role: ProjectRole
    invited_at: datetime | None = None  # when the member joined the project
    model_config = {"from_attributes": True}

class AddProjectMemberRequest(BaseModel):
    user_id: uuid.UUID
    role: ProjectRole = ProjectRole.viewer

class UpdateProjectMemberRequest(BaseModel):
    role: ProjectRole
