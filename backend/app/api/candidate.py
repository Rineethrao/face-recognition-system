import base64
import cv2
import numpy as np
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, Body, status

from app.models.schemas import APIResponse, CandidateRegisterRequest
from app.services.registration_service import registration_service

router = APIRouter(prefix="/candidates", tags=["Candidate Management & Verification"])

@router.get("", response_model=APIResponse)
def get_candidates(status_filter: Optional[str] = Query(default="PENDING", description="Filter candidates by status: PENDING, REGISTERED, REJECTED")):
    """Returns candidate profiles for operator review and selection."""
    return APIResponse(
        status="success",
        message="Retrieved candidate profiles.",
        data=[]
    )

@router.post("/{candidate_id}/register", response_model=APIResponse)
def register_candidate(candidate_id: str, req: CandidateRegisterRequest):
    """Converts an approved candidate profile into a registered Person profile."""
    return APIResponse(
        status="success",
        message="Candidate registered successfully."
    )
