"""Approved, package-local bank parsers."""

from .bank_of_scotland import BankOfScotlandPlugin
from .baader import BaaderPlugin
from .fnz_finvesto import FnzFinvestoPlugin
from .deka import DekaQuartalsberichtPlugin
from .comdirect import ComdirectFinanzreportPlugin, ComdirectPlugin
from .comdirect_pp import ComdirectPPPlugin
from .ing import IngPlugin

__all__ = ["BaaderPlugin", "BankOfScotlandPlugin", "ComdirectFinanzreportPlugin", "ComdirectPlugin", "ComdirectPPPlugin", "FnzFinvestoPlugin", "DekaQuartalsberichtPlugin", "IngPlugin"]

