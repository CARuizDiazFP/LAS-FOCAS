# Nombre de archivo: relevamiento_cromo_cables_fantasma_2026-10-02.md
# Ubicación de archivo: docs/relevamiento_cromo_cables_fantasma_2026-10-02.md
# Descripción: Relevamiento real (dev) de cables vigentes en LAS-FOCAS que Cromo ya borró, y de cables de Cromo que faltan en la base

# Relevamiento: cables fantasma de Cromo (dev, 2026-10-02)

**Origen:** en Slack, `servicios cable F-TIG-003-B` respondió "2 cables con ese código" (10277060 y 9609095). El 9609095 ya no existe en Cromo: el 2026-09-10 se partió en F-TIG-003-A (10277059) y F-TIG-003-B (10277060), y en LAS-FOCAS seguía vigente porque ningún código daba de baja cables.

**Cómo se midió:** `scripts/cromo_relevamiento_cables_fantasma.py` contra Cromo real y `lasfocasdev-postgres`, en solo lectura: `GET` a Cromo y `SELECT` en una transacción revertida. Duró 456 s. Prod todavía no se relevó.

## Señal de borrado en Cromo (medida)

- `GET /db/objects/{id}` de un cable borrado **responde `st=0`**, no 404. `/inner` también responde, con la lista vacía; por eso el barrido `/inner` del 2026-09-30 lo dio por OK.
- **Criterio:** la última entrada de `hist[]` (la de `next_id = 0`) tiene `to ≠ 0`. Que el objeto pedido tenga `to`/`vto` no alcanza: F-ROW-K52JAAA 10259700 los tiene porque es una versión vieja, y su última versión (10259871) sigue abierta, o sea que está vivo.
- El `vto` final del borrado coincide con el `vfrom` del cable que lo reemplazó en la misma operación (275695 en F-TIG-003-B). Esa es la pista de sucesor.
- Doble señal: un candidato (vigente local que la colección no lista) se da por borrado sólo si su consulta individual lo confirma. Un error de consulta nunca cuenta como borrado.

## Totales por clase

| Clase | `count` Cromo | Objetos listados | Candidatos | Fantasmas confirmados | Faltantes en la base |
|---|---|---|---|---|---|
| 51 | 33115 | 32931 | 98 | 97 | 239 |
| 52 | 695 | 695 | 0 | 0 | 1 |
| 59 | 7 | 7 | 0 | 0 | 0 |
| 60 | 31 | 24 | 0 | 0 | 0 |
| 66 | 19026 | 18998 | 0 | 0 | 4 |

- **97 fantasmas**, todos de la clase 51. Hay 1 candidato vivo no listado (6630098), que no se toca. No hubo errores de confirmación.
- **64 tienen servicios**: 862 asignaciones `REGEX_EXACTO` y 14 `ATRIBUTO_PELO`. **Ninguna es MANUAL**, así que la regla de MANUAL no se aplica en dev.
- La baja afecta a 6144 pelos.
- Todos se borraron en Cromo entre las versiones 271364 y 278840 (agosto y septiembre de 2026). Es decir, **después de la única barrida completa de cables** (corrida 8, 2026-08-06).

## Sucesores: el otro lado del mismo problema

- **36 fantasmas** tienen en Cromo cables nacidos en la misma versión en que murieron: **80 sucesores, de los cuales 70 no existen en la base local**.
- Por eso el relevamiento local sólo encuentra sucesor para 5, y 61 quedan con servicios "sin cobertura": los cables que hoy llevan esos servicios todavía no bajaron.
- Los otros 61 no tienen ningún cable nacido en esa versión. Se borraron sin reemplazo directo, o el reemplazo se hizo en otra operación.

**Consecuencia para el fix retroactivo:** dar de baja primero dejaría a esos servicios sin cable hasta la próxima ingesta. El orden correcto es:

1. alta de los cables faltantes
2. sus pelos (`/inner`)
3. la baja de los fantasmas

## Fantasmas confirmados

| n_id | Nombre | vto final | Pelos | Servicios | Sucesor en base local | Sucesores en Cromo |
|---|---|---|---|---|---|---|
| 9280174 | F-TRI-001 | 273717 | 288 | 69 | — | — |
| 6612797 | F-GRP-26 | 273200 | 144 | 43 | — | 2 |
| 6615318 | F-NVC-2000 | 276581 | 288 | 26 | — | — |
| 10247423 | F-HOR-OCT | 276072 | 72 | 24 | — | 2 |
| 6616768 | F-RPA-HYN | 272737 | 144 | 24 | — | — |
| 10242981 | F-RPA-HYN-A | 272788 | 144 | 24 | — | — |
| 10242982 | F-RPA-HYN-B | 272774 | 144 | 24 | — | — |
| 6610459 | F-SCO-CD | 271924 | 72 | 24 | — | 2 |
| 6592956 | FL-RTT-437 | 278541 | 72 | 22 | — | 1 |
| 6597090 | F-MIS-LA | 278542 | 72 | 21 | — | 7 |
| 10208750 | F-SCO-D-A | 272003 | 72 | 21 | — | — |
| 9193253 | F-PIL-FRNBA | 274394 | 72 | 20 | — | — |
| 6594211 | FA-36 | 278542 | 72 | 20 | — | 7 |
| 6609515 | F-R25-8500AA | 276446 | 48 | 18 | — | 6 |
| 6610803 | F-MSR-1 | 278542 | 72 | 17 | — | 7 |
| 9926584 | F-JUY-MILBBA-2 | 275685 | 48 | 16 | — | — |
| 9498169 | F-LEM-11-A | 272304 | 144 | 14 | 10260935 (vfrom=vto) | 2 |
| 10232131 | F-VIN-EDG-144A-B- | 273548 | 144 | 14 | — | — |
| 6613033 | F-C407B | 276050 | 72 | 12 | — | — |
| 9990425 | F-VIN-CJFRAN | 273485 | 72 | 10 | — | — |
| 9384582 | F-VIN-HI | 277857 | 48 | 10 | — | — |
| 6592955 | FL-RNA-010 | 278541 | 72 | 9 | — | 1 |
| 6612687 | F-CPN-198 | 272791 | 72 | 8 | — | — |
| 9092177 | F-YRI-001 | 275957 | 72 | 8 | 9091864 (extremo) | — |
| 6616785 | FA-876BB1 | 276868 | 72 | 8 | — | 1 |
| 9966036 | F-BEN-TAG | 275694 | 72 | 7 | — | 3 |
| 6613542 | F-BIND-K32 | 277297 | 72 | 7 | — | — |
| 6609223 | F-MAP-VIAA | 277603 | 48 | 7 | — | 1 |
| 6617022 | F-RUT-23ABA | 273214 | 72 | 7 | — | — |
| 9676935 | F-STW-594A | 276905 | 48 | 7 | — | — |
| 9609095 | F-TIG-003-B | 275695 | 144 | 7 | 10277059 (vfrom=vto), 10277060 (vfrom=vto) | 2 |
| 6610935 | F-SDL-1MA | 274911 | 72 | 5 | — | 1 |
| 6612368 | F-VIN-R25 | 276924 | 24 | 5 | — | 2 |
| 10191201 | F-CAM-CAR-1 | 276890 | 72 | 3 | — | — |
| 10053133 | F-CAM-CAR-2 | 278476 | 72 | 3 | — | — |
| 6611377 | F-JUNVA-9BB | 275180 | 72 | 3 | — | — |
| 6613464 | F-RMRE-1 | 276315 | 72 | 3 | — | — |
| 9330574 | F-RTA6-195 | 276712 | 24 | 3 | — | — |
| 9093567 | F-AVA-69P1 | 278068 | 24 | 2 | — | — |
| 6596060 | F-CA2-366 | 277528 | 72 | 2 | — | — |
| 9763160 | F-HEN-650-A | 276574 | 72 | 2 | — | — |
| 10215947 | F-PST-KYN | 272862 | 72 | 2 | — | 2 |
| 9514923 | F-SMT-420-B | 271460 | 24 | 2 | — | 1 |
| 10208598 | F- MONT- 6427-A | 278840 | 24 | 1 | — | 2 |
| 10194553 | F-ALBT-2154-CLI | 273090 | 24 | 1 | — | 2 |
| 6599854 | F-ALM-PLO | 271471 | 24 | 1 | — | — |
| 9524260 | F-CRO-995 | 274459 | 48 | 1 | — | 2 |
| 10014784 | F-GPAZ-PT6-A | 273319 | 24 | 1 | — | 1 |
| 9355454 | F-HIP-YRY | 275319 | 24 | 1 | — | 2 |
| 9825529 | F-HTI-5130 | 275174 | 24 | 1 | — | — |
| 10177438 | F-LNS-TR1-2-B | 277139 | 144 | 1 | — | — |
| 9222184 | F-MAD1 | 275190 | 72 | 1 | — | — |
| 9528704 | F-MRC-LJ1-A | 271856 | 72 | 1 | — | — |
| 9528783 | F-MRC-LJ1-B-A | 272094 | 72 | 1 | — | — |
| 9528784 | F-MRC-LJ1-B-B | 272102 | 72 | 1 | — | — |
| 9297126 | F-MRC-LJ2 | 272110 | 72 | 1 | — | — |
| 10172221 | F-PDR-MUJ-B | 278139 | 12 | 1 | — | — |
| 10037016 | F-RIVD-BOT -398 | 271991 | 48 | 1 | — | 2 |
| 6601539 | F-ROW-K52JAAA | 272203 | 72 | 1 | 10259700 (nombre) | — |
| 6599090 | F-SAL-3350 | 272217 | 72 | 1 | — | 2 |
| 9866124 | F-SUIP1111-P3 | 273294 | 24 | 1 | — | — |
| 6604672 | F-VER-559 | 274218 | 72 | 1 | — | — |
| 6596640 | F-VNZ-156 | 274285 | 24 | 1 | — | 2 |
| 10073355 | F-WIL-RMA-B | 278026 | 72 | 1 | — | 2 |
| 9971247 | — | 274918 | 0 | 0 | — | — |
| 10239905 | F-12 | 278716 | 72 | 0 | — | 1 |
| 9845098 | F-ACC-CTFO5 | 271613 | 48 | 0 | — | — |
| 9845099 | F-ACC-CTFO5B | 271565 | 48 | 0 | — | — |
| 9037331 | F-CC1-R1-14 | 275479 | 0 | 0 | — | 2 |
| 6594726 | F-CER-1901 | 271364 | 0 | 0 | — | — |
| 9611912 | F-CV-ST2 | 272164 | 0 | 0 | — | — |
| 10004171 | F-FAT-CAM763 | 276258 | 24 | 0 | — | 1 |
| 9994278 | F-GIR-TR-A | 276880 | 0 | 0 | — | — |
| 9994279 | F-GIR-TR-B | 276876 | 0 | 0 | — | — |
| 9911069 | F-MAR-T2-TR2 | 273811 | 72 | 0 | — | — |
| 9993772 | F-MTR-TRB-A | 276880 | 0 | 0 | — | — |
| 9993773 | F-MTR-TRB-B | 276875 | 0 | 0 | — | 1 |
| 9993742 | F-NEX-03-A | 276875 | 0 | 0 | — | 1 |
| 9993743 | F-NEX-03-B | 276880 | 0 | 0 | — | — |
| 10253611 | F-NICA-ORGEPROYECTADO | 275643 | 24 | 0 | — | 2 |
| 9357446 | F-PON-CARD2100 | 278042 | 48 | 0 | — | — |
| 6610370 | F-QUI-ALV | 271536 | 48 | 0 | — | — |
| 9184937 | F-RN8-PIF | 277478 | 48 | 0 | — | — |
| 9839390 | F-SUI-M31-A | 272583 | 48 | 0 | — | 1 |
| 9994173 | F-TL-TRB-B | 276880 | 0 | 0 | — | — |
| 9994119 | F-TRB-TC-B | 276880 | 0 | 0 | — | — |
| 6610688 | F-TRES-310B | 273373 | 12 | 0 | — | — |
| 6615031 | F-TRVG-2B | 272081 | 72 | 0 | — | 2 |
| 6594463 | F-URU-16 | 275340 | 72 | 0 | — | 2 |
| 10110948 | F-VIN-BERG-CTO2 | 272442 | 0 | 0 | 10267070 (nombre) | — |
| 10161337 | F-VIN-HUB5 | 278033 | 48 | 0 | — | — |
| 9505912 | F-VIN-LBT | 272164 | 72 | 0 | — | — |
| 9993960 | FD4-1-A | 276880 | 0 | 0 | — | — |
| 9993803 | FD4-2-B | 276880 | 0 | 0 | — | — |
| 10205403 | FT-SAS-COS | 272254 | 288 | 0 | — | — |
| 10123543 | F_prueba_9-A-A | 276502 | 144 | 0 | — | — |
| 10123544 | F_prueba_9-A-B | 276484 | 144 | 0 | — | — |
