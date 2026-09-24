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

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.getenv("WEB_SECRET_KEY", secrets.token_hex(32))

PAGE_SIZE_DEFAULT = 25
PAGE_SIZE_MAX = 100
QUALITY_PAGE_SIZE = 200
QUALITY_WORKERS = 6
QUALITY_TTL = 900
ANALYTICS_TTL = 120
QUALITY_SCHEMA_VERSION = "core-contact-v2"

# Data Quality hanya menilai field inti yang memang diminta pada form Contact.
# Field metadata opsional seperti Title, City, Country, Address, Description, dll.
# tidak boleh membuat Contact baru terlihat "tidak lengkap".
QUALITY_FIELDS = (
    "firstName",
    "lastName",
    "emailAddress",
    "phoneNumber",
    "accountId",
)
QUALITY_BUCKETS = ("complete", "partial", "minimal")
STAGES = ("Prospecting", "Qualification", "Proposal", "Negotiation", "Closed Won", "Closed Lost")
TASK_STATUSES = ("Not Started", "In Progress", "Completed", "Canceled", "Deferred")
CASE_STATUSES = ("New", "Assigned", "Pending", "Closed")
CASE_PRIORITIES = ("Normal", "Urgent")
CASE_TYPES = ("Question", "Incident", "Problem")

store = AppStore(Path(os.getenv("APP_STORE_DB", "runtime/app.sqlite3")))
accurate = AccurateClient(store)

# Pastikan cache quality lama yang dibangun dengan definisi field sebelumnya
# tidak dipakai setelah skema Data Quality berubah.
if store.get_meta("quality_schema_version") != QUALITY_SCHEMA_VERSION:
    store.invalidate_quality(clear_cache=True)
    store.set_meta("quality_schema_version", QUALITY_SCHEMA_VERSION)

_quality_lock = threading.Lock()
_quality_job = {"running": False, "error": None, "started_at": None, "finished_at": None}
_analytics_lock = threading.Lock()
_analytics_cache = {"data": None, "expires_at": 0.0, "running": False, "error": None}


def clean(value):
    return str(value or "").strip()


def normalize_records(result):
    if isinstance(result, dict):
        rows = result.get("list", []) if isinstance(result.get("list", []), list) else []
        try:
            total = int(result.get("total", len(rows)) or 0)
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
    page = max(1, safe_int(request.args.get("page"), 1))
    page_size = max(1, min(PAGE_SIZE_MAX, safe_int(request.args.get("page_size"), default_size)))
    return page, page_size, (page - 1) * page_size


def contact_name(row):
    name = clean(row.get("name"))
    if name:
        return name
    return " ".join(x for x in (clean(row.get("firstName")), clean(row.get("lastName"))) if x) or "Untitled Contact"


def completeness(row):
    filled = sum(1 for field in QUALITY_FIELDS if clean(row.get(field)))
    score = round((filled / len(QUALITY_FIELDS)) * 100)
    # Semua field inti terisi = Lengkap.
    # Sebagian besar field inti = Kurang.
    # Kurang dari 60% = Tidak komplet.
    if score >= 100:
        status = "complete"
    elif score >= 60:
        status = "partial"
    else:
        status = "minimal"
    return score, status


def decorate_contact(row):
    item = dict(row or {})
    score, status = completeness(item)
    item["displayName"] = contact_name(item)
    item["completenessScore"] = score
    item["completenessStatus"] = status
    return item


def normalize_phone(value):
    raw = clean(value)
    compact = "".join(ch for ch in raw if ch.isdigit() or ch == "+")
    if compact.startswith("08"):
        compact = "+62" + compact[1:]
    if compact.startswith("+62"):
        digits = compact[3:]
        return "+62 " + digits
    return raw


def parse_amount(value):
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError as exc:
        raise api.EspoCRMError("Amount harus berupa angka.") from exc


def total(entity):
    result = api.get_collection(entity, offset=0, max_size=1)
    _, count = normalize_records(result)
    return count


def fetch_all_pages(entity, page_size=200, fields=(), order_by=None, order="asc", max_records=50000):
    """Fetch a large collection in server-side pages for background analytics only."""
    fields = list(fields or [])
    first = api.get_collection_advanced(
        entity, offset=0, max_size=page_size,
        select=fields or None, order_by=order_by, order=order
    )
    rows, total_count = normalize_records(first)
    rows = list(rows)
    target = min(int(total_count), int(max_records))
    offset = page_size
    while offset < target:
        chunk = api.get_collection_advanced(
            entity, offset=offset, max_size=page_size,
            select=fields or None, order_by=order_by, order=order
        )
        chunk_rows, _ = normalize_records(chunk)
        if not chunk_rows:
            break
        rows.extend(chunk_rows)
        offset += page_size
    return rows[:max_records]


def quality_ready():
    return store.quality_count() > 0 and store.quality_state().get("ready", False)


def scan_quality():
    with _quality_lock:
        if _quality_job["running"]:
            return False
        _quality_job.update({"running": True, "error": None, "started_at": time.time(), "finished_at": None})
    try:
        result = api.get_collection("Contact", offset=0, max_size=1)
        _, count = normalize_records(result)
        store.start_quality_scan(count)
        if count == 0:
            store.finish_quality_scan(True, None)
            return True
        offsets = list(range(0, count, QUALITY_PAGE_SIZE))
        keep_ids = set()
        with ThreadPoolExecutor(max_workers=QUALITY_WORKERS) as pool:
            futures = {
                pool.submit(fetch_quality_page, offset): offset
                for offset in offsets
            }
            for future in as_completed(futures):
                rows = future.result()
                tombstones = store.tombstoned_quality_ids()
                for row in rows:
                    contact_id = str(row.get("id") or "")
                    if not contact_id or contact_id in tombstones:
                        continue
                    keep_ids.add(contact_id)
                    item = decorate_contact(row)
                    store.upsert_quality(item)
        store.prune_quality(keep_ids)
        store.finish_quality_scan(True, None)
        with _quality_lock:
            _quality_job.update({"error": None, "finished_at": time.time()})
        return True
    except Exception as exc:
        store.finish_quality_scan(False, str(exc))
        with _quality_lock:
            _quality_job.update({"error": str(exc), "finished_at": time.time()})
        return False
    finally:
        with _quality_lock:
            _quality_job["running"] = False


def fetch_quality_page(offset):
    result = api.get_collection(
        "Contact",
        offset=offset,
        max_size=QUALITY_PAGE_SIZE,
        select=(
            "id", "name", "firstName", "lastName", "emailAddress", "phoneNumber",
            "title", "addressCity", "addressCountry", "description", "middleName",
            "addressStreet", "addressPostalCode", "accountId", "accountName", "createdAt", "modifiedAt"
        ),
        order_by="createdAt",
        order="desc",
    )
    rows, _ = normalize_records(result)
    return rows


def start_quality_scan(force=False):
    with _quality_lock:
        running = _quality_job["running"]
    state = store.quality_state()
    if running:
        return False
    # Keep serving the last complete cache while a background refresh runs.
    # A forced refresh is used after destructive mutations so the UI stays alive
    # while the cache is reconciled in the background.
    if not force and state.get("ready") and state.get("updated_at", 0) + QUALITY_TTL > time.time():
        return False
    thread = threading.Thread(target=scan_quality, daemon=True)
    thread.start()
    return True


def quality_payload():
    state = store.quality_state()
    counts = store.quality_counts()
    with _quality_lock:
        running = _quality_job["running"]
        error = _quality_job["error"]
    return {
        "ready": bool(state.get("ready")),
        "running": running,
        "error": error or state.get("error"),
        "updated_at": state.get("updated_at"),
        "counts": counts,
        "samples": {key: store.quality_page(key, 1, 5)["records"] for key in QUALITY_BUCKETS},
    }


def aggregate_quality_relationship():
    counts = store.quality_counts()
    complete = counts.get("complete", 0)
    partial = counts.get("partial", 0)
    minimal = counts.get("minimal", 0)
    return {
        "complete": complete,
        "partial": partial,
        "minimal": minimal,
        "missing_context": partial + minimal,
    }


def fetch_entity_pages_simple(entity, fields, page_size=200, order_by=None, order="asc", workers=6):
    """Reliable background fetcher using the proven collection API path.

    It deliberately avoids the advanced searchParams wrapper for analytics because
    analytics only needs full collections in server-side pages, and the basic
    collection endpoint is already proven by the live explorer/stats paths.
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
        first = api.get_collection(entity, offset=0, max_size=page_size)

    rows, total_count = normalize_records(first)
    rows = list(rows)
    total_count = max(0, int(total_count or 0))
    if total_count <= page_size:
        return rows

    offsets = list(range(page_size, total_count, page_size))

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
            result = api.get_collection(entity, offset=offset, max_size=page_size)
        page_rows, _ = normalize_records(result)
        return page_rows

    with ThreadPoolExecutor(max_workers=max(1, min(int(workers), len(offsets)))) as pool:
        futures = {pool.submit(load_page, offset): offset for offset in offsets}
        pages = []
        for future in as_completed(futures):
            offset = futures[future]
            page_rows = future.result()
            pages.append((offset, page_rows))

    for _, page_rows in sorted(pages, key=lambda item: item[0]):
        rows.extend(page_rows)
    return rows[:total_count]


def analytics_snapshot():
    now = time.time()
    with _analytics_lock:
        if _analytics_cache["data"] is not None and _analytics_cache["expires_at"] > now:
            return _analytics_cache["data"]
        if _analytics_cache["running"]:
            return None
        _analytics_cache["running"] = True
        _analytics_cache["error"] = None

    errors = {}
    try:
        try:
            opportunity_rows = fetch_entity_pages_simple(
                "Opportunity",
                ("id", "name", "stage", "amount", "amountCurrency", "closeDate",
                 "assignedUserName", "assignedUserId", "accountName", "contactName", "createdAt", "modifiedAt"),
                order_by="modifiedAt", order="desc"
            )
        except Exception as exc:
            opportunity_rows = []
            errors["Opportunity"] = str(exc)

        try:
            task_rows = fetch_entity_pages_simple(
                "Task",
                ("id", "name", "status", "priority", "dateEnd", "assignedUserName", "assignedUserId",
                 "parentName", "parentType", "parentId", "contactId", "contactName", "createdAt", "modifiedAt"),
                order_by="dateEnd", order="asc"
            )
        except Exception as exc:
            task_rows = []
            errors["Task"] = str(exc)

        try:
            cases_rows = fetch_entity_pages_simple(
                "Case",
                ("id", "name", "status", "priority", "type", "assignedUserName", "assignedUserId",
                 "contactId", "contactName", "accountId", "accountName", "createdAt", "modifiedAt"),
                order_by="modifiedAt", order="desc"
            )
        except Exception as exc:
            cases_rows = []
            errors["Case"] = str(exc)

        stage_counts = {stage: 0 for stage in STAGES}
        stage_amount = {stage: 0.0 for stage in STAGES}
        period = {}
        pic_counts = {}
        for row in opportunity_rows:
            stage = clean(row.get("stage")) or "Unknown"
            stage_counts.setdefault(stage, 0)
            stage_counts[stage] += 1
            try:
                stage_amount.setdefault(stage, 0.0)
                stage_amount[stage] += float(row.get("amount") or 0)
            except (TypeError, ValueError):
                pass
            date_value = clean(row.get("closeDate"))
            if date_value:
                key = date_value[:7]
                period[key] = period.get(key, 0) + 1
            pic = clean(row.get("assignedUserName")) or "Unassigned"
            pic_counts[pic] = pic_counts.get(pic, 0) + 1

        task_status = {status: 0 for status in TASK_STATUSES}
        task_pic = {}
        overdue = 0
        now_dt = datetime.now()
        for row in task_rows:
            status = clean(row.get("status")) or "Unknown"
            task_status.setdefault(status, 0)
            task_status[status] += 1
            pic = clean(row.get("assignedUserName")) or "Unassigned"
            task_pic[pic] = task_pic.get(pic, 0) + 1
            end = clean(row.get("dateEnd"))
            if end:
                try:
                    end_dt = datetime.strptime(end, "%Y-%m-%d %H:%M:%S")
                    if end_dt < now_dt and status not in ("Completed", "Canceled"):
                        overdue += 1
                except ValueError:
                    pass

        case_status = {status: 0 for status in CASE_STATUSES}
        urgent_cases = 0
        for row in cases_rows:
            status = clean(row.get("status")) or "Unknown"
            case_status.setdefault(status, 0)
            case_status[status] += 1
            if clean(row.get("priority")).lower() == "urgent":
                urgent_cases += 1

        pic_workload = {}
        for name, value in pic_counts.items():
            pic_workload.setdefault(name, {"opportunities": 0, "tasks": task_pic.get(name, 0)})
            pic_workload[name]["opportunities"] = value
        for name, value in task_pic.items():
            pic_workload.setdefault(name, {"opportunities": 0, "tasks": 0})
            pic_workload[name]["tasks"] = value

        quality = aggregate_quality_relationship()
        analytics = {
            "opportunity_stage": stage_counts,
            "opportunity_amount": stage_amount,
            "opportunity_period": dict(sorted(period.items())),
            "opportunity_pic": dict(sorted(pic_counts.items(), key=lambda x: x[1], reverse=True)[:12]),
            "task_status": task_status,
            "task_overdue": overdue,
            "pic_workload": dict(sorted(pic_workload.items(), key=lambda x: x[1]["opportunities"] + x[1]["tasks"], reverse=True)[:12]),
            "data_quality": {"complete": quality["complete"], "partial": quality["partial"], "minimal": quality["minimal"]},
            "relationship_health": {
                "with_full_context": quality["complete"],
                "needs_attention": quality["partial"],
                "poor_context": quality["minimal"],
            },
            "meta": {
                "opportunities": len(opportunity_rows),
                "tasks": len(task_rows),
                "cases": len(cases_rows),
                "urgent_cases": urgent_cases,
                "generated_at": time.time(),
                "errors": errors,
                "complete": not errors,
            },
        }
        with _analytics_lock:
            _analytics_cache["data"] = analytics
            _analytics_cache["expires_at"] = time.time() + ANALYTICS_TTL
        return analytics
    except Exception as exc:
        with _analytics_lock:
            _analytics_cache["error"] = str(exc)
        return None
    finally:
        with _analytics_lock:
            _analytics_cache["running"] = False




@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/health")
def health():
    started = time.perf_counter()
    try:
        result = api.get_collection("Contact", offset=0, max_size=1)
        _, total_count = normalize_records(result)
        return jsonify({"success": True, "total": total_count, "response_ms": round((time.perf_counter() - started) * 1000, 2)})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc), "response_ms": round((time.perf_counter() - started) * 1000, 2)}), 503


@app.get("/api/stats")
def stats():
    try:
        data = {
            "contacts": total("Contact"),
            "accounts": total("Account"),
            "opportunities": total("Opportunity"),
            "tasks": total("Task"),
            "cases": total("Case"),
        }
        q = store.quality_counts()
        state = store.quality_state()
        data.update(q)
        data["quality_ready"] = bool(state.get("ready"))
        return jsonify({"success": True, **data})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@app.get("/api/contacts/quality")
def contacts_quality():
    start_quality_scan()
    return jsonify({"success": True, **quality_payload()})


@app.post("/api/contacts/quality/refresh")
def refresh_quality():
    with _quality_lock:
        _quality_job["running"] = False
    store.invalidate_quality(clear_cache=True)
    start_quality_scan(force=True)
    return jsonify({"success": True, "message": "Quality scan dijalankan di background."})


@app.get("/api/contacts")
def contacts():
    page, page_size, offset = page_args(5)
    search = clean(request.args.get("search"))
    category = clean(request.args.get("category")) or None
    mode = clean(request.args.get("mode")) or "quality"
    sort = clean(request.args.get("sort")) or "createdAt"
    order = clean(request.args.get("order")) or "desc"
    allowed_sort = {"createdAt", "modifiedAt", "name"}
    if sort not in allowed_sort:
        sort = "createdAt"
    if order not in {"asc", "desc"}:
        order = "desc"

    if mode == "quality" and category in QUALITY_BUCKETS and store.quality_state().get("ready"):
        data = store.quality_page(category, page, page_size, search)
        return jsonify({"success": True, "mode": mode, **data})

    result = api.get_collection(
        "Contact", offset=offset, max_size=page_size,
        search=search or None, order_by=sort, order=order
    )
    rows, total_count = normalize_records(result)
    decorated = [decorate_contact(row) for row in rows]
    if mode == "quality" and category in QUALITY_BUCKETS:
        decorated = [row for row in decorated if row["completenessStatus"] == category]
        total_count = len(decorated)
    pages = max(1, math.ceil(total_count / page_size))
    return jsonify({
        "success": True, "mode": mode, "records": decorated, "total": total_count,
        "page": page, "pages": pages, "page_size": page_size,
        "quality_ready": bool(store.quality_state().get("ready")),
        "sort": sort, "order": order,
    })



@app.get("/api/contacts/<contact_id>")
def contact_detail(contact_id):
    try:
        row = decorate_contact(api.get_contact(contact_id))
        return jsonify({"success": True, "data": row})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@app.get("/api/contacts/<contact_id>/relationships")
def contact_relationships(contact_id):
    try:
        result = api.get_contact_relationships(contact_id, max_size=50)
        return jsonify({"success": True, "data": result})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


def resolve_account_id(account_id=None, new_account_name=None):
    account_id = clean(account_id) or None
    new_account_name = clean(new_account_name)
    if account_id or not new_account_name:
        return account_id
    matches = api.search_accounts(new_account_name, max_size=20)
    rows, _ = normalize_records(matches)
    exact = [r for r in rows if clean(r.get("name")).casefold() == new_account_name.casefold()]
    if len(exact) == 1 and exact[0].get("id"):
        return exact[0]["id"]
    account = api.create_record("Account", {"name": new_account_name})
    return account.get("id") if isinstance(account, dict) else None


@app.post("/api/contacts")
def create_contact():
    payload = request.get_json(silent=True) or {}
    try:
        account_id = resolve_account_id(payload.get("accountId"), payload.get("newAccountName"))
        created = api.create_contact(payload.get("firstName"), payload.get("lastName"), payload.get("emailAddress"), normalize_phone(payload.get("phoneNumber")), account_id)
        created = decorate_contact(created)
        store.upsert_quality(created)
        related = {"opportunity": None, "case": None, "errors": []}

        opp = payload.get("opportunity") or {}
        if clean(opp.get("name")):
            try:
                opp_account = clean(opp.get("accountId")) or None
                if clean(opp.get("newAccountName")):
                    acc = api.create_record("Account", {"name": clean(opp.get("newAccountName"))})
                    opp_account = acc.get("id")
                amount = parse_amount(opp.get("amount"))
                if amount is None:
                    raise api.EspoCRMError("Amount Opportunity wajib diisi.")
                close_date = clean(opp.get("closeDate"))
                if not close_date:
                    raise api.EspoCRMError("Close Date Opportunity wajib diisi.")
                opp_data = {"name": clean(opp.get("name")), "stage": clean(opp.get("stage")) or "Prospecting", "amount": amount, "amountCurrency": "USD", "closeDate": close_date}
                if opp_account: opp_data["accountId"] = opp_account
                if clean(opp.get("description")): opp_data["description"] = clean(opp.get("description"))
                related["opportunity"] = api.create_opportunity_for_contact(created["id"], opp_data)
                if isinstance(related["opportunity"], dict) and isinstance(related["opportunity"].get("record"), dict):
                    maybe_auto_sync(related["opportunity"]["record"])
            except Exception as exc:
                related["errors"].append({"type": "Opportunity", "message": str(exc)})

        case = payload.get("case") or {}
        if clean(case.get("name")):
            try:
                case_account = resolve_account_id(case.get("accountId"), case.get("newAccountName"))
                case_data = {"name": clean(case.get("name")), "status": clean(case.get("status")) or "New", "priority": clean(case.get("priority")) or "Normal", "type": clean(case.get("type")) or "Question"}
                if case_account: case_data["accountId"] = case_account
                if clean(case.get("description")): case_data["description"] = clean(case.get("description"))
                related["case"] = api.create_case_for_contact(created["id"], case_data)
            except Exception as exc:
                related["errors"].append({"type": "Case", "message": str(exc)})

        return jsonify({"success": True, "data": created, "related": related})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@app.put("/api/contacts/<contact_id>")
def update_contact(contact_id):
    payload = request.get_json(silent=True) or {}
    try:
        result = api.update_contact(contact_id, payload.get("firstName"), payload.get("lastName"), payload.get("emailAddress"), normalize_phone(payload.get("phoneNumber")), payload.get("accountId"))
        result = decorate_contact(result)
        store.upsert_quality(result)
        return jsonify({"success": True, "data": result})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@app.delete("/api/contacts/<contact_id>")
def delete_contact(contact_id):
    try:
        result = api.delete_contact_with_snapshot(contact_id)
        store.delete_quality(contact_id)
        # Keep the currently valid cache available immediately and refresh it
        # in the background instead of blanking the whole directory.
        start_quality_scan(force=True)
        return jsonify({"success": True, "data": result, "quality_refresh_started": True})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@app.get("/api/contacts/delete-mode")
def contacts_delete_mode():
    """Server-side paginated list for the destructive Contact deletion mode."""
    category = clean(request.args.get("category"))
    if category not in QUALITY_BUCKETS:
        return jsonify({"success": False, "error": "Kategori penghapusan tidak valid."}), 400
    if not store.quality_state().get("ready"):
        return jsonify({"success": False, "error": "Klasifikasi Contact belum siap.", "ready": False}), 409
    page = max(1, safe_int(request.args.get("page"), 1))
    page_size = max(25, min(100, safe_int(request.args.get("page_size"), 100)))
    search = clean(request.args.get("search")) or None
    data = store.quality_page(category, page, page_size, search)
    records = []
    for row in data.get("records", []):
        item = dict(row)
        item["displayName"] = contact_name(item)
        item["completenessScore"] = item.get("completenessScore", 0)
        item["completenessStatus"] = item.get("completenessStatus", category)
        records.append(item)
    return jsonify({"success": True, "category": category, **{**data, "records": records}})


@app.post("/api/contacts/bulk-delete")
def bulk_delete_contacts():
    payload = request.get_json(silent=True) or {}
    raw_ids = payload.get("ids") or []
    if not isinstance(raw_ids, list):
        return jsonify({"success": False, "error": "ids harus berupa array."}), 400
    ids = []
    seen = set()
    for value in raw_ids:
        item = clean(value)
        if item and item not in seen:
            ids.append(item)
            seen.add(item)
    if not ids:
        return jsonify({"success": False, "error": "Belum ada Contact yang dipilih."}), 400
    if len(ids) > 100:
        return jsonify({"success": False, "error": "Maksimal 100 Contact per proses penghapusan."}), 400
    deleted = []
    failed = []
    for contact_id in ids:
        try:
            api.delete_contact(contact_id)
            store.delete_quality(contact_id)
            deleted.append(contact_id)
        except Exception as exc:
            failed.append({"id": contact_id, "error": str(exc)})
    # Refresh classification in the background while continuing to serve the
    # current cache. Deleted IDs are tombstoned so an in-flight scan cannot
    # accidentally resurrect them.
    start_quality_scan(force=True)
    return jsonify({"success": True, "deleted": deleted, "failed": failed, "deleted_count": len(deleted), "failed_count": len(failed), "quality_refresh_started": True})


@app.post("/api/contacts/related")
def create_related_for_contact():
    payload = request.get_json(silent=True) or {}
    contact_id = clean(payload.get("contactId"))
    if not contact_id:
        return jsonify({"success": False, "error": "Contact ID wajib diisi."}), 400
    try:
        out = {}
        opp = payload.get("opportunity") or {}
        case = payload.get("case") or {}
        if clean(opp.get("name")):
            data = {"name": clean(opp.get("name")), "stage": clean(opp.get("stage")) or "Prospecting", "amount": parse_amount(opp.get("amount")) or 0, "amountCurrency": "USD", "closeDate": clean(opp.get("closeDate"))}
            if clean(opp.get("accountId")): data["accountId"] = clean(opp.get("accountId"))
            if clean(opp.get("description")): data["description"] = clean(opp.get("description"))
            out["opportunity"] = api.create_opportunity_for_contact(contact_id, data)
            record = out["opportunity"].get("record") if isinstance(out["opportunity"], dict) else None
            if isinstance(record, dict): maybe_auto_sync(record)
        if clean(case.get("name")):
            data = {"name": clean(case.get("name")), "status": clean(case.get("status")) or "New", "priority": clean(case.get("priority")) or "Normal", "type": clean(case.get("type")) or "Question"}
            if clean(case.get("accountId")): data["accountId"] = clean(case.get("accountId"))
            if clean(case.get("description")): data["description"] = clean(case.get("description"))
            out["case"] = api.create_case_for_contact(contact_id, data)
        return jsonify({"success": True, "data": out})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@app.get("/api/opportunities")
def opportunities():
    page, page_size, offset = page_args(25)
    params = {
        "offset": offset,
        "max_size": page_size,
        "search": clean(request.args.get("search")) or None,
        "stage": clean(request.args.get("stage")) or None,
        "assigned_user_id": clean(request.args.get("assignedUserId")) or None,
        "priority": clean(request.args.get("priority")) or None,
        "account_id": clean(request.args.get("accountId")) or None,
        "contact_id": clean(request.args.get("contactId")) or None,
        "order_by": clean(request.args.get("sort")) or "modifiedAt",
        "order": "asc" if clean(request.args.get("order")).lower() == "asc" else "desc",
    }
    allowed_sort = {"name", "stage", "amount", "closeDate", "createdAt", "modifiedAt", "accountName", "assignedUserName"}
    if params["order_by"] not in allowed_sort:
        params["order_by"] = "modifiedAt"
    started = time.perf_counter()
    try:
        result = api.get_opportunities_advanced(**params)
        rows, total_count = normalize_records(result)
        pages = max(1, math.ceil(total_count / page_size))
        return jsonify({"success": True, "records": rows, "total": total_count, "page": page, "pages": pages, "page_size": page_size, "response_ms": round((time.perf_counter() - started) * 1000, 2)})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@app.get("/api/opportunities/<opportunity_id>")
def opportunity_detail(opportunity_id):
    try:
        row = api.get_opportunity(opportunity_id)
        tasks = api.get_opportunity_tasks(opportunity_id, max_size=25)
        contacts = api.get_opportunity_contacts(opportunity_id, max_size=25)
        accounts = api.get_opportunity_accounts(opportunity_id, max_size=25)
        return jsonify({"success": True, "data": row, "relationships": {"tasks": normalize_records(tasks)[0], "contacts": normalize_records(contacts)[0], "accounts": normalize_records(accounts)[0]}})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@app.put("/api/opportunities/<opportunity_id>")
def update_opportunity(opportunity_id):
    payload = request.get_json(silent=True) or {}
    data = {key: payload[key] for key in ("name", "stage", "amount", "amountCurrency", "closeDate", "description", "accountId", "assignedUserId", "contactId") if key in payload and payload[key] not in (None, "")}
    try:
        result = api.update_record("Opportunity", opportunity_id, data)
        maybe_auto_sync(result)
        return jsonify({"success": True, "data": result})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@app.get("/api/tasks")
def tasks():
    page, page_size, _ = page_args(25)
    try:
        result = api.get_tasks_advanced(
            offset=(page - 1) * page_size,
            max_size=page_size,
            search=clean(request.args.get("search")) or None,
            status=clean(request.args.get("status")) or None,
            priority=clean(request.args.get("priority")) or None,
            assigned_user_id=clean(request.args.get("assignedUserId")) or None,
            parent_id=clean(request.args.get("parentId")) or None,
            overdue_only=clean(request.args.get("overdue")) == "true",
            order_by=clean(request.args.get("sort")) or "dateEnd",
            order="desc" if clean(request.args.get("order")).lower() == "desc" else "asc",
        )
        rows, total_count = normalize_records(result)
        return jsonify({"success": True, "records": rows, "total": total_count, "page": page, "pages": max(1, math.ceil(total_count / page_size)), "page_size": page_size})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@app.get("/api/cases")
def cases():
    page, page_size, offset = page_args(25)
    try:
        result = api.get_cases(offset=offset, max_size=page_size, search=clean(request.args.get("search")) or None)
        rows, total_count = normalize_records(result)
        return jsonify({"success": True, "records": rows, "total": total_count, "page": page, "pages": max(1, math.ceil(total_count / page_size)), "page_size": page_size})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@app.get("/api/cases/<case_id>")
def case_detail(case_id):
    try:
        return jsonify({"success": True, "data": api.get_case(case_id)})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@app.get("/api/analytics")
def analytics():
    data = analytics_snapshot()
    if data is None:
        start_quality_scan()
        with _analytics_lock:
            return jsonify({"success": True, "ready": False, "running": _analytics_cache["running"], "error": _analytics_cache["error"]})
    return jsonify({"success": True, "ready": True, "data": data})


def maybe_start_analytics():
    with _analytics_lock:
        running = _analytics_cache["running"]
        fresh = _analytics_cache["data"] is not None and _analytics_cache["expires_at"] > time.time()
    if not running and not fresh:
        threading.Thread(target=analytics_snapshot, daemon=True).start()


@app.get("/api/accurate/status")
def accurate_status():
    return jsonify({"success": True, **accurate.status()})


@app.get("/accurate/connect")
def accurate_connect():
    try:
        return redirect(accurate.authorization_url())
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@app.get("/accurate/callback")
def accurate_callback():
    code = clean(request.args.get("code"))
    if not code:
        return redirect("/?accurate=error")
    try:
        accurate.exchange_code(code)
        return redirect("/?accurate=connected")
    except Exception:
        return redirect("/?accurate=error")


@app.post("/api/accurate/disconnect")
def accurate_disconnect():
    accurate.disconnect()
    return jsonify({"success": True})


@app.post("/api/accurate/sync/opportunity/<opportunity_id>")
def accurate_sync_opportunity(opportunity_id):
    try:
        result = accurate.sync_opportunity(opportunity_id)
        return jsonify({"success": result.get("status") == "success", "data": result})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@app.get("/api/accurate/sync")
def accurate_sync_status():
    return jsonify({"success": True, "records": store.list_sync_records(limit=100)})


def sync_closed_won_worker():
    while True:
        try:
            if accurate.is_configured():
                result = api.get_opportunities_advanced(offset=0, max_size=50, stage="Closed Won", order_by="modifiedAt", order="desc", no_total=True)
                rows, _ = normalize_records(result)
                for row in rows:
                    if isinstance(row, dict) and row.get("id"):
                        maybe_auto_sync(row)
        except Exception:
            pass
        time.sleep(60)


def maybe_auto_sync(opportunity):
    if not isinstance(opportunity, dict):
        return None
    if clean(opportunity.get("stage")) != "Closed Won":
        return None
    if not accurate.is_configured():
        return None
    try:
        return accurate.sync_opportunity_record(opportunity)
    except Exception as exc:
        return store.record_sync_error(opportunity.get("id"), str(exc))


@app.route("/api/options/users")
def options_users():
    try:
        users = api.get_active_users(max_size=100)
        return jsonify({"success": True, "records": [{"id": row.get("id"), "name": row.get("name")} for row in users if isinstance(row, dict) and row.get("id")]})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@app.get("/api/options/accounts")
def options_accounts():
    try:
        result = api.get_collection("Account", offset=0, max_size=100, search=clean(request.args.get("search")) or None, order_by="name", order="asc", select=("id", "name"))
        rows, _ = normalize_records(result)
        return jsonify({"success": True, "records": [{"id": row.get("id"), "name": row.get("name")} for row in rows if isinstance(row, dict) and row.get("id")]})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@app.after_request
def no_store_for_api(response):
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


if __name__ == "__main__":
    start_quality_scan()
    maybe_start_analytics()
    threading.Thread(target=sync_closed_won_worker, daemon=True).start()
    app.run(host="127.0.0.1", port=5000, debug=False)
