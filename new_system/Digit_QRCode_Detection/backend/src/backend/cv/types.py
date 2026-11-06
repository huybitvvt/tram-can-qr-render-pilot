"""Small CV outputs independent of HTTP serialization."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    width: float
    height: float

    def as_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}


@dataclass(frozen=True)
class Digit:
    value: int | str
    confidence: float
    box: Box
    class_id: int | None = None


@dataclass(frozen=True)
class QrResult:
    data: str
    box: Box
