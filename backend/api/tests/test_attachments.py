from api.attachments import parse_content


def test_parse_content_text_only():
    content = "Hello, world! How are you?"
    segments = parse_content(content)
    assert len(segments) == 1
    assert segments[0].text == content
    assert segments[0].attachment is None


def test_parse_content_single_image():
    content = '=== Attachment: name="avatar.png" size=1024 mime="image/png" ===\ndata:image/png;base64,abcdefg\n=== End Attachment ==='
    segments = parse_content(content)
    assert len(segments) == 1
    assert segments[0].text is None
    assert segments[0].attachment is not None

    att = segments[0].attachment
    assert att.name == "avatar.png"
    assert att.size == 1024
    assert att.mime == "image/png"
    assert att.content == "data:image/png;base64,abcdefg"


def test_parse_content_mixed():
    content = (
        "Check this out:\n\n"
        '=== Attachment: name="code.py" size=45 mime="text/x-python" ===\nprint("hello")\n=== End Attachment ===\n\n'
        "and this screenshot:\n\n"
        '=== Attachment: name="screenshot.jpg" size=1200 mime="image/jpeg" ===\ndata:image/jpeg;base64,xyz\n=== End Attachment ===\n\n'
        "Let me know what you think."
    )
    segments = parse_content(content)

    assert len(segments) == 5
    assert segments[0].text == "Check this out:\n\n"
    assert segments[1].attachment is not None
    assert segments[1].attachment.name == "code.py"
    assert segments[2].text == "\n\nand this screenshot:\n\n"
    assert segments[3].attachment is not None
    assert segments[3].attachment.name == "screenshot.jpg"
    assert segments[4].text == "\n\nLet me know what you think."
