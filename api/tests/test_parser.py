import base64
import unittest

from app.services.parser import parse_pdf_base64


class ParsePdfTests(unittest.TestCase):
    def test_non_pdf_bytes_return_empty_instead_of_raising(self):
        payload = base64.b64encode(b"PK\x03\x04not-a-pdf-spreadsheet").decode()
        self.assertEqual(parse_pdf_base64(payload), [])
