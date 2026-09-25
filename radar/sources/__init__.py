"""Source registry. Importing this package registers every fetcher."""
from .base import FETCHERS, Item, SourceType, register  # noqa: F401
from . import ats, feeds, freelance, job_boards, telegram  # noqa: F401,E402
