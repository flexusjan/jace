from io import StringIO
import re
import unittest

from jace.logs import log


class LogsTest(unittest.TestCase):
    def test_log_uses_postgres_style_timestamp(self):
        output = StringIO()

        log("hello", stream=output)

        self.assertRegex(
            output.getvalue(),
            re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} UTC \[\d+\] INFO: hello\n$"),
        )


if __name__ == "__main__":
    unittest.main()
