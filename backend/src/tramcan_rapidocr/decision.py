"""Select complete readings without deleting detections or inventing digits."""

from dataclasses import asdict, dataclass
from decimal import Decimal

from .parsing import parse_weight


@dataclass(frozen=True)
class Observation:
    text: str
    confidence: float
    variant: str
    region: tuple[int,int,int,int] | None = None


@dataclass
class Reading:
    value: Decimal | None
    reason: str
    observations: list[Observation]
    elapsed_ms: float = 0

    def as_dict(self) -> dict:
        return {'weight':str(self.value) if self.value is not None else None,
                'reason':self.reason,'elapsed_ms':self.elapsed_ms,
                'observations':[asdict(o) for o in self.observations]}


def decide(observations: list[Observation], *, min_confidence: float = .85, fixed_digits: bool = False) -> Reading:
    values = {value for o in observations if o.confidence >= min_confidence
              and (value:=parse_weight(o.text,fixed_digits=fixed_digits)) is not None}
    # A moderately confident original crop must be allowed to veto a
    # confidently wrong enhanced crop. Confidence alone cannot settle a tie.
    plausible = {value for o in observations if o.confidence >= min(.70,min_confidence)
                 and (value:=parse_weight(o.text,fixed_digits=fixed_digits)) is not None}
    if len(plausible)>1:
        return Reading(None,'conflicting-readings',observations)
    if not values:
        return Reading(None,'no-complete-confident-reading',observations)
    return Reading(next(iter(values)),'complete-reading',observations)
