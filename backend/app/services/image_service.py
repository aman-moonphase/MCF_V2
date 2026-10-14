"""Service for generating and managing creative visual image assets for LinkedIn posts."""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers.image_provider import ImageGenerationRequest, get_image_provider
from app.core.redaction import redact_payload
from app.models.content_image import ContentImage
from app.models.generated_content import GeneratedContent
from app.models.product import Product
from app.models.project import Project


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ImageService:
    def __init__(self, db: AsyncSession, user_id: int):
        self.db = db
        self.user_id = user_id

    async def _get_project_and_draft(self, project_id: UUID) -> tuple[Project, GeneratedContent]:
        project_res = await self.db.execute(
            select(Project).where(Project.id == project_id, Project.user_id == self.user_id)
        )
        project = project_res.scalar_one_or_none()
        if not project:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found or access denied.")

        draft_res = await self.db.execute(
            select(GeneratedContent).where(GeneratedContent.project_id == project_id)
        )
        draft = draft_res.scalar_one_or_none()
        if not draft:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="There is no generated post for this project. Generate a post first before generating an image."
            )
        return project, draft

    async def get_current_image(self, project_id: UUID) -> Optional[ContentImage]:
        _, draft = await self._get_project_and_draft(project_id)
        res = await self.db.execute(
            select(ContentImage)
            .where(ContentImage.project_id == project_id, ContentImage.generated_content_id == draft.id)
            .order_by(ContentImage.updated_at.desc().nullslast(), ContentImage.created_at.desc())
        )
        return res.scalars().first()

    async def generate_image(
        self,
        project_id: UUID,
        prompt: Optional[str] = None,
        aspect_ratio: str = "16:9",
        style: str = "professional",
        alt_text: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> ContentImage:
        project, draft = await self._get_project_and_draft(project_id)
        if draft.status == "approved":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This post has been approved. A new creative asset cannot be attached to an approved post. Create a new draft version first."
            )

        # Context loading
        product_res = await self.db.execute(select(Product).where(Product.id == draft.product_id))
        product = product_res.scalar_one_or_none()

        post_content = draft.content or {}
        hook = post_content.get("hook")
        body = post_content.get("body")
        pillar = post_content.get("pillar")

        product_name = None
        target_audience = None
        if product:
            profile = product.profile or {}
            product_name = profile.get("name") or product.name
            target_audience = profile.get("target_audience")
        elif draft.context_snapshot:
            product_name = draft.context_snapshot.get("product_name")

        # Request to provider
        req = ImageGenerationRequest(
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            style=style,
            alt_text=alt_text,
            product_name=product_name,
            hook=hook,
            body=body,
            pillar=pillar,
            target_audience=target_audience,
        )

        provider_instance = get_image_provider(provider)
        try:
            res = await provider_instance.generate_image(req)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )
        except TimeoutError as exc:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=str(exc),
            )
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=redact_payload(str(exc)),
            )

        # Check existing image for this draft
        existing_res = await self.db.execute(
            select(ContentImage).where(
                ContentImage.project_id == project_id,
                ContentImage.generated_content_id == draft.id,
                ContentImage.content_version == draft.version,
            )
        )
        image = existing_res.scalar_one_or_none()

        if image:
            image.prompt = res.prompt
            image.alt_text = res.alt_text
            image.image_url = res.image_url
            image.aspect_ratio = res.aspect_ratio
            image.style = res.style
            image.provider = res.provider
            image.is_demo = res.is_demo
            image.status = "generated"
            image.updated_at = _now()
        else:
            image = ContentImage(
                project_id=project_id,
                generated_content_id=draft.id,
                content_version=draft.version,
                prompt=res.prompt,
                alt_text=res.alt_text,
                image_url=res.image_url,
                aspect_ratio=res.aspect_ratio,
                style=res.style,
                provider=res.provider,
                is_demo=res.is_demo,
                status="generated",
            )
            self.db.add(image)

        # IMPORTANT: Draft status (draft vs approved) is strictly untouched!
        await self.db.commit()
        await self.db.refresh(image)
        return image

    async def update_image(
        self,
        project_id: UUID,
        prompt: Optional[str] = None,
        alt_text: Optional[str] = None,
        style: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
    ) -> ContentImage:
        _, draft = await self._get_project_and_draft(project_id)
        if draft.status == "approved":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This post has been approved and its creative assets are locked. Create a new draft version first."
            )

        image = await self.get_current_image(project_id)
        if not image:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No creative image found to update.")

        ratio_changed = aspect_ratio is not None and aspect_ratio != image.aspect_ratio
        style_changed = style is not None and style != image.style

        if prompt is not None:
            image.prompt = prompt
        if alt_text is not None:
            image.alt_text = alt_text
        if style is not None:
            image.style = style
        if aspect_ratio is not None:
            image.aspect_ratio = aspect_ratio

        # When aspect_ratio or style changes in demo mode, immediately re-render the image URL
        if (ratio_changed or style_changed) and image.is_demo:
            product_res = await self.db.execute(select(Product).where(Product.id == draft.product_id))
            product = product_res.scalar_one_or_none()
            post_content = draft.content or {}
            hook = post_content.get("hook")
            body = post_content.get("body")
            pillar = post_content.get("pillar")
            product_name = None
            target_audience = None
            if product:
                profile = product.profile or {}
                product_name = profile.get("name") or product.name
                target_audience = profile.get("target_audience")
            elif draft.context_snapshot:
                product_name = draft.context_snapshot.get("product_name")

            req = ImageGenerationRequest(
                prompt=image.prompt,
                aspect_ratio=image.aspect_ratio,
                style=image.style,
                alt_text=image.alt_text,
                product_name=product_name,
                hook=hook,
                body=body,
                pillar=pillar,
                target_audience=target_audience,
            )
            provider = get_image_provider(image.provider)
            res = await provider.generate_image(req)
            image.image_url = res.image_url

        image.status = "saved"
        image.updated_at = _now()

        await self.db.commit()
        await self.db.refresh(image)
        return image

    async def delete_image(self, project_id: UUID) -> bool:
        _, draft = await self._get_project_and_draft(project_id)
        if draft.status == "approved":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This post has been approved and its creative assets cannot be deleted. Create a new draft version first."
            )

        image = await self.get_current_image(project_id)
        if not image:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No creative image found to delete.")

        await self.db.delete(image)
        await self.db.commit()
        return True


def serialize_image(image: Optional[ContentImage], draft_version: int) -> Optional[Dict[str, Any]]:
    if not image:
        return None
    return {
        "id": str(image.id),
        "project_id": str(image.project_id),
        "generated_content_id": str(image.generated_content_id),
        "content_version": image.content_version,
        "version_matches_post": image.content_version == draft_version,
        "prompt": image.prompt,
        "alt_text": image.alt_text,
        "image_url": image.image_url,
        "aspect_ratio": image.aspect_ratio,
        "style": image.style,
        "provider": image.provider,
        "is_demo": image.is_demo,
        "status": image.status,
        "created_at": image.created_at,
        "updated_at": image.updated_at,
    }
