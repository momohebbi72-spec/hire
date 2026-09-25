"""Connector registry. Importing this package registers every connector."""
from .base import FETCHERS, GROUPS, Item, SourceConfig, SourceType, register  # noqa: F401
from . import (  # noqa: F401,E402
    ats, feeds, freelance, iran, job_boards, jobspy_boards, linkedin, telegram, websearch,
)
