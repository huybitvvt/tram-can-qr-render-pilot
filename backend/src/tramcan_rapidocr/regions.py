"""Locate illuminated red digit rows without knowing their numeric value."""

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class Region:
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def area(self) -> int:
        return (self.x2-self.x1)*(self.y2-self.y1)

    def crop(self, frame: np.ndarray) -> np.ndarray:
        return frame[self.y1:self.y2, self.x1:self.x2]


def red_display_regions(frame: np.ndarray, *, max_regions: int = 3) -> list[Region]:
    if frame is None or frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("Expected a BGR camera image")
    height,width = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0,80,100), (16,255,255)) | cv2.inRange(hsv, (164,80,100), (179,255,255))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(3,round(width*.013)), max(1,round(height*.003))))
    joined = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    contours,_ = cv2.findContours(joined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    rows = []
    for contour in contours:
        x,y,w,h = cv2.boundingRect(contour)
        if not (max(12,width*.012) <= w <= width*.40 and max(8,height*.008) <= h <= height*.15 and 1.3 <= w/h <= 10):
            continue
        density = cv2.countNonZero(mask[y:y+h,x:x+w])/(w*h)
        if not .025 <= density <= .80:
            continue
        padx,pady = max(4,round(w*.10)),max(4,round(h*.25))
        rows.append(Region(max(0,x-padx),max(0,y-pady),min(width,x+w+padx),min(height,y+h+pady)))
    # For aligned rows on one scale head, Gross is the upper row. A failed
    # Gross read must never fall through to a clearer tare/net zero.
    top = []
    for r in rows:
        rw,rh = r.x2-r.x1,r.y2-r.y1
        below = any(other != r and .5 <= (other.x2-other.x1)/rw <= 2
            and abs((other.x1+other.x2-r.x1-r.x2)/2) < rw*.35
            and rh*.35 < r.y1-other.y1 < rh*3.5 for other in rows)
        if not below:
            top.append(r)
    return sorted(top,key=lambda r:r.area,reverse=True)[:max_regions]


def recognition_variants(crop: np.ndarray) -> list[tuple[str,np.ndarray]]:
    """Use original pixels and a contrast-only view; do not reconstruct digits."""
    if crop.size == 0:
        return []
    green = cv2.createCLAHE(clipLimit=2,tileGridSize=(4,4)).apply(crop[:,:,1])
    gray = cv2.cvtColor(green,cv2.COLOR_GRAY2BGR)
    return [('original',crop),('green-clahe',gray)]
