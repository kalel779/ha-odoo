"""Minimal XML-RPC client for querying Odoo (standard external API, no extra module needed)."""
from __future__ import annotations

import logging
import xmlrpc.client
from typing import Any

_LOGGER = logging.getLogger(__name__)


class OdooAuthError(Exception):
    """Odoo authentication error."""


class OdooConnectionError(Exception):
    """Odoo connection error."""


class OdooClient:
    """Small synchronous wrapper around Odoo's XML-RPC API.

    Every method is blocking: it must be called via
    hass.async_add_executor_job() from the integration's async code.
    """

    def __init__(self, url: str, db: str, username: str, api_key: str) -> None:
        self._url = url.rstrip("/")
        self._db = db
        self._username = username
        self._api_key = api_key
        self._uid: int | None = None
        self._models = None

    def authenticate(self) -> int:
        """Authenticate and return the Odoo uid. Raises OdooAuthError/OdooConnectionError."""
        try:
            common = xmlrpc.client.ServerProxy(
                f"{self._url}/xmlrpc/2/common", allow_none=True
            )
            uid = common.authenticate(self._db, self._username, self._api_key, {})
        except (xmlrpc.client.Fault, OSError, ValueError) as err:
            raise OdooConnectionError(str(err)) from err

        if not uid:
            raise OdooAuthError(
                "Authentication refused: check the URL, database, username "
                "and API key."
            )

        self._uid = uid
        self._models = xmlrpc.client.ServerProxy(
            f"{self._url}/xmlrpc/2/object", allow_none=True
        )
        return uid

    def _ensure_ready(self) -> None:
        if self._uid is None or self._models is None:
            self.authenticate()

    def execute_kw(self, model: str, method: str, args: list, kwargs: dict | None = None) -> Any:
        """Call execute_kw on Odoo."""
        self._ensure_ready()
        try:
            return self._models.execute_kw(
                self._db, self._uid, self._api_key, model, method, args, kwargs or {}
            )
        except xmlrpc.client.Fault as err:
            raise OdooConnectionError(str(err)) from err
        except OSError as err:
            raise OdooConnectionError(str(err)) from err

    def sum_field(self, model: str, domain: list, field: str) -> float:
        """Sum a numeric field via read_group (server-side aggregation in Odoo)."""
        result = self.execute_kw(
            model,
            "read_group",
            [domain, [f"{field}:sum"], []],
        )
        if not result:
            return 0.0
        value = result[0].get(field)
        return float(value) if value else 0.0

    def search_count(self, model: str, domain: list) -> int:
        return int(self.execute_kw(model, "search_count", [domain]))

    def search_read(
        self,
        model: str,
        domain: list,
        fields: list,
        order: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        kwargs: dict = {"fields": fields}
        if order:
            kwargs["order"] = order
        if limit:
            kwargs["limit"] = limit
        return self.execute_kw(model, "search_read", [domain], kwargs)
