import re
import uuid
from typing import Annotated

from pydantic import BeforeValidator


# --- patterns ---
LEFT_RIGHT_DOT_PATTERN = re.compile(r"^[a-z][a-z0-9]*(\.[a-z0-9]+)*$")

UUID4_STR_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


# --- methods ---
def is_left_right_dot(v: str) -> str:
    if not isinstance(v, str):
        raise ValueError(f"<{v}>: LeftRightDot must be a string.")

    if not LEFT_RIGHT_DOT_PATTERN.fullmatch(v):
        raise ValueError(f"<{v}>: Fails LeftRightDot format.")

    return v


def is_uuid4_str(v: str) -> str:
    if not isinstance(v, str):
        raise ValueError(f"<{v}>: uuid4.str must be a string.")

    if not UUID4_STR_PATTERN.fullmatch(v):
        raise ValueError(f"<{v}>: Fails uuid4.str format.")

    try:
        u = uuid.UUID(v)
    except Exception as e:
        raise ValueError(f"Invalid UUID4: {v}  <{e}>") from e
    if u.version != 4:
        raise ValueError(
            f"{v} is valid uid, but of version {u.version}. Fails UuidCanonicalTextual"
        )
    return str(u)


# --- annotated types ---
LeftRightDot = Annotated[
    str,
    BeforeValidator(is_left_right_dot),
]

UUID4Str = Annotated[
    str,
    BeforeValidator(is_uuid4_str),
]
