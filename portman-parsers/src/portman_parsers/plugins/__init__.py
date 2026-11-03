"""Approved, package-local bank parsers."""

from .bank_of_scotland import BankOfScotlandPlugin
from .fnz_finvesto import FnzFinvestoPlugin
from .comdirect import ComdirectFinanzreportPlugin, ComdirectPlugin
from .comdirect_pp import ComdirectPPPlugin

__all__ = ["BankOfScotlandPlugin", "ComdirectFinanzreportPlugin", "ComdirectPlugin", "ComdirectPPPlugin", "FnzFinvestoPlugin"]

