"""Scope HTTP record access; workers use unscoped independent sessions."""

from models import Claim


def scoped(query, db):
    actor = db.info.get("actor_id")
    return query.where(Claim.owner_id == actor) if actor is not None else query


def owns(db, claim):
    actor = db.info.get("actor_id")
    return claim is not None and (actor is None or claim.owner_id == actor)
