"""
api.py
============================================================

EspoCRM API Communication Layer
============================================================

Base:
    http://localhost:8081/api/v1

Authentication:
    Basic Authentication
    USERNAME + PASSWORD dari config.py

============================================================
CONTACT
============================================================

- get_contacts()
- get_contact()
- create_contact()
- create_contact_from_data()
- update_contact()
- delete_contact()
- create_contacts_bulk()
- generate_test_contacts()
- create_test_accounts()

============================================================
ACCOUNT
============================================================

- get_accounts()
- get_account()
- get_contact_accounts()
- link_contact_account()
- unlink_contact_account()

============================================================
OPPORTUNITY
============================================================

- get_opportunities()
- get_opportunity()
- get_contact_opportunities()
- link_contact_opportunity()
- unlink_contact_opportunity()
- create_opportunity_for_contact()
- update_opportunity()
- delete_opportunity()

============================================================
CASE
============================================================

- get_cases()
- get_case()
- get_contact_cases()
- link_contact_case()
- unlink_contact_case()
- create_case_for_contact()
- update_case()
- delete_case()

============================================================
RELATIONSHIP
============================================================

- get_related_records()
- link_records()
- unlink_records()
- get_relationship_summary()
- get_contact_relationships()
- get_contact_relationship_ids()

============================================================
UNDO / RESTORE
============================================================

- get_contact_restore_snapshot()
- delete_contact_with_snapshot()
- restore_contact()

============================================================
SEARCH
============================================================

- search_accounts()
- search_opportunities()
- search_cases()

============================================================
UTILITY
============================================================

- request()
- check_connection()
- test_connection()
- get_users()
- get_user()
- get_tasks()
- get_task()
- create_task()
- update_task()
- delete_task()
- get_opportunity_tasks()
- get_opportunity_contacts()
- get_opportunity_accounts()
- get_opportunities_advanced()
- get_tasks_advanced()
- create_records_bulk()
- generate_large_accounts()
- generate_large_contacts()
- generate_large_opportunities()
- generate_large_tasks()
- generate_large_crm_dataset()
"""

import re
import random
import uuid
import time
import json
import uuid
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.auth import HTTPBasicAuth

from config import BASE_URL, USERNAME, PASSWORD


# ============================================================
# CONFIGURATION
# ============================================================

TIMEOUT = 15
TEST_DATA_RETRY_COUNT = 3
TEST_DATA_RETRY_DELAY = 0.15
TEST_DATA_BATCH_DELAY = 0.03

LARGE_DATASET_DEFAULT_WORKERS = 6
LARGE_DATASET_DEFAULT_BATCH_SIZE = 200
LARGE_DATASET_MAX_WORKERS = 12
LARGE_DATASET_RETRY_COUNT = 4
LARGE_DATASET_RETRY_DELAY = 0.25


# ============================================================
# AUTHENTICATION
# ============================================================

AUTH = HTTPBasicAuth(
    USERNAME,
    PASSWORD
)


# ============================================================
# HEADERS
# ============================================================

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}


# ============================================================
# CUSTOM EXCEPTION
# ============================================================

class EspoCRMError(Exception):
    """
    Custom exception untuk error EspoCRM.
    """
    pass


# ============================================================
# URL BUILDER
# ============================================================

def build_url(endpoint):
    """
    Membuat URL API.

    Contoh:

        build_url("Contact")

    menjadi:

        http://localhost:8081/api/v1/Contact
    """

    base = str(BASE_URL).rstrip("/")
    endpoint = str(endpoint).strip("/")

    return f"{base}/{endpoint}"


# ============================================================
# HELPER - STRING
# ============================================================

def _clean_string(value):
    """
    Membersihkan value menjadi string.

    None -> ""

    Contoh:

        _clean_string("  Chitoge  ")

    menjadi:

        "Chitoge"
    """

    if value is None:
        return ""

    return str(value).strip()


# ============================================================
# HELPER - EMAIL
# ============================================================

def _validate_email(email):
    """
    Validasi sederhana email.

    Tidak terlalu ketat karena validasi final
    tetap dilakukan oleh EspoCRM.
    """

    email = _clean_string(email)

    if not email:
        raise EspoCRMError(
            "Email wajib diisi."
        )

    pattern = (
        r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    )

    if not re.match(pattern, email):

        raise EspoCRMError(
            f"Format email tidak valid:\n{email}"
        )

    return email


# ============================================================
# HELPER - PHONE
# ============================================================

def _validate_phone(phone):
    """
    Validasi nomor telepon.

    Mengizinkan:

        +628123456789
        08123456789
        +62 812-3456-789

    Karakter yang diperbolehkan:

        angka
        +
        spasi
        -
        (
        )
    """

    phone = _clean_string(phone)

    if not phone:

        raise EspoCRMError(
            "Phone wajib diisi."
        )

    # --------------------------------------------------------
    # Karakter yang tidak diperbolehkan
    # --------------------------------------------------------

    if not re.match(
        r"^[0-9+\-\s()]+$",
        phone
    ):

        raise EspoCRMError(
            "Format Phone tidak valid.\n\n"
            "Gunakan angka, +, spasi, -, atau tanda kurung."
        )

    # --------------------------------------------------------
    # Minimal angka
    # --------------------------------------------------------

    digit_count = len(
        re.sub(
            r"\D",
            "",
            phone
        )
    )

    if digit_count < 5:

        raise EspoCRMError(
            "Nomor Phone terlalu pendek."
        )

    return phone


# ============================================================
# HELPER - REQUIRED CONTACT
# ============================================================

def _validate_contact_data(
    first_name,
    last_name,
    email,
    phone
):
    """
    Validasi data Contact sebelum dikirim
    ke EspoCRM.
    """

    first_name = _clean_string(
        first_name
    )

    last_name = _clean_string(
        last_name
    )

    if not first_name:

        raise EspoCRMError(
            "First Name wajib diisi."
        )

    if not last_name:

        raise EspoCRMError(
            "Last Name wajib diisi."
        )

    email = _validate_email(
        email
    )

    phone = _validate_phone(
        phone
    )

    return {
        "firstName": first_name,
        "lastName": last_name,
        "emailAddress": email,
        "phoneNumber": phone,
    }


# ============================================================
# RESPONSE ERROR HANDLER
# ============================================================

def _handle_response(response):
    """
    Memproses response dari EspoCRM.

    Success:
        return JSON / True

    Error:
        raise EspoCRMError
    """

    status = response.status_code

    # ========================================================
    # SUCCESS
    # ========================================================

    if 200 <= status < 300:

        if not response.content:
            return True

        try:

            return response.json()

        except ValueError:

            return True

    # ========================================================
    # ERROR MESSAGE
    # ========================================================

    message = ""

    try:

        data = response.json()

        if isinstance(data, dict):

            message = (
                data.get("message")
                or data.get("error")
                or data.get("errorMessage")
                or ""
            )

            # ------------------------------------------------
            # EspoCRM kadang mengirim validationFailure
            # ------------------------------------------------

            if not message:

                validation = data.get(
                    "validationFailure"
                )

                if validation:

                    message = str(
                        validation
                    )

    except Exception:
        pass

    # ========================================================
    # FALLBACK RESPONSE TEXT
    # ========================================================

    if not message:

        message = (
            response.text
            or "Unknown error"
        )

    # ========================================================
    # STATUS MESSAGE
    # ========================================================

    if status == 400:

        prefix = "Bad Request"

    elif status == 401:

        prefix = (
            "Unauthorized - "
            "Username atau password EspoCRM tidak valid."
        )

    elif status == 403:

        prefix = (
            "Forbidden - "
            "User tidak memiliki permission."
        )

    elif status == 404:

        prefix = (
            "Not Found - "
            "Endpoint atau data tidak ditemukan."
        )

    elif status == 409:

        prefix = (
            "Conflict - "
            "Data mengalami konflik atau duplikat."
        )

    elif status >= 500:

        prefix = (
            "EspoCRM Server Error"
        )

    else:

        prefix = (
            f"HTTP Error {status}"
        )

    # ========================================================
    # CREATE ERROR MESSAGE
    # ========================================================

    raise EspoCRMError(
        f"{prefix}\n\n"
        f"Status: {status}\n"
        f"Message: {message}"
    )


# ============================================================
# GENERIC REQUEST
# ============================================================

def request(
    method,
    endpoint,
    params=None,
    data=None
):
    """
    Fungsi utama komunikasi dengan EspoCRM.

    Parameters
    ----------
    method:
        GET / POST / PUT / PATCH / DELETE

    endpoint:
        Contoh:
            Contact
            Contact/123
            Contact/123/accounts

    params:
        Query parameter.

    data:
        JSON body.
    """

    url = build_url(
        endpoint
    )

    method = str(
        method
    ).upper()

    try:

        response = requests.request(
            method=method,
            url=url,
            headers=HEADERS,
            auth=AUTH,
            params=params,
            json=data,
            timeout=TIMEOUT
        )

    except requests.exceptions.ConnectionError as exc:

        raise EspoCRMError(
            "Tidak dapat terhubung ke EspoCRM.\n\n"
            "Pastikan Docker/EspoCRM sedang berjalan.\n\n"
            f"Server:\n{BASE_URL}\n\n"
            f"Detail:\n{exc}"
        )

    except requests.exceptions.Timeout as exc:

        raise EspoCRMError(
            "Request ke EspoCRM mengalami timeout.\n\n"
            f"Detail:\n{exc}"
        )

    except requests.exceptions.RequestException as exc:

        raise EspoCRMError(
            "Terjadi error ketika menghubungi EspoCRM.\n\n"
            f"Detail:\n{exc}"
        )

    return _handle_response(
        response
    )


# ============================================================
# GET COLLECTION
# ============================================================

def get_collection(
    entity,
    offset=0,
    max_size=20,
    search=None,
    select=None,
    order_by=None,
    order="asc"
):
    """
    Mengambil collection dari EspoCRM.
    """

    params = {
        "offset": int(offset),
        "maxSize": int(max_size),
    }

    # ========================================================
    # SEARCH
    # ========================================================

    if search is not None:

        search = _clean_string(
            search
        )

        if search:

            params["textFilter"] = search

    # ========================================================
    # SELECT
    # ========================================================

    if select:

        if isinstance(
            select,
            (list, tuple)
        ):

            params["select"] = ",".join(
                str(x)
                for x in select
            )

        else:

            params["select"] = str(
                select
            )

    # ========================================================
    # ORDER
    # ========================================================

    if order_by:

        params["orderBy"] = str(
            order_by
        )

        params["order"] = (
            "desc"
            if str(order).lower() == "desc"
            else "asc"
        )

    return request(
        "GET",
        entity,
        params=params
    )


# ============================================================
# GET SINGLE RECORD
# ============================================================

def get_record(
    entity,
    record_id
):
    """
    Mengambil satu record berdasarkan ID.
    """

    record_id = _clean_string(
        record_id
    )

    if not record_id:

        raise EspoCRMError(
            f"ID {entity} tidak boleh kosong."
        )

    return request(
        "GET",
        f"{entity}/{record_id}"
    )


# ============================================================
# CREATE RECORD
# ============================================================

def create_record(
    entity,
    data
):
    """
    Membuat record baru.
    """

    if not isinstance(
        data,
        dict
    ):

        raise EspoCRMError(
            "Data harus berupa dictionary."
        )

    if not data:

        raise EspoCRMError(
            "Data tidak boleh kosong."
        )

    return request(
        "POST",
        entity,
        data=data
    )


# ============================================================
# UPDATE RECORD
# ============================================================

def update_record(
    entity,
    record_id,
    data
):
    """
    Mengubah record.
    """

    record_id = _clean_string(
        record_id
    )

    if not record_id:

        raise EspoCRMError(
            f"ID {entity} tidak boleh kosong."
        )

    if not isinstance(
        data,
        dict
    ):

        raise EspoCRMError(
            "Data harus berupa dictionary."
        )

    if not data:

        raise EspoCRMError(
            "Tidak ada data yang akan diubah."
        )

    return request(
        "PUT",
        f"{entity}/{record_id}",
        data=data
    )


# ============================================================
# DELETE RECORD
# ============================================================

def delete_record(
    entity,
    record_id
):
    """
    Menghapus record.
    """

    record_id = _clean_string(
        record_id
    )

    if not record_id:

        raise EspoCRMError(
            f"ID {entity} tidak boleh kosong."
        )

    return request(
        "DELETE",
        f"{entity}/{record_id}"
    )


# ============================================================
# RELATED RECORDS
# ============================================================

def get_related_records(
    entity,
    record_id,
    link,
    max_size=100,
    offset=0,
    search=None,
    select=None,
    order_by=None,
    order="asc"
):
    """
    Mengambil record yang berhubungan.

    Contoh:

        Contact/{id}/accounts
        Contact/{id}/opportunities
        Contact/{id}/cases
    """

    record_id = _clean_string(
        record_id
    )

    link = _clean_string(
        link
    )

    if not record_id:

        raise EspoCRMError(
            "Record ID tidak boleh kosong."
        )

    if not link:

        raise EspoCRMError(
            "Relationship link tidak boleh kosong."
        )

    params = {
        "offset": int(offset),
        "maxSize": int(max_size)
    }

    # ========================================================
    # SEARCH
    # ========================================================

    if search is not None:

        search = _clean_string(
            search
        )

        if search:

            params["textFilter"] = search

    # ========================================================
    # SELECT
    # ========================================================

    if select:

        if isinstance(
            select,
            (list, tuple)
        ):

            params["select"] = ",".join(
                str(x)
                for x in select
            )

        else:

            params["select"] = str(
                select
            )

    # ========================================================
    # ORDER
    # ========================================================

    if order_by:

        params["orderBy"] = str(
            order_by
        )

        params["order"] = (
            "desc"
            if str(order).lower() == "desc"
            else "asc"
        )

    return request(
        "GET",
        f"{entity}/{record_id}/{link}",
        params=params
    )


# ============================================================
# EXTRACT RECORDS
# ============================================================

def _extract_records(result):
    """
    Mengubah response collection menjadi list record.
    """

    if isinstance(
        result,
        dict
    ):

        records = result.get(
            "list",
            []
        )

        if isinstance(
            records,
            list
        ):

            return records

        return []

    if isinstance(
        result,
        list
    ):

        return result

    return []


# ============================================================
# EXTRACT TOTAL
# ============================================================

def _extract_total(result):
    """
    Mengambil total record.
    """

    if isinstance(
        result,
        dict
    ):

        total = result.get(
            "total"
        )

        if total is not None:

            try:

                return int(
                    total
                )

            except (
                TypeError,
                ValueError
            ):

                pass

        records = result.get(
            "list",
            []
        )

        if isinstance(
            records,
            list
        ):

            return len(
                records
            )

    elif isinstance(
        result,
        list
    ):

        return len(
            result
        )

    return 0


# ============================================================
# CONTACT
# ============================================================

def get_contacts(
    offset=0,
    max_size=20,
    search=None
):
    """
    Mengambil daftar Contact.
    """

    return get_collection(
        "Contact",
        offset=offset,
        max_size=max_size,
        search=search,
        order_by="createdAt",
        order="desc"
    )


# ============================================================

def get_contact(
    contact_id
):
    """
    Mengambil detail Contact.
    """

    return get_record(
        "Contact",
        contact_id
    )


# ============================================================
# CREATE CONTACT
# ============================================================

def create_contact(
    first_name,
    last_name,
    email,
    phone,
    account_id=None
):
    """
    Membuat Contact baru.

    Validasi dilakukan sebelum request
    dikirim ke EspoCRM.
    """

    # ========================================================
    # VALIDATE REQUIRED FIELDS
    # ========================================================

    data = _validate_contact_data(
        first_name,
        last_name,
        email,
        phone
    )

    # ========================================================
    # ACCOUNT
    # ========================================================

    account_id = _clean_string(
        account_id
    )

    if account_id:

        data["accountId"] = account_id

    # ========================================================
    # CREATE
    # ========================================================

    return create_record(
        "Contact",
        data
    )


# ============================================================
# CREATE CONTACT FROM DATA
# ============================================================

def create_contact_from_data(
    data
):
    """
    Membuat Contact dari snapshot.

    Digunakan terutama untuk Restore.
    """

    if not isinstance(
        data,
        dict
    ):

        raise EspoCRMError(
            "Data Contact harus berupa dictionary."
        )

    allowed_fields = (
        "salutationName",
        "firstName",
        "lastName",
        "middleName",
        "emailAddress",
        "phoneNumber",
        "phoneNumberMobile",
        "phoneNumberHome",
        "phoneNumberFax",
        "accountId",
        "title",
        "description",
        "addressStreet",
        "addressCity",
        "addressState",
        "addressCountry",
        "addressPostalCode",
        "doNotCall",
        "emailAddressIsOptedOut",
    )

    payload = {}

    for field in allowed_fields:

        if field not in data:
            continue

        value = data.get(
            field
        )

        # Jangan kirim None
        if value is None:
            continue

        # Jangan kirim string kosong
        # untuk field optional
        if isinstance(
            value,
            str
        ):

            value = value.strip()

            if not value:
                continue

        payload[field] = value

    # ========================================================
    # REQUIRED FIELDS
    # ========================================================

    first_name = payload.get(
        "firstName",
        ""
    )

    last_name = payload.get(
        "lastName",
        ""
    )

    email = payload.get(
        "emailAddress",
        ""
    )

    phone = payload.get(
        "phoneNumber",
        ""
    )

    if not first_name:

        raise EspoCRMError(
            "Snapshot Contact tidak memiliki First Name."
        )

    if not last_name:

        raise EspoCRMError(
            "Snapshot Contact tidak memiliki Last Name."
        )

    if not email:

        raise EspoCRMError(
            "Snapshot Contact tidak memiliki Email."
        )

    if not phone:

        raise EspoCRMError(
            "Snapshot Contact tidak memiliki Phone."
        )

    # ========================================================
    # VALIDATE
    # ========================================================

    payload["firstName"] = _clean_string(
        first_name
    )

    payload["lastName"] = _clean_string(
        last_name
    )

    payload["emailAddress"] = _validate_email(
        email
    )

    payload["phoneNumber"] = _validate_phone(
        phone
    )

    # ========================================================
    # CREATE
    # ========================================================

    return create_record(
        "Contact",
        payload
    )


# ============================================================
# UPDATE CONTACT
# ============================================================

def update_contact(
    contact_id,
    first_name=None,
    last_name=None,
    email=None,
    phone=None,
    account_id=None
):
    """
    Update Contact.

    Hanya field yang dikirim akan diubah.
    """

    contact_id = _clean_string(
        contact_id
    )

    if not contact_id:

        raise EspoCRMError(
            "Contact ID tidak boleh kosong."
        )

    data = {}

    # ========================================================
    # FIRST NAME
    # ========================================================

    if first_name is not None:

        first_name = _clean_string(
            first_name
        )

        if not first_name:

            raise EspoCRMError(
                "First Name wajib diisi."
            )

        data["firstName"] = first_name

    # ========================================================
    # LAST NAME
    # ========================================================

    if last_name is not None:

        last_name = _clean_string(
            last_name
        )

        if not last_name:

            raise EspoCRMError(
                "Last Name wajib diisi."
            )

        data["lastName"] = last_name

    # ========================================================
    # EMAIL
    # ========================================================

    if email is not None:

        email = _validate_email(
            email
        )

        data["emailAddress"] = email

    # ========================================================
    # PHONE
    # ========================================================

    if phone is not None:

        phone = _validate_phone(
            phone
        )

        data["phoneNumber"] = phone

    # ========================================================
    # ACCOUNT
    # ========================================================

    if account_id is not None:

        account_id = _clean_string(
            account_id
        )

        if account_id:

            data["accountId"] = account_id

    # ========================================================
    # CHECK DATA
    # ========================================================

    if not data:

        raise EspoCRMError(
            "Tidak ada data yang akan diubah."
        )

    # ========================================================
    # UPDATE
    # ========================================================

    return update_record(
        "Contact",
        contact_id,
        data
    )


# ============================================================
# DELETE CONTACT
# ============================================================

def delete_contact(
    contact_id
):
    """
    Delete Contact.
    """

    return delete_record(
        "Contact",
        contact_id
    )


# ============================================================
# ACCOUNT
# ============================================================

def get_accounts(
    offset=0,
    max_size=100,
    search=None
):
    """
    Mengambil daftar Account.
    """

    return get_collection(
        "Account",
        offset=offset,
        max_size=max_size,
        search=search,
        order_by="name",
        order="asc"
    )


# ============================================================

def get_account(
    account_id
):
    """
    Mengambil detail Account.
    """

    return get_record(
        "Account",
        account_id
    )


# ============================================================
# CONTACT -> ACCOUNTS
# ============================================================

def get_contact_accounts(
    contact_id,
    max_size=100,
    offset=0,
    search=None
):
    """
    Mengambil Account yang terhubung
    dengan Contact.
    """

    return get_related_records(
        "Contact",
        contact_id,
        "accounts",
        max_size=max_size,
        offset=offset,
        search=search,
        order_by="name",
        order="asc"
    )


# ============================================================
# LINK ACCOUNT
# ============================================================

def link_contact_account(
    contact_id,
    account_id
):
    """
    Menghubungkan Contact dengan Account.
    """

    return link_records(
        "Contact",
        contact_id,
        "accounts",
        account_id
    )


# ============================================================
# UNLINK ACCOUNT
# ============================================================

def unlink_contact_account(
    contact_id,
    account_id
):
    """
    Melepaskan hubungan Contact dengan Account.
    """

    return unlink_records(
        "Contact",
        contact_id,
        "accounts",
        account_id
    )


# ============================================================
# OPPORTUNITY
# ============================================================

def get_opportunities(
    offset=0,
    max_size=100,
    search=None
):
    """
    Mengambil daftar Opportunity.
    """

    return get_collection(
        "Opportunity",
        offset=offset,
        max_size=max_size,
        search=search,
        order_by="createdAt",
        order="desc"
    )


# ============================================================

def get_opportunity(
    opportunity_id
):
    """
    Mengambil detail Opportunity.
    """

    return get_record(
        "Opportunity",
        opportunity_id
    )


# ============================================================
# CONTACT -> OPPORTUNITIES
# ============================================================

def get_contact_opportunities(
    contact_id,
    max_size=100,
    offset=0,
    search=None
):
    """
    Mengambil Opportunity yang terhubung
    dengan Contact.
    """

    return get_related_records(
        "Contact",
        contact_id,
        "opportunities",
        max_size=max_size,
        offset=offset,
        search=search,
        order_by="createdAt",
        order="desc"
    )


# ============================================================
# LINK OPPORTUNITY
# ============================================================

def link_contact_opportunity(
    contact_id,
    opportunity_id
):
    """
    Menghubungkan Contact dengan Opportunity.
    """

    return link_records(
        "Contact",
        contact_id,
        "opportunities",
        opportunity_id
    )


# ============================================================
# UNLINK OPPORTUNITY
# ============================================================

def unlink_contact_opportunity(
    contact_id,
    opportunity_id
):
    """
    Melepaskan hubungan Contact dengan Opportunity.
    """

    return unlink_records(
        "Contact",
        contact_id,
        "opportunities",
        opportunity_id
    )


# ============================================================
# CREATE OPPORTUNITY FOR CONTACT
# ============================================================

def create_opportunity_for_contact(
    contact_id,
    data
):
    """
    Membuat Opportunity baru lalu
    otomatis menghubungkannya dengan Contact.
    """

    contact_id = _clean_string(
        contact_id
    )

    if not contact_id:

        raise EspoCRMError(
            "Contact ID tidak boleh kosong."
        )

    if not isinstance(
        data,
        dict
    ):

        raise EspoCRMError(
            "Data Opportunity harus berupa dictionary."
        )

    if not data:

        raise EspoCRMError(
            "Data Opportunity tidak boleh kosong."
        )

    # ========================================================
    # CREATE
    # ========================================================

    created = create_record(
        "Opportunity",
        data
    )

    if not isinstance(
        created,
        dict
    ):

        raise EspoCRMError(
            "EspoCRM tidak mengembalikan "
            "data Opportunity."
        )

    opportunity_id = created.get(
        "id"
    )

    if not opportunity_id:

        raise EspoCRMError(
            "Opportunity berhasil dibuat tetapi "
            "ID tidak ditemukan."
        )

    # ========================================================
    # LINK
    # ========================================================

    link_contact_opportunity(
        contact_id,
        opportunity_id
    )

    return {
        "record": created,
        "relationship_created": True
    }


# ============================================================
# UPDATE OPPORTUNITY
# ============================================================

def update_opportunity(
    opportunity_id,
    data
):
    """
    Update Opportunity.
    """

    return update_record(
        "Opportunity",
        opportunity_id,
        data
    )


# ============================================================
# DELETE OPPORTUNITY
# ============================================================

def delete_opportunity(
    opportunity_id
):
    """
    Delete Opportunity.
    """

    return delete_record(
        "Opportunity",
        opportunity_id
    )


# ============================================================
# CASE
# ============================================================

def get_cases(
    offset=0,
    max_size=100,
    search=None
):
    """
    Mengambil daftar Case.
    """

    return get_collection(
        "Case",
        offset=offset,
        max_size=max_size,
        search=search,
        order_by="createdAt",
        order="desc"
    )


# ============================================================

def get_case(
    case_id
):
    """
    Mengambil detail Case.
    """

    return get_record(
        "Case",
        case_id
    )


# ============================================================
# CONTACT -> CASES
# ============================================================

def get_contact_cases(
    contact_id,
    max_size=100,
    offset=0,
    search=None
):
    """
    Mengambil Case yang terhubung
    dengan Contact.
    """

    return get_related_records(
        "Contact",
        contact_id,
        "cases",
        max_size=max_size,
        offset=offset,
        search=search,
        order_by="createdAt",
        order="desc"
    )


# ============================================================
# LINK CASE
# ============================================================

def link_contact_case(
    contact_id,
    case_id
):
    """
    Menghubungkan Contact dengan Case.
    """

    return link_records(
        "Contact",
        contact_id,
        "cases",
        case_id
    )


# ============================================================
# UNLINK CASE
# ============================================================

def unlink_contact_case(
    contact_id,
    case_id
):
    """
    Melepaskan hubungan Contact dengan Case.
    """

    return unlink_records(
        "Contact",
        contact_id,
        "cases",
        case_id
    )


# ============================================================
# CREATE CASE FOR CONTACT
# ============================================================

def create_case_for_contact(
    contact_id,
    data
):
    """
    Membuat Case baru lalu
    otomatis menghubungkannya dengan Contact.
    """

    contact_id = _clean_string(
        contact_id
    )

    if not contact_id:

        raise EspoCRMError(
            "Contact ID tidak boleh kosong."
        )

    if not isinstance(
        data,
        dict
    ):

        raise EspoCRMError(
            "Data Case harus berupa dictionary."
        )

    if not data:

        raise EspoCRMError(
            "Data Case tidak boleh kosong."
        )

    # ========================================================
    # CREATE
    # ========================================================

    created = create_record(
        "Case",
        data
    )

    if not isinstance(
        created,
        dict
    ):

        raise EspoCRMError(
            "EspoCRM tidak mengembalikan "
            "data Case."
        )

    case_id = created.get(
        "id"
    )

    if not case_id:

        raise EspoCRMError(
            "Case berhasil dibuat tetapi "
            "ID tidak ditemukan."
        )

    # ========================================================
    # LINK
    # ========================================================

    link_contact_case(
        contact_id,
        case_id
    )

    return {
        "record": created,
        "relationship_created": True
    }


# ============================================================
# UPDATE CASE
# ============================================================

def update_case(
    case_id,
    data
):
    """
    Update Case.
    """

    return update_record(
        "Case",
        case_id,
        data
    )


# ============================================================
# DELETE CASE
# ============================================================

def delete_case(
    case_id
):
    """
    Delete Case.
    """

    return delete_record(
        "Case",
        case_id
    )


# ============================================================
# GENERIC LINK
# ============================================================

def link_records(
    entity,
    record_id,
    link,
    related_id
):
    """
    Menghubungkan dua record.

    Endpoint:

        POST Entity/{record_id}/{link}

    Body:

        {
            "id": "related_id"
        }
    """

    record_id = _clean_string(
        record_id
    )

    link = _clean_string(
        link
    )

    related_id = _clean_string(
        related_id
    )

    if not record_id:

        raise EspoCRMError(
            "Record ID tidak boleh kosong."
        )

    if not link:

        raise EspoCRMError(
            "Relationship link tidak boleh kosong."
        )

    if not related_id:

        raise EspoCRMError(
            "Related ID tidak boleh kosong."
        )

    return request(
        "POST",
        f"{entity}/{record_id}/{link}",
        data={
            "id": related_id
        }
    )


# ============================================================
# GENERIC LINK MANY
# ============================================================

def link_records_many(
    entity,
    record_id,
    link,
    related_ids
):
    """
    Menghubungkan satu record dengan
    banyak record sekaligus.
    """

    record_id = _clean_string(
        record_id
    )

    link = _clean_string(
        link
    )

    if not record_id:

        raise EspoCRMError(
            "Record ID tidak boleh kosong."
        )

    if not link:

        raise EspoCRMError(
            "Relationship link tidak boleh kosong."
        )

    if not isinstance(
        related_ids,
        (list, tuple)
    ):

        raise EspoCRMError(
            "related_ids harus berupa list."
        )

    # FIX:
    # sebelumnya menggunakan record_id
    # bukan related_id

    cleaned_ids = [
        str(related_id).strip()
        for related_id in related_ids
        if related_id
    ]

    if not cleaned_ids:

        raise EspoCRMError(
            "Tidak ada Related ID."
        )

    return request(
        "POST",
        f"{entity}/{record_id}/{link}",
        data={
            "ids": cleaned_ids
        }
    )


# ============================================================
# GENERIC UNLINK
# ============================================================

def unlink_records(
    entity,
    record_id,
    link,
    related_id
):
    """
    Melepaskan relationship.
    """

    record_id = _clean_string(
        record_id
    )

    link = _clean_string(
        link
    )

    related_id = _clean_string(
        related_id
    )

    if not record_id:

        raise EspoCRMError(
            "Record ID tidak boleh kosong."
        )

    if not link:

        raise EspoCRMError(
            "Relationship link tidak boleh kosong."
        )

    if not related_id:

        raise EspoCRMError(
            "Related ID tidak boleh kosong."
        )

    return request(
        "DELETE",
        f"{entity}/{record_id}/{link}",
        data={
            "id": related_id
        }
    )


# ============================================================
# GENERIC UNLINK MANY
# ============================================================

def unlink_records_many(
    entity,
    record_id,
    link,
    related_ids
):
    """
    Melepaskan banyak relationship sekaligus.
    """

    record_id = _clean_string(
        record_id
    )

    link = _clean_string(
        link
    )

    if not record_id:

        raise EspoCRMError(
            "Record ID tidak boleh kosong."
        )

    if not link:

        raise EspoCRMError(
            "Relationship link tidak boleh kosong."
        )

    if not isinstance(
        related_ids,
        (list, tuple)
    ):

        raise EspoCRMError(
            "related_ids harus berupa list."
        )

    # FIX:
    # sebelumnya menggunakan record_id
    # bukan related_id

    cleaned_ids = [
        str(related_id).strip()
        for related_id in related_ids
        if related_id
    ]

    if not cleaned_ids:

        raise EspoCRMError(
            "Tidak ada Related ID."
        )

    return request(
        "DELETE",
        f"{entity}/{record_id}/{link}",
        data={
            "ids": cleaned_ids
        }
    )


# ============================================================
# GET CONTACT RELATIONSHIP SUMMARY
# ============================================================

def get_relationship_summary(
    contact_id
):
    """
    Mengambil jumlah relationship Contact.

    Return:

        {
            "accounts": 1,
            "opportunities": 2,
            "cases": 3
        }
    """

    contact_id = _clean_string(
        contact_id
    )

    if not contact_id:

        raise EspoCRMError(
            "Contact ID tidak boleh kosong."
        )

    summary = {
        "accounts": 0,
        "opportunities": 0,
        "cases": 0
    }

    # ========================================================
    # ACCOUNT
    # ========================================================

    try:

        result = get_contact_accounts(
            contact_id,
            max_size=1
        )

        summary["accounts"] = (
            _extract_total(
                result
            )
        )

    except Exception:

        summary["accounts"] = 0

    # ========================================================
    # OPPORTUNITY
    # ========================================================

    try:

        result = get_contact_opportunities(
            contact_id,
            max_size=1
        )

        summary["opportunities"] = (
            _extract_total(
                result
            )
        )

    except Exception:

        summary["opportunities"] = 0

    # ========================================================
    # CASE
    # ========================================================

    try:

        result = get_contact_cases(
            contact_id,
            max_size=1
        )

        summary["cases"] = (
            _extract_total(
                result
            )
        )

    except Exception:

        summary["cases"] = 0

    return summary


# ============================================================
# GET ALL CONTACT RELATIONSHIPS
# ============================================================

def get_contact_relationships(
    contact_id,
    max_size=100
):
    """
    Mengambil seluruh relationship Contact.

    Return:

        {
            "accounts": [...],
            "opportunities": [...],
            "cases": [...],
            "summary": {
                ...
            }
        }
    """

    contact_id = _clean_string(
        contact_id
    )

    if not contact_id:

        raise EspoCRMError(
            "Contact ID tidak boleh kosong."
        )

    # ========================================================
    # ACCOUNT
    # ========================================================

    accounts_result = (
        get_contact_accounts(
            contact_id,
            max_size=max_size
        )
    )

    # ========================================================
    # OPPORTUNITY
    # ========================================================

    opportunities_result = (
        get_contact_opportunities(
            contact_id,
            max_size=max_size
        )
    )

    # ========================================================
    # CASE
    # ========================================================

    cases_result = (
        get_contact_cases(
            contact_id,
            max_size=max_size
        )
    )

    # ========================================================
    # EXTRACT
    # ========================================================

    accounts = _extract_records(
        accounts_result
    )

    opportunities = _extract_records(
        opportunities_result
    )

    cases = _extract_records(
        cases_result
    )

    return {
        "accounts": accounts,
        "opportunities": opportunities,
        "cases": cases,

        "summary": {
            "accounts": len(accounts),
            "opportunities": len(opportunities),
            "cases": len(cases)
        }
    }


# ============================================================
# GET CONTACT RELATIONSHIP IDS
# ============================================================

def get_contact_relationship_ids(
    contact_id
):
    """
    Mengambil hanya ID relationship.

    Berguna untuk Undo/Restore.
    """

    relationships = (
        get_contact_relationships(
            contact_id
        )
    )

    return {
        "accounts": [
            item.get("id")
            for item in relationships["accounts"]
            if isinstance(
                item,
                dict
            )
            and item.get("id")
        ],

        "opportunities": [
            item.get("id")
            for item in relationships["opportunities"]
            if isinstance(
                item,
                dict
            )
            and item.get("id")
        ],

        "cases": [
            item.get("id")
            for item in relationships["cases"]
            if isinstance(
                item,
                dict
            )
            and item.get("id")
        ]
    }


# ============================================================
# CONTACT RESTORE SNAPSHOT
# ============================================================

def get_contact_restore_snapshot(
    contact_id
):
    """
    Mengambil snapshot lengkap Contact
    sebelum dihapus.

    Snapshot:

        contact
        relationships.accounts
        relationships.opportunities
        relationships.cases
    """

    contact_id = _clean_string(
        contact_id
    )

    if not contact_id:

        raise EspoCRMError(
            "Contact ID tidak boleh kosong."
        )

    # ========================================================
    # CONTACT
    # ========================================================

    contact = get_contact(
        contact_id
    )

    if not isinstance(
        contact,
        dict
    ):

        raise EspoCRMError(
            "Data Contact tidak valid."
        )

    # ========================================================
    # RELATIONSHIP
    # ========================================================

    relationship_ids = (
        get_contact_relationship_ids(
            contact_id
        )
    )

    return {
        "contact": dict(
            contact
        ),

        "relationships": {
            "accounts": relationship_ids[
                "accounts"
            ],

            "opportunities": relationship_ids[
                "opportunities"
            ],

            "cases": relationship_ids[
                "cases"
            ]
        }
    }


# ============================================================
# DELETE CONTACT WITH SNAPSHOT
# ============================================================

def delete_contact_with_snapshot(
    contact_id
):
    """
    Menghapus Contact setelah snapshot dibuat.

    Return:
        snapshot
    """

    snapshot = (
        get_contact_restore_snapshot(
            contact_id
        )
    )

    delete_contact(
        contact_id
    )

    return snapshot


# ============================================================
# RESTORE CONTACT
# ============================================================

def restore_contact(
    snapshot
):
    """
    Restore Contact dari snapshot.

    Relationship akan dicoba dikembalikan.
    """

    if not isinstance(
        snapshot,
        dict
    ):

        raise EspoCRMError(
            "Snapshot restore tidak valid."
        )

    # ========================================================
    # CONTACT DATA
    # ========================================================

    contact_data = snapshot.get(
        "contact"
    )

    if not isinstance(
        contact_data,
        dict
    ):

        raise EspoCRMError(
            "Data Contact pada snapshot tidak ditemukan."
        )

    # ========================================================
    # CREATE CONTACT
    # ========================================================

    created = create_contact_from_data(
        contact_data
    )

    if not isinstance(
        created,
        dict
    ):

        raise EspoCRMError(
            "Contact tidak berhasil dibuat kembali."
        )

    new_contact_id = created.get(
        "id"
    )

    if not new_contact_id:

        raise EspoCRMError(
            "Contact berhasil dibuat tetapi "
            "ID baru tidak ditemukan."
        )

    # ========================================================
    # RELATIONSHIPS
    # ========================================================

    relationships = snapshot.get(
        "relationships",
        {}
    )

    if not isinstance(
        relationships,
        dict
    ):

        relationships = {}

    result = {

        "contact": created,

        "contact_id": new_contact_id,

        "restored_relationships": {
            "accounts": 0,
            "opportunities": 0,
            "cases": 0
        },

        "failed_relationships": {
            "accounts": [],
            "opportunities": [],
            "cases": []
        }
    }

    # ========================================================
    # ACCOUNT
    # ========================================================

    account_ids = relationships.get(
        "accounts",
        []
    )

    if not isinstance(
        account_ids,
        list
    ):

        account_ids = []

    for account_id in account_ids:

        try:

            link_contact_account(
                new_contact_id,
                account_id
            )

            result[
                "restored_relationships"
            ][
                "accounts"
            ] += 1

        except Exception:

            result[
                "failed_relationships"
            ][
                "accounts"
            ].append(
                account_id
            )

    # ========================================================
    # OPPORTUNITY
    # ========================================================

    opportunity_ids = relationships.get(
        "opportunities",
        []
    )

    if not isinstance(
        opportunity_ids,
        list
    ):

        opportunity_ids = []

    for opportunity_id in opportunity_ids:

        try:

            link_contact_opportunity(
                new_contact_id,
                opportunity_id
            )

            result[
                "restored_relationships"
            ][
                "opportunities"
            ] += 1

        except Exception:

            result[
                "failed_relationships"
            ][
                "opportunities"
            ].append(
                opportunity_id
            )

    # ========================================================
    # CASE
    # ========================================================

    case_ids = relationships.get(
        "cases",
        []
    )

    if not isinstance(
        case_ids,
        list
    ):

        case_ids = []

    for case_id in case_ids:

        try:

            link_contact_case(
                new_contact_id,
                case_id
            )

            result[
                "restored_relationships"
            ][
                "cases"
            ] += 1

        except Exception:

            result[
                "failed_relationships"
            ][
                "cases"
            ].append(
                case_id
            )

    return result


# ============================================================
# TEST DATA GENERATOR
# ============================================================

_TEST_FIRST_NAMES = (
    "Dimas", "Arya", "Rizky", "Fajar", "Andi",
    "Budi", "Bagas", "Raka", "Rian", "Ilham",
    "Adit", "Arif", "Bayu", "Deni", "Eko",
    "Farhan", "Galih", "Hendra", "Iqbal", "Joko",
    "Kevin", "Luthfi", "Maulana", "Naufal", "Putra",
    "Reza", "Satria", "Tegar", "Wahyu", "Yoga",
    "Ayu", "Citra", "Dewi", "Fitri", "Indah",
    "Kartika", "Laras", "Maya", "Nadia", "Putri",
    "Rani", "Salsa", "Tiara", "Vina", "Wulan",
)

_TEST_LAST_NAMES = (
    "Pratama", "Saputra", "Wijaya", "Setiawan", "Nugraha",
    "Permana", "Kurniawan", "Hidayat", "Ramadhan", "Santoso",
    "Maulana", "Firmansyah", "Gunawan", "Wibowo", "Siregar",
    "Putri", "Lestari", "Utami", "Anggraini", "Rahmawati",
    "Maharani", "Puspitasari", "Amalia", "Kusuma", "Sari",
)

_TEST_EMAIL_DOMAINS = (
    "gmail.com",
    "gmail.co.id",
)

_TEST_ACCOUNT_NAMES = (
    "PT Nusantara Digital",
    "PT Arta Teknologi Indonesia",
    "PT Cipta Solusi Mandiri",
    "PT Mitra Usaha Sejahtera",
    "PT Sinar Data Indonesia",
    "PT Karya Teknologi Bersama",
    "PT Bintang Nusantara",
    "PT Prima Solusi Digital",
    "PT Sentosa Makmur",
    "PT Mandiri Teknologi Utama",
    "PT Inovasi Bisnis Indonesia",
    "PT Cahaya Abadi Teknologi",
    "PT Maju Jaya Informatika",
    "PT Global Solusi Nusantara",
    "PT Kreasi Digital Indonesia",
    "PT Sukses Bersama",
    "PT Mitra Digital Sejahtera",
    "PT Anugerah Teknologi",
    "PT Pilar Bisnis Indonesia",
    "PT Solusi Cerdas Nusantara",
    "PT Karya Mandiri Digital",
    "PT Graha Teknologi Indonesia",
    "PT Era Digital Nusantara",
    "PT Terang Jaya Abadi",
    "PT Pesona Data Indonesia",
    "PT Sinergi Usaha Digital",
    "PT Wahana Teknologi",
    "PT Adi Karya Nusantara",
    "PT Berkah Solusi Indonesia",
    "PT Sentral Data Indonesia",
    "PT Cakra Digital",
    "PT Samudra Teknologi",
    "PT Jaya Informatika",
    "PT Aksara Digital Indonesia",
    "PT Bhakti Teknologi Nusantara",
    "PT Bumi Solusi Digital",
    "PT Daya Kreasi Indonesia",
    "PT Harmoni Data Nusantara",
    "PT Integra Teknologi",
    "PT Lentera Bisnis Indonesia",
    "PT Makmur Digital Sejahtera",
    "PT Nusa Karya Teknologi",
    "PT Optima Solusi Indonesia",
    "PT Persada Digital Nusantara",
    "PT Reka Cipta Teknologi",
    "PT Surya Data Indonesia",
    "PT Tiga Pilar Digital",
    "PT Utama Solusi Nusantara",
    "PT Visi Teknologi Indonesia",
    "PT Wijaya Digital Sejahtera",
)

_TEST_JOB_TITLES = (
    "Staff Administrasi",
    "Sales Executive",
    "Marketing Specialist",
    "Project Coordinator",
    "Customer Support",
    "Business Development",
    "IT Support",
    "Finance Staff",
    "Operations Staff",
    "Account Executive",
)

_TEST_CITIES = (
    "Jakarta",
    "Bandung",
    "Surabaya",
    "Semarang",
    "Yogyakarta",
    "Medan",
    "Bekasi",
    "Depok",
    "Tangerang",
    "Malang",
)

_TEST_STREETS = (
    "Jl. Sudirman No. 10",
    "Jl. Diponegoro No. 21",
    "Jl. Gatot Subroto No. 15",
    "Jl. Ahmad Yani No. 32",
    "Jl. Merdeka No. 8",
    "Jl. Pahlawan No. 17",
    "Jl. Pemuda No. 24",
    "Jl. Asia Afrika No. 11",
)

_TEST_DESCRIPTIONS = (
    "Data Contact untuk pengujian dashboard.",
    "Contact dummy untuk pengujian CRUD dan relationship.",
    "Data simulasi untuk kebutuhan demonstrasi EspoCRM.",
    "Record pengujian yang dibuat oleh generator aplikasi Python.",
)


def _generate_unique_test_email(first_name, last_name, index, used_emails=None):
    """
    Membuat email dummy yang tetap terlihat natural dan unik.
    """

    first = re.sub(r"[^a-z0-9]", "", str(first_name).lower())
    last = re.sub(r"[^a-z0-9]", "", str(last_name).lower())

    if used_emails is None:
        used_emails = set()

    for domain in random.sample(
        list(_TEST_EMAIL_DOMAINS),
        len(_TEST_EMAIL_DOMAINS)
    ):
        base = f"{first}.{last}@{domain}"

        if base.lower() not in used_emails:
            used_emails.add(base.lower())
            return base

    number = 1
    while True:
        for domain in _TEST_EMAIL_DOMAINS:
            candidate = f"{first}.{last}{number:02d}@{domain}"
            if candidate.lower() not in used_emails:
                used_emails.add(candidate.lower())
                return candidate
        number += 1


def _generate_test_phone(index):
    """
    Membuat nomor telepon Indonesia yang valid untuk EspoCRM.
    """

    suffix = f"{index:06d}"
    return f"+62812{suffix}"


def _build_test_contact_data(index, completeness="complete", used_emails=None):
    """
    Membuat satu data Contact dummy.

    Required fields selalu diisi agar tetap kompatibel dengan
    validasi Contact yang sudah ada.

    completeness:
        complete
        incomplete
        very_incomplete
    """

    first_name = random.choice(_TEST_FIRST_NAMES)
    last_name = random.choice(_TEST_LAST_NAMES)
    city = random.choice(_TEST_CITIES)

    data = {
        "firstName": first_name,
        "lastName": last_name,
        "emailAddress": _generate_unique_test_email(
            first_name,
            last_name,
            index,
            used_emails=used_emails
        ),
        "phoneNumber": _generate_test_phone(index),
    }

    if completeness in ("complete", "incomplete"):
        data["title"] = random.choice(_TEST_JOB_TITLES)
        data["description"] = random.choice(_TEST_DESCRIPTIONS)
        data["addressStreet"] = random.choice(_TEST_STREETS)
        data["addressCity"] = city
        data["addressState"] = city
        data["addressCountry"] = "Indonesia"
        data["addressPostalCode"] = str(
            random.randint(10000, 99999)
        )

    if completeness == "complete":
        data["middleName"] = random.choice(_TEST_FIRST_NAMES)
        data["phoneNumberMobile"] = _generate_test_phone(index + 1000)

    return data


def _is_retryable_test_data_error(exc):
    message = str(exc).lower()

    if "timeout" in message:
        return True

    if "tidak dapat terhubung" in message:
        return True

    for status in (
        "status: 429",
        "status: 500",
        "status: 501",
        "status: 502",
        "status: 503",
        "status: 504",
        "status: 505",
    ):
        if status in message:
            return True

    return False


def _create_test_contact_with_retry(contact_data):
    last_error = None

    for attempt in range(1, TEST_DATA_RETRY_COUNT + 1):
        try:
            created = create_contact_from_data(contact_data)

            if not isinstance(created, dict):
                raise EspoCRMError(
                    "EspoCRM tidak mengembalikan data Contact."
                )

            return created

        except Exception as exc:
            last_error = exc

            if not _is_retryable_test_data_error(exc):
                raise

            if attempt < TEST_DATA_RETRY_COUNT:
                time.sleep(
                    TEST_DATA_RETRY_DELAY * attempt
                )

    raise last_error


def create_contacts_bulk(contact_data_list, stop_on_error=False):
    """
    Membuat banyak Contact dari list dictionary.

    Error sementara seperti timeout, koneksi terputus,
    HTTP 429, dan server 5xx akan dicoba ulang otomatis.
    """

    if not isinstance(contact_data_list, (list, tuple)):
        raise EspoCRMError(
            "contact_data_list harus berupa list atau tuple."
        )

    created_records = []
    failed_records = []

    for index, contact_data in enumerate(
        contact_data_list,
        start=1
    ):
        try:
            if not isinstance(contact_data, dict):
                raise EspoCRMError(
                    "Data Contact harus berupa dictionary."
                )

            created = _create_test_contact_with_retry(
                contact_data
            )

            created_records.append(created)

        except Exception as exc:
            failed_records.append({
                "index": index,
                "data": dict(contact_data)
                if isinstance(contact_data, dict)
                else contact_data,
                "error": str(exc),
            })

            if stop_on_error:
                break

        if index < len(contact_data_list):
            time.sleep(
                TEST_DATA_BATCH_DELAY
            )

    return {
        "success": len(failed_records) == 0,
        "created": created_records,
        "failed": failed_records,
        "created_count": len(created_records),
        "failed_count": len(failed_records),
    }


def _get_existing_account_names():
    names = set()

    try:
        result = get_accounts(
            offset=0,
            max_size=1000
        )

        for record in _extract_records(result):
            if isinstance(record, dict):
                name = _clean_string(record.get("name"))
                if name:
                    names.add(name.lower())
    except Exception:
        pass

    return names


def _build_unique_account_name(used_names, start_index):
    candidates = list(_TEST_ACCOUNT_NAMES)
    random.shuffle(candidates)

    for name in candidates:
        if name.lower() not in used_names:
            used_names.add(name.lower())
            return name

    suffix = max(2, int(start_index) + 1)

    while True:
        base = random.choice(_TEST_ACCOUNT_NAMES)
        name = f"{base} {suffix:02d}"

        if name.lower() not in used_names:
            used_names.add(name.lower())
            return name

        suffix += 1


def create_test_accounts(count=10):
    try:
        count = int(count)
    except (TypeError, ValueError):
        raise EspoCRMError(
            "Jumlah Account harus berupa angka."
        )

    if count < 1:
        return {
            "created": [],
            "failed": [],
            "created_count": 0,
            "failed_count": 0,
        }

    if count > 50:
        count = 50

    used_names = _get_existing_account_names()
    created_records = []
    failed_records = []

    for index in range(count):
        name = _build_unique_account_name(
            used_names,
            index
        )

        try:
            created = create_record(
                "Account",
                {
                    "name": name
                }
            )

            if not isinstance(created, dict):
                raise EspoCRMError(
                    "EspoCRM tidak mengembalikan data Account."
                )

            created_records.append(created)

        except Exception as exc:
            failed_records.append({
                "name": name,
                "error": str(exc),
            })

        time.sleep(
            TEST_DATA_BATCH_DELAY
        )

    return {
        "created": created_records,
        "failed": failed_records,
        "created_count": len(created_records),
        "failed_count": len(failed_records),
    }


def generate_test_contacts(
    count=25,
    link_relationships=True,
    random_seed=None,
    stop_on_error=False
):
    """
    Membuat data Contact dummy untuk kebutuhan demonstrasi.

    Distribusi data:
        70% complete
        20% incomplete
        10% very_incomplete

    Semua Contact tetap memiliki field wajib:
        firstName
        lastName
        emailAddress
        phoneNumber

    Relationship akan memakai record Account, Opportunity, dan Case
    yang sudah tersedia di EspoCRM. Fungsi ini tidak membuat Entity
    relationship baru sehingga tidak mengubah struktur CRM.
    """

    try:
        count = int(count)
    except (TypeError, ValueError):
        raise EspoCRMError(
            "Jumlah Contact harus berupa angka."
        )

    if count < 1:
        raise EspoCRMError(
            "Jumlah Contact minimal 1."
        )

    if count > 500:
        raise EspoCRMError(
            "Jumlah Contact maksimal 500 per proses."
        )

    if random_seed is not None:
        random.seed(random_seed)

    contact_data_list = []
    completeness_list = []
    used_emails = set()

    try:
        existing_contacts = get_contacts(
            offset=0,
            max_size=1000,
            search=None
        )

        for record in _extract_records(existing_contacts):
            if isinstance(record, dict):
                email = _clean_string(
                    record.get("emailAddress")
                ).lower()
                if email:
                    used_emails.add(email)
    except Exception:
        pass

    complete_count = int(round(count * 0.70))
    incomplete_count = int(round(count * 0.20))
    very_incomplete_count = count - complete_count - incomplete_count

    completeness_list.extend(
        ["complete"] * complete_count
    )
    completeness_list.extend(
        ["incomplete"] * incomplete_count
    )
    completeness_list.extend(
        ["very_incomplete"] * very_incomplete_count
    )

    random.shuffle(completeness_list)

    base_index = int(time.time() * 1000) % 100000000

    for position, completeness in enumerate(
        completeness_list,
        start=1
    ):
        contact_data_list.append(
            _build_test_contact_data(
                base_index + position,
                completeness=completeness,
                used_emails=used_emails
            )
        )

    bulk_result = create_contacts_bulk(
        contact_data_list,
        stop_on_error=stop_on_error
    )

    account_target = max(
        5,
        min(30, (count + 9) // 10)
    )

    account_result = create_test_accounts(
        count=account_target
    )

    relationship_result = {
        "accounts_created": account_result["created_count"],
        "accounts_failed": account_result["failed_count"],
        "accounts": 0,
        "opportunities": 0,
        "cases": 0,
    }

    if link_relationships and bulk_result["created"]:
        relationship_pools = {
            "accounts": [],
            "opportunities": [],
            "cases": [],
        }

        try:
            relationship_pools["accounts"] = _extract_records(
                get_accounts(
                    offset=0,
                    max_size=100
                )
            )
        except Exception:
            relationship_pools["accounts"] = []

        try:
            relationship_pools["opportunities"] = _extract_records(
                get_opportunities(
                    offset=0,
                    max_size=100
                )
            )
        except Exception:
            relationship_pools["opportunities"] = []

        try:
            relationship_pools["cases"] = _extract_records(
                get_cases(
                    offset=0,
                    max_size=100
                )
            )
        except Exception:
            relationship_pools["cases"] = []

        for position, contact in enumerate(
            bulk_result["created"]
        ):
            contact_id = contact.get("id")

            if not contact_id:
                continue

            completeness = completeness_list[
                position
            ]

            if completeness == "very_incomplete":
                max_accounts = 0
                max_opportunities = 0
                max_cases = 0
            elif completeness == "incomplete":
                max_accounts = random.randint(0, 1)
                max_opportunities = random.randint(0, 1)
                max_cases = random.randint(0, 1)
            else:
                max_accounts = random.randint(1, 2)
                max_opportunities = random.randint(1, 2)
                max_cases = random.randint(1, 2)

            account_ids = [
                item.get("id")
                for item in random.sample(
                    relationship_pools["accounts"],
                    k=min(
                        max_accounts,
                        len(relationship_pools["accounts"])
                    )
                )
                if isinstance(item, dict)
                and item.get("id")
            ]

            opportunity_ids = [
                item.get("id")
                for item in random.sample(
                    relationship_pools["opportunities"],
                    k=min(
                        max_opportunities,
                        len(relationship_pools["opportunities"])
                    )
                )
                if isinstance(item, dict)
                and item.get("id")
            ]

            case_ids = [
                item.get("id")
                for item in random.sample(
                    relationship_pools["cases"],
                    k=min(
                        max_cases,
                        len(relationship_pools["cases"])
                    )
                )
                if isinstance(item, dict)
                and item.get("id")
            ]

            if account_ids:
                try:
                    link_records_many(
                        "Contact",
                        contact_id,
                        "accounts",
                        account_ids
                    )
                    relationship_result["accounts"] += len(
                        account_ids
                    )
                except Exception:
                    pass

            if opportunity_ids:
                try:
                    link_records_many(
                        "Contact",
                        contact_id,
                        "opportunities",
                        opportunity_ids
                    )
                    relationship_result["opportunities"] += len(
                        opportunity_ids
                    )
                except Exception:
                    pass

            if case_ids:
                try:
                    link_records_many(
                        "Contact",
                        contact_id,
                        "cases",
                        case_ids
                    )
                    relationship_result["cases"] += len(
                        case_ids
                    )
                except Exception:
                    pass

    return {
        "success": bulk_result["failed_count"] == 0,
        "requested": count,
        "created_count": bulk_result["created_count"],
        "failed_count": bulk_result["failed_count"],
        "contacts": bulk_result["created"],
        "failed": bulk_result["failed"],
        "relationships": relationship_result,
        "new_accounts": account_result["created_count"],
        "failed_accounts": account_result["failed_count"],
        "account_records": account_result["created"],
        "account_failures": account_result["failed"],
    }



# ============================================================
# USER / PIC
# ============================================================

def get_users(
    offset=0,
    max_size=100,
    search=None
):
    """
    Mengambil daftar User yang dapat digunakan sebagai PIC.
    """
    return get_collection(
        "User",
        offset=offset,
        max_size=max_size,
        search=search,
        select=[
            "id",
            "name",
            "userName",
            "firstName",
            "lastName",
            "emailAddress",
            "isActive",
        ],
        order_by="name",
        order="asc"
    )


def get_user(
    user_id
):
    """
    Mengambil detail User/PIC.
    """
    return get_record(
        "User",
        user_id
    )


def get_active_users(
    max_size=1000
):
    """
    Mengambil User/PIC aktif untuk assignment Task.

    Instance tertentu dapat menolak request User dengan maxSize
    besar atau parameter select/order tertentu. Karena itu data
    User diambil dalam page kecil tanpa select dan tanpa sorting.

    Pagination tetap dipakai agar fungsi tetap bisa menangani
    lebih dari satu PIC.
    """
    try:
        requested_size = max(1, int(max_size))
    except (
        TypeError,
        ValueError
    ):
        requested_size = 1000

    page_size = 5
    records = []
    offset = 0

    while len(records) < requested_size:
        current_size = min(
            page_size,
            requested_size - len(records)
        )

        try:
            result = get_collection(
                "User",
                offset=offset,
                max_size=current_size
            )
        except Exception as exc:
            if records:
                break

            raise EspoCRMError(
                "Gagal membaca User/PIC dari EspoCRM.\n\n"
                f"Detail:\n{exc}"
            )

        page_records = _extract_records(
            result
        )

        if not page_records:
            break

        records.extend(
            page_records
        )

        if len(page_records) < current_size:
            break

        offset += current_size

    active = []

    for record in records:
        if not isinstance(
            record,
            dict
        ):
            continue

        record_id = record.get(
            "id"
        )

        if not record_id:
            continue

        is_active = record.get(
            "isActive"
        )

        if is_active is False:
            continue

        if isinstance(
            is_active,
            str
        ):
            normalized = (
                is_active
                .strip()
                .lower()
            )

            if normalized in (
                "false",
                "0",
                "no",
                "inactive"
            ):
                continue

        active.append(
            record
        )

    return active[:requested_size]


# ============================================================
# TASK
# ============================================================

def get_tasks(
    offset=0,
    max_size=100,
    search=None
):
    """
    Mengambil daftar Task.
    """
    return get_collection(
        "Task",
        offset=offset,
        max_size=max_size,
        search=search,
        select=[
            "id",
            "name",
            "status",
            "priority",
            "dateStart",
            "dateEnd",
            "assignedUserId",
            "assignedUserName",
            "parentType",
            "parentId",
            "parentName",
            "createdAt",
            "modifiedAt",
        ],
        order_by="dateEnd",
        order="asc"
    )


def get_task(
    task_id
):
    """
    Mengambil detail Task.
    """
    return get_record(
        "Task",
        task_id
    )


def create_task(
    name,
    status=None,
    priority=None,
    date_start=None,
    date_end=None,
    assigned_user_id=None,
    parent_type=None,
    parent_id=None,
    description=None
):
    """
    Membuat Task.
    Field opsional hanya dikirim jika memiliki nilai.
    """
    name = _clean_string(name)

    if not name:
        raise EspoCRMError(
            "Task Name wajib diisi."
        )

    data = {
        "name": name
    }

    optional_fields = {
        "status": status,
        "priority": priority,
        "dateStart": date_start,
        "dateEnd": date_end,
        "assignedUserId": assigned_user_id,
        "parentType": parent_type,
        "parentId": parent_id,
        "description": description,
    }

    for field, value in optional_fields.items():
        cleaned = (
            _clean_string(value)
            if isinstance(value, str)
            else value
        )

        if cleaned is None:
            continue

        if isinstance(cleaned, str) and not cleaned:
            continue

        data[field] = cleaned

    return create_record(
        "Task",
        data
    )


def update_task(
    task_id,
    data
):
    """
    Mengubah Task.
    """
    return update_record(
        "Task",
        task_id,
        data
    )


def delete_task(
    task_id
):
    """
    Menghapus Task.
    """
    return delete_record(
        "Task",
        task_id
    )


def get_opportunity_tasks(
    opportunity_id,
    max_size=100,
    offset=0,
    search=None
):
    """
    Mengambil Task yang parent-nya Opportunity.
    Prefer menggunakan parent relation API jika tersedia.
    """
    opportunity_id = _clean_string(
        opportunity_id
    )

    if not opportunity_id:
        raise EspoCRMError(
            "Opportunity ID tidak boleh kosong."
        )

    params = {
        "offset": int(offset),
        "maxSize": int(max_size),
        "orderBy": "dateEnd",
        "order": "asc",
        "select": (
            "id,name,status,priority,dateStart,dateEnd,"
            "assignedUserId,assignedUserName,parentType,parentId,parentName"
        ),
    }

    if search:
        params["textFilter"] = _clean_string(
            search
        )

    try:
        return request(
            "GET",
            f"Opportunity/{opportunity_id}/tasks",
            params=params
        )
    except Exception:
        return get_collection_advanced(
            "Task",
            offset=offset,
            max_size=max_size,
            search=search,
            select=[
                "id",
                "name",
                "status",
                "priority",
                "dateStart",
                "dateEnd",
                "assignedUserId",
                "assignedUserName",
                "parentType",
                "parentId",
                "parentName",
            ],
            order_by="dateEnd",
            order="asc",
            where=[
                {
                    "type": "equals",
                    "attribute": "parentType",
                    "value": "Opportunity",
                },
                {
                    "type": "equals",
                    "attribute": "parentId",
                    "value": opportunity_id,
                },
            ],
        )


def get_opportunity_contacts(
    opportunity_id,
    max_size=100,
    offset=0,
    search=None
):
    """
    Mengambil Contact yang terhubung ke Opportunity.
    """
    return get_related_records(
        "Opportunity",
        opportunity_id,
        "contacts",
        max_size=max_size,
        offset=offset,
        search=search,
        order_by="name",
        order="asc"
    )


def get_opportunity_accounts(
    opportunity_id,
    max_size=100,
    offset=0,
    search=None
):
    """
    Mengambil Account yang terhubung ke Opportunity.
    """
    return get_related_records(
        "Opportunity",
        opportunity_id,
        "accounts",
        max_size=max_size,
        offset=offset,
        search=search,
        order_by="name",
        order="asc"
    )


# ============================================================
# ADVANCED COLLECTION HELPERS
# ============================================================

def get_collection_advanced(
    entity,
    offset=0,
    max_size=50,
    search=None,
    select=None,
    order_by=None,
    order="asc",
    where=None,
    primary_filter=None,
    bool_filter_list=None,
    no_total=False
):
    """
    Versi collection yang mendukung filter server-side.

    Tidak mengubah get_collection() yang sudah digunakan
    oleh sistem lama.
    """
    params = {
        "offset": int(offset),
        "maxSize": int(max_size),
    }

    if search:
        params["textFilter"] = _clean_string(
            search
        )

    if select:
        if isinstance(
            select,
            (list, tuple)
        ):
            params["select"] = ",".join(
                str(item)
                for item in select
            )
        else:
            params["select"] = str(
                select
            )

    if order_by:
        params["orderBy"] = str(
            order_by
        )
        params["order"] = (
            "desc"
            if str(order).lower() == "desc"
            else "asc"
        )

    search_params = {}

    if where:
        search_params["where"] = where

    if primary_filter:
        search_params["primaryFilter"] = (
            primary_filter
        )

    if bool_filter_list:
        search_params["boolFilterList"] = (
            bool_filter_list
        )

    if search_params:
        search_params["offset"] = int(offset)
        search_params["maxSize"] = int(max_size)

        if select:
            search_params["select"] = (
                list(select)
                if isinstance(select, (list, tuple))
                else [
                    field.strip()
                    for field in str(select).split(",")
                    if field.strip()
                ]
            )

        if order_by:
            search_params["orderBy"] = str(
                order_by
            )
            search_params["order"] = (
                "desc"
                if str(order).lower() == "desc"
                else "asc"
            )

        if search:
            search_params["textFilter"] = (
                _clean_string(search)
            )

        params = {
            "searchParams": json.dumps(
                search_params,
                separators=(",", ":")
            )
        }

    headers = None

    if no_total:
        headers = {
            **HEADERS,
            "X-No-Total": "true"
        }

    if headers is None:
        return request(
            "GET",
            entity,
            params=params
        )

    try:
        response = requests.request(
            method="GET",
            url=build_url(entity),
            headers={
                **headers
            },
            auth=AUTH,
            params=params,
            timeout=TIMEOUT
        )

    except requests.exceptions.ConnectionError as exc:
        raise EspoCRMError(
            "Tidak dapat terhubung ke EspoCRM.\n\n"
            "Pastikan Docker/EspoCRM sedang berjalan.\n\n"
            f"Server:\n{BASE_URL}\n\n"
            f"Detail:\n{exc}"
        )

    except requests.exceptions.Timeout as exc:
        raise EspoCRMError(
            "Request ke EspoCRM mengalami timeout.\n\n"
            f"Detail:\n{exc}"
        )

    except requests.exceptions.RequestException as exc:
        raise EspoCRMError(
            "Terjadi error ketika menghubungi EspoCRM.\n\n"
            f"Detail:\n{exc}"
        )

    return _handle_response(
        response
    )


def get_opportunities_advanced(
    offset=0,
    max_size=50,
    search=None,
    stage=None,
    assigned_user_id=None,
    priority=None,
    account_id=None,
    contact_id=None,
    order_by="createdAt",
    order="desc",
    no_total=False
):
    """
    Opportunity Explorer dengan filter server-side.
    """
    where = []

    if stage:
        where.append({
            "type": "equals",
            "attribute": "stage",
            "value": str(stage)
        })

    if assigned_user_id:
        where.append({
            "type": "equals",
            "attribute": "assignedUserId",
            "value": str(assigned_user_id)
        })

    if priority:
        where.append({
            "type": "equals",
            "attribute": "priority",
            "value": str(priority)
        })

    if account_id:
        where.append({
            "type": "equals",
            "attribute": "accountId",
            "value": str(account_id)
        })

    if contact_id:
        where.append({
            "type": "equals",
            "attribute": "contactId",
            "value": str(contact_id)
        })

    return get_collection_advanced(
        "Opportunity",
        offset=offset,
        max_size=max_size,
        search=search,
        select=[
            "id",
            "name",
            "stage",
            "amount",
            "amountCurrency",
            "closeDate",
            "assignedUserId",
            "assignedUserName",
            "accountId",
            "accountName",
            "contactId",
            "contactName",
            "createdAt",
            "modifiedAt",
        ],
        order_by=order_by,
        order=order,
        where=where or None,
        no_total=no_total
    )


def get_tasks_advanced(
    offset=0,
    max_size=50,
    search=None,
    status=None,
    priority=None,
    assigned_user_id=None,
    parent_id=None,
    overdue_only=False,
    order_by="dateEnd",
    order="asc",
    no_total=False
):
    """
    Task Explorer dengan filter server-side.
    """
    where = []

    if status:
        where.append({
            "type": "equals",
            "attribute": "status",
            "value": str(status)
        })

    if priority:
        where.append({
            "type": "equals",
            "attribute": "priority",
            "value": str(priority)
        })

    if assigned_user_id:
        where.append({
            "type": "equals",
            "attribute": "assignedUserId",
            "value": str(assigned_user_id)
        })

    if parent_id:
        where.append({
            "type": "equals",
            "attribute": "parentId",
            "value": str(parent_id)
        })

    if overdue_only:
        now_text = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        where.append({
            "type": "lessThan",
            "attribute": "dateEnd",
            "value": now_text
        })

        where.append({
            "type": "notEquals",
            "attribute": "status",
            "value": "Completed"
        })

        where.append({
            "type": "notEquals",
            "attribute": "status",
            "value": "Canceled"
        })

    return get_collection_advanced(
        "Task",
        offset=offset,
        max_size=max_size,
        search=search,
        select=[
            "id",
            "name",
            "status",
            "priority",
            "dateStart",
            "dateEnd",
            "assignedUserId",
            "assignedUserName",
            "parentType",
            "parentId",
            "parentName",
            "createdAt",
            "modifiedAt",
        ],
        order_by=order_by,
        order=order,
        where=where or None,
        no_total=no_total
    )


# ============================================================
# LARGE DATASET GENERATOR
# ============================================================

_LARGE_FIRST_NAMES = (
    "Dimas", "Arya", "Rizky", "Fajar", "Andi",
    "Budi", "Bagas", "Raka", "Rian", "Ilham",
    "Adit", "Arif", "Bayu", "Deni", "Eko",
    "Farhan", "Galih", "Hendra", "Iqbal", "Joko",
    "Kevin", "Luthfi", "Maulana", "Naufal", "Putra",
    "Reza", "Satria", "Tegar", "Wahyu", "Yoga",
    "Ayu", "Citra", "Dewi", "Fitri", "Indah",
    "Kartika", "Laras", "Maya", "Nadia", "Putri",
    "Rani", "Salsa", "Tiara", "Vina", "Wulan",
)

_LARGE_LAST_NAMES = (
    "Pratama", "Saputra", "Wijaya", "Setiawan", "Nugraha",
    "Permana", "Kurniawan", "Hidayat", "Ramadhan", "Santoso",
    "Maulana", "Firmansyah", "Gunawan", "Wibowo", "Siregar",
    "Putra", "Lestari", "Utami", "Anggraini", "Rahmawati",
    "Maharani", "Puspitasari", "Amalia", "Kusuma", "Sari",
)

_LARGE_INDUSTRIES = (
    "Technology",
    "Retail",
    "Manufacturing",
    "Finance",
    "Healthcare",
    "Logistics",
    "Education",
    "Construction",
    "Telecommunications",
    "Hospitality",
)

_LARGE_STAGES = (
    "Prospecting",
    "Qualification",
    "Proposal",
    "Negotiation",
    "Closed Won",
    "Closed Lost",
)

_LARGE_PRIORITIES = (
    "Low",
    "Normal",
    "High",
    "Urgent",
)

_LARGE_TASK_STATUSES = (
    "Not Started",
    "In Progress",
    "Completed",
    "Canceled",
    "Deferred",
)

_LARGE_TASK_NAMES = (
    "Follow up client",
    "Prepare proposal",
    "Schedule meeting",
    "Send quotation",
    "Review contract",
    "Client presentation",
    "Collect requirements",
    "Internal coordination",
    "Technical validation",
    "Commercial negotiation",
    "Final approval",
    "Post-sale follow up",
)

_LARGE_CITIES = (
    "Jakarta",
    "Bandung",
    "Surabaya",
    "Semarang",
    "Yogyakarta",
    "Medan",
    "Bekasi",
    "Depok",
    "Tangerang",
    "Malang",
    "Makassar",
    "Denpasar",
)


def _large_slug(
    value
):
    return re.sub(
        r"[^a-z0-9]+",
        "",
        str(value).lower()
    )


_LARGE_RUN_TOKEN = str(random.SystemRandom().randint(10_000_000, 99_999_999))


def _large_unique_email(
    first_name,
    last_name,
    sequence
):
    first = _large_slug(first_name)
    last = _large_slug(last_name)

    domains = (
        "gmail.com",
        "gmail.co.id"
    )

    base = f"{first}.{last}"

    return (
        f"{base}.{_LARGE_RUN_TOKEN}.{sequence:06d}"
        f"@{domains[sequence % len(domains)]}"
    )


def _large_phone(
    sequence
):
    return f"+62812{_LARGE_RUN_TOKEN}{sequence:05d}"


def _large_quality(
    sequence,
    total
):
    position = sequence % max(
        1,
        total
    )

    ratio = position / max(
        1,
        total
    )

    if ratio < 0.70:
        return "complete"

    if ratio < 0.90:
        return "partial"

    return "poor"


def _large_should_include(
    quality,
    probability
):
    return random.random() < probability


def _build_large_account_data(
    sequence
):
    name = (
        f"PT "
        f"{random.choice(_TEST_ACCOUNT_NAMES)} "
        f"{_LARGE_RUN_TOKEN}-{sequence:05d}"
    )

    return {
        "name": name,
        "description": (
            "Data dummy untuk pengujian dataset besar "
            f"Account #{sequence:05d}."
        ),
        "industry": random.choice(
            _LARGE_INDUSTRIES
        ),
    }


def _build_large_contact_data(
    sequence,
    account_id=None,
    total=10000
):
    first_name = random.choice(
        _LARGE_FIRST_NAMES
    )
    last_name = random.choice(
        _LARGE_LAST_NAMES
    )

    quality = _large_quality(
        sequence,
        total
    )

    unique_last_name = (
        f"{last_name} "
        f"{_LARGE_RUN_TOKEN}-{sequence:05d}"
    )

    data = {
        "firstName": first_name,
        "lastName": unique_last_name,
        "emailAddress": _large_unique_email(
            first_name,
            last_name,
            sequence
        ),
        "phoneNumber": _large_phone(
            sequence
        ),
    }

    city = random.choice(
        _LARGE_CITIES
    )

    if quality in (
        "complete",
        "partial"
    ):
        data.update({
            "title": random.choice(
                _TEST_JOB_TITLES
            ),
            "description": (
                "Synthetic CRM Contact "
                f"#{sequence:05d} untuk benchmark."
            ),
            "addressStreet": random.choice(
                _TEST_STREETS
            ),
            "addressCity": city,
            "addressState": city,
            "addressCountry": "Indonesia",
            "addressPostalCode": str(
                random.randint(10000, 99999)
            ),
        })

    if quality == "complete":
        data["middleName"] = random.choice(
            _LARGE_FIRST_NAMES
        )

    if account_id and quality == "complete":
        data["accountId"] = account_id

    elif account_id and quality == "partial":
        if _large_should_include(
            quality,
            0.55
        ):
            data["accountId"] = account_id

    return data


def _build_large_opportunity_data(
    sequence,
    account_id=None,
    contact_id=None,
    user_id=None,
    total=10000
):
    quality = _large_quality(
        sequence,
        total
    )

    stage = random.choice(
        _LARGE_STAGES
    )

    now = datetime.now()

    close_days = random.randint(
        -240,
        240
    )

    close_date = (
        now + timedelta(
            days=close_days
        )
    ).strftime(
        "%Y-%m-%d"
    )

    data = {
        "name": (
            f"Opportunity "
            f"{sequence:06d} - "
            f"{random.choice(_TEST_ACCOUNT_NAMES)}"
        ),
        "stage": stage,
        "amount": round(
            random.uniform(
                5_000_000,
                1_500_000_000
            ),
            2
        ),
        "amountCurrency": "USD",
        "closeDate": close_date,
    }

    if quality == "complete":
        if account_id:
            data["accountId"] = account_id

        if contact_id:
            data["contactId"] = contact_id

        if user_id:
            data["assignedUserId"] = user_id

        data["description"] = (
            "Synthetic Opportunity lengkap "
            f"#{sequence:06d}."
        )

    elif quality == "partial":
        if account_id and random.random() < 0.75:
            data["accountId"] = account_id

        if contact_id and random.random() < 0.65:
            data["contactId"] = contact_id

        if user_id and random.random() < 0.70:
            data["assignedUserId"] = user_id

        data["description"] = (
            "Synthetic Opportunity partial "
            f"#{sequence:06d}."
        )

    else:
        if account_id and random.random() < 0.25:
            data["accountId"] = account_id

        if contact_id and random.random() < 0.15:
            data["contactId"] = contact_id

        if user_id and random.random() < 0.20:
            data["assignedUserId"] = user_id

        data["description"] = (
            "Synthetic Opportunity poor "
            f"#{sequence:06d}."
        )

    return data


def _build_large_task_data(
    sequence,
    opportunity_id=None,
    user_id=None,
    total=10000
):
    quality = _large_quality(
        sequence,
        total
    )

    now = datetime.now()

    offset_days = random.randint(
        -180,
        120
    )

    start = (
        now + timedelta(
            days=offset_days,
            hours=random.randint(
                0,
                8
            )
        )
    )

    duration_hours = random.randint(
        1,
        72
    )

    end = start + timedelta(
        hours=duration_hours
    )

    status = random.choice(
        _LARGE_TASK_STATUSES
    )

    if offset_days < 0 and random.random() < 0.60:
        status = random.choice(
            (
                "Not Started",
                "In Progress"
            )
        )

    data = {
        "name": (
            f"{random.choice(_LARGE_TASK_NAMES)} "
            f"#{sequence:06d}"
        ),
        "status": status,
        "priority": random.choice(
            _LARGE_PRIORITIES
        ),
        "dateStart": start.strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "dateEnd": end.strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
    }

    if user_id:
        data["assignedUserId"] = user_id

    if quality == "complete":
        if opportunity_id:
            data["parentType"] = "Opportunity"
            data["parentId"] = opportunity_id

        data["description"] = (
            "Synthetic Task lengkap "
            f"#{sequence:06d}."
        )

    elif quality == "partial":
        if opportunity_id and random.random() < 0.75:
            data["parentType"] = "Opportunity"
            data["parentId"] = opportunity_id

        data["description"] = (
            "Synthetic Task partial "
            f"#{sequence:06d}."
        )

    else:
        if opportunity_id and random.random() < 0.25:
            data["parentType"] = "Opportunity"
            data["parentId"] = opportunity_id

        data["description"] = (
            "Synthetic Task poor "
            f"#{sequence:06d}."
        )

    return data


def _large_retryable_error(
    exc
):
    return _is_retryable_test_data_error(
        exc
    )


def _create_large_record(
    entity,
    data,
    sequence,
    minimal_data=None,
    retry_count=LARGE_DATASET_RETRY_COUNT,
    retry_delay=LARGE_DATASET_RETRY_DELAY
):
    last_error = None

    attempts = max(
        1,
        int(retry_count)
    )

    for attempt in range(
        1,
        attempts + 1
    ):
        try:
            created = create_record(
                entity,
                data
            )

            if not isinstance(
                created,
                dict
            ):
                raise EspoCRMError(
                    f"EspoCRM tidak mengembalikan data {entity}."
                )

            return created

        except Exception as exc:
            last_error = exc

            if not _large_retryable_error(
                exc
            ):
                break

            if attempt < attempts:
                time.sleep(
                    retry_delay * attempt
                )

    if minimal_data is not None:
        try:
            created = create_record(
                entity,
                minimal_data
            )

            if not isinstance(
                created,
                dict
            ):
                raise EspoCRMError(
                    f"Fallback {entity} tidak mengembalikan data."
                )

            return created

        except Exception as fallback_exc:
            last_error = fallback_exc

    raise last_error


def create_records_bulk(
    entity,
    data_list,
    workers=LARGE_DATASET_DEFAULT_WORKERS,
    retry_count=LARGE_DATASET_RETRY_COUNT,
    retry_delay=LARGE_DATASET_RETRY_DELAY,
    batch_size=LARGE_DATASET_DEFAULT_BATCH_SIZE
):
    """
    Bulk create synthetic data dengan worker paralel terbatas.

    Data diproses per batch supaya 10.000+ record tidak sekaligus
    menumpuk sebagai Future aktif di memory dan supaya beban
    EspoCRM lebih stabil.
    """
    if not isinstance(
        data_list,
        (list, tuple)
    ):
        raise EspoCRMError(
            "data_list harus berupa list atau tuple."
        )

    records = list(
        data_list
    )

    if not records:
        return {
            "success": True,
            "entity": entity,
            "requested": 0,
            "created_count": 0,
            "failed_count": 0,
            "created": [],
            "failed": [],
        }

    try:
        worker_count = int(
            workers
        )
    except (
        TypeError,
        ValueError
    ):
        worker_count = (
            LARGE_DATASET_DEFAULT_WORKERS
        )

    worker_count = max(
        1,
        min(
            worker_count,
            LARGE_DATASET_MAX_WORKERS
        )
    )

    try:
        safe_batch_size = int(
            batch_size
        )
    except (
        TypeError,
        ValueError
    ):
        safe_batch_size = (
            LARGE_DATASET_DEFAULT_BATCH_SIZE
        )

    safe_batch_size = max(
        1,
        min(
            safe_batch_size,
            1000
        )
    )

    created_records = []
    failed_records = []

    def minimum_payload(
        payload
    ):
        if not isinstance(
            payload,
            dict
        ):
            return None

        if entity == "Account":
            if payload.get("name"):
                return {
                    "name": payload["name"]
                }

        elif entity == "Contact":
            return {
                key: payload[key]
                for key in (
                    "firstName",
                    "lastName",
                    "emailAddress",
                    "phoneNumber"
                )
                if payload.get(key)
            }

        elif entity == "Opportunity":
            minimum = {}

            for key in (
                "name",
                "stage",
                "amount",
                "amountCurrency",
                "closeDate"
            ):
                if payload.get(key) is not None:
                    minimum[key] = payload[key]

            return minimum or None

        elif entity == "Task":
            minimum = {}

            if payload.get("name"):
                minimum["name"] = payload["name"]

            if payload.get("assignedUserId"):
                minimum["assignedUserId"] = (
                    payload["assignedUserId"]
                )

            return minimum or None

        return None

    def worker(
        sequence,
        payload
    ):
        return (
            sequence,
            _create_large_record(
                entity,
                payload,
                sequence=sequence,
                minimal_data=minimum_payload(payload),
                retry_count=retry_count,
                retry_delay=retry_delay
            )
        )

    for batch_start in range(
        0,
        len(records),
        safe_batch_size
    ):
        batch = records[
            batch_start:
            batch_start + safe_batch_size
        ]

        with ThreadPoolExecutor(
            max_workers=worker_count
        ) as executor:

            futures = {
                executor.submit(
                    worker,
                    batch_start + local_index + 1,
                    payload
                ): batch_start + local_index + 1
                for local_index, payload in enumerate(
                    batch
                )
            }

            for future in as_completed(
                futures
            ):
                sequence = futures[
                    future
                ]

                try:
                    sequence, created = future.result()

                    created_records.append({
                        "sequence": sequence,
                        "record": created
                    })

                except Exception as exc:
                    payload = records[
                        sequence - 1
                    ]

                    failed_records.append({
                        "sequence": sequence,
                        "data": (
                            dict(payload)
                            if isinstance(
                                payload,
                                dict
                            )
                            else payload
                        ),
                        "error": str(exc)
                    })

    # Retry final failures once more as a serial pass.
    if failed_records:
        retry_items = list(
            failed_records
        )
        failed_records = []

        for item in retry_items:
            sequence = item["sequence"]
            payload = item["data"]

            try:
                created = _create_large_record(
                    entity,
                    payload,
                    sequence=sequence,
                    minimal_data=minimum_payload(payload),
                    retry_count=max(
                        1,
                        int(retry_count)
                    ),
                    retry_delay=max(
                        0.5,
                        float(retry_delay)
                    )
                )

                created_records.append({
                    "sequence": sequence,
                    "record": created
                })

            except Exception as exc:
                failed_records.append({
                    "sequence": sequence,
                    "data": (
                        dict(payload)
                        if isinstance(
                            payload,
                            dict
                        )
                        else payload
                    ),
                    "error": str(exc)
                })

    created_records.sort(
        key=lambda item: item[
            "sequence"
        ]
    )

    failed_records.sort(
        key=lambda item: item[
            "sequence"
        ]
    )

    clean_created = [
        item["record"]
        for item in created_records
    ]

    return {
        "success": len(
            failed_records
        ) == 0,
        "entity": entity,
        "requested": len(records),
        "created_count": len(
            clean_created
        ),
        "failed_count": len(
            failed_records
        ),
        "created": clean_created,
        "failed": failed_records,
    }


def generate_large_accounts(
    count=10000,
    workers=LARGE_DATASET_DEFAULT_WORKERS,
    random_seed=None
):
    """
    Generate Account besar.
    """
    try:
        count = int(
            count
        )
    except (
        TypeError,
        ValueError
    ):
        raise EspoCRMError(
            "Jumlah Account harus berupa angka."
        )

    if count < 1:
        raise EspoCRMError(
            "Jumlah Account minimal 1."
        )

    if random_seed is not None:
        random.seed(
            random_seed
        )

    payloads = [
        _build_large_account_data(
            sequence
        )
        for sequence in range(
            1,
            count + 1
        )
    ]

    result = create_records_bulk(
        "Account",
        payloads,
        workers=workers
    )

    result["generated_count"] = count

    return result


def _get_pool_ids(
    records
):
    ids = []

    for record in records:
        if not isinstance(
            record,
            dict
        ):
            continue

        record_id = record.get(
            "id"
        )

        if record_id:
            ids.append(
                str(record_id)
            )

    return ids


def _fetch_pool(
    loader,
    max_size=1000
):
    try:
        result = loader(
            offset=0,
            max_size=max_size
        )

        return _extract_records(
            result
        )

    except Exception:
        return []


def generate_large_contacts(
    count=10000,
    workers=LARGE_DATASET_DEFAULT_WORKERS,
    account_ids=None,
    random_seed=None
):
    """
    Generate Contact besar.

    Relationship ke Account dimasukkan langsung
    melalui accountId jika pool tersedia.
    """
    try:
        count = int(
            count
        )
    except (
        TypeError,
        ValueError
    ):
        raise EspoCRMError(
            "Jumlah Contact harus berupa angka."
        )

    if count < 1:
        raise EspoCRMError(
            "Jumlah Contact minimal 1."
        )

    if random_seed is not None:
        random.seed(
            random_seed
        )

    if account_ids is None:
        account_records = _fetch_pool(
            get_accounts,
            max_size=1000
        )

        account_ids = _get_pool_ids(
            account_records
        )

    payloads = []

    for sequence in range(
        1,
        count + 1
    ):
        account_id = (
            random.choice(account_ids)
            if account_ids
            else None
        )

        payloads.append(
            _build_large_contact_data(
                sequence,
                account_id=account_id,
                total=count
            )
        )

    return create_records_bulk(
        "Contact",
        payloads,
        workers=workers
    )


def generate_large_opportunities(
    count=10000,
    workers=LARGE_DATASET_DEFAULT_WORKERS,
    account_ids=None,
    contact_ids=None,
    user_ids=None,
    random_seed=None
):
    """
    Generate Opportunity besar dengan foreign key
    Account, Contact, dan PIC jika tersedia.
    """
    try:
        count = int(
            count
        )
    except (
        TypeError,
        ValueError
    ):
        raise EspoCRMError(
            "Jumlah Opportunity harus berupa angka."
        )

    if count < 1:
        raise EspoCRMError(
            "Jumlah Opportunity minimal 1."
        )

    if random_seed is not None:
        random.seed(
            random_seed
        )

    if account_ids is None:
        account_ids = _get_pool_ids(
            _fetch_pool(
                get_accounts,
                max_size=1000
            )
        )

    if contact_ids is None:
        contact_ids = _get_pool_ids(
            _fetch_pool(
                get_contacts,
                max_size=1000
            )
        )

    if user_ids is None:
        user_ids = _get_pool_ids(
            _fetch_pool(
                get_active_users,
                max_size=100
            )
        )

    payloads = []

    for sequence in range(
        1,
        count + 1
    ):
        account_id = (
            random.choice(account_ids)
            if account_ids
            else None
        )

        contact_id = (
            random.choice(contact_ids)
            if contact_ids
            else None
        )

        user_id = (
            random.choice(user_ids)
            if user_ids
            else None
        )

        payloads.append(
            _build_large_opportunity_data(
                sequence,
                account_id=account_id,
                contact_id=contact_id,
                user_id=user_id,
                total=count
            )
        )

    return create_records_bulk(
        "Opportunity",
        payloads,
        workers=workers
    )


def generate_large_tasks(
    count=10000,
    workers=LARGE_DATASET_DEFAULT_WORKERS,
    opportunity_ids=None,
    user_ids=None,
    random_seed=None
):
    """
    Generate Task besar.

    Task diarahkan ke Opportunity melalui
    parentType=Opportunity dan parentId jika tersedia.
    """
    try:
        count = int(
            count
        )
    except (
        TypeError,
        ValueError
    ):
        raise EspoCRMError(
            "Jumlah Task harus berupa angka."
        )

    if count < 1:
        raise EspoCRMError(
            "Jumlah Task minimal 1."
        )

    if random_seed is not None:
        random.seed(
            random_seed
        )

    if opportunity_ids is None:
        opportunity_ids = _get_pool_ids(
            _fetch_pool(
                get_opportunities,
                max_size=1000
            )
        )

    if user_ids is None:
        user_ids = _get_pool_ids(
            _fetch_pool(
                get_active_users,
                max_size=100
            )
        )

    if not user_ids:
        raise EspoCRMError(
            "Tidak ada User/PIC aktif di EspoCRM. "
            "Task membutuhkan assignedUser."
        )

    payloads = []

    for sequence in range(
        1,
        count + 1
    ):
        opportunity_id = (
            random.choice(
                opportunity_ids
            )
            if opportunity_ids
            else None
        )

        user_id = (
            random.choice(
                user_ids
            )
            if user_ids
            else None
        )

        payloads.append(
            _build_large_task_data(
                sequence,
                opportunity_id=opportunity_id,
                user_id=user_id,
                total=count
            )
        )

    return create_records_bulk(
        "Task",
        payloads,
        workers=workers
    )


def validate_large_dataset_prerequisites():
    """
    Memastikan entity dan PIC dasar bisa dibaca sebelum generator
    mulai membuat puluhan ribu record.
    """
    checks = {}

    try:
        checks["accounts"] = isinstance(
            get_accounts(
                offset=0,
                max_size=1
            ),
            dict
        )
    except Exception as exc:
        checks["accounts"] = False
        checks["accounts_error"] = str(exc)

    try:
        checks["contacts"] = isinstance(
            get_contacts(
                offset=0,
                max_size=1
            ),
            dict
        )
    except Exception as exc:
        checks["contacts"] = False
        checks["contacts_error"] = str(exc)

    try:
        checks["opportunities"] = isinstance(
            get_opportunities(
                offset=0,
                max_size=1
            ),
            dict
        )
    except Exception as exc:
        checks["opportunities"] = False
        checks["opportunities_error"] = str(exc)

    try:
        checks["tasks"] = isinstance(
            get_collection(
                "Task",
                offset=0,
                max_size=1
            ),
            dict
        )
    except Exception as exc:
        checks["tasks"] = False
        checks["tasks_error"] = str(exc)

    try:
        pic_records = get_active_users(
            max_size=100
        )
        checks["pic_count"] = len(
            pic_records
        )
    except Exception as exc:
        checks["pic_count"] = 0
        checks["pic_error"] = str(exc)

    checks["success"] = all(
        checks.get(key, False)
        for key in (
            "accounts",
            "contacts",
            "opportunities",
            "tasks"
        )
    ) and checks.get(
        "pic_count",
        0
    ) > 0

    return checks


def generate_large_crm_dataset(
    account_count=10000,
    contact_count=10000,
    opportunity_count=10000,
    task_count=10000,
    workers=LARGE_DATASET_DEFAULT_WORKERS,
    random_seed=None
):
    """
    Generator orchestrator untuk dataset besar.

    Urutan:
        Account
        Contact
        Opportunity
        Task

    Foreign key diarahkan dari entity sebelumnya.
    User/PIC memakai User yang sudah ada di EspoCRM.
    """
    if random_seed is not None:
        random.seed(
            random_seed
        )

    started_at = datetime.now()

    result = {
        "success": False,
        "started_at": started_at.isoformat(
            timespec="seconds"
        ),
        "finished_at": None,
        "accounts": None,
        "contacts": None,
        "opportunities": None,
        "tasks": None,
        "pic_count": 0,
    }

    user_records = get_active_users(
        max_size=100
    )

    user_ids = _get_pool_ids(
        user_records
    )

    result["pic_count"] = len(
        user_ids
    )

    if not user_ids and int(task_count) > 0:
        raise EspoCRMError(
            "Tidak ada User/PIC aktif yang dapat dipakai Task. "
            "Pastikan minimal satu User aktif dapat dibaca melalui API."
        )

    accounts = generate_large_accounts(
        count=account_count,
        workers=workers,
        random_seed=random_seed
    )

    result["accounts"] = accounts

    account_ids = _get_pool_ids(
        accounts.get(
            "created",
            []
        )
    )

    if not account_ids:
        account_ids = _get_pool_ids(
            _fetch_pool(
                get_accounts,
                max_size=1000
            )
        )

    contacts = generate_large_contacts(
        count=contact_count,
        workers=workers,
        account_ids=account_ids,
        random_seed=random_seed
    )

    result["contacts"] = contacts

    contact_ids = _get_pool_ids(
        contacts.get(
            "created",
            []
        )
    )

    if not contact_ids:
        contact_ids = _get_pool_ids(
            _fetch_pool(
                get_contacts,
                max_size=1000
            )
        )

    opportunities = generate_large_opportunities(
        count=opportunity_count,
        workers=workers,
        account_ids=account_ids,
        contact_ids=contact_ids,
        user_ids=user_ids,
        random_seed=random_seed
    )

    result["opportunities"] = opportunities

    opportunity_ids = _get_pool_ids(
        opportunities.get(
            "created",
            []
        )
    )

    if not opportunity_ids:
        opportunity_ids = _get_pool_ids(
            _fetch_pool(
                get_opportunities,
                max_size=1000
            )
        )

    tasks = generate_large_tasks(
        count=task_count,
        workers=workers,
        opportunity_ids=opportunity_ids,
        user_ids=user_ids,
        random_seed=random_seed
    )

    result["tasks"] = tasks

    finished_at = datetime.now()

    result["finished_at"] = (
        finished_at.isoformat(
            timespec="seconds"
        )
    )

    result["duration_seconds"] = round(
        (
            finished_at - started_at
        ).total_seconds(),
        2
    )

    result["success"] = all(
        section is not None
        and section.get(
            "failed_count",
            0
        ) == 0
        for section in (
            accounts,
            contacts,
            opportunities,
            tasks,
        )
    )

    result["summary"] = {
        "requested": (
            int(account_count)
            + int(contact_count)
            + int(opportunity_count)
            + int(task_count)
        ),
        "created": (
            accounts.get("created_count", 0)
            + contacts.get("created_count", 0)
            + opportunities.get("created_count", 0)
            + tasks.get("created_count", 0)
        ),
        "failed": (
            accounts.get("failed_count", 0)
            + contacts.get("failed_count", 0)
            + opportunities.get("failed_count", 0)
            + tasks.get("failed_count", 0)
        ),
    }

    return result


# ============================================================
# SEARCH ACCOUNT
# ============================================================

def search_accounts(
    keyword,
    max_size=20
):
    """
    Search Account berdasarkan keyword.
    """

    keyword = _clean_string(
        keyword
    )

    if not keyword:

        return get_accounts(
            offset=0,
            max_size=max_size
        )

    return get_accounts(
        offset=0,
        max_size=max_size,
        search=keyword
    )


# ============================================================
# SEARCH OPPORTUNITY
# ============================================================

def search_opportunities(
    keyword,
    max_size=20
):
    """
    Search Opportunity.
    """

    keyword = _clean_string(
        keyword
    )

    if not keyword:

        return get_opportunities(
            offset=0,
            max_size=max_size
        )

    return get_opportunities(
        offset=0,
        max_size=max_size,
        search=keyword
    )


# ============================================================
# SEARCH CASE
# ============================================================

def search_cases(
    keyword,
    max_size=20
):
    """
    Search Case.
    """

    keyword = _clean_string(
        keyword
    )

    if not keyword:

        return get_cases(
            offset=0,
            max_size=max_size
        )

    return get_cases(
        offset=0,
        max_size=max_size,
        search=keyword
    )


# ============================================================
# CHECK CONNECTION
# ============================================================

def check_connection():
    """
    Mengecek koneksi EspoCRM.

    Return:
        True / False
    """

    try:

        request(
            "GET",
            "Contact",
            params={
                "maxSize": 1
            }
        )

        return True

    except Exception:

        return False


# ============================================================
# TEST CONNECTION
# ============================================================

def test_connection():
    """
    Test koneksi dan return informasi.
    """

    try:

        result = request(
            "GET",
            "Contact",
            params={
                "maxSize": 1
            }
        )

        return {
            "success": True,
            "data": result
        }

    except EspoCRMError as exc:

        return {
            "success": False,
            "error": str(exc)
        }


# ============================================================
# TEST RELATIONSHIP
# ============================================================

def test_contact_relationship(
    contact_id
):
    """
    Test seluruh relationship Contact.
    """

    try:

        contact = get_contact(
            contact_id
        )

        relationships = (
            get_contact_relationships(
                contact_id
            )
        )

        return {
            "success": True,

            "contact": contact,

            "relationships": relationships
        }

    except Exception as exc:

        return {
            "success": False,

            "error": str(exc)
        }


# ============================================================
# MAIN TEST
# ============================================================

if __name__ == "__main__":

    print()
    print("=" * 60)
    print("              EspoCRM API TEST")
    print("=" * 60)
    print()

    print(
        f"BASE URL : {BASE_URL}"
    )

    print()

    try:

        # ====================================================
        # CONNECTION
        # ====================================================

        result = get_contacts(
            offset=0,
            max_size=5
        )

        print(
            "Connection : SUCCESS"
        )

        print()

        # ====================================================
        # CONTACT
        # ====================================================

        if isinstance(
            result,
            dict
        ):

            total = result.get(
                "total",
                0
            )

            contacts = result.get(
                "list",
                []
            )

            print(
                f"Total Contact : {total}"
            )

            print()

            if contacts:

                print(
                    "Daftar Contact:"
                )

                print(
                    "-" * 60
                )

                for contact in contacts:

                    print(
                        contact.get(
                            "id",
                            "-"
                        ),
                        "|",
                        contact.get(
                            "name",
                            "-"
                        ),
                        "|",
                        contact.get(
                            "emailAddress",
                            "-"
                        ),
                        "|",
                        contact.get(
                            "phoneNumber",
                            "-"
                        )
                    )

            else:

                print(
                    "Belum ada Contact."
                )

        else:

            print(
                result
            )

    except Exception as exc:

        print(
            "Connection : FAILED"
        )

        print()

        print(
            str(exc)
        )

    print()
    print("=" * 60)
    print()
