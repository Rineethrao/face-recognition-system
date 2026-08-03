from pydantic import BaseModel, ConfigDict
from typing import List, Optional, Dict, Any

class FlexibleModel(BaseModel):
    model_config = ConfigDict(extra='allow')

class DetectedFace(FlexibleModel):
    bbox: List[float] = []
    score: float = 0.0
    landmarks: Optional[List[List[float]]] = None

class TrackedFace(FlexibleModel):
    pass

class RecognitionMatch(FlexibleModel):
    pass

class RecognitionEvent(FlexibleModel):
    pass

class CameraConfigModel(FlexibleModel):
    pass

class APIResponse(FlexibleModel):
    status: str = "success"
    message: str = ""
    data: Optional[Any] = None

class RecognitionStartRequest(FlexibleModel):
    pass

class RegisterStartRequest(FlexibleModel):
    pass

class SnapshotRegisterRequest(FlexibleModel):
    pass

class CandidateRegisterRequest(FlexibleModel):
    pass

class PersonResponse(FlexibleModel):
    person_id: str
    embedding_count: int = 0
    registered_at: str = ""
    face_images: List[str] = []

class PersonDetailResponse(FlexibleModel):
    pass

class PersonGalleryImage(FlexibleModel):
    pass

class CameraStartRequest(FlexibleModel):
    pass
    
class CameraCreateRequest(FlexibleModel):
    id: Optional[str] = None
    camera_id: Optional[str] = None
    name: str = ""
    location: Optional[str] = None
    description: Optional[str] = None
    brand: Optional[str] = None
    ip_address: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    channel: Optional[int] = None
    stream_type: Optional[str] = None
    enabled: bool = True
    rotation: int = 0
    fps_limit: int = 30

class CameraTestRequest(FlexibleModel):
    pass
