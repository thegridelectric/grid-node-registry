import uuid
import re
from datetime import UTC, datetime
from typing import Annotated

from pydantic import BeforeValidator

_LEFT_RIGHT_DOT_PATTERN = re.compile(
    r"^[a-z][a-z0-9]*(?:\.[a-z0-9]+)*$"
)

_SPACEHEAT_NAME_PATTERN = re.compile(
    r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$"
)


_HANDLE_PATTERN = re.compile(
    r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*(?:\.[a-z][a-z0-9]*(?:-[a-z0-9]+)*)*$"
)



def is_utc_milliseconds(v: int) -> int:
    """
    UTCMilliseconds format: unix milliseconds between Jan 1 2000 and Jan 1 3000
    """
    if not isinstance(v, int):
        raise TypeError("Not an int!")
    start_date = datetime(2000, 1, 1, tzinfo=UTC)
    end_date = datetime(3000, 1, 1, tzinfo=UTC)

    start_timestamp_ms = int(start_date.timestamp() * 1000)
    end_timestamp_ms = int(end_date.timestamp() * 1000)

    if v < start_timestamp_ms:
        raise ValueError(f"{v} must be after Jan 1 2000")
    if v > end_timestamp_ms:
        raise ValueError(f"{v} must be before Jan 1 3000")
    return v


def is_utc_seconds(v: int) -> int:
    """
    UTCSeconds format: unix seconds between Jan 1 2000 and Jan 1 3000
    """
    if not isinstance(v, int):
        raise ValueError("Not an int!")
    start_date = datetime(2000, 1, 1, tzinfo=UTC)
    end_date = datetime(3000, 1, 1, tzinfo=UTC)

    start_timestamp = int(start_date.timestamp())
    end_timestamp = int(end_date.timestamp())

    if v < start_timestamp:
        raise ValueError(f"{v}: Fails UTCSeconds format! Must be after Jan 1 2000")
    if v > end_timestamp:
        raise ValueError(f"{v}: Fails UTCSeconds format! Must be before Jan 1 3000")
    return v


def is_handle_name(v: str) -> str:
    """
    HandleName format:
    Dot-separated hierarchical identifier composed of lowercase
    alphanumeric segments with optional internal hyphen-separated words.

    Rules:
      - Each segment must start with a lowercase letter
      - Hyphens may appear only between alphanumeric characters
      - No trailing or leading hyphens in any segment
      - No empty segments
      - Entire string must be lowercase
    """
    if not isinstance(v, str):
        raise ValueError(f"<{v}>: HandleName must be a string.")

    if not _HANDLE_PATTERN.fullmatch(v):
        raise ValueError(f"<{v}>: Fails HandleName format.")

    return v


def is_left_right_dot(v: str) -> str:
    """
    Validate the LeftRightDot format.

    Rules:
      - Must be a string
      - Dot-separated segments
      - First segment must start with a lowercase letter
      - All segments must be lowercase alphanumeric
      - No empty segments
      - No leading or trailing dots
      - No hyphens or underscores
    """
    if not isinstance(v, str):
        raise ValueError(f"<{v}>: LeftRightDot must be a string.")

    if not _LEFT_RIGHT_DOT_PATTERN.fullmatch(v):
        raise ValueError(f"<{v}>: Fails LeftRightDot format.")

    return v


def is_spaceheat_name(v: str) -> str:
    """
    Validate the SpaceheatName format.

    Rules:
      - Must be a string
      - Single segment (no dots)
      - Must start with a lowercase alphabetic character
      - May contain lowercase alphanumeric characters
      - Hyphens allowed only between alphanumeric characters
      - No leading or trailing hyphens
      - No consecutive hyphens
      - Entire string must be lowercase
      - Maximum length 64 characters
    """
    if not isinstance(v, str):
        raise ValueError(f"<{v}>: SpaceheatName must be a string.")
    
    if len(v) > 64:
        raise ValueError(f"<{v}>: SpaceheatName exceeds maximum length of 64.")

    if not _SPACEHEAT_NAME_PATTERN.fullmatch(v):
        raise ValueError(f"<{v}>: Fails SpaceheatName format.")

    return v


def is_uuid4_str(v: str) -> str:
    """
    UuidCanonicalTextual format:  A string of hex words separated by hyphens
    of length 8-4-4-4-12.
    """
    v = str(v)
    try:
        u = uuid.UUID(v)
    except Exception as e:
        raise ValueError(f"Invalid UUID4: {v}  <{e}>") from e
    if u.version != 4:
        raise ValueError(
            f"{v} is valid uid, but of version {u.version}. Fails UuidCanonicalTextual"
        )
    return str(u)


HandleName = Annotated[str, BeforeValidator(is_handle_name)]
LeftRightDot = Annotated[str, BeforeValidator(is_left_right_dot)]
SpaceheatName = Annotated[str, BeforeValidator(is_spaceheat_name)]
UTCMilliseconds = Annotated[int, BeforeValidator(is_utc_milliseconds)]
UTCSeconds = Annotated[int, BeforeValidator(is_utc_seconds)]
UUID4Str = Annotated[str, BeforeValidator(is_uuid4_str)]
