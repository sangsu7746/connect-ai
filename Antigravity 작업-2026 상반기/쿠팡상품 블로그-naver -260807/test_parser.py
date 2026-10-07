import os
import sys

from html.parser import HTMLParser

_TAG_FORMAT = {
    "h1": (True,  "20", "#111111", 1, 1),
    "p":  (False, "14", None,      0, 1),
}

class _HtmlSegmentParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.segments = []
        self._block_stack = []
        self._inline_stack = []
        self._buf = []
        self._skip_depth = 0

    def _flush(self, nl_before=0, nl_after=0, seg_type="normal"):
        text = "".join(self._buf).strip()
        self._buf = []
        if not text:
            return
        bold, size, color = False, "14", None
        if self._inline_stack:
            _, bold, size, color = self._inline_stack[-1]
        elif self._block_stack:
            _, bold, size, color, _, _ = self._block_stack[-1]

        self.segments.append({
            "text": text,
            "type": seg_type,
            "bold": bold,
            "size": size,
            "color": color,
            "newline_before": nl_before,
            "newline_after": nl_after,
        })

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self._skip_depth += 1
            return
        if self._skip_depth > 0: return
        if tag in _TAG_FORMAT:
            self._flush()
            bold, size, color, nl_b, nl_a = _TAG_FORMAT[tag]
            self._block_stack.append((tag, bold, size, color, nl_b, nl_a))

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self._skip_depth -= 1
            return
        if self._skip_depth > 0: return
        if tag in _TAG_FORMAT:
            nl_b, nl_a = 0, 1
            if self._block_stack and self._block_stack[-1][0] == tag:
                _, _, _, _, nl_b, nl_a = self._block_stack[-1]
                self._block_stack.pop()
            self._flush(nl_before=nl_b, nl_after=nl_a)

    def handle_data(self, data):
        if self._skip_depth > 0: return
        self._buf.append(data)

    def result(self):
        self._flush()
        return [s for s in self.segments if s["text"].strip()]

p = _HtmlSegmentParser()
p.feed("<h1>Hello</h1><p>World</p>")
print("Segments:", p.result())
