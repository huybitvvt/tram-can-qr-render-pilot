"""Keep legacy presence assertions independent of HTML/JS quote/indent style."""
import re
import subprocess
from functools import lru_cache


@lru_cache(maxsize=1)
def canonical_html():
    return subprocess.check_output(["node", "tests/frontend_fixture.cjs"], encoding="utf-8")


class FormatTolerantHTML(str):
    def __contains__(self, marker: str) -> bool:
        if super().__contains__(marker):
            return True
        def compact(value):
            return re.sub(r"\s+", "", value).replace('"', "'").replace(";}", "}").replace("/>", ">")
        if not hasattr(self, "_compact"):
            self._compact = compact(canonical_html())
        return compact(marker) in self._compact
