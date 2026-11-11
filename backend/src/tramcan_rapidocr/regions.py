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
    """Read the lit row at a consistent scale without reconstructing digits.

    Dark panel margins change the recognizer's digit scale, particularly for
    a narrow leading 7. CLAHE on the green channel can also amplify its halo
    into a false 2. Keep the camera pixels and use ordinary grayscale as the
    second view instead of enhancing individual segments.
    """
    if crop.size == 0:
        return []
    blue,green,red = cv2.split(crop)
    threshold,_ = cv2.threshold(red,0,255,cv2.THRESH_BINARY|cv2.THRESH_OTSU)
    # Locate red pixels, including decimal points and minus signs. Exposure
    # and white balance can leave a lit red digit with little or no green.
    # Thresholding green against brighter digits then crops away that digit.
    # Signed arithmetic prevents uint8 wraparound from admitting blue pixels.
    lit = ((red >= threshold)
           & (red.astype(np.int16)-green > 10)
           & (red.astype(np.int16)-blue > 15))
    ys,xs = np.nonzero(lit)
    if len(xs):
        x1,y1,x2,y2 = int(xs.min()),int(ys.min()),int(xs.max())+1,int(ys.max())+1
        padx,pady = max(1,round((x2-x1)*.10)),max(1,round((y2-y1)*.10))
        row = crop[max(0,y1-pady):min(crop.shape[0],y2+pady),
                   max(0,x1-padx):min(crop.shape[1],x2+padx)]
        name = 'red-row'
    else:
        row,name = crop,'original'
    gray = cv2.cvtColor(cv2.cvtColor(row,cv2.COLOR_BGR2GRAY),cv2.COLOR_GRAY2BGR)
    return [(name,row),('gray',gray)]
