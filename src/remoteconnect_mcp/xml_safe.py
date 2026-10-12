"""Local XML readers with entity expansion and DTD loading disabled."""

from __future__ import annotations

from pathlib import Path

MAX_XML_BYTES = 128 * 1024 * 1024


def xml_parser():
    from lxml import etree

    return etree.XMLParser(
        resolve_entities=False, load_dtd=False, no_network=True,
        remove_comments=True, remove_pis=True,
    )


def parse_xml_bytes(data: bytes):
    from lxml import etree

    if len(data) > MAX_XML_BYTES:
        raise ValueError(f"XML input exceeds the {MAX_XML_BYTES}-byte inspection limit")
    root = etree.fromstring(data, parser=xml_parser())
    if root.getroottree().docinfo.doctype:
        raise ValueError("DTD declarations and XML entities are not permitted")
    return root


def parse_xml_file(path: str | Path):
    with Path(path).open("rb") as stream:
        return parse_xml_bytes(stream.read(MAX_XML_BYTES + 1))
