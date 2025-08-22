# Nombre de archivo: test_comparador_fo_runner.py
# Ubicación de archivo: tests/test_comparador_fo_runner.py
# Descripción: Pruebas para la función run del comparador de trazas FO

from modules.comparador_fo import run


def test_run_detecta_trazas_iguales(tmp_path):
    archivo_a = tmp_path / "traza_a.txt"
    archivo_b = tmp_path / "traza_b.txt"
    contenido = b"traza ejemplo"
    archivo_a.write_bytes(contenido)
    archivo_b.write_bytes(contenido)

    resultado = run(str(archivo_a), str(archivo_b))

    assert resultado["iguales"] is True
    assert resultado["hash_a"] == resultado["hash_b"]


def test_run_detecta_trazas_distintas(tmp_path):
    archivo_a = tmp_path / "traza_a.txt"
    archivo_b = tmp_path / "traza_b.txt"
    archivo_a.write_bytes(b"traza 1")
    archivo_b.write_bytes(b"traza 2")

    resultado = run(str(archivo_a), str(archivo_b))

    assert resultado["iguales"] is False
    assert resultado["hash_a"] != resultado["hash_b"]
