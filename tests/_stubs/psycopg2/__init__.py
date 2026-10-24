"""Import-only stand-in for psycopg2, used by tests when the real driver is not installed.
connect() always fails: tests never reach PostgreSQL."""
IntegrityError = Exception
Error = Exception


def connect(*args, **kwargs):
    raise RuntimeError("psycopg2 stub: no database access in tests")
