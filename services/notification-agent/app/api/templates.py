"""Notification templates, managed from the Control Panel (admin only).

GET    /notifications/templates               every template (built-ins + custom)
GET    /notifications/templates/{name}        one, with its default and placeholders
POST   /notifications/templates               create a custom template
PUT    /notifications/templates/{name}        edit (a built-in's edit is stored as an override)
DELETE /notifications/templates/{name}        restore a built-in / delete a custom one
POST   /notifications/templates/{name}/preview  render unsaved text with sample values
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from jinja2 import TemplateError
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import DataResponse
from app.services import template_store
from app.services.template_store import TemplateValidationError
from shared.auth import CurrentUser
from shared.auth.middleware import require_role

router = APIRouter(dependencies=[Depends(require_role("admin"))])


class TemplateIn(BaseModel):
    subject: str = Field(..., max_length=500)
    body: str = Field(..., max_length=20000)
    description: str = Field("", max_length=500)
    recipient: Optional[str] = Field(None, max_length=500)
    extra_recipients: list[str] = Field(default_factory=list, max_length=20)
    enabled: bool = True


class TemplateCreate(TemplateIn):
    name: str = Field(..., max_length=64)


class PreviewIn(BaseModel):
    subject: str = Field(..., max_length=500)
    body: str = Field(..., max_length=20000)
    recipient: Optional[str] = Field(None, max_length=500)


def _invalid(e: TemplateValidationError) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": "invalid_template", "message": str(e)})


def _summary(t: template_store.Template) -> dict:
    event, default_audience = template_store.TEMPLATE_INFO.get(t.name, ("notification.send", "Whoever the sender names"))
    audience = t.recipient if (t.recipient and t.recipient.strip()) else default_audience
    return {
        "name": t.name, "event": event, "recipient": audience, "configured_recipient": t.recipient,
        "description": t.description, "subject": t.subject, "extra_recipients": t.extra_recipients,
        "enabled": t.enabled, "is_custom": t.is_custom, "customised": t.customised,
        "updated_by": t.updated_by, "updated_at": t.updated_at,
    }


def _detail(t: template_store.Template) -> dict:
    out = _summary(t) | {"body": t.body}
    if t.is_custom:
        out["default"] = None
        out["placeholders"] = template_store.placeholders(t.subject, t.body, t.recipient or "")
        out["placeholders_fixed"] = False
    else:
        subject, body = template_store.builtin_source(t.name)
        default_audience = template_store.TEMPLATE_INFO.get(t.name, ("", ""))[1]
        out["default"] = {"subject": subject, "body": body, "recipient": default_audience}
        out["placeholders"] = template_store.allowed_placeholders(t.name)
        out["placeholders_fixed"] = True
    return out


async def _get_or_404(db: AsyncSession, name: str) -> template_store.Template:
    t = await template_store.get(db, name)
    if t is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": f"no template '{name}'"})
    return t


@router.get("", response_model=DataResponse)
async def list_templates(db: AsyncSession = Depends(get_db)):
    templates = await template_store.list_all(db)
    return DataResponse(data=[_summary(t) for t in templates], meta={"count": len(templates)})


@router.get("/{name}", response_model=DataResponse)
async def get_template(name: str, db: AsyncSession = Depends(get_db)):
    return DataResponse(data=_detail(await _get_or_404(db, name)))


@router.post("", response_model=DataResponse, status_code=201)
async def create_template(
    payload: TemplateCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_role("admin")),
):
    recipients = template_store.parse_recipients(payload.extra_recipients)
    try:
        template_store.validate(
            payload.name, payload.subject, payload.body, recipients,
            recipient=payload.recipient, creating=True,
        )
    except TemplateValidationError as e:
        raise _invalid(e)
    if await template_store.exists(db, payload.name):
        raise HTTPException(status_code=409, detail={"code": "exists", "message": f"'{payload.name}' already exists"})
    t = await template_store.save(
        db, payload.name, subject=payload.subject, body=payload.body, description=payload.description,
        extra_recipients=recipients, enabled=payload.enabled, is_custom=True, updated_by=user.email,
        recipient=payload.recipient,
    )
    return DataResponse(data=_detail(t))


@router.put("/{name}", response_model=DataResponse)
async def update_template(
    name: str,
    payload: TemplateIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_role("admin")),
):
    current = await _get_or_404(db, name)
    recipients = template_store.parse_recipients(payload.extra_recipients)
    try:
        template_store.validate(
            name, payload.subject, payload.body, recipients,
            recipient=payload.recipient,
        )
    except TemplateValidationError as e:
        raise _invalid(e)
    t = await template_store.save(
        db, name, subject=payload.subject, body=payload.body,
        description=payload.description or current.description,
        extra_recipients=recipients, enabled=payload.enabled, is_custom=current.is_custom, updated_by=user.email,
        recipient=payload.recipient,
    )
    return DataResponse(data=_detail(t))


@router.delete("/{name}", response_model=DataResponse)
async def delete_template(name: str, db: AsyncSession = Depends(get_db)):
    current = await _get_or_404(db, name)
    removed = await template_store.delete(db, name)
    if current.is_custom:
        return DataResponse(data={"name": name, "deleted": removed})
    return DataResponse(data=_detail(await _get_or_404(db, name)) | {"restored": removed})


@router.post("/{name}/preview", response_model=DataResponse)
async def preview_template(name: str, payload: PreviewIn, db: AsyncSession = Depends(get_db)):
    """Renders the given text with a sample value for each placeholder."""
    await _get_or_404(db, name)
    try:
        names = template_store.placeholders(payload.subject, payload.body, payload.recipient or "")
        allowed = template_store.allowed_placeholders(name)
        context = template_store.sample_context(sorted(set(names) | set(allowed or [])))
        subject, body = template_store.render_source(payload.subject, payload.body, context, strict=False)
        rendered_recip = template_store.render_recipient_source(payload.recipient, context, strict=False)
    except TemplateError as e:
        raise HTTPException(status_code=422, detail={"code": "preview_failed", "message": str(e)})
    return DataResponse(data={"subject": subject, "body": body, "recipient": rendered_recip})
