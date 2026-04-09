"""Admin-only management endpoints.

Endpoints:
  GET    /admin/proposals              — list all submitted consultations
  GET    /admin/proposals/{id}         — proposal detail + full proposal text
  PATCH  /admin/proposals/{id}/status  — update admin_status
  POST   /admin/analyze                — analytical policy draft from multiple proposals
  GET    /admin/trends                 — category × severity heatmap aggregation
  POST   /admin/trends/summary         — Gemini-generated management brief
  POST   /admin/departments            — add a new department
  PUT    /admin/departments/{id}       — rename a department
  DELETE /admin/departments/{id}       — delete a department
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.ai.llm import get_gemini
from app.ai.prompts import build_analytical_messages, build_trends_summary_messages
from app.auth.deps import require_admin
from app.db.session import get_conn

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)

_ADMIN_STATUSES = {"New", "In Progress", "Resolved", "Archived"}


# ── Proposals ──────────────────────────────────────────────────────────────


@router.get("/proposals")
async def list_proposals(conn=Depends(get_conn)) -> list[dict]:
    """Return all submitted consultations ordered by creation date (desc)."""
    rows = await conn.fetch(
        """
        SELECT
            id::text,
            department,
            category,
            COALESCE(severity, 0) AS severity,
            COALESCE(feedback, 0) AS feedback,
            summary,
            user_name,
            user_email,
            admin_status,
            is_submitted,
            created_at
        FROM consultations
        WHERE is_submitted = TRUE
        ORDER BY created_at DESC
        """
    )
    return [dict(r) for r in rows]


@router.get("/proposals/{consultation_id}")
async def get_proposal(consultation_id: str, conn=Depends(get_conn)) -> dict:
    """Return full detail of a submitted proposal including the proposal text."""
    row = await conn.fetchrow(
        """
        SELECT
            id::text,
            department,
            category,
            COALESCE(severity, 0) AS severity,
            COALESCE(feedback, 0) AS feedback,
            summary,
            proposal,
            user_name,
            user_email,
            admin_status,
            is_submitted,
            created_at
        FROM consultations
        WHERE id = $1::uuid AND is_submitted = TRUE
        """,
        consultation_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Proposal not found.")
    return dict(row)


class StatusUpdate(BaseModel):
    admin_status: str


@router.patch("/proposals/{consultation_id}/status")
async def update_proposal_status(
    consultation_id: str,
    body: StatusUpdate,
    conn=Depends(get_conn),
) -> dict:
    """Update the admin review status of a submitted proposal."""
    if body.admin_status not in _ADMIN_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"admin_status must be one of: {sorted(_ADMIN_STATUSES)}",
        )
    row = await conn.fetchrow(
        """
        UPDATE consultations
        SET admin_status = $1
        WHERE id = $2::uuid AND is_submitted = TRUE
        RETURNING id::text, admin_status
        """,
        body.admin_status,
        consultation_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Proposal not found.")
    return dict(row)


# ── Analytical mode ────────────────────────────────────────────────────────


class AnalyzeRequest(BaseModel):
    proposal_ids: list[str]
    language: str = "en"


@router.post("/analyze")
async def analyze_proposals(
    body: AnalyzeRequest,
    conn=Depends(get_conn),
) -> dict:
    """Generate a strategic policy draft by synthesising multiple proposals."""
    if not body.proposal_ids:
        raise HTTPException(status_code=422, detail="No proposal IDs provided.")

    rows = await conn.fetch(
        """
        SELECT summary, proposal
        FROM consultations
        WHERE id = ANY($1::uuid[]) AND is_submitted = TRUE
        """,
        body.proposal_ids,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No matching proposals found.")

    summaries_text = "\n\n---\n\n".join(
        f"[Proposal {i + 1}]\n"
        f"Summary: {r['summary'] or '(none)'}\n\n"
        f"Proposal:\n{r['proposal'] or '(none)'}"
        for i, r in enumerate(rows)
    )
    system_prompt, user_message = build_analytical_messages(
        summaries=summaries_text, count=len(rows), language=body.language
    )
    llm = get_gemini()
    response = await llm.ainvoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_message)]
    )
    return {"draft": response.content, "proposal_count": len(rows)}


# ── Trends ─────────────────────────────────────────────────────────────────


def _parse_date(value: str | None) -> date | None:
    """Parse an ISO date string (YYYY-MM-DD) into a datetime.date, or return None."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _build_trends_where(
    department: str | None,
    date_from: str | None,
    date_to: str | None,
) -> tuple[str, list]:
    """Build WHERE clause and param list for trends queries.

    asyncpg requires datetime.date objects (not strings) for date comparisons.
    """
    conditions = ["TRUE"]
    params: list = []
    if department:
        params.append(department)
        conditions.append(f"department = ${len(params)}")
    d_from = _parse_date(date_from)
    if d_from is not None:
        params.append(d_from)
        conditions.append(f"created_at::date >= ${len(params)}")
    d_to = _parse_date(date_to)
    if d_to is not None:
        # advance by one day in Python so we can use a simple < comparison
        params.append(d_to + timedelta(days=1))
        conditions.append(f"created_at::date < ${len(params)}")
    return "WHERE " + " AND ".join(conditions), params


@router.get("/trends")
async def get_trends(
    department: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    conn=Depends(get_conn),
) -> dict:
    """Return category × severity heatmap data with optional filters."""
    where_clause, params = _build_trends_where(department, date_from, date_to)

    heatmap_rows = await conn.fetch(
        f"""
        SELECT
            COALESCE(category, 'Unknown') AS category,
            COALESCE(severity, 0)::int    AS severity,
            COUNT(*)::int                 AS count
        FROM consultations
        {where_clause}
        GROUP BY category, severity
        ORDER BY category, severity
        """,
        *params,
    )

    dept_rows = await conn.fetch(
        f"""
        SELECT
            COALESCE(department, 'Unknown') AS department,
            COUNT(*)::int                   AS consultation_count,
            COUNT(*) FILTER (WHERE is_submitted = TRUE)::int AS submitted_count,
            ROUND(AVG(COALESCE(severity, 0))::numeric, 2)::float AS avg_severity
        FROM consultations
        {where_clause}
        GROUP BY department
        ORDER BY consultation_count DESC
        """,
        *params,
    )

    return {
        "heatmap": [dict(r) for r in heatmap_rows],
        "by_department": [dict(r) for r in dept_rows],
    }


class TrendsSummaryRequest(BaseModel):
    department: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    language: str = "en"


@router.post("/trends/summary")
async def generate_trends_summary(
    body: TrendsSummaryRequest,
    conn=Depends(get_conn),
) -> dict:
    """Call Gemini to generate a management brief from recent consultation trends."""
    where_clause, params = _build_trends_where(body.department, body.date_from, body.date_to)

    rows = await conn.fetch(
        f"""
        SELECT
            COALESCE(category, 'Unknown') AS category,
            COALESCE(department, 'Unknown') AS department,
            COALESCE(severity, 0)::int AS severity,
            COUNT(*)::int AS count
        FROM consultations
        {where_clause}
        GROUP BY category, department, severity
        ORDER BY count DESC, severity DESC
        LIMIT 50
        """,
        *params,
    )
    if not rows:
        raise HTTPException(
            status_code=404,
            detail="No trend data available. Submit some proposals first.",
        )

    data_json = json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2)
    system_prompt, user_message = build_trends_summary_messages(data_json, language=body.language)
    llm = get_gemini()
    response = await llm.ainvoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_message)]
    )
    return {"summary": response.content}


# ── Departments ────────────────────────────────────────────────────────────


class DepartmentCreate(BaseModel):
    name: str


@router.post("/departments", status_code=201)
async def create_department(
    body: DepartmentCreate,
    conn=Depends(get_conn),
) -> dict:
    """Add a new department."""
    row = await conn.fetchrow(
        "INSERT INTO departments (name) VALUES ($1) RETURNING id::text, name",
        body.name,
    )
    return dict(row)


class DepartmentUpdate(BaseModel):
    name: str


@router.put("/departments/{department_id}")
async def update_department(
    department_id: str,
    body: DepartmentUpdate,
    conn=Depends(get_conn),
) -> dict:
    """Rename a department."""
    row = await conn.fetchrow(
        "UPDATE departments SET name = $1 WHERE id = $2::uuid RETURNING id::text, name",
        body.name,
        department_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Department not found.")
    return dict(row)


@router.delete("/departments/{department_id}", status_code=204)
async def delete_department(
    department_id: str,
    conn=Depends(get_conn),
) -> None:
    """Delete a department (does not cascade to consultations)."""
    result = await conn.execute(
        "DELETE FROM departments WHERE id = $1::uuid",
        department_id,
    )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Department not found.")
