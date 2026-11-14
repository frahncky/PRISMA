"""Baixa e instala o modelo Vosk de português (~31 MB) usado pelo painel touch.

Uso:
    python scripts/baixar_modelo_voz.py            # instala em ~/.prisma/modelos
    python scripts/baixar_modelo_voz.py --destino D:/modelos

Depois, se usou --destino, aponte a variável PRISMA_VOSK_MODEL para a pasta do modelo.
"""
import argparse
from pathlib import Path
import shutil
import sys
import tempfile
import urllib.request
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from prisma.core.speech import MODEL_NAME, MODEL_URL, default_model_dir, model_present  # noqa: E402


def extract(archive: Path, target_parent: Path) -> Path:
    target_parent = target_parent.resolve()
    with zipfile.ZipFile(archive) as zf:
        for member in zf.namelist():
            destination = (target_parent / member).resolve()
            if target_parent not in destination.parents and destination != target_parent:
                raise ValueError(f"Caminho inválido no arquivo: {member}")
        zf.extractall(target_parent)
    return target_parent / MODEL_NAME


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--destino", type=Path, help="pasta onde criar o modelo (padrão: ~/.prisma/modelos)")
    args = parser.parse_args()
    parent = args.destino or default_model_dir().parent
    final = parent / MODEL_NAME
    if model_present(final):
        print(f"Modelo já instalado em {final}")
        return
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / f"{MODEL_NAME}.zip"
        print(f"Baixando {MODEL_URL} …")
        with urllib.request.urlopen(MODEL_URL, timeout=60) as response, archive.open("wb") as out:
            shutil.copyfileobj(response, out)
        print(f"{archive.stat().st_size / 1e6:.1f} MB baixados; extraindo …")
        path = extract(archive, parent)
    print(f"Modelo instalado em {path}")
    if args.destino:
        print(f"Defina PRISMA_VOSK_MODEL={path}")


if __name__ == "__main__":
    main()
