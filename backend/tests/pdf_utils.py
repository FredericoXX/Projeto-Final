"""Gerador de PDFs mínimos e determinísticos para os testes.

Constrói à mão um PDF válido (catálogo, páginas, content streams e a
tabela xref com offsets corretos), com uma página por cada texto
recebido. Evita adicionar uma dependência pesada só para gerar PDFs de
teste; o pypdf usado pela aplicação consegue extrair o texto destas
páginas. Uma string vazia produz uma página sem texto extraível.
"""


def build_pdf(page_texts: list[str]) -> bytes:
    page_count = len(page_texts)
    font_object_number = 3 + 2 * page_count

    objects: list[bytes] = []
    kids = " ".join(f"{3 + index} 0 R" for index in range(page_count))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode())

    for index in range(page_count):
        content_ref = 3 + page_count + index
        objects.append(
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {font_object_number} 0 R >> >> "
                f"/Contents {content_ref} 0 R >>"
            ).encode()
        )

    for text in page_texts:
        if text:
            escaped = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
            stream = f"BT /F1 24 Tf 72 720 Td ({escaped}) Tj ET".encode()
        else:
            stream = b""
        objects.append(
            b"<< /Length "
            + str(len(stream)).encode()
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )

    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    output = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_position = len(output)
    total_entries = len(objects) + 1
    output += f"xref\n0 {total_entries}\n".encode()
    output += b"0000000000 65535 f \n"
    for offset in offsets:
        output += f"{offset:010d} 00000 n \n".encode()
    output += (
        f"trailer\n<< /Size {total_entries} /Root 1 0 R >>\n"
        f"startxref\n{xref_position}\n%%EOF\n"
    ).encode()
    return bytes(output)
