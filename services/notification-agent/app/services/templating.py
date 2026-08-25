"""Jinja2 email rendering.

Each template file under app/templates/*.j2 is a single Jinja2 template
whose *rendered* output is "Subject: ...\\n---\\n<body>". We render the
whole file once (so Jinja variables can appear in the subject line too,
e.g. "Subject: Approval needed: {{ request_type }} for {{ department }}"),
then split on the "\\n---\\n" separator to pull subject/body apart.
"""
import os
from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound, select_autoescape

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")

_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(disabled_extensions=("j2",), default=False),
    trim_blocks=True,
    lstrip_blocks=True,
    # Strict on purpose: a template referencing a field name that doesn't
    # actually exist in the event's documented payload (shared/schemas/
    # events.md) should fail loudly in tests, not silently render blank —
    # this is what makes tests/test_event_schemas.py a meaningful schema
    # guard for a consumer (contrast with the producer-side exact-keys
    # assertions in the reference services' test_event_schemas.py).
    undefined=StrictUndefined,
)


class TemplateRenderError(Exception):
    pass


def template_exists(template_name: str) -> bool:
    try:
        _env.get_template(f"{template_name}.j2")
        return True
    except TemplateNotFound:
        return False


def render_template(template_name: str, context: dict) -> tuple[str, str]:
    """Render `<template_name>.j2` with `context`, returning (subject, body).

    Raises TemplateRenderError if the template is missing the required
    "Subject: ...\\n---\\n" header, since a template that silently drops
    the subject would produce a blank-subject email in Mailpit.
    """
    template = _env.get_template(f"{template_name}.j2")
    rendered = template.render(**context)

    if "\n---\n" not in rendered:
        raise TemplateRenderError(
            f"template {template_name}.j2 did not render a 'Subject: ...\\n---\\n<body>' shape"
        )

    subject_line, _, body = rendered.partition("\n---\n")
    subject = subject_line.strip()
    if subject.lower().startswith("subject:"):
        subject = subject.split(":", 1)[1].strip()

    return subject, body.strip()
