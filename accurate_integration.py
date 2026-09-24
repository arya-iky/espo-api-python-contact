"""
Accurate Online integration client for:
EspoCRM Opportunity -> Accurate Online Sales Invoice

Features:
- Exact database alias selection
- Explicit EspoCRM -> Accurate customer mapping
- Item/Jasa mapping
- Closed Won synchronization
- Create invoice on first sync
- Update the SAME Accurate invoice after source changes
- Existing invoice detail IDs are reused during UPDATE
- Safe handling when source/detail counts differ
- Idempotency using payload hash + source modifiedAt
- Ambiguous POST failures become UNKNOWN
- No automatic retry for ambiguous writes
- Manual forced retry support
- Persistent sync history
- EspoCRM closeDate normalization
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv


# ============================================================
# PATH / ENVIRONMENT
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

ENV_FILE = BASE_DIR / "testumbrella.env"
TOKEN_FILE = BASE_DIR / "accurate_token.json"
CONNECTION_FILE = BASE_DIR / "accurate_connection.json"
SYNC_FILE = BASE_DIR / "accurate_sync.json"

if ENV_FILE.exists():
    load_dotenv(
        ENV_FILE,
        override=True,
    )


# ============================================================
# EXCEPTIONS
# ============================================================


class AccurateConfigError(Exception):
    """Configuration/state error."""


class AccurateAPIError(Exception):
    """Accurate API error."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response: Any = None,
        ambiguous: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = response
        self.ambiguous = ambiguous


# ============================================================
# GENERIC HELPERS
# ============================================================


def _read_json(path: Path) -> dict[str, Any]:
    """Read JSON object safely."""
    if not path.exists():
        return {}

    try:
        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        return (
            data
            if isinstance(data, dict)
            else {}
        )

    except (
        OSError,
        json.JSONDecodeError,
    ):
        return {}


def _write_json(
    path: Path,
    data: dict[str, Any],
) -> None:
    """Write JSON atomically."""
    try:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temp_path = path.with_suffix(
            path.suffix + ".tmp"
        )

        temp_path.write_text(
            json.dumps(
                data,
                indent=4,
                ensure_ascii=False,
                default=str,
            ),
            encoding="utf-8",
        )

        temp_path.replace(path)

    except OSError as exc:
        raise AccurateConfigError(
            (
                "Gagal menyimpan file state Accurate: "
                f"{path.name}: {exc}"
            )
        ) from exc


def _env_text(
    name: str,
    default: str = "",
) -> str:
    """Read environment variable as trimmed string."""
    return str(
        os.getenv(
            name,
            default,
        )
        or ""
    ).strip()


def _env_bool(
    name: str,
    default: bool = False,
) -> bool:
    """Read environment variable as boolean."""
    value = _env_text(
        name,
        "true" if default else "false",
    ).casefold()

    return value in {
        "1",
        "true",
        "yes",
        "on",
    }


def _env_int(
    name: str,
    default: int,
    minimum: int | None = None,
) -> int:
    """Read integer environment variable safely."""
    raw = _env_text(
        name,
        str(default),
    )

    try:
        value = int(raw)
    except (
        TypeError,
        ValueError,
    ):
        value = default

    if minimum is not None:
        value = max(
            value,
            minimum,
        )

    return value


def _env_float(
    name: str,
    default: float,
    minimum: float | None = None,
) -> float:
    """Read float environment variable safely."""
    raw = _env_text(
        name,
        str(default),
    )

    try:
        value = float(raw)
    except (
        TypeError,
        ValueError,
    ):
        value = default

    if minimum is not None:
        value = max(
            value,
            minimum,
        )

    return value


def _decimal(
    value: Any,
    default: Decimal = Decimal("0"),
) -> Decimal:
    """Convert value to Decimal safely."""
    if value in (
        None,
        "",
    ):
        return default

    try:
        return Decimal(
            str(value)
            .strip()
            .replace(",", "")
        )

    except (
        InvalidOperation,
        ValueError,
        TypeError,
    ):
        return default


def _money(value: Any) -> str:
    """Format value as decimal string."""
    text = format(
        _decimal(value),
        "f",
    )

    if "." in text:
        text = (
            text
            .rstrip("0")
            .rstrip(".")
        )

    return text or "0"


def _stage(value: Any) -> str:
    """Normalize Opportunity stage."""
    return str(
        value or ""
    ).strip().casefold()


def _safe_json(value: Any) -> Any:
    """Make value safe for JSON response."""
    try:
        json.dumps(value)
        return value

    except (
        TypeError,
        ValueError,
    ):
        return str(value)


def _message(payload: Any) -> str:
    """Extract readable message from Accurate response."""
    if isinstance(
        payload,
        dict,
    ):
        messages = payload.get("d")

        if (
            isinstance(
                messages,
                list,
            )
            and messages
        ):
            return " | ".join(
                str(item)
                for item in messages
            )

        if isinstance(
            messages,
            str,
        ):
            return messages

        if payload.get("message"):
            return str(
                payload["message"]
            )

        if payload.get("error"):
            return str(
                payload["error"]
            )

    return str(payload)[:2000]


def _accurate_date(value: Any) -> str:
    """
    Convert EspoCRM date/datetime to:

        DD/MM/YYYY

    Supported:
        2026-09-23
        2026-09-23 15:30:00
        2026-09-23T15:30:00
        2026-09-23T15:30:00+07:00
        23/09/2026
        23-09-2026
        09/23/2026
        09-23-2026
    """

    if value in (
        None,
        "",
    ):
        return datetime.now().strftime(
            "%d/%m/%Y"
        )

    if isinstance(
        value,
        datetime,
    ):
        return value.strftime(
            "%d/%m/%Y"
        )

    if isinstance(
        value,
        date,
    ):
        return value.strftime(
            "%d/%m/%Y"
        )

    text = str(
        value
    ).strip()

    if not text:
        return datetime.now().strftime(
            "%d/%m/%Y"
        )

    # --------------------------------------------------------
    # ISO date/datetime
    # --------------------------------------------------------

    try:
        iso_text = text

        if iso_text.endswith("Z"):
            iso_text = (
                iso_text[:-1]
                + "+00:00"
            )

        parsed = datetime.fromisoformat(
            iso_text
        )

        return parsed.strftime(
            "%d/%m/%Y"
        )

    except ValueError:
        pass

    normalized = text.replace(
        "T",
        " ",
    )

    # --------------------------------------------------------
    # Datetime without timezone
    # --------------------------------------------------------

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ):
        try:
            parsed = datetime.strptime(
                normalized,
                fmt,
            )

            return parsed.strftime(
                "%d/%m/%Y"
            )

        except ValueError:
            pass

    # --------------------------------------------------------
    # Date formats
    # --------------------------------------------------------

    for fmt in (
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%m/%d/%Y",
        "%m-%d-%Y",
    ):
        try:
            parsed = datetime.strptime(
                text,
                fmt,
            )

            return parsed.strftime(
                "%d/%m/%Y"
            )

        except ValueError:
            pass

    # --------------------------------------------------------
    # Fallback for ISO strings with extra suffix
    # --------------------------------------------------------

    if len(text) >= 10:
        possible_date = text[:10]

        try:
            parsed = datetime.strptime(
                possible_date,
                "%Y-%m-%d",
            )

            return parsed.strftime(
                "%d/%m/%Y"
            )

        except ValueError:
            pass

    raise AccurateConfigError(
        (
            "Format closeDate tidak dikenali: "
            f'"{value}"'
        )
    )


# ============================================================
# ACCURATE CLIENT
# ============================================================


class AccurateClient:
    """Accurate Online client for the EspoCRM project."""

    # --------------------------------------------------------
    # OAuth endpoints
    # --------------------------------------------------------

    AUTH_BASE = (
        "https://account.accurate.id"
    )

    AUTHORIZE_URL = (
        AUTH_BASE
        + "/oauth/authorize"
    )

    TOKEN_URL = (
        AUTH_BASE
        + "/oauth/token"
    )

    DB_LIST_URL = (
        AUTH_BASE
        + "/api/db-list.do"
    )

    OPEN_DB_URL = (
        AUTH_BASE
        + "/api/open-db.do"
    )

    # --------------------------------------------------------
    # Accurate endpoints
    # --------------------------------------------------------

    INVOICE_ENDPOINT = (
        "/accurate/api/sales-invoice/save.do"
    )

    # Used when updating an existing invoice.
    # Can be overridden using environment variable.
    INVOICE_DETAIL_ENDPOINT = (
        "/accurate/api/sales-invoice/detail.do"
    )

    CUSTOMER_LIST_ENDPOINT = (
        "/accurate/api/customer/list.do"
    )

    CUSTOMER_SAVE_ENDPOINT = (
        "/accurate/api/customer/save.do"
    )

    ITEM_LIST_ENDPOINT = (
        "/accurate/api/item/list.do"
    )

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        store: Any,
    ) -> None:
        self.store = store

        if ENV_FILE.exists():
            load_dotenv(
                ENV_FILE,
                override=True,
            )

        # ----------------------------------------------------
        # OAuth
        # ----------------------------------------------------

        self.client_id = _env_text(
            "ACCURATE_CLIENT_ID"
        )

        self.client_secret = _env_text(
            "ACCURATE_CLIENT_SECRET"
        )

        self.redirect_uri = _env_text(
            "ACCURATE_REDIRECT_URI",
            "http://localhost:5000/callback",
        )

        self.scope = _env_text(
            "ACCURATE_SCOPE",
            (
                "sales_invoice_view "
                "sales_invoice_save "
                "customer_view "
                "customer_save "
                "item_view"
            ),
        )

        # ----------------------------------------------------
        # Database
        # ----------------------------------------------------

        self.database_alias = _env_text(
            "ACCURATE_DATABASE_ALIAS",
            "Umbrella",
        )

        self.database_id = _env_text(
            "ACCURATE_DATABASE_ID"
        )

        # ----------------------------------------------------
        # Endpoint overrides
        # ----------------------------------------------------

        self.invoice_endpoint = _env_text(
            "ACCURATE_SALES_INVOICE_ENDPOINT",
            self.INVOICE_ENDPOINT,
        )

        self.invoice_detail_endpoint = _env_text(
            "ACCURATE_SALES_INVOICE_DETAIL_ENDPOINT",
            self.INVOICE_DETAIL_ENDPOINT,
        )

        self.customer_list_endpoint = _env_text(
            "ACCURATE_CUSTOMER_LIST_ENDPOINT",
            self.CUSTOMER_LIST_ENDPOINT,
        )

        self.customer_save_endpoint = _env_text(
            "ACCURATE_CUSTOMER_SAVE_ENDPOINT",
            self.CUSTOMER_SAVE_ENDPOINT,
        )

        self.item_list_endpoint = _env_text(
            "ACCURATE_ITEM_LIST_ENDPOINT",
            self.ITEM_LIST_ENDPOINT,
        )

        # ----------------------------------------------------
        # Customer mapping
        # ----------------------------------------------------

        self.customer_field = _env_text(
            "ACCURATE_CUSTOMER_FIELD",
            "customerNo",
        )

        self.configured_customer_no = _env_text(
            "ACCURATE_CUSTOMER_NO"
        )

        # ----------------------------------------------------
        # Default item
        # ----------------------------------------------------

        self.default_item_no = _env_text(
            "ACCURATE_DEFAULT_ITEM_NO",
            "100001",
        )

        self.default_item_name = _env_text(
            "ACCURATE_DEFAULT_ITEM_NAME",
            "Laptop Test Umbrella",
        )

        self.default_quantity = _decimal(
            os.getenv(
                "ACCURATE_DEFAULT_ITEM_QUANTITY",
                "1",
            ),
            Decimal("1"),
        )

        if self.default_quantity <= 0:
            self.default_quantity = Decimal("1")

        # ----------------------------------------------------
        # Optional currency mapping
        #
        # Disabled by default because the exact field name
        # and currency setup belong to the user's Accurate
        # database configuration.
        # ----------------------------------------------------

        self.currency_field = _env_text(
            "ACCURATE_CURRENCY_FIELD"
        )

        self.configured_currency_value = _env_text(
            "ACCURATE_CURRENCY_VALUE"
        )

        # ----------------------------------------------------
        # Other settings
        # ----------------------------------------------------

        self.auto_create_customer = _env_bool(
            "ACCURATE_AUTO_CREATE_CUSTOMER",
            False,
        )

        self.page_size = min(
            _env_int(
                "ACCURATE_PAGE_SIZE",
                100,
                1,
            ),
            100,
        )

        self.max_pages = max(
            _env_int(
                "ACCURATE_MAX_LIST_PAGES",
                20,
                1,
            ),
            1,
        )

        self.timeout = _env_float(
            "ACCURATE_TIMEOUT_SECONDS",
            30.0,
            1.0,
        )

        self.get_retries = 3

    # ========================================================
    # TOKEN / SESSION STORAGE
    # ========================================================

    def _store_tokens(
        self,
    ) -> dict[str, Any]:
        try:
            result = self.store.tokens()

            return (
                dict(result)
                if isinstance(
                    result,
                    dict,
                )
                else {}
            )

        except (
            AttributeError,
            TypeError,
        ):
            return {}

    def _local_tokens(
        self,
    ) -> dict[str, Any]:
        token = _read_json(
            TOKEN_FILE
        )

        connection = _read_json(
            CONNECTION_FILE
        )

        merged = {
            **token,
            **connection,
        }

        if (
            not merged.get(
                "session_id"
            )
            and merged.get(
                "session"
            )
        ):
            merged["session_id"] = (
                merged["session"]
            )

        if (
            not merged.get(
                "session"
            )
            and merged.get(
                "session_id"
            )
        ):
            merged["session"] = (
                merged["session_id"]
            )

        return merged

    def _tokens(
        self,
    ) -> dict[str, Any]:
        merged = self._local_tokens()

        for key, value in (
            self._store_tokens().items()
        ):
            if value not in (
                None,
                "",
            ):
                merged[key] = value

        if (
            not merged.get(
                "session_id"
            )
            and merged.get(
                "session"
            )
        ):
            merged["session_id"] = (
                merged["session"]
            )

        if (
            not merged.get(
                "session"
            )
            and merged.get(
                "session_id"
            )
        ):
            merged["session"] = (
                merged["session_id"]
            )

        return merged

    def _save_tokens(
        self,
        **values: Any,
    ) -> None:
        values = {
            key: value
            for key, value in values.items()
            if value is not None
        }

        try:
            self.store.save_tokens(
                **values
            )

        except (
            AttributeError,
            TypeError,
        ):
            pass

        token_keys = {
            "access_token",
            "refresh_token",
            "expires_at",
            "scope",
        }

        connection_keys = {
            "database_id",
            "database_alias",
            "host",
            "session",
            "session_id",
        }

        token = _read_json(
            TOKEN_FILE
        )

        connection = _read_json(
            CONNECTION_FILE
        )

        for key in token_keys:
            if key in values:
                token[key] = values[key]

        for key in connection_keys:
            if key in values:
                connection[key] = values[key]

        if (
            connection.get("session")
            and not connection.get(
                "session_id"
            )
        ):
            connection["session_id"] = (
                connection["session"]
            )

        if (
            connection.get(
                "session_id"
            )
            and not connection.get(
                "session"
            )
        ):
            connection["session"] = (
                connection["session_id"]
            )

        _write_json(
            TOKEN_FILE,
            token,
        )

        _write_json(
            CONNECTION_FILE,
            connection,
        )

    # ========================================================
    # SYNC STATE
    # ========================================================

    def _sync_records(
        self,
    ) -> dict[str, Any]:
        data = _read_json(
            SYNC_FILE
        )

        records = data.get(
            "records"
        )

        return (
            records
            if isinstance(
                records,
                dict,
            )
            else {}
        )

    def _sync_get(
        self,
        opportunity_id: str,
    ) -> dict[str, Any] | None:
        try:
            result = self.store.sync_get(
                opportunity_id
            )

            if isinstance(
                result,
                dict,
            ):
                return result

        except (
            AttributeError,
            TypeError,
        ):
            pass

        record = self._sync_records().get(
            str(opportunity_id)
        )

        return (
            record
            if isinstance(
                record,
                dict,
            )
            else None
        )

    def _sync_save(
        self,
        opportunity_id: str,
        status: str,
        source_modified_at: Any,
        accurate_external_id: Any = None,
        payload_hash: str | None = None,
        attempts: int = 0,
        error_message: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        try:
            self.store.sync_save(
                opportunity_id,
                status,
                source_modified_at,
                accurate_external_id,
                payload_hash,
                attempts,
                error_message,
            )

        except (
            AttributeError,
            TypeError,
        ):
            pass

        records = self._sync_records()

        record = {
            "opportunity_id": str(
                opportunity_id
            ),
            "status": status,
            "source_modified_at": (
                source_modified_at
            ),
            "accurate_external_id": (
                accurate_external_id
            ),
            "payload_hash": payload_hash,
            "attempts": attempts,
            "error_message": error_message,
            "updated_at": time.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            **extra,
        }

        records[
            str(opportunity_id)
        ] = record

        _write_json(
            SYNC_FILE,
            {
                "records": records
            },
        )

        return record

    # ========================================================
    # STATUS
    # ========================================================

    def is_configured(
        self,
    ) -> bool:
        return bool(
            self.client_id
            and self.client_secret
        )

    def is_connected(
        self,
    ) -> bool:
        return bool(
            self._tokens().get(
                "access_token"
            )
        )

    def status(
        self,
    ) -> dict[str, Any]:
        tokens = self._tokens()

        return {
            "configured": self.is_configured(),
            "connected": self.is_connected(),
            "database_id": (
                tokens.get(
                    "database_id"
                )
                or self.database_id
                or None
            ),
            "database_alias": (
                tokens.get(
                    "database_alias"
                )
                or self.database_alias
            ),
            "host": tokens.get(
                "host"
            ),
            "session_ready": bool(
                tokens.get(
                    "session_id"
                )
                or tokens.get(
                    "session"
                )
            ),
            "expires_at": tokens.get(
                "expires_at"
            ),
            "scope": (
                tokens.get(
                    "scope"
                )
                or self.scope
            ),
            "configured_customer_no": (
                self.configured_customer_no
                or None
            ),
            "customer_field": (
                self.customer_field
            ),
            "default_item_no": (
                self.default_item_no
            ),
            "default_item_name": (
                self.default_item_name
            ),
            "currency_field": (
                self.currency_field
                or None
            ),
            "currency_value": (
                self.configured_currency_value
                or None
            ),
            "invoice_detail_endpoint": (
                self.invoice_detail_endpoint
            ),
        }

    # ========================================================
    # OAUTH
    # ========================================================

    def authorization_url(
        self,
    ) -> str:
        if not self.client_id:
            raise AccurateConfigError(
                "ACCURATE_CLIENT_ID belum dikonfigurasi."
            )

        return (
            self.AUTHORIZE_URL
            + "?"
            + urlencode(
                {
                    "client_id": (
                        self.client_id
                    ),
                    "response_type": (
                        "code"
                    ),
                    "redirect_uri": (
                        self.redirect_uri
                    ),
                    "scope": self.scope,
                }
            )
        )

    def _basic_auth(
        self,
    ) -> str:
        raw = (
            f"{self.client_id}:"
            f"{self.client_secret}"
        ).encode(
            "utf-8"
        )

        return (
            "Basic "
            + base64.b64encode(
                raw
            ).decode(
                "ascii"
            )
        )

    def exchange_code(
        self,
        code: str,
    ) -> dict[str, Any]:
        code = str(
            code or ""
        ).strip()

        if not code:
            raise AccurateConfigError(
                "Authorization code kosong."
            )

        response = requests.post(
            self.TOKEN_URL,
            headers={
                "Authorization": (
                    self._basic_auth()
                ),
                "Content-Type": (
                    "application/x-www-form-urlencoded"
                ),
                "Accept": (
                    "application/json"
                ),
            },
            data={
                "code": code,
                "grant_type": (
                    "authorization_code"
                ),
                "redirect_uri": (
                    self.redirect_uri
                ),
            },
            timeout=self.timeout,
            allow_redirects=True,
        )

        if not response.ok:
            raise AccurateAPIError(
                self._http_error(
                    response,
                    (
                        "Gagal mendapatkan "
                        "Access Token"
                    ),
                ),
                status_code=(
                    response.status_code
                ),
                response=(
                    self._response_data(
                        response
                    )
                ),
            )

        data = self._response_data(
            response
        )

        if (
            not isinstance(
                data,
                dict,
            )
            or not data.get(
                "access_token"
            )
        ):
            raise AccurateAPIError(
                (
                    "Response OAuth tidak "
                    "berisi access_token."
                ),
                response=data,
            )

        expires_in = _decimal(
            data.get(
                "expires_in"
            )
        )

        self._save_tokens(
            access_token=(
                data.get(
                    "access_token"
                )
            ),
            refresh_token=(
                data.get(
                    "refresh_token"
                )
            ),
            expires_at=(
                time.time()
                + float(
                    expires_in
                )
            ),
            scope=data.get(
                "scope"
            ),
        )

        self.initialize_database_session()

        return data

    def refresh_if_needed(
        self,
    ) -> str | None:
        tokens = self._tokens()

        access = tokens.get(
            "access_token"
        )

        expires_at = float(
            tokens.get(
                "expires_at"
            )
            or 0
        )

        if (
            access
            and expires_at
            > time.time() + 3600
        ):
            return str(
                access
            )

        refresh = tokens.get(
            "refresh_token"
        )

        if not refresh:
            return (
                str(access)
                if access
                else None
            )

        response = requests.post(
            self.TOKEN_URL,
            headers={
                "Authorization": (
                    self._basic_auth()
                ),
                "Content-Type": (
                    "application/x-www-form-urlencoded"
                ),
                "Accept": (
                    "application/json"
                ),
            },
            data={
                "grant_type": (
                    "refresh_token"
                ),
                "refresh_token": refresh,
            },
            timeout=self.timeout,
            allow_redirects=True,
        )

        if not response.ok:
            raise AccurateAPIError(
                self._http_error(
                    response,
                    (
                        "Gagal refresh "
                        "Access Token"
                    ),
                ),
                status_code=(
                    response.status_code
                ),
                response=(
                    self._response_data(
                        response
                    )
                ),
            )

        data = self._response_data(
            response
        )

        new_access = (
            data.get(
                "access_token"
            )
            if isinstance(
                data,
                dict,
            )
            else None
        )

        if not new_access:
            raise AccurateAPIError(
                (
                    "Refresh response tidak "
                    "berisi access_token."
                ),
                response=data,
            )

        self._save_tokens(
            access_token=new_access,
            refresh_token=(
                data.get(
                    "refresh_token"
                )
                or refresh
            ),
            expires_at=(
                time.time()
                + float(
                    _decimal(
                        data.get(
                            "expires_in"
                        )
                    )
                )
            ),
            scope=(
                data.get(
                    "scope"
                )
                or tokens.get(
                    "scope"
                )
            ),
        )

        return str(
            new_access
        )

    # ========================================================
    # HTTP HELPERS
    # ========================================================

    @staticmethod
    def _response_data(
        response: requests.Response,
    ) -> Any:
        try:
            return response.json()

        except ValueError:
            return response.text[
                :4000
            ]

    def _http_error(
        self,
        response: requests.Response,
        prefix: str,
    ) -> str:
        return (
            f"{prefix} "
            f"(HTTP {response.status_code}): "
            f"{_message(self._response_data(response))}"
        )

    def _headers(
        self,
        session: bool = False,
    ) -> dict[str, str]:
        token = self.refresh_if_needed()

        if not token:
            raise AccurateConfigError(
                (
                    "Accurate belum terhubung. "
                    "Jalankan OAuth terlebih dahulu."
                )
            )

        headers = {
            "Authorization": (
                f"Bearer {token}"
            ),
            "Accept": (
                "application/json"
            ),
        }

        if session:
            tokens = self._tokens()

            session_id = (
                tokens.get(
                    "session_id"
                )
                or tokens.get(
                    "session"
                )
            )

            if not session_id:
                self.initialize_database_session()

                tokens = self._tokens()

                session_id = (
                    tokens.get(
                        "session_id"
                    )
                    or tokens.get(
                        "session"
                    )
                )

            if not session_id:
                raise AccurateConfigError(
                    "X-Session-ID belum tersedia."
                )

            headers["X-Session-ID"] = str(
                session_id
            )

        return headers

    def _business_get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """GET Accurate business API."""
        tokens = self._tokens()

        if (
            not tokens.get(
                "host"
            )
            or not (
                tokens.get(
                    "session_id"
                )
                or tokens.get(
                    "session"
                )
            )
        ):
            self.initialize_database_session()

            tokens = self._tokens()

        host = tokens.get(
            "host"
        )

        if not host:
            raise AccurateConfigError(
                "Host Accurate belum tersedia."
            )

        url = (
            host.rstrip("/")
            + "/"
            + endpoint.lstrip("/")
        )

        last_exc: Exception | None = None

        for attempt in range(
            1,
            self.get_retries + 1,
        ):
            try:
                response = requests.get(
                    url,
                    headers=self._headers(
                        session=True
                    ),
                    params=params or {},
                    timeout=self.timeout,
                    allow_redirects=True,
                )

                if (
                    response.status_code
                    == 401
                    and attempt
                    < self.get_retries
                ):
                    self.refresh_if_needed()

                    time.sleep(
                        0.5 * attempt
                    )

                    continue

                if (
                    response.status_code
                    in {
                        502,
                        503,
                        504,
                    }
                    and attempt
                    < self.get_retries
                ):
                    time.sleep(
                        0.8 * attempt
                    )

                    continue

                if not response.ok:
                    raise AccurateAPIError(
                        self._http_error(
                            response,
                            (
                                "GET Accurate "
                                f"{endpoint} gagal"
                            ),
                        ),
                        status_code=(
                            response.status_code
                        ),
                        response=(
                            self._response_data(
                                response
                            )
                        ),
                    )

                payload = (
                    self._response_data(
                        response
                    )
                )

                if (
                    isinstance(
                        payload,
                        dict,
                    )
                    and payload.get(
                        "s"
                    )
                    is False
                ):
                    raise AccurateAPIError(
                        _message(payload),
                        response=payload,
                    )

                if not isinstance(
                    payload,
                    dict,
                ):
                    raise AccurateAPIError(
                        (
                            "Response GET Accurate "
                            "bukan object JSON."
                        ),
                        response=payload,
                    )

                return payload

            except requests.RequestException as exc:
                last_exc = exc

                if (
                    attempt
                    < self.get_retries
                ):
                    time.sleep(
                        0.8 * attempt
                    )

                    continue

        raise AccurateAPIError(
            f"GET Accurate gagal: {last_exc}"
        )

    def _business_post(
        self,
        endpoint: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """POST Accurate business API."""
        tokens = self._tokens()

        if (
            not tokens.get(
                "host"
            )
            or not (
                tokens.get(
                    "session_id"
                )
                or tokens.get(
                    "session"
                )
            )
        ):
            self.initialize_database_session()

            tokens = self._tokens()

        host = tokens.get(
            "host"
        )

        if not host:
            raise AccurateConfigError(
                "Host Accurate belum tersedia."
            )

        url = (
            host.rstrip("/")
            + "/"
            + endpoint.lstrip("/")
        )

        try:
            response = requests.post(
                url,
                headers=self._headers(
                    session=True
                ),
                data=data,
                timeout=self.timeout,
                allow_redirects=True,
            )

        except (
            requests.Timeout,
            requests.ConnectionError,
        ) as exc:
            raise AccurateAPIError(
                (
                    "POST ke Accurate tidak mendapat "
                    "response. Hasil remote mungkin sudah "
                    "terjadi; verifikasi sebelum retry."
                ),
                ambiguous=True,
            ) from exc

        # ----------------------------------------------------
        # One token-refresh retry
        # ----------------------------------------------------

        if response.status_code == 401:
            self.refresh_if_needed()

            try:
                response = requests.post(
                    url,
                    headers=self._headers(
                        session=True
                    ),
                    data=data,
                    timeout=self.timeout,
                    allow_redirects=True,
                )

            except (
                requests.Timeout,
                requests.ConnectionError,
            ) as exc:
                raise AccurateAPIError(
                    (
                        "Retry POST setelah refresh token "
                        "tidak mendapat response."
                    ),
                    ambiguous=True,
                ) from exc

        # ----------------------------------------------------
        # Ambiguous 5xx
        # ----------------------------------------------------

        if response.status_code in {
            500,
            502,
            503,
            504,
        }:
            raise AccurateAPIError(
                self._http_error(
                    response,
                    (
                        "POST Accurate menghasilkan "
                        "server error; verifikasi hasil "
                        "transaksi sebelum retry"
                    ),
                ),
                status_code=(
                    response.status_code
                ),
                response=(
                    self._response_data(
                        response
                    )
                ),
                ambiguous=True,
            )

        # ----------------------------------------------------
        # Normal HTTP failure
        # ----------------------------------------------------

        if not response.ok:
            raise AccurateAPIError(
                self._http_error(
                    response,
                    (
                        "POST Accurate "
                        f"{endpoint} gagal"
                    ),
                ),
                status_code=(
                    response.status_code
                ),
                response=(
                    self._response_data(
                        response
                    )
                ),
                ambiguous=False,
            )

        payload = self._response_data(
            response
        )

        if (
            isinstance(
                payload,
                dict,
            )
            and payload.get("s")
            is False
        ):
            raise AccurateAPIError(
                _message(payload),
                response=payload,
                ambiguous=False,
            )

        if not isinstance(
            payload,
            dict,
        ):
            raise AccurateAPIError(
                (
                    "Response POST Accurate "
                    "bukan object JSON."
                ),
                response=payload,
            )

        return payload

    # ========================================================
    # DATABASE / SESSION
    # ========================================================

    def initialize_database_session(
        self,
    ) -> dict[str, Any]:
        token_headers = self._headers(
            session=False
        )

        db_id = (
            self.database_id
            or self._tokens().get(
                "database_id"
            )
        )

        alias = self.database_alias

        # ----------------------------------------------------
        # Find database by exact alias
        # ----------------------------------------------------

        if not db_id:
            response = requests.get(
                self.DB_LIST_URL,
                headers=token_headers,
                timeout=self.timeout,
                allow_redirects=True,
            )

            if not response.ok:
                raise AccurateAPIError(
                    self._http_error(
                        response,
                        (
                            "Gagal mengambil "
                            "daftar database"
                        ),
                    ),
                    status_code=(
                        response.status_code
                    ),
                    response=(
                        self._response_data(
                            response
                        )
                    ),
                )

            payload = self._response_data(
                response
            )

            if (
                not isinstance(
                    payload,
                    dict,
                )
                or payload.get("s")
                is False
            ):
                raise AccurateAPIError(
                    _message(payload),
                    response=payload,
                )

            databases = (
                payload.get("d")
                or []
            )

            if not isinstance(
                databases,
                list,
            ):
                raise AccurateConfigError(
                    (
                        "Format daftar database "
                        "Accurate tidak sesuai."
                    )
                )

            target = alias.casefold()

            selected = next(
                (
                    db
                    for db in databases
                    if (
                        isinstance(
                            db,
                            dict,
                        )
                        and str(
                            db.get(
                                "alias",
                                "",
                            )
                        )
                        .strip()
                        .casefold()
                        == target
                    )
                ),
                None,
            )

            if not selected:
                available = [
                    db.get("alias")
                    for db in databases
                    if isinstance(
                        db,
                        dict,
                    )
                ]

                raise AccurateConfigError(
                    (
                        f'Database Accurate "{alias}" '
                        f"tidak ditemukan. "
                        f"Tersedia: {available}"
                    )
                )

            db_id = (
                selected.get("id")
                or selected.get("dbId")
            )

            alias = (
                selected.get("alias")
                or alias
            )

        if not db_id:
            raise AccurateConfigError(
                "ID database Accurate tidak tersedia."
            )

        # ----------------------------------------------------
        # Open database
        # ----------------------------------------------------

        response = requests.get(
            self.OPEN_DB_URL,
            headers=token_headers,
            params={
                "id": db_id
            },
            timeout=self.timeout,
            allow_redirects=True,
        )

        if not response.ok:
            raise AccurateAPIError(
                self._http_error(
                    response,
                    "Gagal membuka database",
                ),
                status_code=(
                    response.status_code
                ),
                response=(
                    self._response_data(
                        response
                    )
                ),
            )

        payload = self._response_data(
            response
        )

        if (
            not isinstance(
                payload,
                dict,
            )
            or payload.get("s")
            is False
        ):
            raise AccurateAPIError(
                _message(payload),
                response=payload,
            )

        data = (
            payload.get("d")
            if isinstance(
                payload.get("d"),
                dict,
            )
            else payload
        )

        host = data.get(
            "host"
        )

        session_id = data.get(
            "session"
        )

        if not host or not session_id:
            raise AccurateConfigError(
                (
                    "Accurate tidak mengembalikan "
                    "host/session database."
                )
            )

        self._save_tokens(
            database_id=str(
                db_id
            ),
            database_alias=alias,
            host=host,
            session=session_id,
            session_id=session_id,
        )

        return {
            "database_id": str(
                db_id
            ),
            "database_alias": alias,
            "host": host,
            "session_id": session_id,
        }

    # ========================================================
    # MASTER DATA
    # ========================================================

    def _list_resource(
        self,
        endpoint: str,
        fields: str,
    ) -> list[dict[str, Any]]:
        records: list[
            dict[str, Any]
        ] = []

        for page in range(
            1,
            self.max_pages + 1,
        ):
            payload = self._business_get(
                endpoint,
                params={
                    "fields": fields,
                    "sp.page": page,
                    "sp.pageSize": self.page_size,
                },
            )

            rows = (
                payload.get("d")
                or []
            )

            if not isinstance(
                rows,
                list,
            ):
                break

            records.extend(
                row
                for row in rows
                if isinstance(
                    row,
                    dict,
                )
            )

            page_info = payload.get(
                "sp"
            )

            if (
                isinstance(
                    page_info,
                    dict,
                )
                and page_info.get(
                    "pageCount"
                )
            ):
                try:
                    if page >= int(
                        page_info[
                            "pageCount"
                        ]
                    ):
                        break

                except (
                    ValueError,
                    TypeError,
                ):
                    pass

            if len(rows) < self.page_size:
                break

        return records

    # ========================================================
    # CUSTOMER
    # ========================================================

    def find_customer(
        self,
        customer_name: str,
    ) -> dict[str, Any] | None:
        target = str(
            customer_name or ""
        ).strip().casefold()

        if not target:
            return None

        # Explicit configured mapping wins.
        if self.configured_customer_no:
            return {
                "id": None,
                "name": customer_name,
                "no": (
                    self.configured_customer_no
                ),
                "customerNo": (
                    self.configured_customer_no
                ),
                "mapping_source": (
                    "ACCURATE_CUSTOMER_NO"
                ),
            }

        customers = self._list_resource(
            self.customer_list_endpoint,
            "id,no,name,customerNo",
        )

        for customer in customers:
            name = str(
                customer.get(
                    "name",
                    "",
                )
            ).strip()

            if (
                name.casefold()
                == target
            ):
                return customer

        return None

    def create_customer(
        self,
        customer_name: str,
    ) -> dict[str, Any]:
        if not self.auto_create_customer:
            raise AccurateConfigError(
                (
                    f'Customer "{customer_name}" '
                    "tidak ditemukan di Accurate. "
                    "Buat customer di Accurate atau set "
                    "ACCURATE_AUTO_CREATE_CUSTOMER=true."
                )
            )

        payload = self._business_post(
            self.customer_save_endpoint,
            {
                "name": customer_name
            },
        )

        record = (
            payload.get("r")
            or payload.get("data")
            or {}
        )

        if not isinstance(
            record,
            dict,
        ):
            raise AccurateAPIError(
                (
                    "Customer save berhasil tetapi "
                    "record tidak ditemukan."
                ),
                response=payload,
            )

        return record

    def resolve_customer(
        self,
        customer_name: str,
    ) -> dict[str, Any]:
        customer_name = str(
            customer_name or ""
        ).strip()

        if not customer_name:
            raise AccurateConfigError(
                "Nama customer/account kosong."
            )

        # Explicit mapping.
        if self.configured_customer_no:
            return {
                "id": None,
                "name": customer_name,
                "no": (
                    self.configured_customer_no
                ),
                "customerNo": (
                    self.configured_customer_no
                ),
                "mapping_source": (
                    "ACCURATE_CUSTOMER_NO"
                ),
            }

        customer = self.find_customer(
            customer_name
        )

        if customer:
            customer_no = (
                customer.get("no")
                or customer.get(
                    "customerNo"
                )
            )

            if not customer_no:
                raise AccurateConfigError(
                    (
                        f'Customer "{customer_name}" '
                        "ditemukan tetapi nomor customer "
                        "tidak tersedia."
                    )
                )

            return customer

        return self.create_customer(
            customer_name
        )

    # ========================================================
    # ITEM / JASA
    # ========================================================

    def find_item(
        self,
        item_no: str = "",
        item_name: str = "",
    ) -> dict[str, Any] | None:
        item_no = str(
            item_no or ""
        ).strip()

        item_name = str(
            item_name or ""
        ).strip()

        if not item_no and not item_name:
            return None

        items = self._list_resource(
            self.item_list_endpoint,
            "id,name,no,itemType",
        )

        if item_no:
            for item in items:
                if (
                    str(
                        item.get(
                            "no",
                            "",
                        )
                    ).strip()
                    == item_no
                ):
                    return item

        if item_name:
            target = item_name.casefold()

            for item in items:
                if (
                    str(
                        item.get(
                            "name",
                            "",
                        )
                    )
                    .strip()
                    .casefold()
                    == target
                ):
                    return item

        return None

    def resolve_item(
        self,
        item_no: str = "",
        item_name: str = "",
    ) -> dict[str, Any]:
        item = self.find_item(
            item_no,
            item_name,
        )

        if item:
            return item

        raise AccurateConfigError(
            (
                "Item/Jasa Accurate tidak ditemukan. "
                f"no='{item_no}', "
                f"name='{item_name}'."
            )
        )

    # ========================================================
    # OPPORTUNITY LINES
    # ========================================================

    def _lines(
        self,
        opportunity: dict[str, Any],
        amount: Decimal,
    ) -> list[dict[str, str]]:
        raw_items = (
            opportunity.get("items")
            or opportunity.get(
                "lineItems"
            )
        )

        lines: list[
            dict[str, str]
        ] = []

        # ----------------------------------------------------
        # Explicit source line items
        # ----------------------------------------------------

        if isinstance(
            raw_items,
            list,
        ):
            for raw in raw_items:
                if not isinstance(
                    raw,
                    dict,
                ):
                    continue

                item_no = str(
                    raw.get("itemNo")
                    or raw.get("no")
                    or ""
                ).strip()

                item_name = str(
                    raw.get("itemName")
                    or raw.get("name")
                    or ""
                ).strip()

                quantity = _decimal(
                    raw.get(
                        "quantity"
                    ),
                    Decimal("1"),
                )

                if quantity <= 0:
                    quantity = Decimal("1")

                unit_price = _decimal(
                    raw.get(
                        "unitPrice"
                    ),
                    Decimal("0"),
                )

                if unit_price <= 0:
                    line_amount = _decimal(
                        raw.get(
                            "amount"
                        )
                    )

                    if line_amount > 0:
                        unit_price = (
                            line_amount
                            / quantity
                        )

                if item_no or item_name:
                    resolved = self.resolve_item(
                        item_no,
                        item_name,
                    )

                    resolved_no = str(
                        resolved.get(
                            "no"
                        )
                        or item_no
                    ).strip()

                    if not resolved_no:
                        raise AccurateConfigError(
                            (
                                "Item line tidak memiliki "
                                "nomor Accurate."
                            )
                        )

                    lines.append(
                        {
                            "item_no": (
                                resolved_no
                            ),
                            "item_name": str(
                                resolved.get(
                                    "name"
                                )
                                or item_name
                            ),
                            "quantity": _money(
                                quantity
                            ),
                            "unit_price": _money(
                                unit_price
                            ),
                        }
                    )

        if lines:
            return lines

        # ----------------------------------------------------
        # Default item
        # ----------------------------------------------------

        if amount <= 0:
            raise AccurateConfigError(
                (
                    "Amount Opportunity "
                    "harus lebih besar dari 0."
                )
            )

        resolved = self.resolve_item(
            self.default_item_no,
            self.default_item_name,
        )

        resolved_no = str(
            resolved.get("no")
            or ""
        ).strip()

        if not resolved_no:
            raise AccurateConfigError(
                (
                    "Item default tidak "
                    "memiliki nomor Accurate."
                )
            )

        quantity = self.default_quantity

        return [
            {
                "item_no": (
                    resolved_no
                ),
                "item_name": str(
                    resolved.get(
                        "name"
                    )
                    or self.default_item_name
                ),
                "quantity": _money(
                    quantity
                ),
                "unit_price": _money(
                    amount / quantity
                ),
            }
        ]

    # ========================================================
    # SALES INVOICE PAYLOAD
    # ========================================================

    def build_sales_invoice_payload(
        self,
        opportunity: dict[str, Any],
        customer: dict[str, Any],
    ) -> dict[str, Any]:
        source_id = str(
            opportunity.get("id")
            or ""
        ).strip()

        source_name = str(
            opportunity.get("name")
            or ""
        ).strip()

        amount = _decimal(
            opportunity.get(
                "amount"
            )
        )

        customer_no = str(
            customer.get("no")
            or customer.get(
                "customerNo"
            )
            or ""
        ).strip()

        if not customer_no:
            raise AccurateConfigError(
                "Nomor customer Accurate tidak tersedia."
            )

        lines = self._lines(
            opportunity,
            amount,
        )

        close_date = _accurate_date(
            opportunity.get(
                "closeDate"
            )
        )

        currency = str(
            opportunity.get(
                "amountCurrency"
            )
            or opportunity.get(
                "currency"
            )
            or "USD"
        ).strip()

        reference = (
            f"[ESPOCRM:{source_id}] "
            f"{source_name}"
        ).strip()

        form: dict[str, Any] = {
            "transDate": close_date,
            self.customer_field: customer_no,
            "description": reference,
        }

        # ----------------------------------------------------
        # Optional currency field
        #
        # Only send when explicitly configured so we don't
        # guess the field name in the user's Accurate database.
        # ----------------------------------------------------

        if (
            self.currency_field
            and self.configured_currency_value
        ):
            form[
                self.currency_field
            ] = self.configured_currency_value

        # ----------------------------------------------------
        # Detail lines
        # ----------------------------------------------------

        for index, line in enumerate(
            lines
        ):
            form[
                f"detailItem[{index}].itemNo"
            ] = line[
                "item_no"
            ]

            form[
                f"detailItem[{index}].quantity"
            ] = line[
                "quantity"
            ]

            form[
                f"detailItem[{index}].unitPrice"
            ] = line[
                "unit_price"
            ]

        return {
            "form": form,
            "mapping": {
                "sourceOpportunityId": (
                    source_id
                ),
                "sourceOpportunityName": (
                    source_name
                ),
                "sourceAccountName": (
                    opportunity.get(
                        "accountName"
                    )
                    or ""
                ),
                "accurateCustomerNo": (
                    customer_no
                ),
                "customerMappingSource": (
                    customer.get(
                        "mapping_source"
                    )
                    or "ACCURATE_API"
                ),
                "amount": _money(
                    amount
                ),
                "currency": currency,
                "closeDate": close_date,
                "lines": lines,
                "externalReference": reference,
            },
        }

    # ========================================================
    # SALES INVOICE DETAIL LOOKUP
    # ========================================================

    def get_sales_invoice(
        self,
        invoice_id: str,
    ) -> dict[str, Any]:
        """
        Retrieve an existing Sales Invoice.

        The endpoint is configurable using:
            ACCURATE_SALES_INVOICE_DETAIL_ENDPOINT

        Default:
            /accurate/api/sales-invoice/detail.do
        """
        invoice_id = str(
            invoice_id or ""
        ).strip()

        if not invoice_id:
            raise AccurateConfigError(
                "Accurate invoice ID kosong."
            )

        payload = self._business_get(
            self.invoice_detail_endpoint,
            params={
                "id": invoice_id
            },
        )

        record = payload.get(
            "d"
        )

        # Some Accurate endpoints may return a record
        # differently, so support common alternatives.
        if isinstance(
            record,
            dict,
        ):
            return record

        if isinstance(
            payload.get("r"),
            dict,
        ):
            return payload["r"]

        if isinstance(
            payload.get("data"),
            dict,
        ):
            return payload["data"]

        raise AccurateAPIError(
            (
                "Response detail Sales Invoice "
                "tidak berisi record invoice."
            ),
            response=payload,
        )

    # ========================================================
    # EXISTING DETAIL HELPERS
    # ========================================================

    @staticmethod
    def _extract_invoice_details(
        invoice: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Extract detailItem from invoice response.

        Expected:
            {
                ...
                "detailItem": [...]
            }
        """
        details = invoice.get(
            "detailItem"
        )

        if not isinstance(
            details,
            list,
        ):
            return []

        return [
            item
            for item in details
            if isinstance(
                item,
                dict,
            )
        ]

    @staticmethod
    def _detail_id(
        detail: dict[str, Any],
    ) -> str | None:
        """Extract detail record ID."""
        value = detail.get(
            "id"
        )

        if value in (
            None,
            "",
        ):
            return None

        return str(
            value
        )

    @staticmethod
    def _detail_item_no(
        detail: dict[str, Any],
    ) -> str:
        """Extract item number from existing detail."""
        item_no = detail.get(
            "itemNo"
        )

        if item_no not in (
            None,
            "",
        ):
            return str(
                item_no
            ).strip()

        item = detail.get(
            "item"
        )

        if isinstance(
            item,
            dict,
        ):
            return str(
                item.get(
                    "no"
                )
                or ""
            ).strip()

        return ""

    def _prepare_update_detail_ids(
        self,
        form: dict[str, Any],
        desired_lines: list[dict[str, str]],
        existing_invoice: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Reuse existing Accurate detail IDs.

        IMPORTANT:

        If the source and existing invoice contain different
        numbers of detail rows, we stop safely instead of
        silently adding duplicate rows.

        This is intentional because the earlier integration
        proved that omitting the existing detail IDs can leave
        old detail rows in place.
        """

        existing_details = (
            self._extract_invoice_details(
                existing_invoice
            )
        )

        desired_count = len(
            desired_lines
        )

        existing_count = len(
            existing_details
        )

        if existing_count == 0:
            raise AccurateConfigError(
                (
                    "Invoice Accurate tidak memiliki "
                    "detailItem yang bisa di-update."
                )
            )

        if existing_count != desired_count:
            raise AccurateConfigError(
                (
                    "Jumlah detail invoice Accurate "
                    f"({existing_count}) berbeda dengan "
                    f"detail dari Opportunity ({desired_count}). "
                    "Update dihentikan untuk mencegah "
                    "duplicate atau detail lama tertinggal. "
                    "Sesuaikan jumlah detail invoice di Accurate "
                    "terlebih dahulu."
                )
            )

        detail_ids: list[str] = []

        for index, line in enumerate(
            desired_lines
        ):
            existing_detail = existing_details[
                index
            ]

            existing_id = self._detail_id(
                existing_detail
            )

            if not existing_id:
                raise AccurateConfigError(
                    (
                        "Detail invoice Accurate pada "
                        f"index {index} tidak memiliki ID."
                    )
                )

            detail_ids.append(
                existing_id
            )

            form[
                f"detailItem[{index}].id"
            ] = existing_id

            form[
                f"detailItem[{index}].itemNo"
            ] = line[
                "item_no"
            ]

            form[
                f"detailItem[{index}].quantity"
            ] = line[
                "quantity"
            ]

            form[
                f"detailItem[{index}].unitPrice"
            ] = line[
                "unit_price"
            ]

        return {
            "existing_detail_count": (
                existing_count
            ),
            "desired_detail_count": (
                desired_count
            ),
            "detail_ids": detail_ids,
        }

    # ========================================================
    # EXTERNAL ID
    # ========================================================

    @staticmethod
    def _external_id(
        response: dict[str, Any],
    ) -> str | None:
        record = (
            response.get("r")
            or response.get("data")
            or {}
        )

        if not isinstance(
            record,
            dict,
        ):
            return None

        for key in (
            "id",
            "invoiceId",
            "salesInvoiceId",
        ):
            value = record.get(
                key
            )

            if value not in (
                None,
                "",
            ):
                return str(
                    value
                )

        return None

    # ========================================================
    # SYNCHRONIZATION
    # ========================================================

    def sync_opportunity(
        self,
        opportunity_id: str,
        *,
        allow_unknown_retry: bool = False,
    ) -> dict[str, Any]:
        """Load Opportunity from EspoCRM then sync."""
        import api

        opportunity = api.get_opportunity(
            opportunity_id
        )

        return self.sync_opportunity_record(
            opportunity,
            allow_unknown_retry=(
                allow_unknown_retry
            ),
        )

    def sync_opportunity_record(
        self,
        opportunity: dict[str, Any],
        *,
        allow_unknown_retry: bool = False,
    ) -> dict[str, Any]:
        """Create/update Accurate invoice for one Opportunity."""

        opportunity_id = str(
            opportunity.get("id")
            or ""
        ).strip()

        if not opportunity_id:
            raise ValueError(
                "Opportunity ID tidak ditemukan."
            )

        # ----------------------------------------------------
        # Only Closed Won
        # ----------------------------------------------------

        if (
            _stage(
                opportunity.get(
                    "stage"
                )
            )
            != "closed won"
        ):
            return {
                "status": "skipped",
                "reason": (
                    "Opportunity belum Closed Won."
                ),
                "opportunity_id": (
                    opportunity_id
                ),
            }

        # ----------------------------------------------------
        # Account/customer
        # ----------------------------------------------------

        account_name = str(
            opportunity.get(
                "accountName"
            )
            or ""
        ).strip()

        if not account_name:
            return self._record_failure(
                opportunity_id,
                opportunity,
                (
                    "Account Opportunity kosong; "
                    "customer Accurate tidak dapat "
                    "ditentukan."
                ),
                "failed_validation",
            )

        source_modified = opportunity.get(
            "modifiedAt"
        )

        # ----------------------------------------------------
        # Idempotency preview
        # ----------------------------------------------------

        preview = {
            "sourceOpportunityId": (
                opportunity_id
            ),
            "customerName": (
                account_name
            ),
            "accurateCustomerNo": (
                self.configured_customer_no
            ),
            "amount": (
                opportunity.get(
                    "amount"
                )
                or 0
            ),
            "currency": (
                opportunity.get(
                    "amountCurrency"
                )
                or opportunity.get(
                    "currency"
                )
                or "USD"
            ),
            "closeDate": (
                opportunity.get(
                    "closeDate"
                )
            ),
            "description": (
                opportunity.get(
                    "description"
                )
                or ""
            ),
            "defaultItemNo": (
                self.default_item_no
            ),
            "defaultItemName": (
                self.default_item_name
            ),
            "defaultQuantity": str(
                self.default_quantity
            ),
            "currencyField": (
                self.currency_field
            ),
            "currencyValue": (
                self.configured_currency_value
            ),
        }

        digest = hashlib.sha256(
            json.dumps(
                preview,
                sort_keys=True,
                default=str,
            ).encode(
                "utf-8"
            )
        ).hexdigest()

        # ----------------------------------------------------
        # Existing sync record
        # ----------------------------------------------------

        existing = self._sync_get(
            opportunity_id
        )

        external_id = None

        if existing:
            status = str(
                existing.get(
                    "status"
                )
                or ""
            ).casefold()

            external_id = existing.get(
                "accurate_external_id"
            )

            # ------------------------------------------------
            # Exact unchanged source
            # ------------------------------------------------

            unchanged = (
                status == "success"
                and external_id
                and existing.get(
                    "payload_hash"
                )
                == digest
                and str(
                    existing.get(
                        "source_modified_at"
                    )
                )
                == str(
                    source_modified
                )
            )

            if unchanged:
                return {
                    "status": "skipped",
                    "reason": (
                        "Sudah tersinkron dan "
                        "tidak berubah."
                    ),
                    "opportunity_id": (
                        opportunity_id
                    ),
                    "external_id": (
                        external_id
                    ),
                }

            # ------------------------------------------------
            # Unknown protection
            # ------------------------------------------------

            if (
                status == "unknown"
                and not allow_unknown_retry
            ):
                return {
                    "status": "unknown",
                    "reason": (
                        "Sync sebelumnya ambiguous. "
                        "Verifikasi Accurate secara manual "
                        "sebelum retry untuk mencegah duplicate."
                    ),
                    "opportunity_id": (
                        opportunity_id
                    ),
                    "external_id": (
                        external_id
                    ),
                }

        # ----------------------------------------------------
        # Configuration
        # ----------------------------------------------------

        if not self.is_configured():
            return self._record_failure(
                opportunity_id,
                opportunity,
                (
                    "ACCURATE_CLIENT_ID / "
                    "ACCURATE_CLIENT_SECRET "
                    "belum dikonfigurasi."
                ),
                "pending_configuration",
                digest,
                int(
                    existing.get(
                        "attempts"
                    )
                    or 0
                )
                if existing
                else 0,
            )

        attempts = (
            int(
                existing.get(
                    "attempts"
                )
                or 0
            )
            + 1
            if existing
            else 1
        )

        # ====================================================
        # ACTUAL SYNC
        # ====================================================

        try:
            # ------------------------------------------------
            # 1. Initialize DB
            # ------------------------------------------------

            self.initialize_database_session()

            # ------------------------------------------------
            # 2. Resolve customer
            # ------------------------------------------------

            customer = self.resolve_customer(
                account_name
            )

            # ------------------------------------------------
            # 3. Build source payload
            # ------------------------------------------------

            payload = (
                self.build_sales_invoice_payload(
                    opportunity,
                    customer,
                )
            )

            form = dict(
                payload["form"]
            )

            mapping = dict(
                payload["mapping"]
            )

            desired_lines = (
                mapping.get(
                    "lines"
                )
                or []
            )

            # ------------------------------------------------
            # 4. Determine operation
            # ------------------------------------------------

            operation = (
                "update"
                if external_id
                else "create"
            )

            # ------------------------------------------------
            # 5. Update same invoice
            # ------------------------------------------------

            detail_update_info = None

            if external_id:
                # Existing invoice ID.
                form["id"] = str(
                    external_id
                )

                # Fetch existing invoice so its existing
                # detail IDs can be reused.
                existing_invoice = (
                    self.get_sales_invoice(
                        str(
                            external_id
                        )
                    )
                )

                detail_update_info = (
                    self._prepare_update_detail_ids(
                        form,
                        desired_lines,
                        existing_invoice,
                    )
                )

            # ------------------------------------------------
            # 6. Create/update Accurate
            # ------------------------------------------------

            response = self._business_post(
                self.invoice_endpoint,
                form,
            )

            success = bool(
                response.get("s")
                or response.get(
                    "success"
                )
            )

            if not success:
                message = _message(
                    response
                )

                self._sync_save(
                    opportunity_id,
                    "failed",
                    source_modified,
                    external_id,
                    digest,
                    attempts,
                    message,
                    mapping=mapping,
                    accurate_operation=operation,
                    detail_update=(
                        detail_update_info
                    ),
                )

                return {
                    "status": "failed",
                    "operation": (
                        operation
                    ),
                    "opportunity_id": (
                        opportunity_id
                    ),
                    "error": message,
                    "attempts": attempts,
                }

            # ------------------------------------------------
            # 7. External ID
            # ------------------------------------------------

            new_external_id = (
                self._external_id(
                    response
                )
                or external_id
            )

            # ------------------------------------------------
            # 8. Save successful state
            # ------------------------------------------------

            self._sync_save(
                opportunity_id,
                "success",
                source_modified,
                new_external_id,
                digest,
                attempts,
                None,
                mapping=mapping,
                accurate_operation=operation,
                detail_update=(
                    detail_update_info
                ),
                accurate_message=_message(
                    response
                ),
            )

            return {
                "status": "success",
                "operation": (
                    operation
                ),
                "opportunity_id": (
                    opportunity_id
                ),
                "accurate_external_id": (
                    new_external_id
                ),
                "message": _message(
                    response
                ),
                "mapping": mapping,
                "detail_update": (
                    detail_update_info
                ),
                "response": _safe_json(
                    response
                ),
            }

        # ====================================================
        # ACCURATE API ERROR
        # ====================================================

        except AccurateAPIError as exc:

            if exc.ambiguous:
                self._sync_save(
                    opportunity_id,
                    "unknown",
                    source_modified,
                    external_id,
                    digest,
                    attempts,
                    str(exc),
                )

                return {
                    "status": "unknown",
                    "operation": (
                        "update"
                        if external_id
                        else "create"
                    ),
                    "opportunity_id": (
                        opportunity_id
                    ),
                    "error": str(
                        exc
                    ),
                    "attempts": attempts,
                    "manual_verification_required": True,
                }

            self._sync_save(
                opportunity_id,
                "failed",
                source_modified,
                external_id,
                digest,
                attempts,
                str(exc),
            )

            return {
                "status": "failed",
                "opportunity_id": (
                    opportunity_id
                ),
                "error": str(
                    exc
                ),
                "attempts": attempts,
            }

        # ====================================================
        # CONNECTION/TIMEOUT ERROR
        # ====================================================

        except (
            requests.Timeout,
            requests.ConnectionError,
        ) as exc:
            self._sync_save(
                opportunity_id,
                "unknown",
                source_modified,
                external_id,
                digest,
                attempts,
                str(exc),
            )

            return {
                "status": "unknown",
                "opportunity_id": (
                    opportunity_id
                ),
                "error": str(
                    exc
                ),
                "attempts": attempts,
                "manual_verification_required": True,
            }

        # ====================================================
        # UNEXPECTED ERROR
        # ====================================================

        except Exception as exc:
            self._sync_save(
                opportunity_id,
                "failed",
                source_modified,
                external_id,
                digest,
                attempts,
                str(exc),
            )

            return {
                "status": "failed",
                "opportunity_id": (
                    opportunity_id
                ),
                "error": str(
                    exc
                ),
                "attempts": attempts,
            }

    # ========================================================
    # FAILURE HELPER
    # ========================================================

    def _record_failure(
        self,
        opportunity_id: str,
        opportunity: dict[str, Any],
        message: str,
        status: str = "failed",
        payload_hash: str | None = None,
        attempts: int = 0,
    ) -> dict[str, Any]:
        self._sync_save(
            opportunity_id,
            status,
            opportunity.get(
                "modifiedAt"
            ),
            None,
            payload_hash,
            attempts,
            message,
        )

        return {
            "status": status,
            "opportunity_id": (
                opportunity_id
            ),
            "error": message,
        }

    # ========================================================
    # SYNC STATUS
    # ========================================================

    def get_sync_status(
        self,
        opportunity_id: str,
    ) -> dict[str, Any] | None:
        return self._sync_get(
            str(opportunity_id)
        )

    # ========================================================
    # MANUAL RETRY
    # ========================================================

    def retry_opportunity(
        self,
        opportunity_id: str,
        *,
        force_unknown: bool = False,
    ) -> dict[str, Any]:
        opportunity_id = str(
            opportunity_id
        ).strip()

        if not opportunity_id:
            raise ValueError(
                "Opportunity ID kosong."
            )

        current = self._sync_get(
            opportunity_id
        )

        if (
            current
            and str(
                current.get(
                    "status"
                )
                or ""
            ).casefold()
            == "unknown"
            and not force_unknown
        ):
            return {
                "status": "blocked",
                "reason": (
                    "Retry diblokir karena hasil POST "
                    "sebelumnya tidak pasti. Verifikasi "
                    "Accurate dulu; setelah itu gunakan "
                    "force_unknown=True."
                ),
                "opportunity_id": (
                    opportunity_id
                ),
            }

        return self.sync_opportunity(
            opportunity_id,
            allow_unknown_retry=(
                force_unknown
            ),
        )

    # ========================================================
    # DISCONNECT
    # ========================================================

    def disconnect(
        self,
    ) -> None:
        try:
            self.store.clear_tokens()

        except (
            AttributeError,
            TypeError,
        ):
            pass

        for path in (
            TOKEN_FILE,
            CONNECTION_FILE,
        ):
            try:
                path.unlink(
                    missing_ok=True
                )
            except OSError:
                pass