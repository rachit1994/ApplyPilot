"""Login-gate API: surface providers awaiting login and let the dashboard resume.

When Direct Apply hits a provider login wall it pauses (jobs parked
``awaiting_login``). The dashboard polls ``/login/pending`` to show "Awaiting
login: <domain>", and POSTs ``/login/resume`` after you've signed in — which
clears the gate and re-queues the parked jobs behind your session.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from applypilot.apply import login_gate

router = APIRouter()


class ResumeRequest(BaseModel):
    domain: str | None = None


@router.get("/login/pending")
def login_pending() -> dict:
    return {"paused": login_gate.is_paused(), "pending": login_gate.pending()}


@router.post("/login/resume")
def login_resume(req: ResumeRequest | None = None) -> dict:
    from applypilot.apply.launcher import resume_login

    domain = req.domain if req else None
    return resume_login(domain)
