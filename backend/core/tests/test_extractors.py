from unittest.mock import patch

import pytest

from core.extractors import extract_text, is_supported_document


class TestExtractors:
    def test_extracts_plain_text_bytes(self):
        raw = "Hello world".encode("utf-8")
        assert extract_text(raw, content_type="text/plain") == "Hello world"

    def test_extracts_plain_text_file_path(self, tmp_path):
        file_path = tmp_path / "sample.txt"
        file_path.write_text("Hello file world", encoding="utf-8")
        assert extract_text(str(file_path), filename="sample.txt") == "Hello file world"

    def test_extracts_markdown(self):
        raw = "# Title\n\nBody text".encode("utf-8")
        result = extract_text(raw, content_type="text/markdown")
        assert "Title" in result
        assert "Body text" in result

    def test_extracts_utf8_with_special_chars(self):
        raw = "Café résumé naïve 🌍".encode("utf-8")
        assert extract_text(raw, content_type="text/plain") == "Café résumé naïve 🌍"

    def test_rejects_unsupported_type(self):
        with pytest.raises(ValueError, match="Unsupported document format"):
            extract_text(
                b"data",
                content_type="application/octet-stream",
                filename="file.unknown",
            )

    @patch("core.extractors.extract_pdf_to_markdown", return_value="PDF text content")
    def test_extracts_pdf(self, mock_extract):
        assert (
            extract_text(b"fake pdf bytes", content_type="application/pdf")
            == "PDF text content"
        )
        mock_extract.assert_called_once_with(b"fake pdf bytes")

    @patch("anydoc.to_markdown", return_value="# Word Doc Title\n\nWord content.")
    def test_extracts_docx_path(self, mock_anydoc, tmp_path):
        file_path = tmp_path / "document.docx"
        file_path.write_bytes(b"dummy docx bytes")
        result = extract_text(str(file_path), filename="document.docx")
        assert result == "# Word Doc Title\n\nWord content."
        mock_anydoc.assert_called_once_with(str(file_path))

    @patch("anydoc.to_markdown_bytes", return_value="# Slide 1\n\nPowerPoint content.")
    def test_extracts_pptx_bytes(self, mock_anydoc_bytes):
        raw_pptx = b"dummy pptx bytes"
        result = extract_text(raw_pptx, filename="presentation.pptx")
        assert result == "# Slide 1\n\nPowerPoint content."
        mock_anydoc_bytes.assert_called_once_with(raw_pptx)

    @patch(
        "anydoc.to_markdown_bytes",
        return_value="| Col A | Col B |\n|---|---|\n| 1 | 2 |",
    )
    def test_extracts_csv_bytes(self, mock_anydoc_bytes):
        raw_csv = b"Col A,Col B\n1,2"
        result = extract_text(raw_csv, content_type="text/csv", filename="data.csv")
        assert "| Col A | Col B |" in result
        mock_anydoc_bytes.assert_called_once_with(raw_csv, "csv")

    def test_is_supported_document(self):
        assert is_supported_document(filename="test.docx")
        assert is_supported_document(filename="test.pptx")
        assert is_supported_document(filename="test.xlsx")
        assert is_supported_document(filename="test.pdf")
        assert is_supported_document(filename="test.md")
        assert not is_supported_document(filename="test.exe")
