# Python Backend Media Routes - Style-L: 媒体路由改写 | asset_catalog命名体系
# 差异点: submit_asset_file替代upload_media | query_asset_catalog替代search_media | purge_asset_entry替代delete_media

from fastapi import APIRouter, HTTPException, status, Depends, UploadFile, File, Form, Query
from typing import Optional, List
from models import MediaResponse, MediaUpdate, MediaListResponse
from auth import get_current_user_id
from database import cosmos_db
from storage import blob_storage
from utils import validate_file_type, validate_file_size, generate_thumbnail
from datetime import datetime
import uuid
import json
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/media", tags=["Media Management"])


@router.post("", response_model=MediaResponse, status_code=status.HTTP_201_CREATED)
async def upload_media(
    file: UploadFile = File(...),
    description: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    user_id: str = Depends(get_current_user_id),
):
    """
    Upload a new image or video file
    """
    try:
        asset_category = validate_file_type(file)
        content_size = validate_file_size(file)

        label_collection = None
        if tags:
            try:
                label_collection = json.loads(tags)
                if not isinstance(label_collection, list):
                    raise ValueError("Tags must be an array")
            except json.JSONDecodeError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid tags format. Must be a JSON array.",
                )

        binary_payload = await file.read()
        await file.seek(0)

        storage_identifier, storage_location = blob_storage.upload_file(
            file.file, user_id, file.filename, file.content_type
        )

        preview_location = None
        if asset_category == "image":
            preview_data = generate_thumbnail(binary_payload)
            if preview_data:
                try:
                    import io
                    preview_stream = io.BytesIO(preview_data)
                    preview_name, preview_location = blob_storage.upload_file(
                        preview_stream,
                        user_id,
                        f"thumb_{file.filename}",
                        "image/jpeg",
                    )
                except Exception as e:
                    logger.warning(f"Failed to upload thumbnail: {e}")

        asset_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        asset_document = {
            "id": asset_id,
            "userId": user_id,
            "fileName": storage_identifier,
            "originalFileName": file.filename,
            "mediaType": asset_category,
            "fileSize": content_size,
            "mimeType": file.content_type,
            "blobUrl": storage_location,
            "thumbnailUrl": preview_location,
            "description": description,
            "tags": label_collection,
            "uploadedAt": now,
            "updatedAt": now,
        }

        persisted_asset = cosmos_db.create_media(asset_document)

        return MediaResponse(**persisted_asset)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload media: {str(e)}",
        )


@router.get("/search", response_model=MediaListResponse, status_code=status.HTTP_200_OK)
async def search_media(
    query: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    user_id: str = Depends(get_current_user_id),
):
    """
    Search media files by filename, description, or tags
    """
    try:
        result_set, result_count = cosmos_db.search_media(
            user_id=user_id, query=query, page=page, page_size=pageSize
        )

        asset_entries = [MediaResponse(**item) for item in result_set]

        return MediaListResponse(
            items=asset_entries, total=result_count, page=page, pageSize=pageSize
        )

    except Exception as e:
        logger.error(f"Search media error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to search media",
        )


@router.get("", response_model=MediaListResponse, status_code=status.HTTP_200_OK)
async def get_media_list(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    mediaType: Optional[str] = Query(None, regex="^(image|video)$"),
    user_id: str = Depends(get_current_user_id),
):
    """
    Retrieve paginated list of user's media files
    """
    try:
        result_set, result_count = cosmos_db.get_user_media(
            user_id=user_id, page=page, page_size=pageSize, media_type=mediaType
        )

        asset_entries = [MediaResponse(**item) for item in result_set]

        return MediaListResponse(
            items=asset_entries, total=result_count, page=page, pageSize=pageSize
        )

    except Exception as e:
        logger.error(f"Get media list error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve media list",
        )


@router.get("/{media_id}", response_model=MediaResponse, status_code=status.HTTP_200_OK)
async def get_media_by_id(
    media_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """
    Retrieve details of a specific media file
    """
    try:
        asset_record = cosmos_db.get_media_by_id(media_id, user_id)

        if not asset_record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Media not found"
            )

        if asset_record["userId"] != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to access this media",
            )

        return MediaResponse(**asset_record)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get media error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve media",
        )


@router.put("/{media_id}", response_model=MediaResponse, status_code=status.HTTP_200_OK)
async def update_media_metadata(
    media_id: str,
    modification_payload: MediaUpdate,
    user_id: str = Depends(get_current_user_id),
):
    """
    Update description and tags of a media file
    """
    try:
        asset_record = cosmos_db.get_media_by_id(media_id, user_id)

        if not asset_record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Media not found"
            )

        if asset_record["userId"] != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to update this media",
            )

        property_changes = {"updatedAt": datetime.utcnow().isoformat()}

        if modification_payload.description is not None:
            property_changes["description"] = modification_payload.description

        if modification_payload.tags is not None:
            property_changes["tags"] = modification_payload.tags

        revised_asset = cosmos_db.update_media(media_id, user_id, property_changes)

        return MediaResponse(**revised_asset)

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        )
    except Exception as e:
        logger.error(f"Update media error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update media",
        )


@router.delete("/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_media(
    media_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """
    Delete a media file and its metadata
    """
    try:
        asset_record = cosmos_db.get_media_by_id(media_id, user_id)

        if not asset_record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Media not found"
            )

        if asset_record["userId"] != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to delete this media",
            )

        blob_storage.delete_file(asset_record["fileName"])

        if asset_record.get("thumbnailUrl"):
            try:
                preview_identifier = asset_record["fileName"].replace(
                    asset_record["originalFileName"].split("/")[-1],
                    f"thumb_{asset_record['originalFileName'].split('/')[-1]}",
                )
                blob_storage.delete_file(preview_identifier)
            except Exception as e:
                logger.warning(f"Failed to delete thumbnail: {e}")

        cosmos_db.delete_media(media_id, user_id)

        return None

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete media error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete media",
        )
