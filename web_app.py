from pathlib import Path

from flask import Flask, jsonify, render_template, request, session, redirect
import math
import os
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import api
from app_store import AppStore
from accurate_integration import AccurateClient, AccurateConfigError


# ============================================================
# APP CONFIGURATION
# ============================================================

app = Flask(
    __name__,
    static_folder="static",
    template_folder="templates",
)

# Load the normal web secret from the environment when available.
app.secret_key = os.getenv(
    "WEB_SECRET_KEY",
    secrets.token_hex(32),
)

PAGE_SIZE_DEFAULT = 25
PAGE_SIZE_MAX = 100

QUALITY_PAGE_SIZE = 200
QUALITY_WORKERS = 6
QUALITY_TTL = 900

ANALYTICS_TTL = 120

# IMPORTANT:
# The worker that scans old Closed Won Opportunities is OFF by default.
# Automatic sync is triggered only from the Opportunity mutation route.
ACCURATE_SYNC_WORKER_ENABLED = (
    os.getenv(
        "ACCURATE_SYNC_WORKER",
        "false",
    ).strip().lower()
    in {"1", "true", "yes", "on"}
)


QUALITY_FIELDS = (
    "firstName",
    "lastName",
    "emailAddress",
    "phoneNumber",
    "accountId",
    "title",
    "addressCity",
    "addressCountry",
)

QUALITY_BUCKETS = (
    "complete",
    "partial",
    "minimal",
)

STAGES = (
    "Prospecting",
    "Qualification",
    "Proposal",
    "Negotiation",
    "Closed Won",
    "Closed Lost",
)

TASK_STATUSES = (
    "Not Started",
    "In Progress",
    "Completed",
    "Canceled",
    "Deferred",
)

CASE_STATUSES = (
    "New",
    "Assigned",
    "Pending",
    "Closed",
)

CASE_PRIORITIES = (
    "Normal",
    "Urgent",
)

CASE_TYPES = (
    "Question",
    "Incident",
    "Problem",
)


# ============================================================
# PERSISTENT STORES / ACCURATE CLIENT
# ============================================================

store = AppStore(
    Path(
        os.getenv(
            "APP_STORE_DB",
            "runtime/app.sqlite3",
        )
    )
)

accurate = AccurateClient(store)


# ============================================================
# BACKGROUND JOB STATE
# ============================================================

_quality_lock = threading.Lock()

_quality_job = {
    "running": False,
    "error": None,
    "started_at": None,
    "finished_at": None,
}

_analytics_lock = threading.Lock()

_analytics_cache = {
    "data": None,
    "expires_at": 0.0,
    "running": False,
    "error": None,
}


# ============================================================
# GENERIC HELPERS
# ============================================================

def clean(value):
    return str(value or "").strip()


def normalize_records(result):
    if isinstance(result, dict):
        rows = (
            result.get("list", [])
            if isinstance(result.get("list", []), list)
            else []
        )

        try:
            total = int(
                result.get(
                    "total",
                    len(rows),
                )
                or 0
            )
        except (TypeError, ValueError):
            total = len(rows)

        return rows, total

    if isinstance(result, list):
        return result, len(result)

    return [], 0


def safe_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def page_args(default_size=PAGE_SIZE_DEFAULT):
    page = max(
        1,
        safe_int(
            request.args.get("page"),
            1,
        ),
    )

    page_size = max(
        1,
        min(
            PAGE_SIZE_MAX,
            safe_int(
                request.args.get(
                    "page_size"
                ),
                default_size,
            ),
        ),
    )

    offset = (
        page - 1
    ) * page_size

    return page, page_size, offset


def contact_name(row):
    name = clean(
        row.get("name")
    )

    if name:
        return name

    return (
        " ".join(
            x
            for x in (
                clean(
                    row.get(
                        "firstName"
                    )
                ),
                clean(
                    row.get(
                        "lastName"
                    )
                ),
            )
            if x
        )
        or "Untitled Contact"
    )


def completeness(row):
    filled = sum(
        1
        for field in QUALITY_FIELDS
        if clean(
            row.get(field)
        )
    )

    score = round(
        (
            filled
            / len(
                QUALITY_FIELDS
            )
        )
        * 100
    )

    if score >= 100:
        status = "complete"
    elif score >= 60:
        status = "partial"
    else:
        status = "minimal"

    return score, status


def decorate_contact(row):
    item = dict(
        row or {}
    )

    score, status = completeness(
        item
    )

    item[
        "displayName"
    ] = contact_name(item)

    item[
        "completenessScore"
    ] = score

    item[
        "completenessStatus"
    ] = status

    return item


def normalize_phone(value):
    raw = clean(value)

    compact = "".join(
        ch
        for ch in raw
        if ch.isdigit()
        or ch == "+"
    )

    if compact.startswith("08"):
        compact = "+62" + compact[1:]

    if compact.startswith("+62"):
        digits = compact[3:]
        return "+62 " + digits

    return raw


def parse_amount(value):
    if value in (
        None,
        "",
    ):
        return None

    try:
        return float(
            str(value)
            .replace(",", "")
            .strip()
        )
    except ValueError as exc:
        raise api.EspoCRMError(
            "Amount harus berupa angka."
        ) from exc


def total(entity):
    result = api.get_collection(
        entity,
        offset=0,
        max_size=1,
    )

    _, count = normalize_records(
        result
    )

    return count


def fetch_all_pages(
    entity,
    page_size=200,
    fields=(),
    order_by=None,
    order="asc",
    max_records=50000,
):
    """
    Fetch a large collection in server-side pages for background analytics only.
    The normal data-table routes remain paginated and do not load everything
    into the browser.
    """
    fields = list(
        fields or []
    )

    first = api.get_collection_advanced(
        entity,
        offset=0,
        max_size=page_size,
        select=fields or None,
        order_by=order_by,
        order=order,
    )

    rows, total_count = normalize_records(
        first
    )

    rows = list(rows)

    target = min(
        int(total_count),
        int(max_records),
    )

    offset = page_size

    while offset < target:
        chunk = api.get_collection_advanced(
            entity,
            offset=offset,
            max_size=page_size,
            select=fields or None,
            order_by=order_by,
            order=order,
        )

        chunk_rows, _ = normalize_records(
            chunk
        )

        if not chunk_rows:
            break

        rows.extend(
            chunk_rows
        )

        offset += page_size

    return rows[:max_records]


# ============================================================
# CONTACT QUALITY CACHE
# ============================================================

def quality_ready():
    return store.quality_count() > 0


def fetch_quality_page(offset):
    result = api.get_collection(
        "Contact",
        offset=offset,
        max_size=QUALITY_PAGE_SIZE,
        select=(
            "id",
            "name",
            "firstName",
            "lastName",
            "emailAddress",
            "phoneNumber",
            "title",
            "addressCity",
            "addressCountry",
            "description",
            "middleName",
            "addressStreet",
            "addressPostalCode",
            "accountId",
            "accountName",
            "createdAt",
            "modifiedAt",
        ),
        order_by="createdAt",
        order="desc",
    )

    rows, _ = normalize_records(
        result
    )

    return rows


def scan_quality():
    with _quality_lock:
        if _quality_job["running"]:
            return False

        _quality_job.update(
            {
                "running": True,
                "error": None,
                "started_at": time.time(),
                "finished_at": None,
            }
        )

    try:
        result = api.get_collection(
            "Contact",
            offset=0,
            max_size=1,
        )

        _, count = normalize_records(
            result
        )

        store.start_quality_scan(
            count
        )

        if count == 0:
            store.finish_quality_scan(
                True,
                None,
            )
            return True

        offsets = list(
            range(
                0,
                count,
                QUALITY_PAGE_SIZE,
            )
        )

        keep_ids = set()

        with ThreadPoolExecutor(
            max_workers=QUALITY_WORKERS
        ) as pool:
            futures = {
                pool.submit(
                    fetch_quality_page,
                    offset,
                ): offset
                for offset in offsets
            }

            for future in as_completed(
                futures
            ):
                rows = future.result()

                tombstones = (
                    store.tombstoned_quality_ids()
                )

                for row in rows:
                    contact_id = str(
                        row.get("id")
                        or ""
                    )

                    if (
                        not contact_id
                        or contact_id
                        in tombstones
                    ):
                        continue

                    keep_ids.add(
                        contact_id
                    )

                    item = decorate_contact(
                        row
                    )

                    store.upsert_quality(
                        item
                    )

        store.prune_quality(
            keep_ids
        )

        store.finish_quality_scan(
            True,
            None,
        )

        with _quality_lock:
            _quality_job.update(
                {
                    "error": None,
                    "finished_at": time.time(),
                }
            )

        return True

    except Exception as exc:
        store.finish_quality_scan(
            False,
            str(exc),
        )

        with _quality_lock:
            _quality_job.update(
                {
                    "error": str(exc),
                    "finished_at": time.time(),
                }
            )

        return False

    finally:
        with _quality_lock:
            _quality_job[
                "running"
            ] = False


def start_quality_scan(
    force=False
):
    with _quality_lock:
        running = _quality_job[
            "running"
        ]

    state = store.quality_state()

    if running:
        return False

    if (
        not force
        and state.get("ready")
        and state.get(
            "updated_at",
            0,
        )
        + QUALITY_TTL
        > time.time()
    ):
        return False

    thread = threading.Thread(
        target=scan_quality,
        daemon=True,
    )

    thread.start()

    return True


def quality_payload():
    state = store.quality_state()

    counts = store.quality_counts()

    with _quality_lock:
        running = _quality_job[
            "running"
        ]

        error = _quality_job[
            "error"
        ]

    return {
        "ready": bool(
            state.get("ready")
        )
        or store.quality_count() > 0,
        "running": running,
        "error": error
        or state.get("error"),
        "updated_at": state.get(
            "updated_at"
        ),
        "counts": counts,
        "samples": {
            key: store.quality_page(
                key,
                1,
                5,
            )["records"]
            for key in QUALITY_BUCKETS
        },
    }


def aggregate_quality_relationship():
    counts = store.quality_counts()

    complete = counts.get(
        "complete",
        0,
    )

    partial = counts.get(
        "partial",
        0,
    )

    minimal = counts.get(
        "minimal",
        0,
    )

    return {
        "complete": complete,
        "partial": partial,
        "minimal": minimal,
        "missing_context": (
            partial
            + minimal
        ),
    }


# ============================================================
# ANALYTICS
# ============================================================

def fetch_entity_pages_simple(
    entity,
    fields,
    page_size=200,
    order_by=None,
    order="asc",
    workers=6,
):
    """
    Reliable background fetcher for analytics.
    It is deliberately server-side and does not feed all data to the browser.
    """
    try:
        first = api.get_collection(
            entity,
            offset=0,
            max_size=page_size,
            select=list(fields),
            order_by=order_by,
            order=order,
        )

    except Exception:
        first = api.get_collection(
            entity,
            offset=0,
            max_size=page_size,
        )

    rows, total_count = normalize_records(
        first
    )

    rows = list(rows)

    total_count = max(
        0,
        int(
            total_count
            or 0
        ),
    )

    if total_count <= page_size:
        return rows

    offsets = list(
        range(
            page_size,
            total_count,
            page_size,
        )
    )

    def load_page(offset):
        try:
            result = api.get_collection(
                entity,
                offset=offset,
                max_size=page_size,
                select=list(fields),
                order_by=order_by,
                order=order,
            )

        except Exception:
            result = api.get_collection(
                entity,
                offset=offset,
                max_size=page_size,
            )

        page_rows, _ = normalize_records(
            result
        )

        return page_rows

    worker_count = max(
        1,
        min(
            int(workers),
            len(offsets),
        ),
    )

    with ThreadPoolExecutor(
        max_workers=worker_count
    ) as pool:
        futures = {
            pool.submit(
                load_page,
                offset,
            ): offset
            for offset in offsets
        }

        pages = []

        for future in as_completed(
            futures
        ):
            offset = futures[
                future
            ]

            page_rows = future.result()

            pages.append(
                (
                    offset,
                    page_rows,
                )
            )

    for _, page_rows in sorted(
        pages,
        key=lambda item: item[0],
    ):
        rows.extend(
            page_rows
        )

    return rows[:total_count]


def analytics_snapshot():
    now = time.time()

    with _analytics_lock:
        if (
            _analytics_cache["data"]
            is not None
            and _analytics_cache[
                "expires_at"
            ]
            > now
        ):
            return _analytics_cache[
                "data"
            ]

        if _analytics_cache[
            "running"
        ]:
            return None

        _analytics_cache[
            "running"
        ] = True

        _analytics_cache[
            "error"
        ] = None

    errors = {}

    try:
        try:
            opportunity_rows = (
                fetch_entity_pages_simple(
                    "Opportunity",
                    (
                        "id",
                        "name",
                        "stage",
                        "amount",
                        "amountCurrency",
                        "closeDate",
                        "assignedUserName",
                        "assignedUserId",
                        "accountName",
                        "contactName",
                        "createdAt",
                        "modifiedAt",
                    ),
                    order_by="modifiedAt",
                    order="desc",
                )
            )

        except Exception as exc:
            opportunity_rows = []
            errors[
                "Opportunity"
            ] = str(exc)

        try:
            task_rows = (
                fetch_entity_pages_simple(
                    "Task",
                    (
                        "id",
                        "name",
                        "status",
                        "priority",
                        "dateEnd",
                        "assignedUserName",
                        "assignedUserId",
                        "parentName",
                        "parentType",
                        "parentId",
                        "contactId",
                        "contactName",
                        "createdAt",
                        "modifiedAt",
                    ),
                    order_by="dateEnd",
                    order="asc",
                )
            )

        except Exception as exc:
            task_rows = []
            errors[
                "Task"
            ] = str(exc)

        try:
            cases_rows = (
                fetch_entity_pages_simple(
                    "Case",
                    (
                        "id",
                        "name",
                        "status",
                        "priority",
                        "type",
                        "assignedUserName",
                        "assignedUserId",
                        "contactId",
                        "contactName",
                        "accountId",
                        "accountName",
                        "createdAt",
                        "modifiedAt",
                    ),
                    order_by="modifiedAt",
                    order="desc",
                )
            )

        except Exception as exc:
            cases_rows = []
            errors[
                "Case"
            ] = str(exc)

        stage_counts = {
            stage: 0
            for stage in STAGES
        }

        stage_amount = {
            stage: 0.0
            for stage in STAGES
        }

        period = {}
        pic_counts = {}

        for row in opportunity_rows:
            stage = (
                clean(
                    row.get("stage")
                )
                or "Unknown"
            )

            stage_counts.setdefault(
                stage,
                0,
            )

            stage_counts[
                stage
            ] += 1

            try:
                stage_amount.setdefault(
                    stage,
                    0.0,
                )

                stage_amount[
                    stage
                ] += float(
                    row.get(
                        "amount"
                    )
                    or 0
                )

            except (
                TypeError,
                ValueError,
            ):
                pass

            date_value = clean(
                row.get(
                    "closeDate"
                )
            )

            if date_value:
                key = date_value[
                    :7
                ]

                period[
                    key
                ] = (
                    period.get(
                        key,
                        0,
                    )
                    + 1
                )

            pic = (
                clean(
                    row.get(
                        "assignedUserName"
                    )
                )
                or "Unassigned"
            )

            pic_counts[
                pic
            ] = (
                pic_counts.get(
                    pic,
                    0,
                )
                + 1
            )

        task_status = {
            status: 0
            for status in TASK_STATUSES
        }

        task_pic = {}
        overdue = 0
        now_dt = datetime.now()

        for row in task_rows:
            status = (
                clean(
                    row.get(
                        "status"
                    )
                )
                or "Unknown"
            )

            task_status.setdefault(
                status,
                0,
            )

            task_status[
                status
            ] += 1

            pic = (
                clean(
                    row.get(
                        "assignedUserName"
                    )
                )
                or "Unassigned"
            )

            task_pic[
                pic
            ] = (
                task_pic.get(
                    pic,
                    0,
                )
                + 1
            )

            end = clean(
                row.get(
                    "dateEnd"
                )
            )

            if end:
                try:
                    end_dt = datetime.strptime(
                        end,
                        "%Y-%m-%d %H:%M:%S",
                    )

                    if (
                        end_dt < now_dt
                        and status
                        not in (
                            "Completed",
                            "Canceled",
                        )
                    ):
                        overdue += 1

                except ValueError:
                    pass

        case_status = {
            status: 0
            for status in CASE_STATUSES
        }

        urgent_cases = 0

        for row in cases_rows:
            status = (
                clean(
                    row.get(
                        "status"
                    )
                )
                or "Unknown"
            )

            case_status.setdefault(
                status,
                0,
            )

            case_status[
                status
            ] += 1

            if (
                clean(
                    row.get(
                        "priority"
                    )
                ).lower()
                == "urgent"
            ):
                urgent_cases += 1

        pic_workload = {}

        for name, value in (
            pic_counts.items()
        ):
            pic_workload.setdefault(
                name,
                {
                    "opportunities": 0,
                    "tasks": task_pic.get(
                        name,
                        0,
                    ),
                },
            )

            pic_workload[
                name
            ][
                "opportunities"
            ] = value

        for name, value in (
            task_pic.items()
        ):
            pic_workload.setdefault(
                name,
                {
                    "opportunities": 0,
                    "tasks": 0,
                },
            )

            pic_workload[
                name
            ][
                "tasks"
            ] = value

        quality = (
            aggregate_quality_relationship()
        )

        analytics = {
            "opportunity_stage": stage_counts,
            "opportunity_amount": stage_amount,
            "opportunity_period": dict(
                sorted(
                    period.items()
                )
            ),
            "opportunity_pic": dict(
                sorted(
                    pic_counts.items(),
                    key=lambda x: x[1],
                    reverse=True,
                )[:12]
            ),
            "task_status": task_status,
            "task_overdue": overdue,
            "pic_workload": dict(
                sorted(
                    pic_workload.items(),
                    key=lambda x:
                    x[1]["opportunities"]
                    + x[1]["tasks"],
                    reverse=True,
                )[:12]
            ),
            "data_quality": {
                "complete": quality[
                    "complete"
                ],
                "partial": quality[
                    "partial"
                ],
                "minimal": quality[
                    "minimal"
                ],
            },
            "relationship_health": {
                "with_full_context": quality[
                    "complete"
                ],
                "needs_attention": quality[
                    "partial"
                ],
                "poor_context": quality[
                    "minimal"
                ],
            },
            "meta": {
                "opportunities": len(
                    opportunity_rows
                ),
                "tasks": len(
                    task_rows
                ),
                "cases": len(
                    cases_rows
                ),
                "urgent_cases": urgent_cases,
                "generated_at": time.time(),
                "errors": errors,
                "complete": not errors,
            },
        }

        with _analytics_lock:
            _analytics_cache[
                "data"
            ] = analytics

            _analytics_cache[
                "expires_at"
            ] = (
                time.time()
                + ANALYTICS_TTL
            )

        return analytics

    except Exception as exc:
        with _analytics_lock:
            _analytics_cache[
                "error"
            ] = str(exc)

        return None

    finally:
        with _analytics_lock:
            _analytics_cache[
                "running"
            ] = False


def maybe_start_analytics():
    with _analytics_lock:
        running = (
            _analytics_cache[
                "running"
            ]
        )

        fresh = (
            _analytics_cache[
                "data"
            ]
            is not None
            and _analytics_cache[
                "expires_at"
            ]
            > time.time()
        )

    if not running and not fresh:
        threading.Thread(
            target=analytics_snapshot,
            daemon=True,
        ).start()


def _safe_related_records(loader, record_id, max_size=25):
    """
    Ambil related records tanpa membuat seluruh detail gagal jika
    satu relationship endpoint tidak tersedia di EspoCRM.

    Return:
        (records, error_message_or_none)
    """
    try:
        result = loader(
            record_id,
            max_size=max_size,
        )
        records, _ = normalize_records(result)
        return records, None
    except Exception as exc:
        return [], str(exc)


# ============================================================
# ROUTES - MAIN / HEALTH / STATS
# ============================================================

@app.get("/")
def index():
    return render_template(
        "index.html"
    )


@app.get("/api/health")
def health():
    started = time.perf_counter()

    try:
        result = api.get_collection(
            "Contact",
            offset=0,
            max_size=1,
        )

        _, total_count = normalize_records(
            result
        )

        return jsonify(
            {
                "success": True,
                "total": total_count,
                "response_ms": round(
                    (
                        time.perf_counter()
                        - started
                    )
                    * 1000,
                    2,
                ),
            }
        )

    except Exception as exc:
        return jsonify(
            {
                "success": False,
                "error": str(exc),
                "response_ms": round(
                    (
                        time.perf_counter()
                        - started
                    )
                    * 1000,
                    2,
                ),
            }
        ), 503


@app.get("/api/stats")
def stats():
    try:
        data = {
            "contacts": total(
                "Contact"
            ),
            "accounts": total(
                "Account"
            ),
            "opportunities": total(
                "Opportunity"
            ),
            "tasks": total(
                "Task"
            ),
            "cases": total(
                "Case"
            ),
        }

        q = store.quality_counts()

        state = store.quality_state()

        data.update(q)

        data[
            "quality_ready"
        ] = bool(
            state.get(
                "ready"
            )
        )

        return jsonify(
            {
                "success": True,
                **data,
            }
        )

    except Exception as exc:
        return jsonify(
            {
                "success": False,
                "error": str(exc),
            }
        ), 400


# ============================================================
# ROUTES - CONTACT QUALITY
# ============================================================

@app.get("/api/contacts/quality")
def contacts_quality():
    start_quality_scan()

    return jsonify(
        {
            "success": True,
            **quality_payload(),
        }
    )


@app.post(
    "/api/contacts/quality/refresh"
)
def refresh_quality():
    with _quality_lock:
        _quality_job[
            "running"
        ] = False

    store.invalidate_quality(
        clear_cache=False
    )

    start_quality_scan(
        force=True
    )

    return jsonify(
        {
            "success": True,
            "message": (
                "Quality scan dijalankan di background."
            ),
        }
    )


# ============================================================
# ROUTES - CONTACTS
# ============================================================

@app.get("/api/contacts")
def contacts():
    page, page_size, offset = page_args(
        5
    )

    search = clean(
        request.args.get(
            "search"
        )
    )

    category = (
        clean(
            request.args.get(
                "category"
            )
        )
        or None
    )

    mode = (
        clean(
            request.args.get(
                "mode"
            )
        )
        or "quality"
    )

    sort = (
        clean(
            request.args.get(
                "sort"
            )
        )
        or "createdAt"
    )

    order = (
        clean(
            request.args.get(
                "order"
            )
        )
        or "desc"
    )

    allowed_sort = {
        "createdAt",
        "modifiedAt",
        "name",
    }

    if sort not in allowed_sort:
        sort = "createdAt"

    if order not in {
        "asc",
        "desc",
    }:
        order = "desc"

    if (
        mode == "quality"
        and category in QUALITY_BUCKETS
        and store.quality_count()
        > 0
    ):
        data = store.quality_page(
            category,
            page,
            page_size,
            search,
        )

        return jsonify(
            {
                "success": True,
                "mode": mode,
                **data,
            }
        )

    result = api.get_collection(
        "Contact",
        offset=offset,
        max_size=page_size,
        search=search or None,
        order_by=sort,
        order=order,
    )

    rows, total_count = normalize_records(
        result
    )

    decorated = [
        decorate_contact(row)
        for row in rows
    ]

    if (
        mode == "quality"
        and category in QUALITY_BUCKETS
    ):
        decorated = [
            row
            for row in decorated
            if row[
                "completenessStatus"
            ]
            == category
        ]

        total_count = len(
            decorated
        )

    pages = max(
        1,
        math.ceil(
            total_count
            / page_size
        ),
    )

    return jsonify(
        {
            "success": True,
            "mode": mode,
            "records": decorated,
            "total": total_count,
            "page": page,
            "pages": pages,
            "page_size": page_size,
            "quality_ready": bool(
                store.quality_state().get(
                    "ready"
                )
            )
            or store.quality_count()
            > 0,
            "sort": sort,
            "order": order,
        }
    )


@app.get(
    "/api/contacts/<contact_id>"
)
def contact_detail(
    contact_id
):
    try:
        row = decorate_contact(
            api.get_contact(
                contact_id
            )
        )

        return jsonify(
            {
                "success": True,
                "data": row,
            }
        )

    except Exception as exc:
        return jsonify(
            {
                "success": False,
                "error": str(exc),
            }
        ), 400


@app.get(
    "/api/contacts/<contact_id>/relationships"
)
def contact_relationships(
    contact_id
):
    try:
        result = (
            api.get_contact_relationships(
                contact_id,
                max_size=50,
            )
        )

        return jsonify(
            {
                "success": True,
                "data": result,
            }
        )

    except Exception as exc:
        return jsonify(
            {
                "success": False,
                "error": str(exc),
            }
        ), 400


def resolve_account_id(
    account_id=None,
    new_account_name=None,
):
    account_id = (
        clean(account_id)
        or None
    )

    new_account_name = clean(
        new_account_name
    )

    if (
        account_id
        or not new_account_name
    ):
        return account_id

    matches = api.search_accounts(
        new_account_name,
        max_size=20,
    )

    rows, _ = normalize_records(
        matches
    )

    exact = [
        r
        for r in rows
        if clean(
            r.get("name")
        ).casefold()
        == new_account_name.casefold()
    ]

    if (
        len(exact) == 1
        and exact[0].get("id")
    ):
        return exact[0]["id"]

    account = api.create_record(
        "Account",
        {
            "name": new_account_name
        },
    )

    return (
        account.get("id")
        if isinstance(
            account,
            dict,
        )
        else None
    )


@app.post("/api/contacts")
def create_contact():
    payload = (
        request.get_json(
            silent=True
        )
        or {}
    )

    try:
        account_id = resolve_account_id(
            payload.get(
                "accountId"
            ),
            payload.get(
                "newAccountName"
            ),
        )

        contact_payload = {
            "firstName": clean(
                payload.get(
                    "firstName"
                )
            ),
            "lastName": clean(
                payload.get(
                    "lastName"
                )
            ),
            "emailAddress": clean(
                payload.get(
                    "emailAddress"
                )
            ),
            "phoneNumber": normalize_phone(
                payload.get(
                    "phoneNumber"
                )
            ),
            "accountId": account_id,
            "title": clean(
                payload.get(
                    "title"
                )
            ),
            "addressCity": clean(
                payload.get(
                    "addressCity"
                )
            ),
            "addressCountry": clean(
                payload.get(
                    "addressCountry"
                )
            ),
        }

        contact_payload = {
            key: value
            for key, value
            in contact_payload.items()
            if value
        }

        created = (
            api.create_contact_from_data(
                contact_payload
            )
        )

        created = decorate_contact(
            created
        )

        store.upsert_quality(
            created
        )

        related = {
            "opportunity": None,
            "case": None,
            "errors": [],
        }

        # ----------------------------------------------------
        # OPTIONAL RELATED OPPORTUNITY CREATION
        # ----------------------------------------------------
        opp = payload.get(
            "opportunity"
        ) or {}

        if clean(
            opp.get("name")
        ):
            try:
                opp_account = (
                    clean(
                        opp.get(
                            "accountId"
                        )
                    )
                    or None
                )

                if clean(
                    opp.get(
                        "newAccountName"
                    )
                ):
                    acc = api.create_record(
                        "Account",
                        {
                            "name": clean(
                                opp.get(
                                    "newAccountName"
                                )
                            )
                        },
                    )

                    opp_account = acc.get(
                        "id"
                    )

                amount = parse_amount(
                    opp.get("amount")
                )

                if amount is None:
                    raise api.EspoCRMError(
                        "Amount Opportunity wajib diisi."
                    )

                close_date = clean(
                    opp.get(
                        "closeDate"
                    )
                )

                if not close_date:
                    raise api.EspoCRMError(
                        "Close Date Opportunity wajib diisi."
                    )

                opp_data = {
                    "name": clean(
                        opp.get(
                            "name"
                        )
                    ),
                    "stage": clean(
                        opp.get(
                            "stage"
                        )
                    )
                    or "Prospecting",
                    "amount": amount,
                    "amountCurrency": "USD",
                    "closeDate": close_date,
                }

                if opp_account:
                    opp_data[
                        "accountId"
                    ] = opp_account

                if clean(
                    opp.get(
                        "description"
                    )
                ):
                    opp_data[
                        "description"
                    ] = clean(
                        opp.get(
                            "description"
                        )
                    )

                related[
                    "opportunity"
                ] = (
                    api.create_opportunity_for_contact(
                        created["id"],
                        opp_data,
                    )
                )

                if (
                    isinstance(
                        related[
                            "opportunity"
                        ],
                        dict,
                    )
                    and isinstance(
                        related[
                            "opportunity"
                        ].get(
                            "record"
                        ),
                        dict,
                    )
                ):
                    maybe_auto_sync(
                        related[
                            "opportunity"
                        ][
                            "record"
                        ]
                    )

            except Exception as exc:
                related[
                    "errors"
                ].append(
                    {
                        "type": "Opportunity",
                        "message": str(exc),
                    }
                )

        # ----------------------------------------------------
        # OPTIONAL RELATED CASE CREATION
        # ----------------------------------------------------
        case = payload.get(
            "case"
        ) or {}

        if clean(
            case.get("name")
        ):
            try:
                case_account = (
                    resolve_account_id(
                        case.get(
                            "accountId"
                        ),
                        case.get(
                            "newAccountName"
                        ),
                    )
                )

                case_data = {
                    "name": clean(
                        case.get(
                            "name"
                        )
                    ),
                    "status": clean(
                        case.get(
                            "status"
                        )
                    )
                    or "New",
                    "priority": clean(
                        case.get(
                            "priority"
                        )
                    )
                    or "Normal",
                    "type": clean(
                        case.get(
                            "type"
                        )
                    )
                    or "Question",
                }

                if case_account:
                    case_data[
                        "accountId"
                    ] = case_account

                if clean(
                    case.get(
                        "description"
                    )
                ):
                    case_data[
                        "description"
                    ] = clean(
                        case.get(
                            "description"
                        )
                    )

                related[
                    "case"
                ] = (
                    api.create_case_for_contact(
                        created["id"],
                        case_data,
                    )
                )

            except Exception as exc:
                related[
                    "errors"
                ].append(
                    {
                        "type": "Case",
                        "message": str(exc),
                    }
                )

        return jsonify(
            {
                "success": True,
                "data": created,
                "related": related,
            }
        )

    except Exception as exc:
        return jsonify(
            {
                "success": False,
                "error": str(exc),
            }
        ), 400


@app.put(
    "/api/contacts/<contact_id>"
)
def update_contact(
    contact_id
):
    payload = (
        request.get_json(
            silent=True
        )
        or {}
    )

    try:
        result = api.update_contact(
            contact_id,
            payload.get(
                "firstName"
            ),
            payload.get(
                "lastName"
            ),
            payload.get(
                "emailAddress"
            ),
            normalize_phone(
                payload.get(
                    "phoneNumber"
                )
            ),
            payload.get(
                "accountId"
            ),
        )

        result = decorate_contact(
            result
        )

        store.upsert_quality(
            result
        )

        return jsonify(
            {
                "success": True,
                "data": result,
            }
        )

    except Exception as exc:
        return jsonify(
            {
                "success": False,
                "error": str(exc),
            }
        ), 400


@app.delete(
    "/api/contacts/<contact_id>"
)
def delete_contact(
    contact_id
):
    try:
        result = (
            api.delete_contact_with_snapshot(
                contact_id
            )
        )

        store.delete_quality(
            contact_id
        )

        start_quality_scan(
            force=True
        )

        return jsonify(
            {
                "success": True,
                "data": result,
                "quality_refresh_started": True,
            }
        )

    except Exception as exc:
        return jsonify(
            {
                "success": False,
                "error": str(exc),
            }
        ), 400


@app.get(
    "/api/contacts/delete-mode"
)
def contacts_delete_mode():
    """
    Server-side paginated list for destructive Contact deletion mode.
    """
    category = clean(
        request.args.get(
            "category"
        )
    )

    if category not in QUALITY_BUCKETS:
        return jsonify(
            {
                "success": False,
                "error": (
                    "Kategori penghapusan tidak valid."
                ),
            }
        ), 400

    if not store.quality_state().get(
        "ready"
    ):
        return jsonify(
            {
                "success": False,
                "error": (
                    "Klasifikasi Contact belum siap."
                ),
                "ready": False,
            }
        ), 409

    page = max(
        1,
        safe_int(
            request.args.get(
                "page"
            ),
            1,
        ),
    )

    page_size = max(
        25,
        min(
            100,
            safe_int(
                request.args.get(
                    "page_size"
                ),
                100,
            ),
        ),
    )

    search = (
        clean(
            request.args.get(
                "search"
            )
        )
        or None
    )

    data = store.quality_page(
        category,
        page,
        page_size,
        search,
    )

    records = []

    for row in data.get(
        "records",
        [],
    ):
        item = dict(
            row
        )

        item[
            "displayName"
        ] = contact_name(
            item
        )

        item[
            "completenessScore"
        ] = item.get(
            "completenessScore",
            0,
        )

        item[
            "completenessStatus"
        ] = item.get(
            "completenessStatus",
            category,
        )

        records.append(
            item
        )

    return jsonify(
        {
            "success": True,
            "category": category,
            **{
                **data,
                "records": records,
            },
        }
    )


@app.post(
    "/api/contacts/bulk-delete"
)
def bulk_delete_contacts():
    payload = (
        request.get_json(
            silent=True
        )
        or {}
    )

    raw_ids = (
        payload.get(
            "ids"
        )
        or []
    )

    if not isinstance(
        raw_ids,
        list,
    ):
        return jsonify(
            {
                "success": False,
                "error": (
                    "ids harus berupa array."
                ),
            }
        ), 400

    ids = []
    seen = set()

    for value in raw_ids:
        item = clean(value)

        if (
            item
            and item not in seen
        ):
            ids.append(
                item
            )

            seen.add(
                item
            )

    if not ids:
        return jsonify(
            {
                "success": False,
                "error": (
                    "Belum ada Contact yang dipilih."
                ),
            }
        ), 400

    if len(ids) > 100:
        return jsonify(
            {
                "success": False,
                "error": (
                    "Maksimal 100 Contact per proses penghapusan."
                ),
            }
        ), 400

    deleted = []
    failed = []

    for contact_id in ids:
        try:
            api.delete_contact(
                contact_id
            )

            store.delete_quality(
                contact_id
            )

            deleted.append(
                contact_id
            )

        except Exception as exc:
            failed.append(
                {
                    "id": contact_id,
                    "error": str(exc),
                }
            )

    start_quality_scan(
        force=True
    )

    return jsonify(
        {
            "success": True,
            "deleted": deleted,
            "failed": failed,
            "deleted_count": len(
                deleted
            ),
            "failed_count": len(
                failed
            ),
            "quality_refresh_started": True,
        }
    )


@app.post(
    "/api/contacts/related"
)
def create_related_for_contact():
    payload = (
        request.get_json(
            silent=True
        )
        or {}
    )

    contact_id = clean(
        payload.get(
            "contactId"
        )
    )

    if not contact_id:
        return jsonify(
            {
                "success": False,
                "error": (
                    "Contact ID wajib diisi."
                ),
            }
        ), 400

    try:
        out = {}

        opp = payload.get(
            "opportunity"
        ) or {}

        case = payload.get(
            "case"
        ) or {}

        if clean(
            opp.get("name")
        ):
            data = {
                "name": clean(
                    opp.get(
                        "name"
                    )
                ),
                "stage": clean(
                    opp.get(
                        "stage"
                    )
                )
                or "Prospecting",
                "amount": (
                    parse_amount(
                        opp.get(
                            "amount"
                        )
                    )
                    or 0
                ),
                "amountCurrency": "USD",
                "closeDate": clean(
                    opp.get(
                        "closeDate"
                    )
                ),
            }

            if clean(
                opp.get(
                    "accountId"
                )
            ):
                data[
                    "accountId"
                ] = clean(
                    opp.get(
                        "accountId"
                    )
                )

            if clean(
                opp.get(
                    "description"
                )
            ):
                data[
                    "description"
                ] = clean(
                    opp.get(
                        "description"
                    )
                )

            out[
                "opportunity"
            ] = (
                api.create_opportunity_for_contact(
                    contact_id,
                    data,
                )
            )

            record = (
                out[
                    "opportunity"
                ].get(
                    "record"
                )
                if isinstance(
                    out[
                        "opportunity"
                    ],
                    dict,
                )
                else None
            )

            if isinstance(
                record,
                dict,
            ):
                maybe_auto_sync(
                    record
                )

        if clean(
            case.get("name")
        ):
            data = {
                "name": clean(
                    case.get(
                        "name"
                    )
                ),
                "status": clean(
                    case.get(
                        "status"
                    )
                )
                or "New",
                "priority": clean(
                    case.get(
                        "priority"
                    )
                )
                or "Normal",
                "type": clean(
                    case.get(
                        "type"
                    )
                )
                or "Question",
            }

            if clean(
                case.get(
                    "accountId"
                )
            ):
                data[
                    "accountId"
                ] = clean(
                    case.get(
                        "accountId"
                    )
                )

            if clean(
                case.get(
                    "description"
                )
            ):
                data[
                    "description"
                ] = clean(
                    case.get(
                        "description"
                    )
                )

            out[
                "case"
            ] = (
                api.create_case_for_contact(
                    contact_id,
                    data,
                )
            )

        return jsonify(
            {
                "success": True,
                "data": out,
            }
        )

    except Exception as exc:
        return jsonify(
            {
                "success": False,
                "error": str(exc),
            }
        ), 400


# ============================================================
# OPPORTUNITY DATA TABLE
# ============================================================

@app.get("/api/opportunities")
def opportunities():
    """
    Server-side paginated Opportunity table.

    Only one page is requested from EspoCRM at a time, which is important
    for the 10,000+ data requirement.
    """
    page, page_size, offset = page_args(
        25
    )

    params = {
        "offset": offset,
        "max_size": page_size,
        "search": (
            clean(
                request.args.get(
                    "search"
                )
            )
            or None
        ),
        "stage": (
            clean(
                request.args.get(
                    "stage"
                )
            )
            or None
        ),
        "assigned_user_id": (
            clean(
                request.args.get(
                    "assignedUserId"
                )
            )
            or None
        ),
        "priority": (
            clean(
                request.args.get(
                    "priority"
                )
            )
            or None
        ),
        "account_id": (
            clean(
                request.args.get(
                    "accountId"
                )
            )
            or None
        ),
        "contact_id": (
            clean(
                request.args.get(
                    "contactId"
                )
            )
            or None
        ),
        "order_by": (
            clean(
                request.args.get(
                    "sort"
                )
            )
            or "modifiedAt"
        ),
        "order": (
            "asc"
            if clean(
                request.args.get(
                    "order"
                )
            ).lower()
            == "asc"
            else "desc"
        ),
    }

    allowed_sort = {
        "name",
        "stage",
        "amount",
        "closeDate",
        "createdAt",
        "modifiedAt",
        "accountName",
        "assignedUserName",
    }

    if params[
        "order_by"
    ] not in allowed_sort:
        params[
            "order_by"
        ] = "modifiedAt"

    started = time.perf_counter()

    try:
        result = (
            api.get_opportunities_advanced(
                **params
            )
        )

        rows, total_count = normalize_records(
            result
        )

        pages = max(
            1,
            math.ceil(
                total_count
                / page_size
            ),
        )

        return jsonify(
            {
                "success": True,
                "records": rows,
                "total": total_count,
                "page": page,
                "pages": pages,
                "page_size": page_size,
                "response_ms": round(
                    (
                        time.perf_counter()
                        - started
                    )
                    * 1000,
                    2,
                ),
            }
        )

    except Exception as exc:
        return jsonify(
            {
                "success": False,
                "error": str(exc),
            }
        ), 400


@app.get(
    "/api/opportunities/<opportunity_id>"
)
def opportunity_detail(
    opportunity_id
):
    """
    Opportunity detail + relationships + Accurate sync state.

    Relationship endpoints are isolated so a missing/unsupported
    relationship (for example Opportunity/accounts) does not make
    the entire Opportunity detail page fail.
    """
    try:
        # ----------------------------------------------------
        # CORE OPPORTUNITY
        # ----------------------------------------------------
        row = api.get_opportunity(
            opportunity_id
        )

        if not isinstance(row, dict):
            raise api.EspoCRMError(
                "Response Opportunity tidak valid."
            )

        # ----------------------------------------------------
        # RELATED TASKS / CONTACTS
        # ----------------------------------------------------
        tasks, tasks_error = _safe_related_records(
            api.get_opportunity_tasks,
            opportunity_id,
            max_size=25,
        )

        contacts, contacts_error = _safe_related_records(
            api.get_opportunity_contacts,
            opportunity_id,
            max_size=25,
        )

        # ----------------------------------------------------
        # ACCOUNT
        # ----------------------------------------------------
        # Opportunity sudah membawa accountId/accountName.
        # Jangan memanggil Opportunity/{id}/accounts karena pada
        # instance EspoCRM ini endpoint tersebut mengembalikan 404.
        accounts = []

        account_id = clean(
            row.get("accountId")
        )
        account_name = clean(
            row.get("accountName")
        )

        if account_id or account_name:
            accounts.append(
                {
                    "id": account_id or None,
                    "name": account_name or "-",
                }
            )

        # ----------------------------------------------------
        # ACCURATE SYNC STATUS
        # ----------------------------------------------------
        accurate_sync = None
        accurate_sync_error = None

        try:
            accurate_sync = accurate.get_sync_status(
                opportunity_id
            )
        except Exception as exc:
            accurate_sync_error = str(exc)

        relationship_errors = {}

        if tasks_error:
            relationship_errors["tasks"] = tasks_error

        if contacts_error:
            relationship_errors["contacts"] = contacts_error

        response_data = {
            "success": True,
            "data": row,
            "accurate_sync": accurate_sync,
            "relationships": {
                "tasks": tasks,
                "contacts": contacts,
                "accounts": accounts,
            },
            "relationship_errors": relationship_errors,
        }

        if accurate_sync_error:
            response_data[
                "accurate_sync_error"
            ] = accurate_sync_error

        return jsonify(response_data)

    except Exception as exc:
        return jsonify(
            {
                "success": False,
                "error": str(exc),
            }
        ), 400


@app.put(
    "/api/opportunities/<opportunity_id>"
)
def update_opportunity(
    opportunity_id
):
    """
    Update an Opportunity in EspoCRM.

    When the resulting Opportunity is Closed Won, call the Accurate sync
    for that specific Opportunity. This supports:
      - first sync when it becomes Closed Won
      - update sync when a previously synced Closed Won Opportunity changes
    """
    payload = (
        request.get_json(
            silent=True
        )
        or {}
    )

    allowed_fields = (
        "name",
        "stage",
        "amount",
        "amountCurrency",
        "closeDate",
        "description",
        "accountId",
        "assignedUserId",
        "contactId",
    )

    data = {
        key: payload[key]
        for key in allowed_fields
        if (
            key in payload
            and payload[key]
            not in (
                None,
                "",
            )
        )
    }

    try:
        result = api.update_record(
            "Opportunity",
            opportunity_id,
            data,
        )

        sync_result = None

        if (
            isinstance(
                result,
                dict,
            )
            and clean(
                result.get(
                    "stage"
                )
            )
            == "Closed Won"
        ):
            sync_result = (
                maybe_auto_sync(
                    result
                )
            )

        return jsonify(
            {
                "success": True,
                "data": result,
                "accurate_sync": sync_result,
            }
        )

    except Exception as exc:
        return jsonify(
            {
                "success": False,
                "error": str(exc),
            }
        ), 400


# ============================================================
# TASKS / CASES
# ============================================================

@app.get("/api/tasks")
def tasks():
    page, page_size, _ = page_args(
        25
    )

    try:
        result = api.get_tasks_advanced(
            offset=(
                page - 1
            )
            * page_size,
            max_size=page_size,
            search=(
                clean(
                    request.args.get(
                        "search"
                    )
                )
                or None
            ),
            status=(
                clean(
                    request.args.get(
                        "status"
                    )
                )
                or None
            ),
            priority=(
                clean(
                    request.args.get(
                        "priority"
                    )
                )
                or None
            ),
            assigned_user_id=(
                clean(
                    request.args.get(
                        "assignedUserId"
                    )
                )
                or None
            ),
            parent_id=(
                clean(
                    request.args.get(
                        "parentId"
                    )
                )
                or None
            ),
            overdue_only=(
                clean(
                    request.args.get(
                        "overdue"
                    )
                )
                == "true"
            ),
            order_by=(
                clean(
                    request.args.get(
                        "sort"
                    )
                )
                or "dateEnd"
            ),
            order=(
                "desc"
                if clean(
                    request.args.get(
                        "order"
                    )
                ).lower()
                == "desc"
                else "asc"
            ),
        )

        rows, total_count = normalize_records(
            result
        )

        return jsonify(
            {
                "success": True,
                "records": rows,
                "total": total_count,
                "page": page,
                "pages": max(
                    1,
                    math.ceil(
                        total_count
                        / page_size
                    ),
                ),
                "page_size": page_size,
            }
        )

    except Exception as exc:
        return jsonify(
            {
                "success": False,
                "error": str(exc),
            }
        ), 400


@app.get("/api/cases")
def cases():
    page, page_size, offset = page_args(
        25
    )

    try:
        result = api.get_cases(
            offset=offset,
            max_size=page_size,
            search=(
                clean(
                    request.args.get(
                        "search"
                    )
                )
                or None
            ),
        )

        rows, total_count = normalize_records(
            result
        )

        return jsonify(
            {
                "success": True,
                "records": rows,
                "total": total_count,
                "page": page,
                "pages": max(
                    1,
                    math.ceil(
                        total_count
                        / page_size
                    ),
                ),
                "page_size": page_size,
            }
        )

    except Exception as exc:
        return jsonify(
            {
                "success": False,
                "error": str(exc),
            }
        ), 400


@app.get(
    "/api/cases/<case_id>"
)
def case_detail(
    case_id
):
    try:
        return jsonify(
            {
                "success": True,
                "data": api.get_case(
                    case_id
                ),
            }
        )

    except Exception as exc:
        return jsonify(
            {
                "success": False,
                "error": str(exc),
            }
        ), 400


# ============================================================
# ANALYTICS ROUTE
# ============================================================

@app.get("/api/analytics")
def analytics():
    data = analytics_snapshot()

    if data is None:
        start_quality_scan()

        with _analytics_lock:
            return jsonify(
                {
                    "success": True,
                    "ready": False,
                    "running": (
                        _analytics_cache[
                            "running"
                        ]
                    ),
                    "error": (
                        _analytics_cache[
                            "error"
                        ]
                    ),
                }
            )

    return jsonify(
        {
            "success": True,
            "ready": True,
            "data": data,
        }
    )


# ============================================================
# ACCURATE INTEGRATION
# ============================================================

@app.get("/api/accurate/status")
def accurate_status():
    """
    Show current Accurate integration state.
    """
    try:
        return jsonify(
            {
                "success": True,
                **accurate.status(),
            }
        )

    except Exception as exc:
        return jsonify(
            {
                "success": False,
                "error": str(exc),
            }
        ), 400


@app.get("/accurate/connect")
def accurate_connect():
    """
    Start Accurate OAuth from the main application.

    The registered callback in Accurate must be:
        http://localhost:5000/callback
    """
    try:
        return redirect(
            accurate.authorization_url()
        )

    except AccurateConfigError as exc:
        return jsonify(
            {
                "success": False,
                "error": str(exc),
            }
        ), 400

    except Exception as exc:
        return jsonify(
            {
                "success": False,
                "error": str(exc),
            }
        ), 400


def handle_accurate_callback():
    """
    Handle Accurate OAuth Authorization Code callback.

    Accurate Developer Area:
        http://localhost:5000/callback
    """
    error = clean(
        request.args.get(
            "error"
        )
    )

    if error:
        description = clean(
            request.args.get(
                "error_description"
            )
        )

        print(
            "[ACCURATE OAUTH ERROR] "
            f"{error} {description}"
        )

        return redirect(
            "/?accurate=error"
        )

    code = clean(
        request.args.get(
            "code"
        )
    )

    if not code:
        print(
            "[ACCURATE OAUTH ERROR] "
            "Authorization code tidak ditemukan."
        )

        return redirect(
            "/?accurate=error"
        )

    try:
        accurate.exchange_code(
            code
        )

        print(
            "[ACCURATE OAUTH] "
            "OAuth berhasil, database session siap."
        )

        return redirect(
            "/?accurate=connected"
        )

    except AccurateConfigError as exc:
        print(
            "[ACCURATE OAUTH CONFIG ERROR] "
            f"{exc}"
        )

        return redirect(
            "/?accurate=error"
        )

    except Exception as exc:
        print(
            "[ACCURATE OAUTH ERROR] "
            f"{exc}"
        )

        return redirect(
            "/?accurate=error"
        )


@app.get("/callback")
def accurate_callback():
    """
    Primary OAuth callback.

    This route MUST match the URL registered in Accurate Developer Area.
    """
    return handle_accurate_callback()


@app.get(
    "/accurate/callback"
)
def accurate_callback_legacy():
    """
    Compatibility callback for older local configuration.
    """
    return handle_accurate_callback()


@app.post(
    "/api/accurate/disconnect"
)
def accurate_disconnect():
    try:
        accurate.disconnect()

        return jsonify(
            {
                "success": True,
                "message": (
                    "Koneksi Accurate lokal telah dibersihkan."
                ),
            }
        )

    except Exception as exc:
        return jsonify(
            {
                "success": False,
                "error": str(exc),
            }
        ), 400


@app.post(
    "/api/accurate/sync/opportunity/<opportunity_id>"
)
def accurate_sync_opportunity(
    opportunity_id
):
    """
    Manual sync endpoint.

    Recommended for:
      - manual testing
      - retry after a known failed validation
      - demo/presentation

    For an "unknown" result, use the explicit retry endpoint only after
    verifying Accurate to avoid duplicate financial transactions.
    """
    try:
        result = (
            accurate.sync_opportunity(
                opportunity_id
            )
        )

        status = result.get(
            "status"
        )

        return jsonify(
            {
                "success": status
                in {
                    "success",
                    "skipped",
                },
                "data": result,
            }
        )

    except Exception as exc:
        return jsonify(
            {
                "success": False,
                "error": str(exc),
            }
        ), 400


@app.post(
    "/api/accurate/sync/opportunity/<opportunity_id>/retry"
)
def accurate_retry_opportunity(
    opportunity_id
):
    """
    Safe retry endpoint.

    By default an "unknown" state is blocked. The frontend should first
    verify the Accurate transaction manually and then call this endpoint
    with {"force_unknown": true}.
    """
    payload = (
        request.get_json(
            silent=True
        )
        or {}
    )

    force_unknown = bool(
        payload.get(
            "force_unknown"
        )
    )

    try:
        result = accurate.retry_opportunity(
            opportunity_id,
            force_unknown=force_unknown,
        )

        status = result.get(
            "status"
        )

        return jsonify(
            {
                "success": status
                in {
                    "success",
                    "skipped",
                },
                "data": result,
            }
        )

    except Exception as exc:
        return jsonify(
            {
                "success": False,
                "error": str(exc),
            }
        ), 400


@app.get(
    "/api/accurate/sync/opportunity/<opportunity_id>"
)
def accurate_sync_status_for_opportunity(
    opportunity_id
):
    """
    Return the sync status of one Opportunity.
    """
    try:
        record = (
            accurate.get_sync_status(
                opportunity_id
            )
        )

        return jsonify(
            {
                "success": True,
                "opportunity_id": opportunity_id,
                "data": record,
            }
        )

    except Exception as exc:
        return jsonify(
            {
                "success": False,
                "error": str(exc),
            }
        ), 400


@app.get("/api/accurate/sync")
def accurate_sync_status():
    """
    Return recent sync records for the UI.
    """
    try:
        records = store.list_sync_records(
            limit=100
        )

        return jsonify(
            {
                "success": True,
                "records": records,
            }
        )

    except Exception as exc:
        return jsonify(
            {
                "success": False,
                "error": str(exc),
            }
        ), 400


# ============================================================
# ACCURATE AUTO-SYNC
# ============================================================

def maybe_auto_sync(opportunity):
    """
    Auto-sync ONE Opportunity when its final state is Closed Won.

    This function intentionally does not scan the entire historical
    Opportunity table.
    """
    if not isinstance(
        opportunity,
        dict,
    ):
        return None

    if clean(
        opportunity.get(
            "stage"
        )
    ) != "Closed Won":
        return None

    if not accurate.is_configured():
        print(
            "[ACCURATE SYNC] "
            "Skip: credential belum terkonfigurasi."
        )

        return None

    opportunity_id = clean(
        opportunity.get(
            "id"
        )
    )

    if not opportunity_id:
        print(
            "[ACCURATE SYNC] "
            "Skip: Opportunity ID kosong."
        )

        return None

    try:
        result = (
            accurate.sync_opportunity_record(
                opportunity
            )
        )

        print(
            "[ACCURATE SYNC] "
            f"Opportunity={opportunity_id} "
            f"Result={result.get('status')}"
        )

        return result

    except Exception as exc:
        print(
            "[ACCURATE SYNC ERROR] "
            f"Opportunity={opportunity_id} "
            f"Error={exc}"
        )

        try:
            return store.record_sync_error(
                opportunity_id,
                str(exc),
            )
        except Exception:
            return {
                "status": "failed",
                "error": str(exc),
            }


def sync_closed_won_worker():
    """
    OPTIONAL background worker.

    It is OFF by default through:
        ACCURATE_SYNC_WORKER=false

    When enabled, it checks a small recent window instead of attempting to
    push all historical Closed Won rows. This protects the 10,000+ record
    dataset from an accidental mass sync.
    """
    while ACCURATE_SYNC_WORKER_ENABLED:
        try:
            if accurate.is_configured():
                result = (
                    api.get_opportunities_advanced(
                        offset=0,
                        max_size=10,
                        stage="Closed Won",
                        order_by="modifiedAt",
                        order="desc",
                        no_total=True,
                    )
                )

                rows, _ = normalize_records(
                    result
                )

                for row in rows:
                    if (
                        isinstance(
                            row,
                            dict,
                        )
                        and row.get(
                            "id"
                        )
                    ):
                        maybe_auto_sync(
                            row
                        )

        except Exception as exc:
            print(
                "[ACCURATE WORKER ERROR] "
                f"{exc}"
            )

        time.sleep(60)


# ============================================================
# ROUTES - OPTIONS
# ============================================================

@app.route(
    "/api/options/users"
)
def options_users():
    try:
        users = api.get_active_users(
            max_size=100
        )

        return jsonify(
            {
                "success": True,
                "records": [
                    {
                        "id": row.get(
                            "id"
                        ),
                        "name": row.get(
                            "name"
                        ),
                    }
                    for row in users
                    if (
                        isinstance(
                            row,
                            dict,
                        )
                        and row.get(
                            "id"
                        )
                    )
                ],
            }
        )

    except Exception as exc:
        return jsonify(
            {
                "success": False,
                "error": str(exc),
            }
        ), 400


@app.get(
    "/api/options/accounts"
)
def options_accounts():
    try:
        result = api.get_collection(
            "Account",
            offset=0,
            max_size=100,
            search=(
                clean(
                    request.args.get(
                        "search"
                    )
                )
                or None
            ),
            order_by="name",
            order="asc",
            select=(
                "id",
                "name",
            ),
        )

        rows, _ = normalize_records(
            result
        )

        return jsonify(
            {
                "success": True,
                "records": [
                    {
                        "id": row.get(
                            "id"
                        ),
                        "name": row.get(
                            "name"
                        ),
                    }
                    for row in rows
                    if (
                        isinstance(
                            row,
                            dict,
                        )
                        and row.get(
                            "id"
                        )
                    )
                ],
            }
        )

    except Exception as exc:
        return jsonify(
            {
                "success": False,
                "error": str(exc),
            }
        ), 400


# ============================================================
# RESPONSE / FRONTEND LAYOUT PATCH
# ============================================================

# The Opportunity detail UI lives in templates/index.html, while this
# backend owns the Flask response.  To keep the existing template compatible
# and avoid requiring a simultaneous rewrite of the frontend, inject a small
# defensive layout patch into HTML responses.  It fixes the detail drawer so
# it starts below the top navigation and can scroll all the way to the bottom.
#
# The patch is intentionally DOM-driven: it locates the drawer using the
# existing visible labels "Sync Accurate" / "Tasks terkait" instead of relying
# on a fragile class name from the template.
FRONTEND_LAYOUT_PATCH = r"""
<style id="accurate-opportunity-layout-patch">
html.accurate-opportunity-layout-patched,
html.accurate-opportunity-layout-patched body {
    min-height: 100%;
}

body.accurate-opportunity-drawer-open {
    overflow-x: hidden;
}

/* Safety rule: the top navigation must remain visually above the drawer. */
header, nav, [role="navigation"] {
    position: relative;
    z-index: 1101 !important;
}

/* The JS below adds this class to the actual Opportunity detail container. */
.accurate-opportunity-detail-fixed {
    position: fixed !important;
    right: 0 !important;
    bottom: 0 !important;
    z-index: 1100 !important;
    box-sizing: border-box !important;
    overflow-x: hidden !important;
    overflow-y: auto !important;
    overscroll-behavior: contain;
    -webkit-overflow-scrolling: touch;
    max-height: none !important;
}

.accurate-opportunity-detail-fixed::-webkit-scrollbar {
    width: 10px;
}

.accurate-opportunity-detail-fixed > :first-child:last-child {
    min-height: min-content;
}
</style>

<script id="accurate-opportunity-layout-patch-script">
(function () {
    "use strict";

    if (window.__accurateOpportunityLayoutPatchInstalled) {
        return;
    }
    window.__accurateOpportunityLayoutPatchInstalled = true;

    function visible(el) {
        if (!el) return false;
        var rect = el.getBoundingClientRect();
        var style = window.getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 &&
            style.display !== "none" && style.visibility !== "hidden";
    }

    function navigationElement() {
        var candidates = Array.prototype.slice.call(
            document.querySelectorAll(
                "header, nav, [role='navigation'], [class*='navbar'], [class*='nav-bar']"
            )
        );

        var scored = candidates.filter(visible).map(function (el) {
            var rect = el.getBoundingClientRect();
            var score = 0;
            if (rect.top <= 12) score += 50;
            if (rect.width >= window.innerWidth * 0.50) score += 30;
            if (rect.height >= 40 && rect.height <= 180) score += 25;
            if (window.getComputedStyle(el).position === "fixed") score += 20;
            return { el: el, score: score, rect: rect };
        });

        scored.sort(function (a, b) {
            return b.score - a.score;
        });

        return scored.length ? scored[0] : null;
    }

    function containsLabel(el, label) {
        if (!el || !el.textContent) return false;
        return el.textContent.trim().toLowerCase().indexOf(label.toLowerCase()) !== -1;
    }

    function findLabelTarget(label) {
        var nodes = Array.prototype.slice.call(
            document.querySelectorAll("button, a, h1, h2, h3, h4, h5, h6, section, aside, div")
        );

        var matches = nodes.filter(function (el) {
            return visible(el) && containsLabel(el, label);
        });

        matches.sort(function (a, b) {
            var ar = a.getBoundingClientRect();
            var br = b.getBoundingClientRect();
            return (br.width * br.height) - (ar.width * ar.height);
        });

        return matches.length ? matches[0] : null;
    }

    function scorePanelCandidate(el) {
        if (!visible(el)) return -Infinity;

        var rect = el.getBoundingClientRect();
        var cs = window.getComputedStyle(el);
        var score = 0;

        if (rect.right >= window.innerWidth * 0.70) score += 30;
        if (rect.width >= Math.min(320, window.innerWidth * 0.28)) score += 25;
        if (rect.height >= window.innerHeight * 0.45) score += 20;
        if (cs.position === "fixed") score += 45;
        else if (cs.position === "absolute") score += 30;
        else if (cs.position === "sticky") score += 10;

        if (cs.overflowY === "auto" || cs.overflowY === "scroll") score += 25;
        if (rect.left >= window.innerWidth * 0.45) score += 15;

        return score;
    }

    function findDetailPanel() {
        var labels = ["Sync Accurate", "Tasks terkait"];
        var candidates = [];

        labels.forEach(function (label) {
            var target = findLabelTarget(label);
            if (!target) return;

            var current = target;
            for (var i = 0; i < 10 && current; i += 1) {
                candidates.push({
                    el: current,
                    score: scorePanelCandidate(current)
                });
                current = current.parentElement;
            }
        });

        if (!candidates.length) return null;

        var unique = [];
        var seen = new Set();
        candidates.forEach(function (item) {
            if (!seen.has(item.el)) {
                seen.add(item.el);
                unique.push(item);
            }
        });

        unique.sort(function (a, b) {
            return b.score - a.score;
        });

        return unique.length && unique[0].score > 0 ? unique[0].el : null;
    }

    function softenNestedScrollContainers(panel) {
        if (!panel) return;

        var nodes = Array.prototype.slice.call(panel.querySelectorAll("*"));
        nodes.forEach(function (el) {
            var cs = window.getComputedStyle(el);
            var rect = el.getBoundingClientRect();

            var scrollContainer =
                (cs.overflowY === "auto" || cs.overflowY === "scroll") &&
                el.scrollHeight > el.clientHeight + 80 &&
                rect.height > 180;

            var explicitHeightLimit =
                cs.maxHeight !== "none" &&
                cs.maxHeight !== "0px" &&
                cs.maxHeight.indexOf("vh") !== -1;

            if (scrollContainer && explicitHeightLimit) {
                el.style.setProperty("max-height", "none", "important");
                el.style.setProperty("height", "auto", "important");
                el.style.setProperty("overflow-y", "visible", "important");
            }
        });
    }

    function applyLayout() {
        if (!document.body) return;

        var nav = navigationElement();
        var navBottom = 0;
        var navEl = null;

        if (nav && nav.rect) {
            navBottom = Math.max(0, nav.rect.bottom);
            navEl = nav.el;
        }

        var panel = findDetailPanel();
        if (!panel) return;

        var panelRect = panel.getBoundingClientRect();
        var panelStyle = window.getComputedStyle(panel);

        /* Ignore the result when a matching label is somewhere in the normal
           page body rather than inside a right-side detail drawer. */
        if (panelRect.left < window.innerWidth * 0.35 &&
            panelStyle.position !== "fixed" &&
            panelStyle.position !== "absolute") {
            return;
        }

        document.documentElement.classList.add("accurate-opportunity-layout-patched");
        document.body.classList.add("accurate-opportunity-drawer-open");
        panel.classList.add("accurate-opportunity-detail-fixed");

        if (navEl) {
            navEl.style.setProperty("z-index", "1101", "important");
            if (window.getComputedStyle(navEl).position === "static") {
                navEl.style.setProperty("position", "relative", "important");
            }
        }

        panel.style.setProperty("top", Math.ceil(navBottom) + "px", "important");
        panel.style.setProperty("bottom", "0px", "important");
        panel.style.setProperty("height", "calc(100vh - " + Math.ceil(navBottom) + "px)", "important");
        panel.style.setProperty("max-height", "none", "important");
        panel.style.setProperty("overflow-y", "auto", "important");
        panel.style.setProperty("box-sizing", "border-box", "important");
        panel.style.setProperty("z-index", "1100", "important");

        /* Keep a little breathing room after the final field/button. */
        var contentNodes = panel.querySelectorAll(".detail-content, .drawer-content, .panel-content, main, section");
        Array.prototype.forEach.call(contentNodes, function (el) {
            var cs = window.getComputedStyle(el);
            if (cs.paddingBottom === "0px") {
                el.style.paddingBottom = "28px";
            }
        });

        softenNestedScrollContainers(panel);
    }

    var scheduled = false;
    function scheduleApply() {
        if (scheduled) return;
        scheduled = true;
        window.requestAnimationFrame(function () {
            scheduled = false;
            window.setTimeout(applyLayout, 30);
        });
    }

    document.addEventListener("DOMContentLoaded", scheduleApply, { once: true });
    window.addEventListener("load", scheduleApply);
    window.addEventListener("resize", scheduleApply);

    var observer = new MutationObserver(function () {
        scheduleApply();
    });

    observer.observe(document.body, {
        childList: true,
        subtree: true
    });

    scheduleApply();
})();
</script>
"""


def _inject_frontend_layout_patch(response):
    """Inject the Opportunity drawer layout patch into HTML pages only."""
    if request.path.startswith("/api/"):
        return response

    content_type = (response.headers.get("Content-Type") or "").lower()
    if "text/html" not in content_type:
        return response

    try:
        html = response.get_data(as_text=True)
    except Exception:
        return response

    marker = 'id="accurate-opportunity-layout-patch"'
    if marker in html:
        return response

    if "</head>" in html.lower():
        lower_html = html.lower()
        head_index = lower_html.rfind("</head>")
        html = html[:head_index] + FRONTEND_LAYOUT_PATCH + html[head_index:]
    elif "</body>" in html.lower():
        lower_html = html.lower()
        body_index = lower_html.rfind("</body>")
        html = html[:body_index] + FRONTEND_LAYOUT_PATCH + html[body_index:]
    else:
        html += FRONTEND_LAYOUT_PATCH

    response.set_data(html)
    response.headers["Content-Length"] = str(len(response.get_data()))
    return response


# ============================================================
# RESPONSE HEADERS
# ============================================================

@app.after_request
def no_store_for_api(
    response
):
    if request.path.startswith(
        "/api/"
    ):
        response.headers[
            "Cache-Control"
        ] = "no-store"

    return response


@app.after_request
def inject_frontend_layout_patch(
    response
):
    return _inject_frontend_layout_patch(response)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    start_quality_scan()
    maybe_start_analytics()

    # IMPORTANT:
    # Default is OFF to prevent historical Closed Won records from being
    # synchronized accidentally when the server starts.
    if ACCURATE_SYNC_WORKER_ENABLED:
        threading.Thread(
            target=sync_closed_won_worker,
            daemon=True,
        ).start()

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
    )
