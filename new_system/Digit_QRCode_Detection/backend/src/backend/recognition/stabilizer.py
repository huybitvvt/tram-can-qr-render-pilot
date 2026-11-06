"""Require consecutive matching readings before allowing save."""

class Stabilizer:
    def __init__(self, required_frames: int) -> None:
        self.required_frames = required_frames
        self.previous: tuple[str, str] | None = None
        self.count = 0

    def update(self, key: tuple[str, str] | None) -> bool:
        if key is None:
            self.previous = None
            self.count = 0
            return False
        self.count = self.count + 1 if key == self.previous else 1
        self.previous = key
        return self.count >= self.required_frames
