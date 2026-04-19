"""CRUD endpoints for business (tenant) management."""

from typing import List, Optional

from fastapi import APIRouter, HTTPException

from app.core import json_storage
from app.models.business import Business
from app.schemas.business import BusinessCreate, BusinessResponse, BusinessUpdate

router = APIRouter()


@router.post("/", response_model=BusinessResponse, status_code=201)
async def create_business(business_data: BusinessCreate):
    """Register a new business."""
    # Check if phone number already exists
    existing = await json_storage.get_business_by_phone(business_data.phone_number)
    if existing:
        raise HTTPException(status_code=400, detail="Phone number already registered")

    business = Business(**business_data.model_dump())
    result = await json_storage.create_business(business.model_dump())
    return result


@router.get("/", response_model=List[BusinessResponse])
async def list_businesses():
    """List all registered businesses."""
    return await json_storage.list_businesses()


@router.get("/lookup", response_model=Optional[BusinessResponse])
async def lookup_business_by_phone(phone: str):
    """Find business by phone number (used for inbound ANI lookup)."""
    return await json_storage.get_business_by_phone(phone)


@router.get("/{business_id}", response_model=BusinessResponse)
async def get_business(business_id: str):
    """Get a single business by ID."""
    business = await json_storage.get_business(business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


@router.put("/{business_id}", response_model=BusinessResponse)
async def update_business(business_id: str, update_data: BusinessUpdate):
    """Update an existing business."""
    existing = await json_storage.get_business(business_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Business not found")

    # Merge update data with existing
    merged = {**existing, **update_data.model_dump(exclude_unset=True)}
    result = await json_storage.update_business(business_id, merged)
    return result


@router.delete("/{business_id}", status_code=204)
async def delete_business(business_id: str):
    """Delete a business."""
    success = await json_storage.delete_business(business_id)
    if not success:
        raise HTTPException(status_code=404, detail="Business not found")
    return None
