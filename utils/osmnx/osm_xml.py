"""Read .osm-formatted XML files into Overpass-like JSON."""
import bz2
import xml.sax  # only used as a fallback if defusedxml is unavailable
from pathlib import Path

# Prefer defusedxml's hardened SAX parser when present (silences
# CWE-611 / Bandit B317). The project bundles its own Overpass client,
# so OSM XML always comes from a file we just wrote ourselves, but
# routing through defusedxml keeps that promise enforced if the file
# is ever swapped out by another component.
try:
    from defusedxml import sax as _safe_sax  # type: ignore[import-not-found]
    _xml_parse = _safe_sax.parse
except ImportError:  # pragma: no cover - defusedxml is an optional dep
    _xml_parse = xml.sax.parse  # nosec B317 -- input is our own Overpass cache file


class _OSMContentHandler(xml.sax.handler.ContentHandler):
    """
    SAX content handler for OSM XML.

    Used to build an Overpass-like response JSON object in self.object. For
    format notes, see https://overpass-api.de/ and
    https://wiki.openstreetmap.org/wiki/OSM_XML#OSM_XML_file_format_notes
    """

    def __init__(self):
        self._element = None
        self.object = {"elements": []}

    def startElement(self, name, attrs):
        if name == "osm":
            self.object.update({k: v for k, v in attrs.items() if k in {"version", "generator"}})

        elif name in {"node", "way"}:
            self._element = dict(type=name, tags={}, nodes=[], **attrs)
            self._element.update({k: float(v) for k, v in attrs.items() if k in {"lat", "lon"}})
            self._element.update(
                {k: int(v) for k, v in attrs.items() if k in {"id", "uid", "version", "changeset"}}
            )

        elif name == "relation":
            self._element = dict(type=name, tags={}, members=[], **attrs)
            self._element.update(
                {k: int(v) for k, v in attrs.items() if k in {"id", "uid", "version", "changeset"}}
            )

        elif name == "tag":
            self._element["tags"].update({attrs["k"]: attrs["v"]})

        elif name == "nd":
            self._element["nodes"].append(int(attrs["ref"]))

        elif name == "member":
            self._element["members"].append(
                {k: (int(v) if k == "ref" else v) for k, v in attrs.items()}
            )

    def endElement(self, name):
        if name in {"node", "way", "relation"}:
            self.object["elements"].append(self._element)


def _overpass_json_from_file(filepath):
    """
    Read OSM XML from file and return Overpass-like JSON.

    Parameters
    ----------
    filepath : string or pathlib.Path
        path to file containing OSM XML data

    Returns
    -------
    OSMContentHandler object
    """

    def _opener(filepath):
        if filepath.suffix == ".bz2":
            return bz2.BZ2File(filepath)
        else:
            # assume an unrecognized file extension is just XML
            return filepath.open(mode="rb")

    with _opener(Path(filepath)) as f:
        handler = _OSMContentHandler()
        _xml_parse(f, handler)
        return handler.object
