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
"""

import re

import requests
from requests.auth import HTTPBasicAuth

from config import BASE_URL, USERNAME, PASSWORD


# ============================================================
# CONFIGURATION
# ============================================================

TIMEOUT = 15


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