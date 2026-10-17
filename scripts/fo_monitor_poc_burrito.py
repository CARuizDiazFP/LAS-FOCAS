# Nombre de archivo: fo_monitor_poc_burrito.py
# Ubicación de archivo: scripts/fo_monitor_poc_burrito.py
# Descripción: Fase 0 de FO Monitor — prueba real bot→bot contra burritoIA en Slack (latencia, hilo, bloque FOMON)

"""Prueba de concepto de FO Monitor contra burritoIA (sin DB).

Publica una consulta por escenario en el canal de prueba con el bot de LAS-FOCAS, lee el hilo con
`conversations.replies` cada `--poll` segundos y registra, por escenario:

- si burritoIA respondió a una mención hecha por otro bot (la compuerta de la Fase 0);
- en qué hilo respondió, con qué `user`/`bot_id`/`subtype` llegan sus mensajes;
- latencia hasta el primer mensaje, hasta la marca `(ref: #...)` y hasta el bloque completo;
- resultado del parser (`core/services/fo_monitor/parser.py`).

Todo se guarda crudo en `Logs/fo_monitor_poc/<timestamp>.json` para fijar `max_ids_por_mensaje`,
los timeouts y para usar las respuestas reales como fixtures de tests.

Uso (dev):
    python scripts/fo_monitor_poc_burrito.py --escenarios S1
    python scripts/fo_monitor_poc_burrito.py --escenarios S2,S3 --paralelo
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from slack_sdk import WebClient
from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.services.fo_monitor.parser import parsear_respuesta  # noqa: E402
from core.services.fo_monitor.prompt import construir_prompt  # noqa: E402

ESCENARIOS: dict[str, list[str]] = {
    "S1": ["117995"],
    "S2": ["117995", "113705", "110733"],
    "S3": ["117995", "113705", "110733", "109692", "109877"],
    "S4": ["117995", "113705", "110733", "109692", "109877", "113110", "118638", "122883", "120900", "116548"],
    "S5": ["112731", "9999991"],  # FO (no soportado) + inexistente
    "S6": ["117995", "9999991", "113705"],  # inexistente en medio de válidos
    "S7": ["117995", "112731", "113705"],  # FO (sin datos técnicos en PROV) en medio de válidos
    "S8": ["121830"],  # SW de última milla sin gestión (E2E dev 2026-10-14)
    "S9": ["121830", "119813"],  # idem + acceso caído en ambos extremos
}


def _leer_token(ruta: Path) -> str:
    token = ruta.read_text(encoding="utf-8").strip()
    if not token.startswith("xoxb-"):
        raise SystemExit(f"El archivo {ruta} no contiene un bot token xoxb-")
    return token


def _mensajes_burrito(client: WebClient, canal: str, ts: str, burrito: str) -> tuple[list[dict], list[dict]]:
    resp = client.conversations_replies(channel=canal, ts=ts, limit=100)
    mensajes = resp.get("messages", [])[1:]  # el primero es nuestra consulta
    de_burrito = [m for m in mensajes if m.get("user") == burrito or (m.get("bot_profile") or {}).get("name", "").lower().startswith("burrito")]
    return mensajes, de_burrito


def _correr(client: WebClient, canal: str, burrito: str, nombre: str, ids: list[str], timeout: int, poll: int, silencio: int, version: str = "v2") -> dict:
    qid = f"POC{int(time.time())}{nombre}"
    texto = construir_prompt(burrito, qid, ids, version=version)
    enviado = client.chat_postMessage(channel=canal, text=texto, unfurl_links=False, unfurl_media=False)
    ts = enviado["ts"]
    t0 = time.monotonic()
    reg: dict = {"prompt_version": version, "escenario": nombre, "ids": ids, "consulta_id": qid, "ts": ts, "enviado_at": datetime.now(timezone.utc).isoformat()}
    primer = ref_at = completo_at = None
    ultimo_conteo = 0
    ultimo_cambio = t0
    mensajes: list[dict] = []
    de_burrito: list[dict] = []
    while time.monotonic() - t0 < timeout:
        time.sleep(poll)
        mensajes, de_burrito = _mensajes_burrito(client, canal, ts, burrito)
        ahora = time.monotonic()
        if len(de_burrito) != ultimo_conteo:
            ultimo_conteo, ultimo_cambio = len(de_burrito), ahora
        if de_burrito and primer is None:
            primer = ahora - t0
        parse = parsear_respuesta([m.get("text", "") for m in de_burrito], ids)
        if parse.ref and ref_at is None:
            ref_at = ahora - t0
        if parse.completa and completo_at is None:
            completo_at = ahora - t0
        if parse.completa or (parse.ref and ahora - ultimo_cambio >= silencio):
            break
    parse = parsear_respuesta([m.get("text", "") for m in de_burrito], ids)
    reg.update(
        {
            "respondio": bool(de_burrito),
            "latencia_primer_msg_s": primer,
            "latencia_ref_s": ref_at,
            "latencia_completo_s": completo_at,
            "duracion_total_s": round(time.monotonic() - t0, 1),
            "mensajes_hilo": [
                {k: m.get(k) for k in ("user", "bot_id", "subtype", "ts", "thread_ts", "text")} for m in mensajes
            ],
            "parse": {
                "completa": parse.completa,
                "ref": parse.ref,
                "lineas_invalidas": parse.lineas_invalidas,
                "resultados": {k: vars(v) for k, v in parse.resultados.items()},
            },
            "permalink": client.chat_getPermalink(channel=canal, message_ts=ts).get("permalink"),
        }
    )
    estado = "OK" if parse.completa else ("SIN_RESPUESTA" if not de_burrito else "INCOMPLETA")
    print(f"[{nombre}] {estado} ids={len(ids)} primer={primer} ref={ref_at} completo={completo_at} invalidas={len(parse.lineas_invalidas)}")
    return reg


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--canal", default="C08UB8ML3LP", help="#baneo-de-camaras-prueba")
    ap.add_argument("--burrito", default="U0A2HE3K950")
    ap.add_argument("--token-file", type=Path, default=Path(".secrets/Dev_slack_bot_token_v1.txt"))
    ap.add_argument("--escenarios", default="S1")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--poll", type=int, default=10)
    ap.add_argument("--silencio", type=int, default=30, help="segundos sin mensajes nuevos tras ver el ref")
    ap.add_argument("--paralelo", action="store_true", help="publica todos los escenarios a la vez")
    ap.add_argument("--prompt-version", default="v4", choices=["v1", "v2", "v3", "v4"])
    ap.add_argument("--salida", type=Path, default=Path("Logs/fo_monitor_poc"))
    args = ap.parse_args()

    client = WebClient(token=_leer_token(args.token_file))
    client.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=3))
    quien = client.auth_test()
    print(f"Publicando como bot_id={quien.get('bot_id')} user_id={quien.get('user_id')} en {args.canal}")

    nombres = [n.strip() for n in args.escenarios.split(",") if n.strip()]
    if args.paralelo:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=len(nombres)) as ex:
            registros = list(ex.map(lambda n: _correr(client, args.canal, args.burrito, n, ESCENARIOS[n], args.timeout, args.poll, args.silencio, args.prompt_version), nombres))
    else:
        registros = [_correr(client, args.canal, args.burrito, n, ESCENARIOS[n], args.timeout, args.poll, args.silencio, args.prompt_version) for n in nombres]

    args.salida.mkdir(parents=True, exist_ok=True)
    destino = args.salida / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    destino.write_text(json.dumps({"bot": {"bot_id": quien.get("bot_id"), "user_id": quien.get("user_id")}, "paralelo": args.paralelo, "registros": registros}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Guardado: {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
