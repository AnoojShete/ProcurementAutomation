import json
import logging
from shared.logging.formatter import JSONFormatter

def test_log_redaction_email_action_path():
    raw_token = "secret-token-abc123xyz-999"
    logger = logging.getLogger("test_redaction_logger")
    formatter = JSONFormatter("test-service")

    record = logger.makeRecord(
        name="test_logger",
        level=logging.INFO,
        fn="test.py",
        lno=10,
        msg=f"Handling request to /email-action/{raw_token} for user",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    data = json.loads(output)
    
    assert raw_token not in output
    assert raw_token not in data["message"]
    assert "/email-action/[REDACTED]" in data["message"]

def test_log_redaction_token_query_param():
    raw_token = "secret-token-query-param-456"
    logger = logging.getLogger("test_redaction_logger")
    formatter = JSONFormatter("test-service")

    record = logger.makeRecord(
        name="test_logger",
        level=logging.INFO,
        fn="test.py",
        lno=20,
        msg=f"GET /verify-something?foo=bar&token={raw_token}&baz=qux",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    data = json.loads(output)

    assert raw_token not in output
    assert raw_token not in data["message"]
    assert "token=[REDACTED]" in data["message"]

def test_log_redaction_in_exception():
    raw_token = "token-in-exception-789"
    logger = logging.getLogger("test_redaction_logger")
    formatter = JSONFormatter("test-service")

    try:
        raise ValueError(f"Failed at /email-action/{raw_token}")
    except ValueError:
        import sys
        record = logger.makeRecord(
            name="test_logger",
            level=logging.ERROR,
            fn="test.py",
            lno=30,
            msg="Exception occurred",
            args=(),
            exc_info=sys.exc_info(),
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert raw_token not in output
        assert raw_token not in data["exception"]
        assert "/email-action/[REDACTED]" in data["exception"]
