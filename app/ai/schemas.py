from pydantic import BaseModel, Field

class Segment(BaseModel):
    start: float
    end: float
    text: str

class AudioAnalysis(BaseModel):
    language: str
    duration_seconds: float
    transcript_raw: str
    transcript_clean: str
    topic: str
    summary: str
    segments: list[Segment]

class Scene(BaseModel):
    id: int
    start: float
    end: float
    narration: str
    importance: float = Field(ge=0, le=1)
    visual_type: str = "generated_video"
    video_prompt: str
    negative_prompt: str = ""
    camera: str = ""
    transition: str = "cut"

class VideoScript(BaseModel):
    title: str
    visual_direction: str
    scenes: list[Scene]
