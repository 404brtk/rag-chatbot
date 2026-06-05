import re
from dataclasses import dataclass


_ATTACHMENT_PATTERN = re.compile(
    r'=== Attachment:\s*name="([^"]*)"\s*size=(\d+)\s*mime="([^"]*)"\s*===\n([\s\S]*?)\n=== End Attachment ==='
)


@dataclass
class Attachment:
    name: str
    size: int
    mime: str
    content: str


@dataclass
class ContentSegment:
    text: str | None = None
    attachment: Attachment | None = None


def parse_content(content: str) -> list[ContentSegment]:
    segments: list[ContentSegment] = []
    last_idx = 0

    for match in _ATTACHMENT_PATTERN.finditer(content):
        start, end = match.span()
        text_before = content[last_idx:start]
        if text_before:
            segments.append(ContentSegment(text=text_before))

        name, size_str, mime, file_content = match.groups()
        segments.append(
            ContentSegment(
                attachment=Attachment(
                    name=name,
                    size=int(size_str),
                    mime=mime,
                    content=file_content,
                )
            )
        )

        last_idx = end

    text_remaining = content[last_idx:]
    if text_remaining:
        segments.append(ContentSegment(text=text_remaining))

    if not segments:
        segments.append(ContentSegment(text=content))

    return segments
