import io
import re
import pymupdf
from app.config import get_settings

settings = get_settings()

PT_PER_MM = 72.0 / 25.4

CHAVE_RE = re.compile(r"\b\d{44}\b")
NF_RE = re.compile(r"NF\s*[:#]?\s*(\d[\d.,]*)", re.IGNORECASE)
PACK_RE = re.compile(r"Pack ID\s*[:#]?\s*(\d+)", re.IGNORECASE)
WARN_LOW_SCALE = 0.6

PAGE_SIZES = {
    "100x150": {"width_mm": 100.0, "height_mm": 150.0},
    "auto": {"width_mm": 0, "height_mm": 0},
    "a4": {"width_mm": 210.0, "height_mm": 297.0},
}
DEFAULT_PAGE_SIZE = "100x150"


class PdfProcessError(Exception):
    pass


def _is_danfe_page(page) -> bool:
    text = page.get_text("text").lower()
    return "danfe" in text or "chave de acesso" in text


def _barcode_crop_rect(page):
    best = None
    for img in page.get_images(full=True):
        for r in page.get_image_rects(img[0]):
            if best is None or r.width > best.width:
                best = r
    if best is None:
        return None
    bottom = best.y1 + 15.0
    if bottom >= page.rect.height - 20.0:
        return None
    return pymupdf.Rect(0, 0, page.rect.width, bottom)


def _qr_image_info(page):
    """Imagem quase quadrada (QR code) de maior area na pagina."""
    infos = []
    for info in page.get_image_info(xrefs=True):
        bbox = info.get("bbox") or (0, 0, 0, 0)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        if w <= 0 or h <= 0:
            continue
        aspect = w / h
        if 0.7 <= aspect <= 1.45:
            infos.append(info)
    if not infos:
        return None
    infos.sort(
        key=lambda i: (i["bbox"][2] - i["bbox"][0]) * (i["bbox"][3] - i["bbox"][1]),
        reverse=True,
    )
    return infos[0]


def _redraw_qr_square(page, src, pno, info, target, scale_x, scale_y, clip):
    """Redesenha a imagem do QR no tamanho correto (quadrado), sem esticar."""
    bx0, by0, bx1, by1 = info["bbox"]
    xref = info["xref"]
    ox = target.x0
    oy = target.y0

    out_x0 = ox + (bx0 - clip.x0) * scale_x
    out_x1 = ox + (bx1 - clip.x0) * scale_x
    out_y0 = oy + (by0 - clip.y0) * scale_y
    out_y1 = oy + (by1 - clip.y0) * scale_y
    w_out = out_x1 - out_x0
    h_out = out_y1 - out_y0
    if w_out <= 0 or h_out <= 0:
        return

    cover = pymupdf.Rect(out_x0, out_y0, out_x1, out_y1)
    page.draw_rect(cover, color=None, fill=(1, 1, 1))

    side = min(w_out, h_out)
    cx = (out_x0 + out_x1) / 2.0
    cy = (out_y0 + out_y1) / 2.0
    square = pymupdf.Rect(cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2)

    try:
        imgdata = src.extract_image(xref)
        if imgdata:
            page.insert_image(square, stream=imgdata["image"], keep_proportion=True)
    except Exception:
        pass


def _page_spec(src, page_no, compact_danfe):
    p = src[page_no]
    rect = p.rect
    clip = rect
    if compact_danfe and page_no % 2 == 1 and _is_danfe_page(p):
        c = _barcode_crop_rect(p)
        if c is not None:
            clip = c
    return (page_no, rect, clip)


def _compose(data: bytes, width_mm=0, height_mm=0, compact_danfe=True):
    """Igual ao composer.py do desktop, mas trabalha com bytes."""
    src = pymupdf.open("pdf", data)
    out_buffer = io.BytesIO()
    try:
        page_count = src.page_count
        if page_count == 0:
            raise PdfProcessError("O PDF está vazio (não possui páginas).")

        used = page_count
        groups = [list(range(i, min(i + 2, used))) for i in range(0, used, 2)]
        if not groups:
            raise PdfProcessError("O PDF não possui páginas para processar.")

        out = pymupdf.open()
        scales = []
        for group in groups:
            specs = [_page_spec(src, pno, compact_danfe) for pno in group]

            max_w = max(r.width for _, r, _ in specs)
            total_h = sum(c.height for _, _, c in specs)

            auto = width_mm <= 0 or height_mm <= 0
            if auto:
                out_w = max_w
                out_h = max(total_h, 1.0)
                scale_x = 1.0
                scale_y = 1.0
            else:
                out_w = width_mm * PT_PER_MM
                out_h = height_mm * PT_PER_MM
                scale_x = out_w / max_w
                scale_y = out_h / total_h

            page = out.new_page(width=out_w, height=out_h)

            y = 0.0
            for pno, rect, clip in specs:
                w = rect.width * scale_x
                h = clip.height * scale_y
                x0 = (out_w - w) / 2.0
                target = pymupdf.Rect(x0, y, x0 + w, y + h)
                page.show_pdf_page(
                    target,
                    src,
                    pno,
                    clip=clip,
                    keep_proportion=False,
                )

                if abs(scale_x - scale_y) > 0.02:
                    qr = _qr_image_info(src[pno])
                    if qr is not None:
                        _redraw_qr_square(page, src, pno, qr, target, scale_x, scale_y, clip)

                y += h
            scales.append(min(scale_x, scale_y))

        out.set_metadata(
            {
                "title": "UniDANFE - PDF processado",
                "producer": "UniDANFE SaaS",
                "creator": "UniDANFE",
            }
        )
        out.save(out_buffer, garbage=3, deflate=True)
        return used, len(groups), min(scales), out_buffer.getvalue()
    finally:
        src.close()


def _extract_page_text(doc, page_no) -> str:
    return doc[page_no].get_text("text")


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _check_token(full_text, token) -> bool:
    return _normalize(token).lower() in _normalize(full_text).lower()


def _check_pair(src_text, out_text, pair_index) -> list:
    warnings = []
    for chave in set(CHAVE_RE.findall(src_text)):
        if chave not in out_text:
            warnings.append(
                f"Chave de acesso ausente no PDF gerado (pedido {pair_index + 1}): {chave}"
            )
    for nf in set(NF_RE.findall(src_text)):
        if not _check_token(out_text, nf):
            warnings.append(f"NF ausente no PDF gerado (pedido {pair_index + 1}): {nf}")
    for pack in set(PACK_RE.findall(src_text)):
        if pack not in out_text:
            warnings.append(f"Pack ID ausente no PDF gerado (pedido {pair_index + 1}): {pack}")
    return warnings


def _compare_integrity(input_data: bytes, output_data: bytes, used_pages: int, output_pages: int) -> list:
    warnings = []
    try:
        src_doc = pymupdf.open("pdf", input_data)
        out_doc = pymupdf.open("pdf", output_data)
        try:
            n_pairs = min(output_pages, (used_pages + 1) // 2)
            for i in range(n_pairs):
                p0 = i * 2
                src_text = _extract_page_text(src_doc, p0) if p0 < src_doc.page_count else ""
                if p0 + 1 < used_pages and p0 + 1 < src_doc.page_count:
                    src_text += "\n" + _extract_page_text(src_doc, p0 + 1)
                out_text = _extract_page_text(out_doc, i)
                if not out_text.strip():
                    warnings.append(
                        "Não foi possível extrair texto de segurança da página "
                        f"{i + 1} do PDF gerado."
                    )
                    continue
                warnings.extend(_check_pair(src_text, out_text, i))
        finally:
            src_doc.close()
            out_doc.close()
    except Exception as exc:
        warnings.append(f"Falha ao validar integridade: {exc}")
    return warnings


def process_pdf(data: bytes, page_size: str = DEFAULT_PAGE_SIZE) -> dict:
    """Processa os bytes de um PDF e retorna dict com resultado + validações."""
    warnings = []
    try:
        doc = pymupdf.open("pdf", data)
        page_count = doc.page_count
        doc.close()
    except Exception:
        raise PdfProcessError("Arquivo inválido. Envie o PDF gerado pela plataforma de e-commerce.")

    if page_count == 0:
        raise PdfProcessError("O PDF está vazio (não possui páginas).")

    size = PAGE_SIZES.get(page_size, PAGE_SIZES[DEFAULT_PAGE_SIZE])

    try:
        used, output_pages, scale, output_data = _compose(
            data, size["width_mm"], size["height_mm"]
        )
    except PdfProcessError:
        raise
    except Exception as exc:
        raise PdfProcessError(f"Erro ao processar o PDF: {exc}")

    if page_count == 1:
        warnings.append(
            "O PDF possui apenas 1 página (não foi encontrada a página 2 com o DANFE "
            "Simplificado). O conteúdo disponível foi copiado sem alterações."
        )

    warnings.extend(_compare_integrity(data, output_data, used, output_pages))

    if scale < WARN_LOW_SCALE:
        warnings.append(
            f"Para caber na página escolhida, o conteúdo foi reduzido a "
            f"{scale * 100:.0f}% do tamanho original. "
            "Se houver dificuldade para ler o código de barras, imprima em A4."
        )

    return {
        "ok": True,
        "output_data": output_data,
        "pages_used": used,
        "pages_generated": output_pages,
        "scale": scale,
        "warnings": warnings,
    }