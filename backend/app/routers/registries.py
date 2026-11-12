from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import registries
from ..db import get_db
from ..deps import audit, require
from ..models import Registry, User
from ..security import encrypt

router = APIRouter(prefix="/api/registries", tags=["registries"])


class RegistryIn(BaseModel):
    url: str = Field(min_length=1, max_length=255)
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1)
    verify: bool = True


class RegistryPatch(BaseModel):
    username: str | None = None
    password: str | None = None
    verify: bool = True


def out(r: Registry) -> dict:
    return {"id": r.id, "url": r.url, "username": r.username, "created_at": r.created_at}


@router.get("")
def list_registries(_: User = Depends(require("admin")), db: Session = Depends(get_db)):
    return [out(r) for r in db.scalars(select(Registry).order_by(Registry.url))]


@router.post("")
def add_registry(data: RegistryIn, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    url = registries.normalize_url(data.url)
    if db.scalar(select(Registry).where(Registry.url == url)):
        raise HTTPException(409, "Registry already exists")
    if data.verify:
        ok, msg = registries.test_login(url, data.username, data.password)
        if not ok:
            raise HTTPException(400, f"docker login failed: {msg}")
    r = Registry(url=url, username=data.username.strip(), password_enc=encrypt(data.password))
    db.add(r)
    db.commit()
    registries.write_config()
    audit(db, user, "registry.add", url, data.username)
    return out(r)


@router.patch("/{reg_id}")
def update_registry(reg_id: int, data: RegistryPatch, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    r = db.get(Registry, reg_id)
    if not r:
        raise HTTPException(404, "Not found")
    if data.username:
        r.username = data.username.strip()
    if data.password:
        if data.verify:
            ok, msg = registries.test_login(r.url, r.username, data.password)
            if not ok:
                raise HTTPException(400, f"docker login failed: {msg}")
        r.password_enc = encrypt(data.password)
    db.commit()
    registries.write_config()
    audit(db, user, "registry.update", r.url)
    return out(r)


@router.delete("/{reg_id}")
def delete_registry(reg_id: int, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    r = db.get(Registry, reg_id)
    if not r:
        raise HTTPException(404, "Not found")
    db.delete(r)
    db.commit()
    registries.write_config()
    audit(db, user, "registry.delete", r.url)
    return {"ok": True}
