from flask import Flask, jsonify, render_template, request
import math
import api

app = Flask(__name__, static_folder="static", template_folder="templates")
PAGE_SIZE_DEFAULT = 5
PAGE_SIZE_MAX = 50
GROUP_SIZE = 5


def clean_text(value):
    return str(value or "").strip()


def normalize_records(result):
    if isinstance(result, dict):
        records = result.get("list", [])
        if not isinstance(records, list):
            records = []
        total = result.get("total", len(records))
        try:
            total = int(total or 0)
        except (TypeError, ValueError):
            total = len(records)
        return records, total
    if isinstance(result, list):
        return result, len(result)
    return [], 0


def completeness(contact):
    fields = (
        "firstName", "lastName", "emailAddress", "phoneNumber", "title",
        "addressCity", "addressCountry", "description", "middleName",
        "phoneNumberMobile", "addressStreet", "addressPostalCode",
    )
    filled = sum(1 for field in fields if clean_text(contact.get(field)))
    score = round((filled / len(fields)) * 100)
    if score >= 72:
        status = "complete"
    elif score >= 38:
        status = "partial"
    else:
        status = "minimal"
    return {"score": score, "status": status}


def decorate_contact(contact):
    contact = dict(contact)
    result = completeness(contact)
    name = clean_text(contact.get("name")) or " ".join(
        x for x in (clean_text(contact.get("firstName")), clean_text(contact.get("lastName"))) if x
    ) or "Untitled Contact"
    contact.update({
        "displayName": name,
        "completenessScore": result["score"],
        "completenessStatus": result["status"],
    })
    return contact


def group_records(records, size=GROUP_SIZE):
    return [records[i:i + size] for i in range(0, len(records), size)]


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/contacts")
def contacts():
    search = clean_text(request.args.get("search")) or None
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = int(request.args.get("page_size", PAGE_SIZE_DEFAULT))
    except (TypeError, ValueError):
        page_size = PAGE_SIZE_DEFAULT
    page_size = max(1, min(page_size, PAGE_SIZE_MAX))
    offset = (page - 1) * page_size
    result = api.get_contacts(offset=offset, max_size=page_size, search=search)
    records, total = normalize_records(result)
    data = [decorate_contact(x) for x in records if isinstance(x, dict)]
    return jsonify({
        "success": True, "data": data, "total": total, "page": page,
        "page_size": page_size, "pages": max(1, math.ceil(total / page_size)),
        "group_size": GROUP_SIZE,
    })


@app.get("/api/contacts/<contact_id>")
def contact_detail(contact_id):
    try:
        result = api.get_contact(contact_id)
        return jsonify({"success": True, "data": decorate_contact(result) if isinstance(result, dict) else result})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@app.get("/api/contacts/<contact_id>/relationships")
def contact_relationships(contact_id):
    try:
        return jsonify({"success": True, "data": api.get_contact_relationships(contact_id, max_size=100)})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@app.get("/api/stats")
def stats():
    try:
        counts = {}
        for key, getter in (("contacts", api.get_contacts), ("accounts", api.get_accounts), ("opportunities", api.get_opportunities), ("cases", api.get_cases)):
            result = getter(offset=0, max_size=1)
            _, counts[key] = normalize_records(result)
        return jsonify({"success": True, **counts})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@app.get("/api/contacts/category/<status>")
def category_contacts(status):
    if status not in {"complete", "partial", "minimal"}:
        return jsonify({"success": False, "error": "Kategori tidak valid."}), 400
    try:
        result = api.get_contacts(offset=0, max_size=1000, search=None)
        records, _ = normalize_records(result)
        data = [decorate_contact(x) for x in records if isinstance(x, dict)]
        filtered = [x for x in data if x["completenessStatus"] == status]
        groups = group_records(filtered)
        return jsonify({"success": True, "status": status, "total": len(filtered), "groups": groups})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@app.post("/api/contacts")
def create_contact():
    payload = request.get_json(silent=True) or {}
    try:
        result = api.create_contact(payload.get("firstName"), payload.get("lastName"), payload.get("emailAddress"), payload.get("phoneNumber"), payload.get("accountId"))
        return jsonify({"success": True, "data": result})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@app.put("/api/contacts/<contact_id>")
def update_contact(contact_id):
    payload = request.get_json(silent=True) or {}
    try:
        result = api.update_contact(contact_id, first_name=payload.get("firstName"), last_name=payload.get("lastName"), email=payload.get("emailAddress"), phone=payload.get("phoneNumber"), account_id=payload.get("accountId"))
        return jsonify({"success": True, "data": result})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@app.delete("/api/contacts/<contact_id>")
def delete_contact(contact_id):
    try:
        return jsonify({"success": True, "data": api.delete_contact_with_snapshot(contact_id)})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@app.post("/api/contacts/restore")
def restore_contact():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify({"success": True, "data": api.restore_contact(payload.get("snapshot"))})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@app.post("/api/generate")
def generate_test_data():
    payload = request.get_json(silent=True) or {}
    try:
        count = max(1, min(500, int(payload.get("count", 25))))
    except (TypeError, ValueError):
        count = 25
    generator = getattr(api, "generate_test_contacts", None)
    if generator is None:
        return jsonify({"success": False, "error": "Fungsi generate_test_contacts() tidak tersedia di api.py."}), 400
    try:
        return jsonify({"success": True, "data": generator(count)})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@app.get("/api/health")
def health():
    try:
        ok = bool(api.check_connection())
        return jsonify({"success": ok})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
