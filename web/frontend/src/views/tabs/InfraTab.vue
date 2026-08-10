<!--
  Nombre de archivo: InfraTab.vue
  Ubicación de archivo: web/frontend/src/views/tabs/InfraTab.vue
  Descripción: Tab de Infraestructura / Dashboard de Cámaras — migrado desde panel.js
-->
<template>
  <article class="infra-view">
    <!-- Toast container -->
    <teleport to="body">
      <div id="infra-toast-container" class="toast-container" aria-live="polite">
        <transition-group name="toast-anim">
          <div
            v-for="t in toasts"
            :key="t.id"
            :class="['toast', t.type]"
          >
            <span class="toast-icon">{{ toastIcon(t.type) }}</span>
            <div class="toast-content">
              <div class="toast-title">{{ t.title }}</div>
              <div v-if="t.message" class="toast-message">{{ t.message }}</div>
            </div>
            <button class="toast-close" @click="removeToast(t.id)">×</button>
          </div>
        </transition-group>
      </div>
    </teleport>

    <!-- Hidden file input para tracking upload -->
    <input ref="trackingFileInputEl" type="file" accept=".txt" style="display:none" @change="handleTrackingFile">

    <!-- Modal: Protocolo de Protección (ban) — Wizard 3 pasos -->
    <dialog ref="banModalEl" class="infra-generic-modal ban-wizard-modal" @click.self="closeBanModal">
      <div class="modal-inner">

        <!-- Header fijo -->
        <div class="modal-header-row">
          <h3 class="modal-title">🔴 Protocolo de Protección</h3>
          <button class="close-btn" :disabled="banLoading" @click="closeBanModal">×</button>
        </div>

        <!-- Stepper visual -->
        <div class="wizard-stepper">
          <div v-for="(label, i) in ['Identificación', 'Selección', 'Confirmación']" :key="i" class="wizard-step-row">
            <div :class="['wizard-step-item', { active: currentBanStep === i + 1, done: currentBanStep > i + 1 }]">
              <span class="wizard-step-num">{{ currentBanStep > i + 1 ? '✓' : i + 1 }}</span>
              <span class="wizard-step-label">{{ label }}</span>
            </div>
            <div v-if="i < 2" class="wizard-step-connector"></div>
          </div>
        </div>

        <!-- ─── PASO 1: Identificación ─── -->
        <template v-if="currentBanStep === 1">
          <label class="form-label">Ticket del incidente (opcional)</label>
          <input v-model="banForm.ticket_asociado" type="text" placeholder="INC0012345" />
          <label class="form-label">Servicio afectado (el que se cortó) <span class="req">*</span></label>
          <input
            v-model="banForm.servicio_afectado_id"
            type="text"
            placeholder="Ej: 52547"
            @keydown.enter.prevent="banGoNext"
          />
          <label class="form-label">Motivo (opcional)</label>
          <textarea v-model="banForm.motivo" rows="2" placeholder="Corte de fibra en Av. Corrientes..."></textarea>
          <div class="modal-actions">
            <button class="btn subtle" @click="closeBanModal">Cancelar</button>
            <button
              class="btn primary"
              :disabled="!banForm.servicio_afectado_id.trim()"
              @click="banGoNext"
            >Siguiente →</button>
          </div>
        </template>

        <!-- ─── PASO 2: Selección del objetivo ─── -->
        <template v-else-if="currentBanStep === 2">
          <div class="ban-step2-affected">
            Servicio afectado: <strong>{{ banForm.servicio_afectado_id }}</strong>
          </div>

          <!-- Tabs: mismo / otro servicio -->
          <div class="ban-prot-tabs">
            <button
              :class="['ban-prot-tab', { active: banProtMode === 'same' }]"
              @click="banSwitchMode('same')"
            >Proteger el mismo servicio</button>
            <button
              :class="['ban-prot-tab', { active: banProtMode === 'other' }]"
              @click="banSwitchMode('other')"
            >Otro servicio (redundancia cruzada)</button>
          </div>

          <!-- Input solo para "otro servicio" -->
          <template v-if="banProtMode === 'other'">
            <label class="form-label">ID del servicio a proteger <span class="req">*</span></label>
            <div class="ban-search-row">
              <input
                v-model="banSearchServicioInput"
                type="text"
                placeholder="Ej: 52548"
                @keydown.enter.prevent="loadRutasForBan(banSearchServicioInput.trim())"
              />
              <button
                class="btn primary"
                :disabled="banLoadingRutas || !banSearchServicioInput.trim()"
                @click="loadRutasForBan(banSearchServicioInput.trim())"
              >{{ banLoadingRutas ? '...' : 'Buscar rutas' }}</button>
            </div>
          </template>

          <!-- Error de carga de rutas -->
          <div v-if="banRutasError" class="ban-rutas-error">⚠ {{ banRutasError }}</div>

          <!-- Grilla de rutas -->
          <template v-if="banRutas.length > 0">
            <label class="form-label" style="margin-top: 10px;">Ruta a proteger</label>
            <div class="ban-ruta-grid">
              <!-- Opción "Todas las rutas activas" -->
              <div
                :class="['ban-ruta-card', 'all-option', { selected: banSelectedRutaId === null }]"
                @click="banSelectedRutaId = null"
              >
                <span class="ban-ruta-icon">📡</span>
                <div>
                  <div class="ban-ruta-nombre">Todas las rutas activas</div>
                  <div class="ban-ruta-meta">{{ banRutas.filter(r => r.activa).length }} caminos · ~{{ banEstimatedCamaras }} empalmes</div>
                </div>
              </div>
              <!-- Una tarjeta por ruta -->
              <div
                v-for="ruta in banRutas"
                :key="ruta.id"
                :class="['ban-ruta-card', { selected: banSelectedRutaId === ruta.id }]"
                @click="banSelectedRutaId = ruta.id"
              >
                <span class="ban-ruta-icon">{{ ruta.tipo === 'PRINCIPAL' ? '🔵' : ruta.tipo === 'BACKUP' ? '🟡' : '🟣' }}</span>
                <div>
                  <div class="ban-ruta-nombre">{{ ruta.nombre }}</div>
                  <div class="ban-ruta-meta">{{ ruta.tipo }} · {{ ruta.empalmes_count }} empalmes{{ !ruta.activa ? ' · INACTIVA' : '' }}</div>
                  <!-- Alerta tracking desactualizado -->
                  <div v-if="ruta.hash_contenido === null && banSelectedRutaId === ruta.id" class="ban-tracking-alert">
                    ⚠ Sin tracking guardado para esta ruta.
                    <div class="ban-tracking-alert-actions">
                      <button class="btn subtle small" @click.stop="downloadTrackingByRutaId(ruta.id)">📄 Descargar TXT</button>
                      <button class="btn warning small" @click.stop="triggerUploadTrackingForBan(ruta.id)">⬆ Actualizar Tracking</button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </template>
          <div v-else-if="!banLoadingRutas && !banRutasError && banRutas.length === 0 && banForm.servicio_protegido_id" class="ban-rutas-empty">
            Sin rutas registradas para este servicio.
          </div>

          <div class="modal-actions">
            <button class="btn subtle" @click="banGoPrev">← Anterior</button>
            <button
              class="btn primary"
              :disabled="!banForm.servicio_protegido_id.trim() || banLoadingRutas"
              @click="banGoNext"
            >Siguiente →</button>
          </div>
        </template>

        <!-- ─── PASO 3: Confirmación ─── -->
        <template v-else-if="currentBanStep === 3">
          <div class="ban-summary-block">
            <div class="ban-summary-row"><span class="ban-summary-label">Ticket</span><span>{{ banForm.ticket_asociado || '—' }}</span></div>
            <div class="ban-summary-row"><span class="ban-summary-label">Servicio afectado</span><strong>{{ banForm.servicio_afectado_id }}</strong></div>
            <div class="ban-summary-row"><span class="ban-summary-label">Servicio a proteger</span><strong>{{ banForm.servicio_protegido_id }}</strong></div>
            <div class="ban-summary-row">
              <span class="ban-summary-label">Ruta</span>
              <span>{{ banSelectedRutaId === null ? 'Todas las rutas activas' : (banRutas.find(r => r.id === banSelectedRutaId)?.nombre ?? '—') }}</span>
            </div>
            <div class="ban-summary-row"><span class="ban-summary-label">Empalmes estimados</span><strong>~{{ banEstimatedCamaras }}</strong></div>
            <div v-if="banForm.motivo" class="ban-summary-row"><span class="ban-summary-label">Motivo</span><span>{{ banForm.motivo }}</span></div>
          </div>
          <label class="ban-confirm-row">
            <input v-model="banConfirmChecked" type="checkbox" />
            <span>Confirmo que entiendo que las cámaras de este servicio serán <strong>bloqueadas</strong></span>
          </label>
          <div class="modal-actions">
            <button class="btn subtle" :disabled="banLoading" @click="banGoPrev">← Anterior</button>
            <button
              class="btn danger"
              :disabled="banLoading || !banConfirmChecked"
              @click="submitBan"
            >{{ banLoading ? 'Activando...' : '🚨 EJECUTAR BANEO' }}</button>
          </div>
        </template>

      </div>
    </dialog>

    <!-- Modal: Resolución de tracking (flujo Portero 2 fases) -->
    <dialog ref="trackingResolveModalEl" class="infra-generic-modal tracking-resolve-modal" @click.self="closeUploadModal">
      <div class="modal-inner">
        <div class="modal-header-row">
          <h3 class="modal-title">📁 Subir Tracking</h3>
          <button class="close-btn" @click="closeUploadModal">×</button>
        </div>
        <div v-if="uploadAnalyzing" class="upload-analyzing">
          ⏳ Analizando <strong>{{ fileName }}</strong>...
        </div>
        <template v-else-if="analyzeResult">
          <div :class="['resolve-status-badge', 'status-' + (analyzeResult.status ?? 'error').toLowerCase()]">
            {{ analyzeResult.status }}
          </div>
          <p class="resolve-message">{{ analyzeResult.message }}</p>
          <div v-if="analyzeResult.servicio_id" class="resolve-svc-info">
            Servicio: <strong>{{ analyzeResult.servicio_id }}</strong>
            <span v-if="analyzeResult.parsed_empalmes_count"> · {{ analyzeResult.parsed_empalmes_count }} empalmes</span>
            <template v-if="analyzeResult.punta_a_sitio">
              <span> · {{ analyzeResult.punta_a_sitio }} → {{ analyzeResult.punta_b_sitio ?? '?' }}</span>
            </template>
          </div>

          <!-- NEW: crear servicio nuevo -->
          <template v-if="analyzeResult.status === 'NEW'">
            <p class="resolve-hint">El servicio no existe. Se creará con una ruta Principal.</p>
            <div class="modal-actions">
              <button class="btn primary" :disabled="uploadResolving" @click="resolveTracking('CREATE_NEW', {})">
                {{ uploadResolving ? 'Procesando...' : 'Crear nuevo servicio' }}
              </button>
              <button class="btn subtle" @click="closeUploadModal">Cancelar</button>
            </div>
          </template>

          <!-- IDENTICAL: ya existe igual -->
          <template v-else-if="analyzeResult.status === 'IDENTICAL'">
            <p class="resolve-hint">El archivo es idéntico a una ruta existente. Sin cambios necesarios.</p>
            <div class="modal-actions">
              <button class="btn subtle" @click="closeUploadModal">Cerrar</button>
            </div>
          </template>

          <!-- CONFLICT: servicio existe con contenido diferente -->
          <template v-else-if="analyzeResult.status === 'CONFLICT'">
            <p class="resolve-hint">El servicio ya existe con contenido diferente.</p>
            <div v-if="analyzeResult.rutas_existentes.length" class="resolve-rutas-list">
              <div v-for="r in analyzeResult.rutas_existentes" :key="r.id" class="resolve-ruta-item">
                <strong>{{ r.nombre }}</strong>
                <span class="resolve-ruta-meta">{{ r.tipo }} · {{ r.empalmes_count }} emp.</span>
              </div>
            </div>
            <label v-if="analyzeResult.rutas_existentes.length > 0" class="form-label">Ruta destino para Merge / Reemplazar</label>
            <select
              v-if="analyzeResult.rutas_existentes.length > 0"
              v-model="resolveTargetRutaId"
              class="resolve-select"
            >
              <option v-for="r in analyzeResult.rutas_existentes" :key="r.id" :value="r.id">
                {{ r.nombre }} ({{ r.tipo }}, {{ r.empalmes_count }} emp.)
              </option>
            </select>
            <label class="form-label">Nombre del nuevo camino (para "Crear Camino")</label>
            <input v-model="resolveNewRutaNombre" type="text" placeholder="Ej: Backup Corrientes" />
            <div class="modal-actions resolve-conflict-actions">
              <button class="btn subtle" :disabled="uploadResolving" @click="resolveTracking('MERGE_APPEND', { target_ruta_id: resolveTargetRutaId })">
                {{ uploadResolving ? '...' : '+ Merge empalmes' }}
              </button>
              <button class="btn warning" :disabled="uploadResolving" @click="resolveTracking('REPLACE', { target_ruta_id: resolveTargetRutaId })">
                {{ uploadResolving ? '...' : '↺ Reemplazar ruta' }}
              </button>
              <button
                class="btn primary"
                :disabled="uploadResolving || !resolveNewRutaNombre.trim()"
                @click="resolveTracking('BRANCH', { new_ruta_name: resolveNewRutaNombre, new_ruta_tipo: 'ALTERNATIVA' })"
              >{{ uploadResolving ? '...' : '⑂ Crear Camino' }}</button>
              <button
                class="btn primary"
                :disabled="uploadResolving"
                @click="resolveTracking('ADD_STRAND', { target_ruta_id: resolveTargetRutaId })"
              >{{ uploadResolving ? '...' : '🧵 Nuevo Pelo' }}</button>
              <button class="btn subtle" @click="closeUploadModal">Cancelar</button>
            </div>
          </template>

          <!-- POTENTIAL_UPGRADE: posible upgrade de servicio -->
          <template v-else-if="analyzeResult.status === 'POTENTIAL_UPGRADE'">
            <p class="resolve-hint">Se detectó un posible upgrade de servicio.</p>
            <div v-if="analyzeResult.upgrade_info" class="resolve-upgrade-info">
              <div>Servicio viejo: <strong>{{ analyzeResult.upgrade_info.old_service_id }}</strong></div>
              <div>Razón: {{ analyzeResult.upgrade_info.match_reason }}</div>
              <div v-if="analyzeResult.upgrade_info.punta_a_match">Punta A: {{ analyzeResult.upgrade_info.punta_a_match }}</div>
              <div v-if="analyzeResult.upgrade_info.punta_b_match">Punta B: {{ analyzeResult.upgrade_info.punta_b_match }}</div>
            </div>
            <div class="modal-actions">
              <button
                class="btn primary"
                :disabled="uploadResolving"
                @click="resolveTracking('CONFIRM_UPGRADE', { old_service_id: analyzeResult?.upgrade_info?.old_service_id ?? '' })"
              >{{ uploadResolving ? '...' : 'Confirmar upgrade' }}</button>
              <button class="btn subtle" :disabled="uploadResolving" @click="resolveTracking('CREATE_NEW', {})">
                {{ uploadResolving ? '...' : 'Crear como nuevo' }}
              </button>
              <button class="btn subtle" @click="closeUploadModal">Cancelar</button>
            </div>
          </template>

          <!-- NEW_STRAND: nuevo pelo -->
          <template v-else-if="analyzeResult.status === 'NEW_STRAND'">
            <p class="resolve-hint">Se detectó un nuevo pelo para un servicio existente.</p>
            <div v-if="analyzeResult.strand_info" class="resolve-upgrade-info">
              <div>Servicio: <strong>{{ analyzeResult.strand_info.service_id }}</strong></div>
              <div>Pelos actuales: {{ analyzeResult.strand_info.current_strands }}</div>
              <div v-if="analyzeResult.strand_info.new_strand_pelo">Nuevo pelo: {{ analyzeResult.strand_info.new_strand_pelo }}</div>
            </div>
            <div class="modal-actions">
              <button
                class="btn primary"
                :disabled="uploadResolving"
                @click="resolveTracking('ADD_STRAND', { target_ruta_id: analyzeResult?.strand_info?.ruta_id })"
              >{{ uploadResolving ? '...' : 'Agregar pelo' }}</button>
              <button class="btn subtle" :disabled="uploadResolving" @click="resolveTracking('CREATE_NEW', {})">
                {{ uploadResolving ? '...' : 'Crear como nuevo' }}
              </button>
              <button class="btn subtle" @click="closeUploadModal">Cancelar</button>
            </div>
          </template>

          <!-- ERROR (y cualquier status desconocido) -->
          <template v-else>
            <p class="resolve-error">{{ analyzeResult.error ?? 'Error desconocido durante el análisis.' }}</p>
            <div class="modal-actions">
              <button class="btn subtle" @click="closeUploadModal">Cerrar</button>
            </div>
          </template>
        </template>
      </div>
    </dialog>

    <!-- Modal: Baneos Activos -->
    <dialog ref="activeBansModalEl" class="infra-generic-modal active-bans-modal" @click.self="closeActiveBansModal">
      <div class="modal-inner">
        <div class="modal-header-row">
          <h3 class="modal-title">🔒 Baneos Activos</h3>
          <button class="close-btn" @click="closeActiveBansModal">×</button>
        </div>

        <!-- Cargando -->
        <div v-if="activeBansLoading" class="active-bans-loading">Cargando baneos activos...</div>

        <!-- Error -->
        <div v-else-if="activeBansError" class="active-bans-error">⚠ {{ activeBansError }}</div>

        <!-- Sin baneos -->
        <div v-else-if="activeBans.length === 0" class="active-bans-empty">
          <span>✅ No hay baneos activos en este momento.</span>
        </div>

        <!-- Lista de incidentes -->
        <template v-else>
          <div class="active-bans-count">{{ activeBans.length }} incidente{{ activeBans.length !== 1 ? 's' : '' }} activo{{ activeBans.length !== 1 ? 's' : '' }}</div>
          <div class="active-bans-list">
            <div v-for="inc in activeBans" :key="inc.id" class="active-ban-card">
              <div class="active-ban-card-header">
                <div class="active-ban-ticket">
                  <span class="active-ban-ticket-label">Ticket</span>
                  <strong>{{ inc.ticket_asociado || '—' }}</strong>
                </div>
                <div class="active-ban-duracion">{{ formatDuracion(inc.duracion_horas) }}</div>
              </div>
              <div class="active-ban-servicios">
                <span class="active-ban-svc-item afectado">
                  <span class="active-ban-svc-dot afectado"></span>
                  Afectado: <strong>{{ inc.servicio_afectado_id }}</strong>
                </span>
                <span class="active-ban-arrow">→</span>
                <span class="active-ban-svc-item protegido">
                  <span class="active-ban-svc-dot protegido"></span>
                  Protegido: <strong>{{ inc.servicio_protegido_id }}</strong>
                </span>
              </div>
              <div v-if="inc.ruta_protegida_id" class="active-ban-ruta">
                Ruta: <span>ID {{ inc.ruta_protegida_id }}</span>
              </div>
              <div v-if="inc.motivo" class="active-ban-motivo">{{ inc.motivo }}</div>
              <div class="active-ban-meta">
                <span>Inicio: {{ formatFecha(inc.fecha_inicio) }}</span>
                <span v-if="inc.camaras_count">· {{ inc.camaras_count }} cámara{{ inc.camaras_count !== 1 ? 's' : '' }}</span>
                <span v-if="inc.usuario_ejecutor">· por {{ inc.usuario_ejecutor }}</span>
              </div>
              <div class="active-ban-actions">
                <button
                  class="btn warning small"
                  :disabled="avisoLoadingId === inc.id"
                  @click="openAvisoModal(inc)"
                >{{ avisoLoadingId === inc.id ? '...' : '📧 Dar Aviso' }}</button>
                <button
                  class="btn success small"
                  :disabled="liftLoadingId === inc.id"
                  @click="confirmLiftBan(inc)"
                >{{ liftLoadingId === inc.id ? 'Levantando...' : '🔓 Levantar Baneo' }}</button>
              </div>
            </div>
          </div>
        </template>

        <div class="modal-actions" style="margin-top:8px">
          <button class="btn subtle" @click="closeActiveBansModal">Cerrar</button>
          <button class="btn primary small" :disabled="activeBansLoading" @click="loadActiveBans">↻ Actualizar</button>
        </div>
      </div>
    </dialog>

    <!-- Sub-modal: Dar Aviso por email -->
    <dialog ref="avisoModalEl" class="infra-generic-modal aviso-modal" @click.self="closeAvisoModal">
      <div class="modal-inner" v-if="avisoIncidente">
        <div class="modal-header-row">
          <h3 class="modal-title">📧 Dar Aviso — {{ avisoIncidente.ticket_asociado || 'Sin ticket' }}</h3>
          <button class="close-btn" @click="closeAvisoModal">×</button>
        </div>
        <div v-if="avisoLoadingTemplate" class="aviso-loading-template">⏳ Cargando plantilla...</div>
        <template v-else>
          <label class="form-label">Destinatarios <span class="req">*</span> <span class="aviso-hint">(separados por coma)</span></label>
          <input v-model="avisoForm.to" type="text" placeholder="operador@empresa.com, supervisor@empresa.com" />
          <label class="form-label">Con copia (CC) <span class="aviso-hint">(opcional)</span></label>
          <input v-model="avisoForm.cc" type="text" placeholder="noc@empresa.com" />
          <label class="form-label">Asunto <span class="req">*</span></label>
          <input v-model="avisoForm.subject" type="text" />
          <label class="form-label">Cuerpo del mensaje <span class="req">*</span> <span class="aviso-hint">(editable)</span></label>
          <textarea v-model="avisoForm.body" rows="11" class="aviso-body-textarea"></textarea>
          <div class="aviso-options">
            <label class="aviso-checkbox-row">
              <input v-model="avisoForm.include_xls" type="checkbox" />
              <span>Adjuntar resumen XLS</span>
            </label>
            <label class="aviso-checkbox-row">
              <input v-model="avisoForm.include_txt" type="checkbox" />
              <span>Adjuntar tracking TXT</span>
            </label>
          </div>
          <div class="modal-actions">
            <button class="btn subtle" :disabled="avisoSending" @click="closeAvisoModal">Cancelar</button>
            <button
              class="btn primary small"
              :disabled="avisoSending"
              @click="downloadEml"
            >📥 Descargar EML</button>
            <button
              class="btn warning"
              :disabled="avisoSending || !avisoForm.to.trim() || !avisoForm.subject.trim() || !avisoForm.body.trim()"
              @click="sendAviso"
            >{{ avisoSending ? 'Enviando...' : '📧 Enviar Aviso' }}</button>
          </div>
        </template>
      </div>
    </dialog>

    <!-- Modal: Limpiar servicio -->
    <dialog ref="limpiarModalEl" class="infra-generic-modal" @click.self="closeLimpiarModal">
      <div class="modal-inner">
        <div class="modal-header-row">
          <h3 class="modal-title">🗑 Limpiar Servicio</h3>
          <button class="close-btn" @click="closeLimpiarModal">×</button>
        </div>
        <p class="modal-desc danger-text">⚠️ Operación destructiva e irreversible. Se eliminarán todas las asociaciones de empalmes y rutas del servicio.</p>
        <label class="form-label">ID del servicio <span class="req">*</span></label>
        <input v-model="limpiarServicioId" type="text" placeholder="Ej: 52547" />
        <div class="modal-actions">
          <button
            class="btn danger"
            :disabled="limpiarLoading || !limpiarServicioId.trim()"
            @click="submitLimpiar"
          >{{ limpiarLoading ? 'Limpiando...' : 'Limpiar servicio' }}</button>
          <button class="btn subtle" @click="closeLimpiarModal">Cancelar</button>
        </div>
      </div>
    </dialog>

    <!-- Main content -->
    <div class="infra-panel">
      <header class="infra-header">
        <div>
          <span class="infra-kicker">Planta externa</span>
          <h1>Infraestructura FO</h1>
        </div>
        <div class="infra-toolbar-actions">
          <button class="btn danger" @click="openBanModal">
            <i class="ph ph-shield-warning" aria-hidden="true"></i>
            Protocolo Protección
          </button>
          <button class="btn subtle active-bans-btn" @click="openActiveBansModal">
            <i class="ph ph-lock-key" aria-hidden="true"></i>
            Baneos activos
            <span v-if="activeBans.length > 0" class="active-bans-badge">{{ activeBans.length }}</span>
          </button>
          <div
            class="btn subtle upload-drop-zone"
            :class="{ 'drag-over': isDragOver }"
            role="button"
            tabindex="0"
            @click="triggerUploadTracking"
            @keydown.enter.prevent="triggerUploadTracking"
            @keydown.space.prevent="triggerUploadTracking"
            @dragover.prevent="onDragOver"
            @dragenter.prevent="onDragEnter"
            @dragleave="onDragLeave"
            @drop.prevent="onDrop"
          >
            <i class="ph ph-folder-simple-plus" aria-hidden="true"></i>
            Subir tracking
          </div>
          <button class="btn subtle" @click="openLimpiarModal">
            <i class="ph ph-eraser" aria-hidden="true"></i>
            Limpiar servicio
          </button>
          <div class="download-dropdown-wrapper" ref="downloadDropdownEl">
            <button class="btn primary" @click.stop="toggleDownloadMenu">
              <i class="ph ph-download-simple" aria-hidden="true"></i>
              Descargar
              <i :class="['ph', 'ph-caret-down', 'dropdown-caret', { open: isDownloadMenuOpen }]" aria-hidden="true"></i>
            </button>
            <ul v-if="isDownloadMenuOpen" class="download-dropdown-menu" @click.stop>
              <li class="dropdown-item" @click="downloadCameras('xlsx', null)"><i class="ph ph-file-xls" aria-hidden="true"></i>Todas (XLSX)</li>
              <li class="dropdown-item" @click="downloadCameras('csv', null)"><i class="ph ph-file-csv" aria-hidden="true"></i>Todas (CSV)</li>
              <li class="dropdown-divider"></li>
              <li class="dropdown-item" @click="downloadCameras('xlsx', 'BANEADA')"><span class="infra-legend-dot baneada"></span>Solo Baneadas</li>
              <li class="dropdown-item" @click="downloadCameras('xlsx', 'OCUPADA')"><span class="infra-legend-dot ocupada"></span>Con Ingreso</li>
            </ul>
          </div>
        </div>
      </header>

      <hr class="noc-rule" />

      <div class="infra-search-area">
        <div class="fop-search-row">
          <div class="fop-search-input">
            <i class="ph ph-magnifying-glass" aria-hidden="true"></i>
            <input
              v-model="searchInput"
              type="text"
              placeholder="Buscar por nombre, dirección, servicio…"
              @keydown.enter="addTerm"
            />
          </div>
          <button class="btn subtle" @click="addTerm">Agregar término</button>
          <button class="btn primary" :disabled="loading || (searchTerms.length === 0 && !activeStateFilter)" @click="searchCamaras">
            <i class="ph ph-magnifying-glass" aria-hidden="true"></i>
            Buscar
          </button>
          <button class="btn infra-btn-ghost" @click="clearAll">Limpiar</button>
        </div>

        <div class="infra-chips-row">
          <span v-if="searchTerms.length" class="fop-search-terms">
            <span v-for="(term, i) in searchTerms" :key="i" class="fop-search-term">
              <span class="fop-search-term-value">{{ term }}</span>
              <button class="fop-search-term-remove" @click="removeTerm(i)">×</button>
            </span>
          </span>

          <span v-if="searchTerms.length" class="infra-chips-separator" aria-hidden="true"></span>

          <button
            v-for="item in legendItems"
            :key="item.estado"
            type="button"
            :class="['infra-legend-item', { active: activeStateFilter === item.estado }]"
            @click="toggleStateFilter(item.estado)"
          >
            <span v-if="item.estado !== 'TRACKING'" :class="['infra-legend-dot', item.dotClass]"></span>
            <i v-else class="ph ph-map-pin" aria-hidden="true"></i>
            {{ item.estado }}
            <span class="infra-legend-count">{{ legendCounts[item.estado] ?? 0 }}</span>
          </button>

          <span class="infra-count">
            <strong>{{ filteredCamaras.length }}</strong> cámaras
          </span>
        </div>

        <div v-if="statusText" :class="['fop-status', statusVariant]">{{ statusText }}</div>
      </div>

      <div v-if="loading" class="infra-state-box">
        <i class="ph ph-circle-notch infra-spin" aria-hidden="true"></i>
        Buscando...
      </div>
      <div v-else-if="!hasSearched" class="infra-state-box">
        <i class="ph ph-magnifying-glass" aria-hidden="true"></i>
        <p>Agregá términos de búsqueda y presioná "Buscar"</p>
      </div>
      <div v-else-if="camaras.length === 0" class="infra-state-box">
        <i class="ph ph-magnifying-glass" aria-hidden="true"></i>
        <p>Sin resultados para estos términos.</p>
      </div>
      <div v-else-if="filteredCamaras.length === 0" class="infra-state-box">
        <i class="ph ph-map-pin" aria-hidden="true"></i>
        <p>Sin cámaras en TRACKING con los términos actuales.</p>
      </div>
      <div v-else class="fop-grid">
        <article
          v-for="camara in filteredCamaras"
          :key="camara.id"
          class="fop-camara-card"
          :data-estado="camara.estado ?? 'LIBRE'"
          :data-inconsistente="camara.inconsistente ? 'true' : 'false'"
        >
          <div class="infra-camara-row">
            <span :class="['infra-camara-dot', estadoDotClass(camara.estado)]" aria-hidden="true"></span>
            <span class="infra-camara-estado-text">{{ camara.estado || 'LIBRE' }}</span>
            <span v-if="camara.id != null" class="fop-camara-id">{{ camaraIdLabel(camara) }}</span>
          </div>

          <h3 class="fop-camara-nombre">{{ camara.nombre || camara.direccion || 'Sin nombre' }}</h3>

          <div class="infra-camara-hairline"></div>

          <div class="infra-camara-row">
            <span class="fop-camara-meta">{{ camaraMeta(camara) }}</span>
            <RouterLink
              v-if="camara.id != null"
              class="fop-edit-btn"
              :to="`/infra/Camaras/${camara.id}`"
            >Detalle</RouterLink>
          </div>
        </article>
      </div>
    </div>
  </article>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { useSession } from '../../composables/useSession';

const { state, csrf } = useSession();
const isAdmin = computed(() => (state.value.role ?? '').toLowerCase() === 'admin');

// --- Toast ---
interface Toast { id: number; type: string; title: string; message?: string }
const toasts = ref<Toast[]>([]);
let _toastId = 0;
function showToast(type: string, title: string, message?: string, duration = 5000) {
  const id = ++_toastId;
  toasts.value.push({ id, type, title, message });
  if (duration > 0) setTimeout(() => removeToast(id), duration);
}
function removeToast(id: number) {
  const i = toasts.value.findIndex(t => t.id === id);
  if (i !== -1) toasts.value.splice(i, 1);
}
function toastIcon(type: string) {
  return { success: '✓', error: '✗', warning: '⚠', info: 'ℹ' }[type] ?? 'ℹ';
}

// --- Search ---
const searchInput = ref('');
const searchTerms = ref<string[]>([]);
const camaras = ref<Record<string, unknown>[]>([]);
const loading = ref(false);
const hasSearched = ref(false);
const statusText = ref('');
const statusVariant = ref('muted');

function setStatus(text: string, variant = 'muted') {
  statusText.value = text;
  statusVariant.value = variant;
}

function addTerm() {
  const val = searchInput.value.trim();
  if (!val) return;
  if (searchTerms.value.some(t => t.toLowerCase() === val.toLowerCase())) {
    showToast('warning', 'Término duplicado', 'Este término ya está activo');
    return;
  }
  searchTerms.value.push(val);
  searchInput.value = '';
}

function removeTerm(i: number) {
  searchTerms.value.splice(i, 1);
}

function clearAll() {
  searchTerms.value = [];
  searchInput.value = '';
  camaras.value = [];
  hasSearched.value = false;
  activeStateFilter.value = null;
  setStatus('');
}

// --- Filtro rápido por estado ---
const activeStateFilter = ref<string | null>(null);

function toggleStateFilter(estado: string) {
  activeStateFilter.value = activeStateFilter.value === estado ? null : estado;
  // Si ya hay resultados, el computed filtra instantáneamente sin nueva llamada.
  // Si no hay resultados aún (primera interacción), disparar búsqueda "traer todo".
  if (activeStateFilter.value !== null && !hasSearched.value) {
    searchCamaras();
  }
}

// El filtro de estado se aplica en el servidor (salvo TRACKING, que depende de la relación rutas).
// Este computed solo filtra client-side para el caso especial TRACKING.
const filteredCamaras = computed(() => {
  if (activeStateFilter.value === 'TRACKING') {
    return camaras.value.filter(c => ((c.rutas as unknown[]) ?? []).length > 0);
  }
  return camaras.value;
});

const legendItems = [
  { estado: 'LIBRE', dotClass: 'libre' },
  { estado: 'OCUPADA', dotClass: 'ocupada' },
  { estado: 'BANEADA', dotClass: 'baneada' },
  { estado: 'DETECTADA', dotClass: 'detectada' },
  { estado: 'TRACKING', dotClass: 'tracking' },
];

const legendCounts = computed<Record<string, number>>(() => {
  const counts: Record<string, number> = { LIBRE: 0, OCUPADA: 0, BANEADA: 0, DETECTADA: 0, TRACKING: 0 };
  for (const camara of camaras.value) {
    const estado = String(camara.estado ?? 'LIBRE').toUpperCase();
    if (estado in counts) counts[estado] += 1;
    if (((camara.rutas as unknown[]) ?? []).length > 0) counts.TRACKING += 1;
  }
  return counts;
});

function estadoDotClass(estado: unknown): string {
  const value = String(estado ?? 'libre').toLowerCase();
  return ['libre', 'ocupada', 'baneada', 'detectada'].includes(value) ? value : 'libre';
}

function camaraMeta(camara: Record<string, unknown>): string {
  const servicios = ((camara.servicios as unknown[]) ?? []).length;
  const botellas = Number(camara.botellas_count ?? 0);
  const partes: string[] = [];
  if (botellas > 0) partes.push(`${botellas} botella${botellas !== 1 ? 's' : ''}`);
  partes.push(servicios > 0 ? `${servicios} servicio${servicios !== 1 ? 's' : ''}` : 'Sin relevar');
  return partes.join(' · ');
}

function camaraIdLabel(camara: Record<string, unknown>): string {
  // Etapa Cámara/Botella: fallback al ID interno — el ID de Cromo/Fontine aún no está garantizado
  // para todas las cámaras (hoy 0% poblado en dev, ver docs/infra.md).
  const fontineId = camara.fontine_id;
  if (typeof fontineId === 'string' && fontineId.trim()) return fontineId;
  return `ID ${camara.id}`;
}

async function searchCamaras() {
  // Permitir la búsqueda si hay términos de texto O si hay un filtro de estado activo.
  // Con terms:[] la API devuelve todas las cámaras (ver SmartSearchRequestModel).
  if (searchTerms.value.length === 0 && !activeStateFilter.value) return;
  loading.value = true;
  hasSearched.value = true;
  const statusMsg = searchTerms.value.length > 0
    ? `Buscando con ${searchTerms.value.length} término(s)...`
    : `Cargando cámaras ${activeStateFilter.value}...`;
  setStatus(statusMsg, 'loading');
  try {
    const res = await fetch('/api/infra/smart-search', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({
        terms: searchTerms.value,
        limit: activeStateFilter.value === 'TRACKING' ? 500 : 100,
        offset: 0,
        // Para TRACKING no enviamos estado al backend (no es un CamaraEstado enum); filtramos client-side.
        ...(activeStateFilter.value && activeStateFilter.value !== 'TRACKING'
          ? { estado: activeStateFilter.value }
          : {}),
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error((err as Record<string, string>).detail ?? (err as Record<string, string>).error ?? `Error ${res.status}`);
    }
    const data = await res.json();
    camaras.value = data.camaras ?? [];
    const count = camaras.value.length;
    const total = data.total ?? count;
    setStatus(
      count === 0
        ? 'Sin resultados para estos términos'
        : total > count
          ? `Mostrando ${count} de ${total} cámaras`
          : `${count} cámara${count !== 1 ? 's' : ''} encontrada${count !== 1 ? 's' : ''}`,
      count > 0 ? 'success' : 'muted',
    );
  } catch (e: unknown) {
    camaras.value = [];
    setStatus(`Error: ${e instanceof Error ? e.message : String(e)}`, 'error');
  } finally {
    loading.value = false;
  }
}

// --- Camera cards ---
const RUTA_COLORS: Record<string, string> = {
  PRINCIPAL: '#3B82F6',
  BACKUP: '#37BC7D',
  ALTERNATIVA: '#F54927',
  CUARTO: '#E61876',
};

// --- Protocolo de Protección (ban) — Wizard 3 pasos ---
interface BanFormData {
  ticket_asociado: string;
  servicio_afectado_id: string;
  servicio_protegido_id: string;
  motivo: string;
  usuario_ejecutor: string;
}
interface BanRutaOption {
  id: number;
  nombre: string;
  tipo: string;
  empalmes_count: number;
  activa: boolean;
  hash_contenido: string | null;
}

const banModalEl = ref<HTMLDialogElement | null>(null);
const banLoading = ref(false);
const currentBanStep = ref<1 | 2 | 3>(1);
const banProtMode = ref<'same' | 'other'>('same');
const banSearchServicioInput = ref('');
const banRutas = ref<BanRutaOption[]>([]);
const banLoadingRutas = ref(false);
const banRutasError = ref('');
const banSelectedRutaId = ref<number | null>(null);
const banConfirmChecked = ref(false);

function resetBanModalState() {
  banForm.value = { ticket_asociado: '', servicio_afectado_id: '', servicio_protegido_id: '', motivo: '', usuario_ejecutor: '' };
  currentBanStep.value = 1;
  banProtMode.value = 'same';
  banSearchServicioInput.value = '';
  banRutas.value = [];
  banLoadingRutas.value = false;
  banRutasError.value = '';
  banSelectedRutaId.value = null;
  banConfirmChecked.value = false;
}

const banForm = ref<BanFormData>({
  ticket_asociado: '',
  servicio_afectado_id: '',
  servicio_protegido_id: '',
  motivo: '',
  usuario_ejecutor: '',
});

const banEstimatedCamaras = computed<number>(() => {
  if (banSelectedRutaId.value === null) {
    return banRutas.value.filter(r => r.activa).reduce((s, r) => s + r.empalmes_count, 0);
  }
  return banRutas.value.find(r => r.id === banSelectedRutaId.value)?.empalmes_count ?? 0;
});

function openBanModal() {
  resetBanModalState();
  banModalEl.value?.showModal();
}

function closeBanModal(force = false) {
  if (banLoading.value && !force) return;
  banModalEl.value?.close();
  resetBanModalState();
}

async function loadRutasForBan(servicioId: string) {
  if (!servicioId) return;
  banLoadingRutas.value = true;
  banRutasError.value = '';
  banRutas.value = [];
  banSelectedRutaId.value = null;
  banForm.value.servicio_protegido_id = servicioId;
  try {
    const res = await fetch(`/api/infra/servicios/${encodeURIComponent(servicioId)}/rutas`, { credentials: 'include' });
    const data = await res.json() as { rutas?: BanRutaOption[]; detail?: string };
    if (!res.ok) throw new Error(data.detail ?? `Error ${res.status}`);
    banRutas.value = data.rutas ?? [];
    if (banRutas.value.length === 0) banRutasError.value = `El servicio ${servicioId} no tiene rutas registradas.`;
  } catch (e: unknown) {
    banRutasError.value = e instanceof Error ? e.message : String(e);
    banForm.value.servicio_protegido_id = '';
  } finally {
    banLoadingRutas.value = false;
  }
}

function banSwitchMode(mode: 'same' | 'other') {
  if (banProtMode.value === mode) return;
  banProtMode.value = mode;
  banRutas.value = [];
  banRutasError.value = '';
  banSelectedRutaId.value = null;
  banSearchServicioInput.value = '';
  banForm.value.servicio_protegido_id = '';
  if (mode === 'same') {
    void loadRutasForBan(banForm.value.servicio_afectado_id.trim());
  }
}

async function banGoNext() {
  if (currentBanStep.value === 1) {
    if (!banForm.value.servicio_afectado_id.trim()) {
      showToast('warning', 'Campo requerido', 'Ingresá el ID del servicio afectado');
      return;
    }
    currentBanStep.value = 2;
    if (banProtMode.value === 'same') {
      await loadRutasForBan(banForm.value.servicio_afectado_id.trim());
    }
  } else if (currentBanStep.value === 2) {
    if (!banForm.value.servicio_protegido_id.trim()) {
      showToast('warning', 'Servicio requerido', banProtMode.value === 'other' ? 'Buscá un servicio para proteger' : 'No se pudo cargar el servicio');
      return;
    }
    currentBanStep.value = 3;
  }
}

function banGoPrev() {
  if (currentBanStep.value > 1) currentBanStep.value = (currentBanStep.value - 1) as 1 | 2 | 3;
}

// Descarga tracking de una ruta directamente (sin abrir el modal de tracking)
async function downloadTrackingByRutaId(rutaId: number) {
  try {
    const res = await fetch(`/api/infra/tracking/${rutaId}/download`, { credentials: 'include' });
    if (res.status === 404) { showToast('warning', 'Sin archivo', 'El TXT original no está disponible'); return; }
    if (!res.ok) throw new Error(`Error ${res.status}`);
    const blob = await res.blob();
    const cd = res.headers.get('Content-Disposition') ?? '';
    const match = cd.match(/filename="(.+?)"/);
    const filename = match ? match[1] : `tracking_ruta_${rutaId}.txt`;
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename; document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast('success', 'Descarga completa', filename);
  } catch (e: unknown) {
    showToast('error', 'Error de descarga', e instanceof Error ? e.message : String(e));
  }
}

// Abre el flujo de upload tracking desde el wizard de ban
function triggerUploadTrackingForBan(_rutaId: number) {
  banModalEl.value?.close();
  trackingFileInputEl.value?.click();
}

// --- Baneos Activos ---
interface IncidenteActivo {
  id: number;
  ticket_asociado: string | null;
  servicio_afectado_id: string;
  servicio_protegido_id: string;
  ruta_protegida_id: number | null;
  usuario_ejecutor: string | null;
  motivo: string | null;
  fecha_inicio: string | null;
  activo: boolean;
  duracion_horas: number | null;
  camaras_count: number;
}

const activeBansModalEl = ref<HTMLDialogElement | null>(null);
const activeBans = ref<IncidenteActivo[]>([]);
const activeBansLoading = ref(false);
const activeBansError = ref('');
const liftLoadingId = ref<number | null>(null);
const avisoLoadingId = ref<number | null>(null);

// Sub-modal Dar Aviso
const avisoModalEl = ref<HTMLDialogElement | null>(null);
const avisoIncidente = ref<IncidenteActivo | null>(null);
const avisoSending = ref(false);
const avisoLoadingTemplate = ref(false);
interface AvisoForm {
  to: string;
  cc: string;
  subject: string;
  body: string;
  include_xls: boolean;
  include_txt: boolean;
}
const avisoForm = ref<AvisoForm>({
  to: '', cc: '', subject: '', body: '', include_xls: true, include_txt: true,
});

// --- Plantilla por defecto ---
function buildAvisoBody(inc: IncidenteActivo, fechaHora: string): string {
  const lineas = [
    'Estimados,',
    '',
    'Se les informa que se ha activado el Protocolo de Protección en la red de fibra óptica debido a una afectación de servicio.',
    '',
    'DATOS DEL INCIDENTE:',
    `• Ticket: ${inc.ticket_asociado ?? 'Sin ticket'}`,
    `• Servicio Afectado: ${inc.servicio_afectado_id}`,
    `• Servicio Protegido: ${inc.servicio_protegido_id}`,
    `• Cámaras Restringidas: ${inc.camaras_count} cámara${inc.camaras_count !== 1 ? 's' : ''}`,
    `• Fecha/Hora: ${fechaHora}`,
    `• Motivo: ${inc.motivo ?? 'No especificado'}`,
    '',
    'Se adjunta el listado detallado de cámaras restringidas (Excel) y el archivo de tracking original.',
    '',
    'Por favor, tomar las precauciones necesarias y abstenerse de realizar trabajos en las cámaras listadas hasta nuevo aviso.',
    '',
    'Saludos cordiales,',
    'Operaciones de Red',
    'Metrotel S.A.',
    '',
    'Generado por LAS-FOCAS - Metrotel',
  ];
  return lineas.join('\n');
}

function saveAvisoDestinatarios() {
  try {
    localStorage.setItem('focas_baneo_to', avisoForm.value.to.trim());
    localStorage.setItem('focas_baneo_cc', avisoForm.value.cc.trim());
  } catch { /* localStorage no disponible */ }
}

function formatDuracion(horas: number | null): string {
  if (horas === null || horas === undefined) return '';
  if (horas < 1) return `${Math.round(horas * 60)} min`;
  return `${horas.toFixed(1)} h`;
}

function formatFecha(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

async function loadActiveBans() {
  activeBansLoading.value = true;
  activeBansError.value = '';
  try {
    const res = await fetch('/api/infra/ban/active', { credentials: 'include' });
    const data = await res.json();
    if (!res.ok) throw new Error((data as Record<string, string>).detail ?? `Error ${res.status}`);
    activeBans.value = (data as { incidentes: IncidenteActivo[] }).incidentes ?? [];
  } catch (e: unknown) {
    activeBansError.value = e instanceof Error ? e.message : String(e);
  } finally {
    activeBansLoading.value = false;
  }
}

function openActiveBansModal() {
  activeBansError.value = '';
  activeBansModalEl.value?.showModal();
  void loadActiveBans();
}

function closeActiveBansModal() {
  activeBansModalEl.value?.close();
}

async function confirmLiftBan(inc: IncidenteActivo) {
  const ticket = inc.ticket_asociado ? `#${inc.ticket_asociado}` : `ID ${inc.id}`;
  if (!window.confirm(`¿Levantar el baneo ${ticket}?\n\nSe restaurarán las cámaras del servicio ${inc.servicio_protegido_id} y se notificará en Slack.`)) return;
  liftLoadingId.value = inc.id;
  try {
    const res = await fetch('/api/infra/ban/lift', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'X-CSRF-Token': csrf() },
      body: JSON.stringify({ incidente_id: inc.id }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error((data as Record<string, string>).detail ?? `Error ${res.status}`);
    showToast('success', 'Baneo levantado', `Servicio ${inc.servicio_protegido_id} restaurado`);
    await loadActiveBans();
    if (hasSearched.value) await searchCamaras();
  } catch (e: unknown) {
    showToast('error', 'Error al levantar baneo', e instanceof Error ? e.message : String(e));
  } finally {
    liftLoadingId.value = null;
  }
}

async function openAvisoModal(inc: IncidenteActivo) {
  avisoIncidente.value = inc;
  avisoLoadingId.value = inc.id;
  avisoLoadingTemplate.value = true;
  avisoForm.value.include_xls = true;
  avisoForm.value.include_txt = true;

  // Restaurar destinatarios desde localStorage
  try {
    avisoForm.value.to = localStorage.getItem('focas_baneo_to') ?? '';
    avisoForm.value.cc = localStorage.getItem('focas_baneo_cc') ?? '';
  } catch {
    avisoForm.value.to = '';
    avisoForm.value.cc = '';
  }

  // Plantilla por defecto con datos del incidente
  const ahora = new Date().toLocaleString('es-AR', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  });
  avisoForm.value.subject = '[AVISO] BANEO de Camaras';
  avisoForm.value.body = buildAvisoBody(inc, ahora);

  // Intentar sobreescribir con plantilla guardada en el backend
  try {
    const res = await fetch(`/api/infra/ban/${inc.id}`, { credentials: 'include' });
    if (res.ok) {
      const det = await res.json() as { email_subject?: string | null; email_body?: string | null };
      if (det.email_subject) avisoForm.value.subject = det.email_subject;
      if (det.email_body) avisoForm.value.body = det.email_body;
    }
  } catch { /* usar plantilla local */ }

  avisoLoadingTemplate.value = false;
  avisoLoadingId.value = null;
  avisoModalEl.value?.showModal();
}

function closeAvisoModal() {
  avisoModalEl.value?.close();
  avisoIncidente.value = null;
}

async function sendAviso() {
  if (!avisoIncidente.value) return;
  const toList = avisoForm.value.to.split(',').map(s => s.trim()).filter(Boolean);
  const ccList = avisoForm.value.cc.split(',').map(s => s.trim()).filter(Boolean);
  if (toList.length === 0) {
    showToast('warning', 'Destinatarios requeridos', 'Ingresá al menos un destinatario');
    return;
  }
  saveAvisoDestinatarios();
  avisoSending.value = true;
  try {
    const payload = {
      to: toList,
      cc: ccList.length ? ccList : undefined,
      subject: avisoForm.value.subject.trim(),
      body: avisoForm.value.body.trim(),
      incidente_ids: [avisoIncidente.value.id],
      include_xls: avisoForm.value.include_xls,
      include_txt: avisoForm.value.include_txt,
    };
    const res = await fetch('/api/infra/notify/email', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'X-CSRF-Token': csrf() },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok || !(data as { success: boolean }).success) {
      throw new Error((data as Record<string, string>).error ?? (data as Record<string, string>).detail ?? `Error ${res.status}`);
    }
    closeAvisoModal();
    showToast('success', 'Aviso enviado', `Notificación enviada a ${toList.length} destinatario${toList.length !== 1 ? 's' : ''}`);
  } catch (e: unknown) {
    showToast('error', 'Error al enviar aviso', e instanceof Error ? e.message : String(e));
  } finally {
    avisoSending.value = false;
  }
}

async function downloadEml() {
  if (!avisoIncidente.value) return;
  saveAvisoDestinatarios();
  const toList = avisoForm.value.to.split(',').map(s => s.trim()).filter(Boolean);
  const fd = new FormData();
  fd.append('incident_id', String(avisoIncidente.value.id));
  if (toList.length) fd.append('recipients', toList.join(', '));
  if (avisoForm.value.subject.trim()) fd.append('subject', avisoForm.value.subject.trim());
  if (avisoForm.value.body.trim()) fd.append('html_body', avisoForm.value.body.trim());
  try {
    const res = await fetch('/api/infra/notify/download-eml', {
      method: 'POST',
      credentials: 'include',
      body: fd,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error((err as Record<string, string>).detail ?? `Error ${res.status}`);
    }
    const blob = await res.blob();
    const cd = res.headers.get('Content-Disposition') ?? '';
    const match = cd.match(/filename="(.+?)"/);
    const filename = match ? match[1] : `aviso_baneo_${avisoIncidente.value.id}.eml`;
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename; document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast('success', 'EML descargado', filename);
  } catch (e: unknown) {
    showToast('error', 'Error al generar EML', e instanceof Error ? e.message : String(e));
  }
}

async function submitBan() {
  if (!banForm.value.servicio_afectado_id.trim() || !banForm.value.servicio_protegido_id.trim()) {
    showToast('warning', 'Campos requeridos', 'Faltan datos del servicio');
    return;
  }
  banLoading.value = true;
  try {
    const payload = {
      ticket_asociado: banForm.value.ticket_asociado.trim() || null,
      servicio_afectado_id: banForm.value.servicio_afectado_id.trim(),
      servicio_protegido_id: banForm.value.servicio_protegido_id.trim(),
      ruta_protegida_id: banSelectedRutaId.value,
      motivo: banForm.value.motivo.trim() || null,
      usuario_ejecutor: banForm.value.usuario_ejecutor.trim() || null,
    };
    const res = await fetch('/api/infra/ban/create', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'X-CSRF-Token': csrf() },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error((data as Record<string, string>).detail ?? `Error ${res.status}`);
    closeBanModal(true);
    const baneadas = (data as Record<string, number>).camaras_baneadas ?? 0;
    showToast('success', 'Protocolo activado', `${baneadas} cámara(s) baneadas`);
    if (hasSearched.value) await searchCamaras();
  } catch (e: unknown) {
    showToast('error', 'Error al activar protocolo', e instanceof Error ? e.message : String(e));
  } finally {
    banLoading.value = false;
  }
}

// --- Upload Tracking (flujo Portero 2 fases) ---
interface RutaInfo {
  id: number; nombre: string; tipo: string; empalmes_count: number; activa: boolean;
}
interface UpgradeInfo {
  old_service_id: string; old_service_db_id: number; new_service_id: string;
  match_reason: string; punta_a_match?: string | null; punta_b_match?: string | null;
}
interface StrandInfo {
  service_id: string; service_db_id: number; ruta_id: number;
  current_strands: number; new_strand_pelo?: string | null;
}
interface AnalyzeResult {
  status: string; servicio_id?: string | null; servicio_db_id?: number | null;
  rutas_existentes: RutaInfo[]; parsed_empalmes_count: number; message: string;
  error?: string | null; upgrade_info?: UpgradeInfo | null; strand_info?: StrandInfo | null;
  punta_a_sitio?: string | null; punta_b_sitio?: string | null;
}

const trackingFileInputEl = ref<HTMLInputElement | null>(null);
const trackingResolveModalEl = ref<HTMLDialogElement | null>(null);
const uploadAnalyzing = ref(false);
const uploadResolving = ref(false);
const analyzeResult = ref<AnalyzeResult | null>(null);
const fileContent = ref('');
const fileName = ref('');
const resolveTargetRutaId = ref<number | null>(null);
const resolveNewRutaNombre = ref('');

function triggerUploadTracking() {
  trackingFileInputEl.value?.click();
}

// --- Drag & Drop para la zona de upload de tracking ---
const isDragOver = ref(false);

function onDragOver() {
  isDragOver.value = true;
}

function onDragEnter() {
  isDragOver.value = true;
}

function onDragLeave(e: DragEvent) {
  // Solo desactivar si el mouse salió del wrapper completo
  const target = e.currentTarget as HTMLElement;
  if (!target.contains(e.relatedTarget as Node)) {
    isDragOver.value = false;
  }
}

function onDrop(e: DragEvent) {
  isDragOver.value = false;
  const file = e.dataTransfer?.files?.[0];
  if (!file) return;
  if (!file.name.toLowerCase().endsWith('.txt')) {
    showToast('warning', 'Archivo inválido', 'Solo se aceptan archivos .txt');
    return;
  }
  const reader = new FileReader();
  reader.onload = (ev) => {
    fileContent.value = (ev.target?.result as string) ?? '';
    fileName.value = file.name;
    void analyzeTracking();
  };
  reader.readAsText(file, 'utf-8');
}

function handleTrackingFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = '';
  if (!file) return;
  if (!file.name.toLowerCase().endsWith('.txt')) {
    showToast('warning', 'Archivo inválido', 'Solo se aceptan archivos .txt');
    return;
  }
  const reader = new FileReader();
  reader.onload = (e) => {
    fileContent.value = (e.target?.result as string) ?? '';
    fileName.value = file.name;
    void analyzeTracking();
  };
  reader.readAsText(file, 'utf-8');
}

async function analyzeTracking() {
  uploadAnalyzing.value = true;
  analyzeResult.value = null;
  resolveTargetRutaId.value = null;
  resolveNewRutaNombre.value = '';
  trackingResolveModalEl.value?.showModal();
  try {
    const blob = new Blob([fileContent.value], { type: 'text/plain' });
    const formData = new FormData();
    formData.append('file', blob, fileName.value);
    const res = await fetch('/api/infra/trackings/analyze', {
      method: 'POST',
      credentials: 'include',
      headers: { Accept: 'application/json' },
      body: formData,
    });
    const data = await res.json();
    if (!res.ok) throw new Error((data as Record<string, string>).detail ?? `Error ${res.status}`);
    analyzeResult.value = data as AnalyzeResult;
    if (analyzeResult.value.rutas_existentes?.length) {
      resolveTargetRutaId.value = analyzeResult.value.rutas_existentes[0].id;
    }
  } catch (e: unknown) {
    analyzeResult.value = {
      status: 'ERROR', message: 'Error analizando el archivo',
      parsed_empalmes_count: 0, rutas_existentes: [],
      error: e instanceof Error ? e.message : String(e),
    };
  } finally {
    uploadAnalyzing.value = false;
  }
}

async function resolveTracking(action: string, extras: Record<string, unknown> = {}) {
  uploadResolving.value = true;
  try {
    const body: Record<string, unknown> = {
      action,
      content: fileContent.value,
      filename: fileName.value,
      ...extras,
    };
    const res = await fetch('/api/infra/trackings/resolve', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'X-CSRF-Token': csrf() },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error((data as Record<string, string>).detail ?? `Error ${res.status}`);
    if (!(data as Record<string, boolean>).success) {
      throw new Error((data as Record<string, string>).error ?? 'Error al resolver el tracking');
    }
    closeUploadModal();
    showToast('success', 'Tracking procesado', (data as Record<string, string>).message ?? '');
    if (hasSearched.value) await searchCamaras();
  } catch (e: unknown) {
    showToast('error', 'Error al procesar tracking', e instanceof Error ? e.message : String(e));
  } finally {
    uploadResolving.value = false;
  }
}

function closeUploadModal() {
  trackingResolveModalEl.value?.close();
  uploadAnalyzing.value = false;
  analyzeResult.value = null;
  fileContent.value = '';
  fileName.value = '';
  resolveTargetRutaId.value = null;
  resolveNewRutaNombre.value = '';
}

// --- Limpiar servicio ---
const limpiarModalEl = ref<HTMLDialogElement | null>(null);
const limpiarServicioId = ref('');
const limpiarLoading = ref(false);

function openLimpiarModal() {
  limpiarServicioId.value = '';
  limpiarModalEl.value?.showModal();
}

function closeLimpiarModal() {
  limpiarModalEl.value?.close();
}

async function submitLimpiar() {
  const svcId = limpiarServicioId.value.trim();
  if (!svcId) return;
  limpiarLoading.value = true;
  try {
    const res = await fetch(`/api/infra/servicios/${encodeURIComponent(svcId)}/empalmes`, {
      method: 'DELETE',
      credentials: 'include',
      headers: { Accept: 'application/json', 'X-CSRF-Token': csrf() },
    });
    const data = await res.json();
    if (!res.ok) throw new Error((data as Record<string, string>).detail ?? `Error ${res.status}`);
    closeLimpiarModal();
    showToast('success', 'Servicio limpiado', (data as Record<string, string>).message ?? '');
    if (hasSearched.value) await searchCamaras();
  } catch (e: unknown) {
    showToast('error', 'Error al limpiar servicio', e instanceof Error ? e.message : String(e));
  } finally {
    limpiarLoading.value = false;
  }
}

// --- Descargar: dropdown de exportación ---
const downloadDropdownEl = ref<HTMLElement | null>(null);
const isDownloadMenuOpen = ref(false);

function toggleDownloadMenu() {
  isDownloadMenuOpen.value = !isDownloadMenuOpen.value;
}

function _closeDownloadMenu(e: MouseEvent) {
  if (downloadDropdownEl.value && !downloadDropdownEl.value.contains(e.target as Node)) {
    isDownloadMenuOpen.value = false;
  }
}

onMounted(() => document.addEventListener('click', _closeDownloadMenu));
onUnmounted(() => document.removeEventListener('click', _closeDownloadMenu));

async function downloadCameras(format: 'xlsx' | 'csv', filterStatus: string | null) {
  isDownloadMenuOpen.value = false;
  const params = new URLSearchParams({ format });
  if (filterStatus) params.set('filter_status', filterStatus);
  if (!filterStatus && searchTerms.value.length === 1 && /^\d+$/.test(searchTerms.value[0].trim())) {
    params.set('servicio_id', searchTerms.value[0].trim());
  }
  const ext = format === 'csv' ? 'csv' : 'xlsx';
  const filterLabel = filterStatus ? ` (${filterStatus})` : '';
  showToast('info', 'Preparando descarga...', `Exportando cámaras${filterLabel} en ${format.toUpperCase()}`);
  try {
    const res = await fetch(`/api/infra/export/cameras?${params.toString()}`, { credentials: 'include' });
    if (!res.ok) throw new Error(`Error ${res.status}`);
    const blob = await res.blob();
    const cd = res.headers.get('Content-Disposition') ?? '';
    const match = cd.match(/filename="(.+?)"/);
    const filename = match ? match[1] : `camaras_${Date.now()}.${ext}`;
    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = blobUrl; a.download = filename;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(blobUrl);
    showToast('success', 'Descarga completa', filename);
  } catch (e: unknown) {
    showToast('error', 'Error al descargar', e instanceof Error ? e.message : String(e));
  }
}
</script>

<style scoped>
.infra-view { display: flex; flex-direction: column; height: 100%; overflow: hidden; background: var(--color-bg); }
.infra-panel { display: flex; flex-direction: column; height: 100%; overflow: hidden; }
.infra-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; padding: 22px 26px 0; flex-wrap: wrap; }
.infra-kicker { font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--color-accent); }
.infra-header h1 { font-size: 27px; margin: 3px 0 0; }

.infra-search-area { padding: 15px 26px 14px; display: flex; flex-direction: column; gap: 11px; }
.fop-search-row { display: flex; gap: 8px; flex-wrap: wrap; }
.fop-search-input { position: relative; flex: 1; min-width: 220px; }
.fop-search-input i { position: absolute; left: 11px; top: 50%; transform: translateY(-50%); color: var(--color-neutral-500); font-size: 15px; pointer-events: none; }
.fop-search-input input {
  width: 100%; min-height: 38px; padding: 6px 10px 6px 33px; font-size: 14px;
  background: var(--color-surface); border: 1px solid var(--color-divider); border-radius: var(--radius-md);
  color: var(--color-text); caret-color: var(--color-accent);
}
.fop-search-input input:focus-visible { border-color: var(--color-accent); outline-offset: 0; }
.infra-btn-ghost { color: var(--color-accent); padding-inline: 2.8px; background: transparent; }
.infra-btn-ghost:hover { background: transparent; text-decoration: underline; }

.infra-chips-row { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
.fop-search-terms { display: inline-flex; flex-wrap: wrap; gap: 6px; }
.fop-search-term {
  display: inline-flex; align-items: center; gap: 4px;
  background: color-mix(in srgb, var(--color-accent) 12%, transparent); color: var(--color-accent-200);
  border: 1px solid var(--color-accent); border-radius: var(--radius-pill);
  padding: 3px 6px 3px 10px; font-size: 11.5px;
}
.fop-search-term-remove { background: none; border: none; cursor: pointer; color: inherit; padding: 0; line-height: 1; }
.infra-chips-separator { width: 1px; height: 15px; background: var(--color-divider); }
.infra-count { margin-left: auto; font-size: 12px; font-variant-numeric: tabular-nums; color: color-mix(in srgb, var(--color-text) 55%, transparent); white-space: nowrap; }
.infra-count strong { color: var(--color-text); font-weight: 500; }
.fop-status { font-size: 12.5px; color: color-mix(in srgb, var(--color-text) 55%, transparent); }
.fop-status.error { color: var(--color-state-error); }
.fop-status.success { color: var(--color-state-ok); }

.infra-state-box {
  display: flex; flex-direction: column; align-items: center; gap: 8px;
  max-width: 260px; margin: 34px auto; padding: 34px 22px;
  text-align: center; color: color-mix(in srgb, var(--color-text) 48%, transparent); font-size: 12.5px;
}
.infra-state-box i { font-size: 26px; color: var(--color-neutral-600); }
.infra-state-box p { margin: 0; }
.infra-spin { animation: spin 1s linear infinite; }

.fop-grid {
  flex: 1; min-height: 0; overflow: auto;
  display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 11px;
  padding: 12px 26px 30px;
}
@media (max-width: 1280px) { .fop-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 1024px) { .fop-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 700px) { .fop-grid { grid-template-columns: 1fr; } }

.fop-camara-card {
  display: flex; flex-direction: column; gap: 9px;
  padding: 12px 13px 11px; border-radius: var(--radius-md);
  background: var(--color-surface); box-shadow: var(--shadow-sm);
  transition: box-shadow 0.15s ease;
}
.fop-camara-card:hover { box-shadow: 0 0 0 1px var(--color-accent), 0 6px 18px rgba(0, 0, 0, 0.5); }
.infra-camara-row { display: flex; align-items: center; gap: 7px; }
.infra-camara-dot { width: 7px; height: 7px; flex: none; border-radius: 50%; background: var(--color-state-idle); }
.infra-camara-dot.libre { background: var(--color-state-ok); }
.infra-camara-dot.ocupada { background: var(--color-state-warn); }
.infra-camara-dot.baneada { background: var(--color-state-error); }
.infra-camara-dot.detectada { background: var(--color-state-idle); }
.infra-camara-estado-text {
  font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.08em;
  color: color-mix(in srgb, var(--color-text) 62%, transparent);
}
.fop-camara-id { margin-left: auto; font-size: 10.5px; font-variant-numeric: tabular-nums; color: var(--color-neutral-500); }
.fop-camara-nombre {
  margin: 0; min-height: 36px; font-size: 14.5px; font-weight: 500; line-height: 1.25;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.infra-camara-hairline { height: 1px; background: var(--color-divider); }
.fop-camara-meta {
  font-size: 10.5px; color: color-mix(in srgb, var(--color-text) 48%, transparent);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.fop-edit-btn {
  margin-left: auto; flex: none; padding: 3px 9px; border: 1px solid var(--color-accent);
  border-radius: 4px; font-family: var(--font-heading); font-size: 11px; font-weight: 500;
  color: var(--color-accent); text-decoration: none;
}
/* Modal */
.camera-state-modal, .tracking-detail-modal { position: fixed; inset: 0; margin: auto; border: 1px solid var(--border); border-radius: 10px; background: var(--color-surface); color: var(--text); padding: 24px; max-width: 520px; width: 95vw; max-height: 90vh; overflow-y: auto; }
.camera-state-modal::backdrop, .tracking-detail-modal::backdrop { background: rgba(0,0,0,.6); }
.camera-state-title-row { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.camera-state-meta-row { display: flex; gap: 16px; flex-wrap: wrap; font-size: .85rem; margin-bottom: 8px; color: var(--muted); }
.camera-state-badge { padding: 2px 8px; border-radius: 10px; font-size: .75rem; }
.camera-state-badge.ok { background: color-mix(in srgb, var(--color-state-ok) 15%, transparent); color: var(--color-state-ok); }
.camera-state-badge.warning { background: color-mix(in srgb, var(--color-state-warn) 15%, transparent); color: var(--color-state-warn); }
.camera-state-incidents { margin: 12px 0; }
.camera-state-incidents-title { font-size: .8rem; font-weight: 600; color: var(--muted); margin-bottom: 6px; }
.camera-state-incident-item { font-size: .82rem; padding: 6px 0; border-bottom: 1px solid var(--border); display: flex; gap: 12px; flex-wrap: wrap; }
.camera-state-empty { font-size: .82rem; color: var(--muted); margin: 8px 0; }
.camera-state-select { width: 100%; margin: 8px 0 14px; }
.camera-state-actions { display: flex; gap: 8px; margin-top: 14px; }
.close-btn { background: none; border: none; cursor: pointer; color: var(--muted); font-size: 1.3rem; margin-left: auto; }
/* Tracking modal */
.tracking-detail-header { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.tracking-detail-title { margin: 0; font-size: 1rem; flex: 1; }
.tracking-detail-close { background: none; border: none; cursor: pointer; color: var(--muted); font-size: 1.3rem; }
.tracking-download-btn { font-size: .78rem; padding: 4px 10px; background: color-mix(in srgb, var(--color-text) 7%, transparent); border: 1px solid var(--border); border-radius: 6px; cursor: pointer; color: var(--text); }
.tracking-rutas-tabs { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.tracking-ruta-tab { padding: 5px 12px; border-radius: 14px; font-size: .8rem; border: 1px solid var(--border); background: none; cursor: pointer; color: var(--text); }
.tracking-ruta-tab.active { background: var(--tab-color, var(--color-accent)); color: var(--color-neutral-100); border-color: transparent; }
.tracking-sequence { display: flex; flex-direction: column; gap: 6px; }
.tracking-item { display: flex; align-items: flex-start; gap: 8px; font-size: .85rem; padding: 6px 0; border-bottom: 1px solid var(--border); }
.tracking-punta { color: var(--color-accent); }
.tracking-punta-label { font-size: .72rem; color: var(--muted); display: block; }
.tracking-cable { flex-direction: column; gap: 2px; }
.tracking-cable-name { font-weight: 600; }
.tracking-atenuacion { color: var(--color-state-warn); font-size: .78rem; }
.tracking-empalme-id { color: var(--muted); font-size: .75rem; }
.tracking-loading, .tracking-error, .tracking-empty { padding: 16px; color: var(--muted); font-size: .85rem; }
.tracking-error { color: var(--color-state-error); }
/* Toasts */
.toast-container { position: fixed; bottom: 24px; right: 24px; z-index: 9999; display: flex; flex-direction: column; gap: 8px; pointer-events: none; }
.toast { display: flex; align-items: flex-start; gap: 10px; background: var(--color-surface); border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; min-width: 260px; max-width: 380px; pointer-events: all; box-shadow: 0 4px 12px rgba(0,0,0,.4); }
.toast.success { border-left: 3px solid var(--color-state-ok); }
.toast.error { border-left: 3px solid var(--color-state-error); }
.toast.warning { border-left: 3px solid var(--color-state-warn); }
.toast.info { border-left: 3px solid var(--color-accent); }
.toast-icon { font-size: 1rem; line-height: 1; }
.toast-content { flex: 1; }
.toast-title { font-weight: 600; font-size: .88rem; }
.toast-message { font-size: .82rem; color: var(--muted); margin-top: 2px; }
.toast-close { background: none; border: none; cursor: pointer; color: var(--muted); font-size: 1.1rem; padding: 0; }
.toast-anim-enter-active, .toast-anim-leave-active { transition: all .25s ease; }
.toast-anim-enter-from, .toast-anim-leave-to { opacity: 0; transform: translateX(24px); }

/* Toolbar */
.infra-toolbar-actions { display: flex; gap: 7px; flex-wrap: wrap; align-items: center; }
.infra-toolbar-actions .btn { min-height: 34px; font-size: 12.5px; }

/* Zona Drag & Drop de upload tracking (reusa el look de .btn.subtle) */
.upload-drop-zone.drag-over {
  border-color: var(--color-accent); color: var(--color-accent);
}

/* Botones extra (modificadores de .btn global) */
.btn.danger { background: transparent; color: oklch(0.72 0.11 25); border: 1px solid color-mix(in srgb, var(--color-state-error) 50%, transparent); }
.btn.danger:hover:not(:disabled) { background: color-mix(in srgb, var(--color-state-error) 12%, transparent); }
.btn.danger-subtle { background: transparent; color: var(--color-state-error); border: 1px solid color-mix(in srgb, var(--color-state-error) 20%, transparent); }
.btn.danger-subtle:hover:not(:disabled) { background: color-mix(in srgb, var(--color-state-error) 10%, transparent); }
.btn.success { background: transparent; color: var(--color-state-ok); border: 1px solid color-mix(in srgb, var(--color-state-ok) 50%, transparent); }
.btn.success:hover:not(:disabled) { background: color-mix(in srgb, var(--color-state-ok) 12%, transparent); }

/* Dropdown descargar */
.download-dropdown-wrapper { position: relative; }
.dropdown-caret { display: inline-block; transition: transform .2s; font-size: .75rem; margin-left: 2px; }
.dropdown-caret.open { transform: rotate(180deg); }
.download-dropdown-menu {
  position: absolute; top: calc(100% + 4px); right: 0; z-index: 200;
  min-width: 180px; margin: 0; padding: 4px 0; list-style: none;
  background: var(--color-surface); border: 1px solid var(--border); border-radius: 8px;
  box-shadow: 0 6px 18px rgba(0,0,0,.45);
}
.dropdown-item {
  padding: 9px 14px; font-size: .85rem; cursor: pointer;
  color: var(--text); display: flex; align-items: center; gap: 7px; white-space: nowrap;
}
.dropdown-item:hover { background: color-mix(in srgb, var(--color-text) 7%, transparent); }
.dropdown-divider { border: none; border-top: 1px solid var(--border); margin: 4px 0; }
.btn.warning { background: transparent; color: var(--color-state-warn); border: 1px solid color-mix(in srgb, var(--color-state-warn) 50%, transparent); }
.btn.warning:hover:not(:disabled) { background: color-mix(in srgb, var(--color-state-warn) 12%, transparent); }

/* Leyenda de estados — fusionada como chips de filtro */
.infra-legend-item {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 3px 10px; border-radius: var(--radius-pill); font-size: 11.5px; cursor: pointer;
  border: 1px solid var(--color-divider); background: transparent;
  color: color-mix(in srgb, var(--color-text) 66%, transparent);
}
.infra-legend-item:hover { border-color: var(--color-accent); }
.infra-legend-item.active {
  border-color: var(--color-accent); background: color-mix(in srgb, var(--color-accent) 12%, transparent);
  color: var(--color-accent-200);
}
.infra-legend-dot { width: 6px; height: 6px; border-radius: 50%; display: inline-block; flex-shrink: 0; }
.infra-legend-dot.libre { background: var(--color-state-ok); }
.infra-legend-dot.ocupada { background: var(--color-state-warn); }
.infra-legend-dot.baneada { background: var(--color-state-error); }
.infra-legend-dot.detectada { background: var(--color-state-idle); }
.infra-legend-count { font-variant-numeric: tabular-nums; color: color-mix(in srgb, var(--color-text) 42%, transparent); }

/* Modal genérico compartido */
.infra-generic-modal {
  position: fixed; inset: 0; margin: auto;
  border: 1px solid var(--border); border-radius: 10px; background: var(--color-surface);
  color: var(--text); padding: 0; max-width: 520px; width: 95vw; max-height: 90vh; overflow-y: auto;
}
.infra-generic-modal::backdrop { background: rgba(0,0,0,.6); }
.modal-inner { padding: 24px; display: flex; flex-direction: column; gap: 6px; }
.modal-header-row { display: flex; align-items: center; margin-bottom: 10px; }
.modal-title { margin: 0; font-size: 1rem; flex: 1; }
.modal-desc { margin: 0 0 6px; font-size: .83rem; color: var(--muted); }
.danger-text { color: var(--color-state-warn); }
.req { color: var(--color-state-error); }
.modal-actions { display: flex; gap: 8px; margin-top: 14px; flex-wrap: wrap; }
.resolve-conflict-actions { gap: 6px; }

/* ─── Wizard ban ─── */
.ban-wizard-modal { max-width: 600px; }
.wizard-stepper {
  display: flex; align-items: center; gap: 0; margin: 4px 0 18px;
}
.wizard-step-row { display: flex; align-items: center; flex: 1; }
.wizard-step-row:last-child { flex: 0; }
.wizard-step-item {
  display: flex; align-items: center; gap: 6px; flex-shrink: 0;
}
.wizard-step-num {
  width: 24px; height: 24px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
  font-size: .75rem; font-weight: 700; border: 1.5px solid var(--border); color: var(--muted); background: transparent;
  flex-shrink: 0;
}
.wizard-step-label { font-size: .78rem; color: var(--muted); white-space: nowrap; }
.wizard-step-item.active .wizard-step-num { border-color: var(--color-accent); background: color-mix(in srgb, var(--color-accent) 15%, transparent); color: var(--color-accent); }
.wizard-step-item.active .wizard-step-label { color: var(--color-accent); font-weight: 600; }
.wizard-step-item.done .wizard-step-num { border-color: var(--color-state-ok); background: color-mix(in srgb, var(--color-state-ok) 15%, transparent); color: var(--color-state-ok); }
.wizard-step-item.done .wizard-step-label { color: var(--color-state-ok); }
.wizard-step-connector { flex: 1; height: 1px; background: var(--border); margin: 0 6px; }

/* Paso 2 */
.ban-step2-affected {
  font-size: .84rem; color: var(--muted); padding: 6px 10px;
  background: color-mix(in srgb, var(--color-text) 4%, transparent); border-radius: 6px; margin-bottom: 10px;
}
.ban-prot-tabs { display: flex; gap: 0; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; margin-bottom: 10px; }
.ban-prot-tab {
  flex: 1; padding: 8px 10px; font-size: .82rem; cursor: pointer; text-align: center;
  background: transparent; color: var(--muted); border: none; transition: background .15s;
}
.ban-prot-tab:hover { background: color-mix(in srgb, var(--color-text) 6%, transparent); }
.ban-prot-tab.active { background: color-mix(in srgb, var(--color-accent) 12%, transparent); color: var(--color-accent); font-weight: 600; }
.ban-search-row { display: flex; gap: 8px; margin-bottom: 4px; }
.ban-search-row input { flex: 1; }
.ban-rutas-error { font-size: .83rem; color: var(--color-state-error); padding: 6px 0; }
.ban-rutas-empty { font-size: .83rem; color: var(--muted); padding: 10px 0; text-align: center; }
.ban-ruta-grid { display: flex; flex-direction: column; gap: 6px; margin-top: 4px; }
.ban-ruta-card {
  display: flex; align-items: flex-start; gap: 10px; padding: 10px 12px;
  background: color-mix(in srgb, var(--color-text) 4%, transparent); border: 1.5px solid var(--border);
  border-radius: 8px; cursor: pointer; transition: border-color .15s, background .15s;
}
.ban-ruta-card:hover { background: color-mix(in srgb, var(--color-text) 7%, transparent); border-color: color-mix(in srgb, var(--color-accent) 40%, transparent); }
.ban-ruta-card.selected { border-color: var(--color-accent); background: color-mix(in srgb, var(--color-accent) 8%, transparent); }
.ban-ruta-card.all-option { border-style: dashed; }
.ban-ruta-icon { font-size: 1.1rem; padding-top: 1px; flex-shrink: 0; }
.ban-ruta-nombre { font-size: .88rem; font-weight: 600; color: var(--text); }
.ban-ruta-meta { font-size: .78rem; color: var(--muted); margin-top: 2px; }
.ban-tracking-alert {
  margin-top: 6px; padding: 6px 8px; border-radius: 6px; font-size: .78rem;
  background: color-mix(in srgb, var(--color-state-warn) 12%, transparent); color: var(--color-state-warn); border: 1px solid color-mix(in srgb, var(--color-state-warn) 25%, transparent);
}
.ban-tracking-alert-actions { display: flex; gap: 6px; margin-top: 6px; }
.btn.small { padding: 4px 10px; font-size: .78rem; }

/* Paso 3 */
.ban-summary-block {
  background: color-mix(in srgb, var(--color-text) 4%, transparent); border: 1px solid var(--border);
  border-radius: 8px; padding: 12px 14px; display: flex; flex-direction: column;
  gap: 6px; margin-bottom: 12px; font-size: .85rem;
}
.ban-summary-row { display: flex; gap: 8px; }
.ban-summary-label { color: var(--muted); min-width: 130px; flex-shrink: 0; font-size: .82rem; }
.ban-confirm-row {
  display: flex; align-items: flex-start; gap: 8px; font-size: .85rem;
  cursor: pointer; padding: 8px 10px; border-radius: 6px;
  background: color-mix(in srgb, var(--color-state-error) 6%, transparent); border: 1px solid color-mix(in srgb, var(--color-state-error) 20%, transparent);
}
.ban-confirm-row input[type=checkbox] { margin-top: 2px; flex-shrink: 0; }

/* Modal de resolución de tracking */
.tracking-resolve-modal { max-width: 580px; }
.upload-analyzing { padding: 16px 0; font-size: .88rem; color: var(--muted); }
.resolve-status-badge {
  display: inline-block; padding: 4px 12px; border-radius: 12px;
  font-size: .82rem; font-weight: 700; margin-bottom: 6px; background: color-mix(in srgb, var(--color-text) 7%, transparent);
}
.resolve-status-badge.status-new { background: color-mix(in srgb, var(--color-accent) 15%, transparent); color: var(--color-accent); }
.resolve-status-badge.status-identical { background: color-mix(in srgb, var(--color-state-ok) 15%, transparent); color: var(--color-state-ok); }
.resolve-status-badge.status-conflict { background: color-mix(in srgb, var(--color-state-warn) 15%, transparent); color: var(--color-state-warn); }
.resolve-status-badge.status-potential_upgrade { background: color-mix(in srgb, var(--color-accent) 15%, transparent); color: var(--color-accent); }
.resolve-status-badge.status-new_strand { background: color-mix(in srgb, var(--color-accent) 15%, transparent); color: var(--color-accent); }
.resolve-status-badge.status-error { background: color-mix(in srgb, var(--color-state-error) 15%, transparent); color: var(--color-state-error); }
.resolve-message { margin: 0 0 8px; font-size: .85rem; }
.resolve-svc-info { font-size: .83rem; color: var(--muted); margin-bottom: 8px; }
.resolve-hint { font-size: .85rem; color: var(--muted); margin: 4px 0 8px; }
.resolve-error { color: var(--color-state-error); font-size: .85rem; margin: 8px 0; }
.resolve-rutas-list { display: flex; flex-direction: column; gap: 4px; margin: 6px 0; }
.resolve-ruta-item {
  display: flex; align-items: center; gap: 8px; font-size: .82rem;
  padding: 6px 8px; background: color-mix(in srgb, var(--color-text) 4%, transparent); border-radius: 6px;
}
.resolve-ruta-meta { font-size: .78rem; color: var(--muted); }
.resolve-select { width: 100%; margin: 4px 0 10px; }
.resolve-upgrade-info {
  font-size: .83rem; background: color-mix(in srgb, var(--color-text) 4%, transparent); border-radius: 6px;
  padding: 8px 10px; margin: 6px 0; display: flex; flex-direction: column; gap: 3px;
}
/* ─── Baneos Activos ─── */
.active-bans-btn { position: relative; }
.active-bans-badge {
  position: absolute; top: -6px; right: -6px;
  min-width: 18px; height: 18px; border-radius: 9px; padding: 0 4px;
  background: var(--color-state-error); color: var(--color-neutral-100); font-size: .72rem; font-weight: 700;
  display: inline-flex; align-items: center; justify-content: center; line-height: 1;
}
.active-bans-modal { max-width: 640px; }
.active-bans-loading, .active-bans-empty {
  padding: 20px 0; text-align: center; color: var(--muted); font-size: .88rem;
}
.active-bans-error { color: var(--color-state-error); font-size: .85rem; padding: 8px 0; }
.active-bans-count { font-size: .8rem; color: var(--muted); margin-bottom: 10px; }
.active-bans-list { display: flex; flex-direction: column; gap: 10px; max-height: 60vh; overflow-y: auto; }
.active-ban-card {
  background: color-mix(in srgb, var(--color-text) 4%, transparent); border: 1px solid var(--border);
  border-radius: 8px; padding: 12px 14px; display: flex; flex-direction: column; gap: 6px;
}
.active-ban-card-header { display: flex; justify-content: space-between; align-items: flex-start; }
.active-ban-ticket { display: flex; flex-direction: column; gap: 2px; }
.active-ban-ticket-label { font-size: .72rem; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }
.active-ban-duracion {
  font-size: .78rem; font-weight: 600; color: var(--color-state-warn);
  background: color-mix(in srgb, var(--color-state-warn) 10%, transparent); padding: 2px 8px; border-radius: 10px;
  white-space: nowrap; align-self: flex-start;
}
.active-ban-servicios { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: .85rem; }
.active-ban-svc-item { display: flex; align-items: center; gap: 5px; }
.active-ban-svc-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.active-ban-svc-dot.afectado { background: var(--color-state-warn); }
.active-ban-svc-dot.protegido { background: var(--color-state-error); }
.active-ban-arrow { color: var(--muted); font-size: .9rem; }
.active-ban-ruta { font-size: .8rem; color: var(--muted); }
.active-ban-motivo { font-size: .83rem; color: var(--text); font-style: italic; border-left: 2px solid var(--border); padding-left: 8px; }
.active-ban-meta { display: flex; flex-wrap: wrap; gap: 8px; font-size: .78rem; color: var(--muted); }
.active-ban-actions { display: flex; gap: 8px; margin-top: 4px; flex-wrap: wrap; }

/* Sub-modal Dar Aviso */
.aviso-modal { max-width: 560px; }
.aviso-hint { font-size: .75rem; color: var(--muted); font-weight: 400; }
.aviso-loading-template { padding: 24px 0; text-align: center; color: var(--muted); font-size: .88rem; }
.aviso-body-textarea { font-family: inherit; font-size: .84rem; line-height: 1.5; resize: vertical; min-height: 200px; }
.aviso-options { display: flex; flex-direction: column; gap: 6px; margin-top: 4px; }
.aviso-checkbox-row { display: flex; align-items: center; gap: 8px; font-size: .85rem; cursor: pointer; }
.aviso-checkbox-row input[type=checkbox] { flex-shrink: 0; }
</style>
