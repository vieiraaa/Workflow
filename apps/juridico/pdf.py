"""Texto de PDF no servidor com biblioteca pura Python (pypdf), sem binário nativo (Windows ok)."""

import io
import logging

logger = logging.getLogger(__name__)
MAX_PAGINAS = 3000


class ErroPdf(Exception):
    """Não foi possível abrir/ler o PDF (corrompido, com senha...)."""


def extrair_texto(conteudo):
    from pypdf import PdfReader

    try:
        leitor = PdfReader(io.BytesIO(conteudo), strict=False)
        if leitor.is_encrypted and not leitor.decrypt(""):
            raise ErroPdf("PDF protegido por senha.")
        partes = []
        for indice, pagina in enumerate(leitor.pages):
            if indice >= MAX_PAGINAS:
                break
            try:
                partes.append(pagina.extract_text() or "")
            except Exception:  # noqa: BLE001 - página ruim não derruba o PDF inteiro
                partes.append("")
        return "\n".join(partes)
    except ErroPdf:
        raise
    except Exception:  # noqa: BLE001 - pypdf levanta tipos variados em arquivo corrompido
        logger.warning("Falha ao ler PDF do cadastro")
        raise ErroPdf("Não foi possível ler o PDF.") from None
