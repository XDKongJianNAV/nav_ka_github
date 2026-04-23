from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
PAGE_DIR = ROOT / "reports" / "assets" / "ka225_receiver" / "docx_pages"
OUTPUT = ROOT / "reports" / "published" / "ka225_receiver" / "ka225_receiver_work_report.docx"

EMU_PER_INCH = 914400
TWIPS_PER_INCH = 1440
PAGE_WIDTH_TWIPS = 11906
PAGE_HEIGHT_TWIPS = 16838
MARGIN_TWIPS = 360
HEADER_FOOTER_TWIPS = 0
PPI = 220.0


def twips_to_emu(value: int) -> int:
    return int(value / TWIPS_PER_INCH * EMU_PER_INCH)


def image_size_emu(path: Path) -> tuple[int, int]:
    with Image.open(path) as img:
        width_px, height_px = img.size

    natural_width = width_px / PPI * EMU_PER_INCH
    natural_height = height_px / PPI * EMU_PER_INCH

    max_width = twips_to_emu(PAGE_WIDTH_TWIPS - 2 * MARGIN_TWIPS)
    max_height = twips_to_emu(PAGE_HEIGHT_TWIPS - 2 * MARGIN_TWIPS)

    scale = min(max_width / natural_width, max_height / natural_height)
    return int(natural_width * scale), int(natural_height * scale)


def build_document_xml(images: list[Path]) -> str:
    paragraphs: list[str] = []

    for index, image in enumerate(images, start=1):
        cx, cy = image_size_emu(image)
        rel_id = f"rId{index}"
        name = escape(image.name)

        paragraphs.append(
            f"""
      <w:p>
        <w:r>
          <w:drawing>
            <wp:inline distT="0" distB="0" distL="0" distR="0">
              <wp:extent cx="{cx}" cy="{cy}"/>
              <wp:docPr id="{index}" name="Page {index}"/>
              <a:graphic>
                <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
                  <pic:pic>
                    <pic:nvPicPr>
                      <pic:cNvPr id="{index}" name="{name}"/>
                      <pic:cNvPicPr/>
                    </pic:nvPicPr>
                    <pic:blipFill>
                      <a:blip r:embed="{rel_id}"/>
                      <a:stretch><a:fillRect/></a:stretch>
                    </pic:blipFill>
                    <pic:spPr>
                      <a:xfrm>
                        <a:off x="0" y="0"/>
                        <a:ext cx="{cx}" cy="{cy}"/>
                      </a:xfrm>
                      <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
                    </pic:spPr>
                  </pic:pic>
                </a:graphicData>
              </a:graphic>
            </wp:inline>
          </w:drawing>
        </w:r>
      </w:p>
"""
        )

        if index != len(images):
            paragraphs.append(
                """
      <w:p>
        <w:r>
          <w:br w:type="page"/>
        </w:r>
      </w:p>
"""
            )

    body = "".join(paragraphs)
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document
  xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
  xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
  xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
  xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
  <w:body>{body}
    <w:sectPr>
      <w:pgSz w="{PAGE_WIDTH_TWIPS}" h="{PAGE_HEIGHT_TWIPS}"/>
      <w:pgMar
        top="{MARGIN_TWIPS}"
        right="{MARGIN_TWIPS}"
        bottom="{MARGIN_TWIPS}"
        left="{MARGIN_TWIPS}"
        header="{HEADER_FOOTER_TWIPS}"
        footer="{HEADER_FOOTER_TWIPS}"
        gutter="0"/>
    </w:sectPr>
  </w:body>
</w:document>
"""


def build_document_rels(images: list[Path]) -> str:
    rels = []
    for index, image in enumerate(images, start=1):
        rels.append(
            f'<Relationship Id="rId{index}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
            f'Target="media/{escape(image.name)}"/>'
        )

    joined = "".join(rels)
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  {joined}
</Relationships>
"""


def build_root_rels() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
"""


def build_content_types() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>
"""


def build_core_xml() -> str:
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties
  xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
  xmlns:dc="http://purl.org/dc/elements/1.1/"
  xmlns:dcterms="http://purl.org/dc/terms/"
  xmlns:dcmitype="http://purl.org/dc/dcmitype/"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>Ka 22.5 GHz Receiver Report</dc:title>
  <dc:creator>nav_ka_github</dc:creator>
  <cp:lastModifiedBy>nav_ka_github</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{timestamp}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{timestamp}</dcterms:modified>
</cp:coreProperties>
"""


def build_app_xml(page_count: int) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties
  xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
  xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Typst page export</Application>
  <Pages>{page_count}</Pages>
  <Words>0</Words>
  <Characters>0</Characters>
</Properties>
"""


def main() -> None:
    images = sorted(PAGE_DIR.glob("page-*.png"))
    if not images:
        raise SystemExit(f"no rendered pages found in {PAGE_DIR}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    with ZipFile(OUTPUT, "w", compression=ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", build_content_types())
        zf.writestr("_rels/.rels", build_root_rels())
        zf.writestr("docProps/core.xml", build_core_xml())
        zf.writestr("docProps/app.xml", build_app_xml(len(images)))
        zf.writestr("word/document.xml", build_document_xml(images))
        zf.writestr("word/_rels/document.xml.rels", build_document_rels(images))

        for image in images:
            zf.write(image, f"word/media/{image.name}")

    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
