"""SQLite-Hilfen für exakte Dezimalvergleiche; keine Migration oder Persistenzschicht."""
import sqlite3

from portman_v10.domain.values import compare_decimal_text


DECIMAL_COLLATION = "PORTMAN_DECIMAL"


def register_decimal_collation(connection: sqlite3.Connection) -> None:
    """Registriert die numerische Textsortierung vor Nutzung entsprechender Indizes."""
    connection.create_collation(DECIMAL_COLLATION, compare_decimal_text)
