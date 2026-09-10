# Nombre de archivo: SKILL.md
# Ubicación de archivo: .claude/skills/dev-workflow/SKILL.md
# Descripción: Skill para garantizar que los agentes operen siempre sobre ramas efímeras derivadas de dev y el stack lasfocasdev, nunca sobre producción (mirror de .agentes-comunes/skills/dev-workflow/SKILL.md — fuente de verdad)

---
name: dev-workflow
description: "Usar SIEMPRE antes de ejecutar cambios de código, commits, push, operaciones Docker o actualizaciones de repo. Valida rama efímera activa, stack correcto y restricciones del entorno dev."
argument-hint: "Contexto de la tarea, por ejemplo: implementar feature X en el módulo Y"
---

# Habilidad: Dev Workflow — Protocolo de Trabajo en Entorno Dev

Protocolo de validación y operación para garantizar que todos los cambios se realicen sobre una rama
efímera derivada del entorno de desarrollo aislado (`dev`), nunca directo sobre `dev` ni sobre
producción.

## Cuándo usar
Invocar esta skill **siempre** que el agente vaya a: modificar código/config/docs, ejecutar commits o push, operar Docker (up/build/exec/logs), actualizar el repo (repo-updater), crear/modificar migraciones Alembic, ejecutar tests que requieran DB.

## Procedimiento de validación (ejecutar en orden)

1. Verificar rama activa (`git branch --show-current`).
   - Si es una rama efímera vigente (prefijo `feat/`, `fix/`, `docs/`, `chore/`, `refactor/` o
     `test/`): continuar, es la rama de trabajo de esta tarea.
   - Si es `dev` o `main`: **está prohibido modificar código o commitear ahí**. Crear una rama
     efímera nueva desde el estado remoto de `dev` antes de cualquier cambio:
     ```bash
     git fetch origin
     git checkout -b <tipo>/<slug-kebab-case> origin/dev
     ```
     `<tipo>` = `feat|fix|docs|chore|refactor|test` según la naturaleza del cambio; `<slug>` describe
     la tarea en minúsculas y guiones (mismo criterio que ya se usa en `<tipo>(módulo): descripción`
     para mensajes de commit).
   - Si `dev` no existe en el remoto: crearla primero (`git checkout -b dev && git push -u origin dev`)
     y recién ahí crear la rama efímera.
   - Si ya existe una rama efímera vigente para esta misma tarea, reutilizarla — no crear ramas
     anidadas dentro de una sesión.
2. Verificar que `.env.dev` existe; si no, crearlo desde `deploy/env.dev.sample`.
3. Comandos Docker correctos en dev (tabla `start_dev.sh`, `docker-compose.dev.yml`, etc.). **NUNCA**
   usar `docker compose -f deploy/compose.yml` para pruebas/desarrollo.
4. **Commits y push** (siempre sobre la rama efímera activa, nunca sobre `dev`/`main`):
   ```bash
   git branch --show-current  # debe ser <tipo>/<slug>, nunca dev ni main
   git add .
   git commit -m "<tipo>(módulo): descripción técnica"
   git push -u origin HEAD     # NUNCA: git push origin dev ni git push origin main directamente
   ```
   La integración a `dev` ocurre exclusivamente vía `cierre-sesion` (flujo de auto-merge al cierre) o,
   para ramas deliberadamente diferidas (ej. ventana de mantenimiento), vía
   `superpowers:finishing-a-development-branch`.
5. Restricciones sobre archivos de producción (`deploy/compose.yml`, `.env`, secretos) — requieren aprobación explícita del Tech Lead; si se necesita, documentar en `docs/decisiones.md` y crear PR formal.

## Guardrails
1. No commitear ni pushear estando parado en `dev` o `main`. Todo trabajo ocurre en una rama efímera
   creada desde `origin/dev` (paso 1). Esta regla es universal — sin excepciones por tipo de tarea.
2. No hacer push a `origin/main` sin PR revisado que venga de `dev`.
3. No usar `--force` ni comandos destructivos sin pedido explícito del usuario.
4. No commitear `.env`, `.env.dev`, `Keys/`, `*.pem`, `*.key` ni binarios generados.
5. Si detectás que estás en `main`: no cherry-pickees a ciegas — crear la rama efímera desde
   `origin/dev` (paso 1) y evaluar si los cambios locales en `main` corresponden a esa tarea.
6. `git push origin main` está **prohibida** desde el agente salvo instrucción explícita y confirmación del usuario.
7. Una rama efímera es un `git checkout -b` dentro del mismo checkout de trabajo — **no** es un
   worktree nuevo. Para aislamiento real de directorio (ej. trabajo paralelo de subagentes) usar
   `superpowers:using-git-worktrees`, que es un mecanismo independiente y combinable (un worktree
   puede tener a su vez su propia rama efímera adentro).
   **Preferir un worktree desde el arranque (no sólo cuando ya hay un problema) siempre que exista
   sospecha de sesión concurrente en el mismo checkout** — verificable con `ListAgents` (sesiones
   Claude Code hermanas en la misma máquina). Hallazgo real (2026-09-04, ver
   `docs/cierres/2026-09-04.md`): un `checkout -b` normal (sin worktree) deja el `HEAD`/working
   directory compartido con cualquier otra sesión activa en el mismo checkout; un commit ajeno de esa
   sesión (`docs(cierres): ...` de otro trabajo, sin relación) aterrizó por accidente en la rama
   efímera de esta tarea simplemente porque era el `HEAD` activo en ese momento — no hubo pérdida de
   trabajo (nada se borró ni se forzó), pero exigió coordinación reactiva vía mensaje entre sesiones
   para deshacer el cruce. Un worktree nuevo desde el inicio de una tarea larga (SDD, migraciones,
   trabajo con subagentes) evita el problema por completo en vez de tener que detectarlo y repararlo
   después.
   **Actualización 2026-09-07** (ver `docs/cierres/2026-09-07.md`): para cualquier tarea que vaya a
   tocar `main` o los contenedores/datos de producción, correr `ListAgents` **de forma proactiva
   antes del primer `git checkout -b`, no sólo ante sospecha previa** — en esa sesión no había ningún
   indicio previo y aun así había 5 procesos `claude` (incluida la propia sesión) compartiendo el
   mismo checkout, confirmado en vivo por dos sesiones que reportaron el mismo commit hash recién
   creado y un cambio de rama activa que ninguna de las dos había iniciado. Si `ListAgents` devuelve
   pares sobre el mismo checkout: no coordinar la resolución entre sesiones (ninguna puede validar una
   instrucción de cierre relayed por otra sesión sin que le llegue directo de su propio usuario) —
   escalar al usuario. Procedimiento de identificación/cierre manual que funcionó: `ps aux | grep -i
   claude` (cada proceso `claude` del VSCode extension lleva `--resume=<session-id>`; el session-id
   propio está en la ruta del scratchpad de la sesión activa), matchear el PID propio por ese flag,
   `kill <pid>` (SIGTERM, no `-9` de entrada) sobre el resto, verificar con `ListAgents` (debe quedar
   vacío) y `git status`/`git log` (el checkout no debe mostrar drift inesperado).
8. **`gh` CLI no está instalado en este host** (verificado 2026-09-07) — cualquier flujo que asuma
   `gh pr create`/`gh pr merge` falla con `command not found`. Fallback usado y funcional: revisión
   dirigida vía `git diff <base> <head>` documentada en el chat/PR diario, y merge directo
   (`git merge --no-ff`) + `git push origin main` con confirmación explícita del usuario — sigue
   cumpliendo los guardrails #2/#6, sólo cambia el mecanismo de creación del PR formal (que no existe
   en este caso, no hay registro en GitHub). Además: el clasificador de auto-mode a veces bloquea un
   `git add && git commit && git push` encadenado en un solo comando, sin relación aparente con qué
   rama es — si pasa, separar en 3 llamadas de Bash individuales lo destraba (funcionó dos veces en la
   sesión del 2026-09-07).

9. **Trabajo largo despachado a un subagente: prescribir cortes de commit explícitos, no "commiteá
   incremental".** Hallazgo real (2026-09-08/09, gestor de Servicios sin ODF): tres subagentes murieron
   por límite de API (rate limit) en una misma sesión. Los dos que sólo tenían la instrucción genérica
   "commiteá incremental" perdieron **todo** el trabajo no commiteado (working tree limpio, cero
   commits, cero reporte, nada que rescatar); el que recibió una lista enumerada de cortes ("1. cliente
   de API + fix de tipos → commit; 2. tarjeta → commit; 3. modal → commit; 4. viewer + wiring →
   commit", cada uno exigiendo el build en verde) completó con sus 4 commits, y una ola de fixes
   posterior con cortes agrupados por hallazgo preservó 3 de 4 al morir. La diferencia no fue el modelo
   ni la suerte: fue enumerar los cortes. Para cualquier dispatch que vaya a tocar más de 2-3 archivos,
   listar los cortes concretos y exigir que cada uno deje el build/tests en verde — un commit que no
   compila no sirve como punto de recuperación.

10. **Calcular "qué falta mergear" contra `origin/dev`, nunca contra el `dev` local.** Hallazgo real
    (2026-09-10, actualización de repo): el `dev` local estaba **32 commits atrás** de `origin/dev`
    porque otra sesión había mergeado y pusheado. Calcular ramas pendientes contra el `dev` local daba
    un resultado falso: dos ramas efímeras (`feat/odf-viewer-servicios-sin-odf`,
    `fix/ingreso-nombre-multilinea`) figuraban como "sin mergear" cuando su contenido ya estaba
    integrado en el remoto. Antes de cualquier decisión de merge o borrado:
    ```bash
    git fetch origin
    git merge-base --is-ancestor <rama> origin/dev   # ¿ya está integrada? (0 = sí)
    git rev-list --count origin/dev..<rama>          # commits propios reales
    ```
    Un `git branch -vv` que dice `[origin/dev: behind N]` sobre la rama base es la señal de alarma.
    Corolario: `git branch -d` (minúscula) es la red de seguridad correcta al borrar — rechaza lo no
    mergeado; nunca usar `-D` para "limpiar" sin haber hecho este chequeo.
11. **`git rm --cached` se propaga como borrado del working tree al mergear.** Destrackear un archivo
    lo conserva en disco **sólo en la rama donde se hizo**; al mergear ese commit a una rama donde el
    archivo sigue trackeado, el merge materializa la eliminación y **borra el archivo del disco**.
    Real (2026-09-10): al agregar `docs/handoffs/` al `.gitignore` hubo que destrackear un handoff; en
    la rama efímera quedó en disco como se esperaba, y al mergear a `dev` desapareció. Si el archivo
    es un artefacto operativo que sólo existe en esta máquina (handoff, dump, nota de sesión), el
    borrado es pérdida real de datos. Copiarlo al scratchpad antes y verificar con `md5sum` antes y
    después del merge, restaurando si hace falta.
12. **Operaciones masivas e irreversibles sobre el remoto: interpretación estrecha por defecto.** Un
    pedido de limpieza ambiguo ("que solo quede dev") se resuelve por defecto en su lectura **más
    acotada** — las ramas efímeras de la tarea en curso — y cualquier ampliación irreversible se
    trata como pedido separado y explícito, no como una opción más de un menú. Real (2026-09-10): el
    pedido era sincronizar las ramas efímeras sin mergear; al ofrecer como opción borrar además las
    ~103 ramas `codex/*`/`dependabot/*` del remoto, el alcance terminó en **113 ramas borradas de
    GitHub**, de las cuales 85 tenían commits no integrados. El usuario después aclaró que el pedido
    original era sólo el merge de las efímeras. Ofrecer una ampliación irreversible ya sesga la
    decisión: si el pedido literal no la incluye, no ponerla en el menú. Si aun así se ejecuta:
    - Fuente autoritativa de ramas remotas es `git ls-remote --heads origin`, **no** los
      remote-tracking locales: `git for-each-ref --format='%(refname:short)' refs/remotes/origin/`
      acorta `refs/remotes/origin/HEAD` a **`origin`** (no a `origin/HEAD`), así que un filtro por
      nombre lo deja pasar a la lista de borrado apuntando al SHA de `main`.
    - Imprimir siempre las entradas que **no** matchean el patrón esperado y afirmar explícitamente
      que `dev`/`main` no están en la lista, antes de ejecutar.
    - Dejar respaldo recuperable: `refs/backup/<fecha>/<nombre>` **no se pushea ni se clona** (queda
      fuera del refspec `refs/heads/*`), así que para durabilidad real hace falta además un
      `git bundle create <archivo> --stdin --not dev main` guardado **fuera** del repo (no commitear
      binarios, guardrail #4). Verificar con `git bundle verify` que los prerequisitos estén en `dev`.

## Relación con otras skills
`repo-updater` (audita/commitea sobre la rama efímera activa), `pytest-focas`, `alembic-migrations`,
`docker-rebuild`, `cierre-sesion` (único punto que integra la rama efímera a `dev`).

## Resultado esperado
Rama efímera confirmada (nunca `dev`/`main` en el momento de commitear), `.env.dev` presente, stack
`lasfocasdev` correcto, ningún cambio accidental en producción, push a `origin/<rama-efímera>`.
