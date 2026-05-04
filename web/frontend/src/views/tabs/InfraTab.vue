<!--
  Nombre de archivo: InfraTab.vue
  Ubicación de archivo: web/frontend/src/views/tabs/InfraTab.vue
  Descripción: Tab de Infraestructura / Dashboard de Cámaras — migrado desde panel.js
-->
<template>
  <article class="card" style="padding:0">
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

    <!-- Camera state modal -->
    <dialog ref="cameraStateModalEl" class="camera-state-modal" @click.self="closeCameraStateModal">
      <div class="modal-content" v-if="cameraStateData">
        <div class="camera-state-title-row">
          <strong>{{ cameraStateData.camara.nombre || cameraStateData.camara.direccion || 'Sin nombre' }}</strong>
          <span :class="['camera-state-badge', cameraStateData.contexto.inconsistente ? 'warning' : 'ok']">
            {{ cameraStateData.contexto.inconsistente ? 'Inconsistente' : 'Alineada' }}
          </span>
          <button class="close-btn" @click="closeCameraStateModal">×</button>
        </div>
        <div class="camera-state-meta-row">
          <span>Actual: <strong>{{ cameraStateData.contexto.estado_actual }}</strong></span>
          <span>Sugerido: <strong>{{ cameraStateData.contexto.estado_sugerido || cameraStateData.contexto.estado_actual }}</strong></span>
          <span>Baneo activo: <strong>{{ cameraStateData.contexto.tiene_baneo_activo ? 'Sí' : 'No' }}</strong></span>
          <span>Ingreso activo: <strong>{{ cameraStateData.contexto.tiene_ingreso_activo ? 'Sí' : 'No' }}</strong></span>
        </div>
        <div v-if="(cameraStateData.contexto.incidentes_activos ?? []).length" class="camera-state-incidents">
          <div class="camera-state-incidents-title">Incidentes activos vinculados</div>
          <div
            v-for="inc in cameraStateData.contexto.incidentes_activos"
            :key="inc.ticket_asociado"
            class="camera-state-incident-item"
          >
            <strong>{{ inc.ticket_asociado || 'Sin ticket' }}</strong>
            <span>Servicio: {{ inc.servicio_protegido_id || '-' }}</span>
            <span>Ruta: {{ inc.ruta_protegida_id ?? '-' }}</span>
          </div>
        </div>
        <div v-else class="camera-state-empty">No hay incidentes activos vinculados.</div>
        <label class="form-label">Nuevo estado</label>
        <select v-model="newEstado" class="camera-state-select">
          <option v-for="s in ESTADOS" :key="s" :value="s">{{ s }}</option>
        </select>
        <label class="form-label">Motivo del cambio (mínimo 5 caracteres)</label>
        <input v-model="motivo" type="text" placeholder="Describí brevemente el motivo" />
        <div class="camera-state-actions">
          <button class="btn primary" :disabled="savingState" @click="saveCameraState">Guardar</button>
          <button class="btn subtle" @click="closeCameraStateModal">Cancelar</button>
        </div>
      </div>
    </dialog>

    <!-- Tracking modal -->
    <dialog ref="trackingModalEl" class="tracking-detail-modal" @click.self="trackingModalEl?.close()">
      <div class="tracking-detail-content">
        <div class="tracking-detail-header">
          <h3 class="tracking-detail-title">{{ trackingTitle }}</h3>
          <button class="tracking-download-btn" type="button" @click="downloadTracking">📄 Descargar TXT</button>
          <button class="tracking-detail-close" @click="trackingModalEl?.close()">×</button>
        </div>
        <div class="tracking-rutas-tabs">
          <button
            v-for="ruta in trackingRutas"
            :key="ruta.id"
            :class="['tracking-ruta-tab', { active: ruta.id === activeRutaId }]"
            :style="{ '--tab-color': ruta.color }"
            @click="loadRutaTracking(ruta.id)"
          >{{ ruta.nombre }}</button>
        </div>
        <div class="tracking-detail-list">
          <div v-if="trackingLoading" class="tracking-loading">Cargando tracking...</div>
          <div v-else-if="trackingError" class="tracking-error">{{ trackingError }}</div>
          <div v-else class="tracking-sequence">
            <template v-if="trackingItems.punta_a">
              <div class="tracking-item tracking-punta tracking-punta-a">
                <span class="tracking-icon">🔌</span>
                <span class="tracking-text">
                  <span class="tracking-punta-label">Punta A</span>
                  <span class="tracking-punta-sitio">{{ trackingItems.punta_a.sitio }}{{ trackingItems.punta_a.conector ? ': ' + trackingItems.punta_a.conector : '' }}</span>
                  <span v-if="trackingItems.punta_a.identificador" class="tracking-punta-id">{{ trackingItems.punta_a.identificador }}</span>
                </span>
              </div>
            </template>
            <template v-for="(item, i) in trackingItems.tracking ?? []" :key="i">
              <div v-if="item.tipo === 'camara'" class="tracking-item tracking-camara">
                <span class="tracking-icon">📍</span>
                <span class="tracking-text">{{ item.descripcion || 'Cámara' }}</span>
                <span v-if="item.empalme_id" class="tracking-empalme-id">#{{ item.empalme_id }}</span>
              </div>
              <div v-else-if="item.tipo === 'cable'" class="tracking-item tracking-cable">
                <span class="tracking-cable-line"></span>
                <span class="tracking-cable-info">
                  <span class="tracking-cable-name">{{ item.nombre || 'Cable' }}</span>
                  <span v-if="item.atenuacion_db != null" class="tracking-atenuacion">{{ item.atenuacion_db }} dB</span>
                </span>
              </div>
            </template>
            <template v-if="trackingItems.punta_b">
              <div class="tracking-item tracking-punta tracking-punta-b">
                <span class="tracking-icon">🔌</span>
                <span class="tracking-text">
                  <span class="tracking-punta-label">Punta B</span>
                  <span class="tracking-punta-sitio">{{ trackingItems.punta_b.sitio }}{{ trackingItems.punta_b.conector ? ': ' + trackingItems.punta_b.conector : '' }}</span>
                  <span v-if="trackingItems.punta_b.identificador" class="tracking-punta-id">{{ trackingItems.punta_b.identificador }}</span>
                </span>
              </div>
            </template>
          </div>
        </div>
      </div>
    </dialog>

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
      <div class="infra-toolbar">
        <h2 class="infra-toolbar-title">Infraestructura FO</h2>
        <div class="infra-toolbar-actions">
          <button class="btn danger" @click="openBanModal">🔴 Protocolo Protección</button>
          <button class="btn subtle active-bans-btn" @click="openActiveBansModal">🔒 Baneos Activos<span v-if="activeBans.length > 0" class="active-bans-badge">{{ activeBans.length }}</span></button>
          <div
            class="upload-drop-zone"
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
          >📁 Subir Tracking</div>
          <button class="btn danger-subtle" @click="openLimpiarModal">🗑 Limpiar Servicio</button>
          <div class="download-dropdown-wrapper" ref="downloadDropdownEl">
            <button class="btn success" @click.stop="toggleDownloadMenu">
              ⬇ Descargar <span class="dropdown-caret" :class="{ open: isDownloadMenuOpen }">▾</span>
            </button>
            <ul v-if="isDownloadMenuOpen" class="download-dropdown-menu" @click.stop>
              <li class="dropdown-item" @click="downloadCameras('xlsx', null)">📊 Todas (XLSX)</li>
              <li class="dropdown-item" @click="downloadCameras('csv', null)">📄 Todas (CSV)</li>
              <li class="dropdown-divider"></li>
              <li class="dropdown-item" @click="downloadCameras('xlsx', 'BANEADA')">🔴 Solo Baneadas</li>
              <li class="dropdown-item" @click="downloadCameras('xlsx', 'OCUPADA')">🟡 Con Ingreso</li>
            </ul>
          </div>
        </div>
      </div>
      <div class="infra-search-area">
        <div class="infra-search-row">
          <input
            v-model="searchInput"
            type="text"
            placeholder="Buscar por nombre, dirección, servicio..."
            @keydown.enter="addTerm"
          />
          <button class="btn" @click="addTerm">Agregar</button>
          <button class="btn primary" :disabled="loading || searchTerms.length === 0" @click="searchCamaras">Buscar</button>
          <button class="btn subtle" @click="clearAll">Limpiar</button>
        </div>
        <div v-if="searchTerms.length" class="infra-search-terms">
          <span v-for="(term, i) in searchTerms" :key="i" class="infra-search-term">
            <span class="infra-search-term-value">{{ term }}</span>
            <button class="infra-search-term-remove" @click="removeTerm(i)">×</button>
          </span>
        </div>
        <div v-if="activeStateFilter" class="infra-state-filter-chip">
          <span v-if="activeStateFilter !== 'TRACKING'" class="infra-legend-dot" :class="activeStateFilter.toLowerCase()"></span>
          <span v-else style="font-size:.85rem;line-height:1">📍</span>
          <span>{{ activeStateFilter }}</span>
          <button class="infra-state-filter-remove" @click="activeStateFilter = null" aria-label="Quitar filtro de estado">×</button>
        </div>
        <div v-if="statusText" :class="['infra-status', statusVariant]">{{ statusText }}</div>
      </div>

      <!-- Leyenda de estados (atajos de filtrado rápido) (atajos de filtrado rápido) -->
      <div class="infra-legend">
        <button :class="['infra-legend-item', { active: activeStateFilter === 'LIBRE' }]" @click="toggleStateFilter('LIBRE')"><span class="infra-legend-dot libre"></span>LIBRE</button>
        <button :class="['infra-legend-item', { active: activeStateFilter === 'OCUPADA' }]" @click="toggleStateFilter('OCUPADA')"><span class="infra-legend-dot ocupada"></span>OCUPADA</button>
        <button :class="['infra-legend-item', { active: activeStateFilter === 'BANEADA' }]" @click="toggleStateFilter('BANEADA')"><span class="infra-legend-dot baneada"></span>BANEADA</button>
        <button :class="['infra-legend-item', { active: activeStateFilter === 'DETECTADA' }]" @click="toggleStateFilter('DETECTADA')"><span class="infra-legend-dot detectada"></span>DETECTADA</button>
        <button :class="['infra-legend-item', { active: activeStateFilter === 'TRACKING' }]" @click="toggleStateFilter('TRACKING')"><span style="font-size:.85rem;line-height:1">📍</span>TRACKING</button>
      </div>

      <div v-if="loading" class="infra-loading">Buscando...</div>
      <div v-else-if="!hasSearched" class="infra-empty">
        <span>Agregá términos de búsqueda y presioná "Buscar"</span>
      </div>
      <div v-else-if="camaras.length === 0" class="infra-empty">Sin resultados para estos términos.</div>
      <div v-else-if="filteredCamaras.length === 0" class="infra-empty">
        Sin cámaras con estado <strong>{{ activeStateFilter }}</strong> en los resultados actuales.
      </div>
      <div v-else class="infra-grid">
        <div
          v-for="camara in filteredCamaras"
          :key="camara.id"
          :class="['infra-camara-card']"
          :data-estado="camara.estado ?? 'LIBRE'"
          :data-inconsistente="camara.inconsistente ? 'true' : 'false'"
        >
          <div class="infra-camara-header">
            <div class="infra-camara-estado">
              <span :class="['infra-estado-icon', (camara.estado ?? 'libre').toLowerCase()]"></span>
              <span class="infra-estado-text">{{ camara.estado || 'LIBRE' }}</span>
            </div>
            <div class="infra-camara-header-actions">
              <span v-if="camara.fontine_id" class="infra-camara-id">{{ camara.fontine_id }}</span>
              <button
                v-if="isAdmin && camara.editable !== false"
                class="infra-edit-btn"
                @click.stop="openCameraStateModal(camara)"
              >Editar estado</button>
            </div>
          </div>
          <div class="infra-camara-nombre">{{ camara.nombre || camara.direccion || 'Sin nombre' }}</div>
          <div v-if="camara.inconsistente && camara.estado_sugerido" class="infra-camara-warning">
            <strong>Estado manual distinto al sugerido.</strong>
            <span>Actual: {{ camara.estado }} · Sugerido: {{ camara.estado_sugerido }}</span>
          </div>
          <div class="infra-camara-servicios">
            <template v-if="(camara.rutas ?? []).length > 0">
              <span
                v-for="chip in buildServiceChips(camara.rutas)"
                :key="chip.servicioId"
                class="infra-servicio-chip"
                :style="{ backgroundColor: chip.color, cursor: 'pointer' }"
                :title="chip.title"
                @click.stop="openTrackingModal(chip.rutaId, chip.servicioId, chip.rutaNombre, chip.rutaTipo, chip.color)"
              >
                <span class="servicio-id-main">Svc: {{ chip.servicioId }}</span>
                <span v-if="chip.aliasHtml" class="servicio-alias">(ex {{ chip.aliasHtml }})</span>
                <span v-if="chip.pelos > 1" class="servicio-pelos-badge">x{{ chip.pelos }}</span>
              </span>
            </template>
            <span v-else class="infra-no-servicios">Sin servicios asociados</span>
          </div>
          <div v-if="camara.estado === 'BANEADA' && camara.ticket_baneo" class="infra-ban-ticket">{{ camara.ticket_baneo }}</div>
        </div>
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
}

const filteredCamaras = computed(() => {
  if (!activeStateFilter.value) return camaras.value;
  const target = activeStateFilter.value;
  if (target === 'TRACKING') {
    return camaras.value.filter(c => ((c.rutas as unknown[]) ?? []).length > 0);
  }
  return camaras.value.filter(c => (c.estado ?? 'LIBRE') === target);
});

async function searchCamaras() {
  if (searchTerms.value.length === 0) return;
  loading.value = true;
  hasSearched.value = true;
  setStatus(`Buscando con ${searchTerms.value.length} término(s)...`, 'loading');
  try {
    const res = await fetch('/api/infra/smart-search', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ terms: searchTerms.value, limit: 100, offset: 0 }),
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

function getRutaColor(ruta: Record<string, unknown>, index: number): string {
  const fallback = [RUTA_COLORS.PRINCIPAL, RUTA_COLORS.BACKUP, RUTA_COLORS.ALTERNATIVA, RUTA_COLORS.CUARTO];
  if (ruta.ruta_tipo === 'PRINCIPAL') return RUTA_COLORS.PRINCIPAL;
  if (ruta.ruta_tipo === 'BACKUP') return RUTA_COLORS.BACKUP;
  if (ruta.ruta_tipo === 'ALTERNATIVA') return RUTA_COLORS.ALTERNATIVA;
  const n = String(ruta.ruta_nombre ?? '').toLowerCase();
  if (n.includes('principal') || n === 'camino 1') return RUTA_COLORS.PRINCIPAL;
  if (n.includes('backup') || n.includes('secundario') || n === 'camino 2') return RUTA_COLORS.BACKUP;
  if (n === 'camino 3' || n.includes('alternativ')) return RUTA_COLORS.ALTERNATIVA;
  if (n === 'camino 4') return RUTA_COLORS.CUARTO;
  return fallback[index % fallback.length];
}

interface ServiceChip {
  servicioId: string; rutaId: string; rutaNombre: string; rutaTipo: string;
  color: string; title: string; pelos: number; aliasHtml: string;
}

function buildServiceChips(rutas: Record<string, unknown>[]): ServiceChip[] {
  const grouped: Record<string, Record<string, unknown>[]> = {};
  rutas.forEach((r, idx) => {
    const sid = String(r.servicio_id ?? '');
    if (!grouped[sid]) grouped[sid] = [];
    grouped[sid].push({ ...r, _index: idx });
  });
  return Object.entries(grouped).map(([svcId, svcRutas]) => {
    const first = svcRutas[0];
    const allAlias = new Set<string>();
    svcRutas.forEach(r => ((r.alias_ids as string[]) ?? []).forEach(a => allAlias.add(a)));
    return {
      servicioId: svcId,
      rutaId: String(first.ruta_id ?? ''),
      rutaNombre: String(first.ruta_nombre ?? ''),
      rutaTipo: String(first.ruta_tipo ?? ''),
      color: getRutaColor(first, first._index as number),
      title: svcRutas.length > 1 ? `${svcRutas.length} pelos` : String(first.ruta_nombre ?? ''),
      pelos: svcRutas.length,
      aliasHtml: [...allAlias].join(', '),
    };
  });
}

// --- Camera state modal ---
const cameraStateModalEl = ref<HTMLDialogElement | null>(null);
interface CameraStateData {
  camara: Record<string, unknown>;
  contexto: Record<string, unknown>;
}
const cameraStateData = ref<CameraStateData | null>(null);
const newEstado = ref('');
const motivo = ref('');
const savingState = ref(false);
const ESTADOS = ['LIBRE', 'BANEADA', 'EN_MANTENIMIENTO', 'INACCESIBLE'];

async function openCameraStateModal(camara: Record<string, unknown>) {
  try {
    const res = await fetch(`/api/infra/camaras/${camara.id}/estado`, { credentials: 'include' });
    const data = await res.json();
    if (!res.ok) throw new Error((data as Record<string, string>).error ?? `Error ${res.status}`);
    cameraStateData.value = { camara, contexto: data.contexto ?? {} };
    newEstado.value = String((data.contexto as Record<string, unknown>)?.estado_actual ?? camara.estado ?? 'LIBRE');
    motivo.value = '';
    cameraStateModalEl.value?.showModal();
  } catch (e: unknown) {
    showToast('error', 'No se pudo abrir el editor', e instanceof Error ? e.message : String(e));
  }
}

function closeCameraStateModal() {
  cameraStateData.value = null;
  motivo.value = '';
  cameraStateModalEl.value?.close();
}

async function saveCameraState() {
  if (!cameraStateData.value) return;
  if (motivo.value.trim().length < 5) {
    showToast('warning', 'Motivo insuficiente', 'Ingresá al menos 5 caracteres para auditar el cambio');
    return;
  }
  savingState.value = true;
  try {
    const res = await fetch(`/api/infra/camaras/${cameraStateData.value.camara.id}/estado`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ estado: newEstado.value, motivo: motivo.value.trim(), csrf_token: csrf() }),
    });
    const data = await res.json();
    if (!res.ok || !data.success) throw new Error((data as Record<string, string>).error ?? 'No se pudo guardar');
    closeCameraStateModal();
    await searchCamaras();
    showToast('success', 'Estado actualizado', data.changed ? 'El cambio quedó auditado' : 'La cámara ya tenía ese estado');
  } catch (e: unknown) {
    showToast('error', 'Error al guardar', e instanceof Error ? e.message : String(e));
  } finally {
    savingState.value = false;
  }
}

// --- Tracking modal ---
const trackingModalEl = ref<HTMLDialogElement | null>(null);
const trackingTitle = ref('');
const trackingRutas = ref<{ id: number; nombre: string; color: string }[]>([]);
const activeRutaId = ref<number | null>(null);
const currentRutaIdForDownload = ref<number | null>(null);
const trackingLoading = ref(false);
const trackingError = ref<string | null>(null);
interface TrackingData {
  tracking: Record<string, unknown>[];
  punta_a?: Record<string, unknown> | null;
  punta_b?: Record<string, unknown> | null;
}
const trackingItems = ref<TrackingData>({ tracking: [] });

async function openTrackingModal(rutaId: string, servicioId: string, rutaNombre: string, _rutaTipo: string, _color: string) {
  trackingTitle.value = `Svc: ${servicioId}`;
  trackingRutas.value = [];
  activeRutaId.value = null;
  trackingItems.value = { tracking: [] };
  trackingError.value = null;
  trackingLoading.value = true;
  trackingModalEl.value?.showModal();
  try {
    const res = await fetch(`/api/infra/servicios/${servicioId}/rutas`, { credentials: 'include' });
    const data = await res.json();
    const rutas: Record<string, unknown>[] = data.rutas ?? [];
    if (rutas.length === 0) {
      trackingRutas.value = [{ id: Number(rutaId), nombre: rutaNombre, color: _color }];
    } else {
      trackingRutas.value = rutas.map((r, i) => ({
        id: r.id as number,
        nombre: String(r.nombre ?? r.ruta_nombre ?? ''),
        color: getRutaColor(r, i),
      }));
    }
    await loadRutaTracking(Number(rutaId));
  } catch (e: unknown) {
    trackingLoading.value = false;
    trackingError.value = e instanceof Error ? e.message : String(e);
  }
}

async function loadRutaTracking(rutaId: number) {
  activeRutaId.value = rutaId;
  currentRutaIdForDownload.value = rutaId;
  trackingLoading.value = true;
  trackingError.value = null;
  try {
    const res = await fetch(`/api/infra/rutas/${rutaId}/tracking`, { credentials: 'include' });
    const data = await res.json();
    if (data.error) { trackingError.value = data.error; return; }
    trackingItems.value = { tracking: data.tracking ?? [], punta_a: data.punta_a, punta_b: data.punta_b };
  } catch (e: unknown) {
    trackingError.value = e instanceof Error ? e.message : String(e);
  } finally {
    trackingLoading.value = false;
  }
}

async function downloadTracking() {
  const rid = currentRutaIdForDownload.value;
  if (!rid) return;
  try {
    const res = await fetch(`/api/infra/tracking/${rid}/download`, { credentials: 'include' });
    if (res.status === 404) { showToast('warning', 'Archivo no disponible', 'El TXT original no está disponible'); return; }
    if (!res.ok) throw new Error(`Error ${res.status}`);
    const blob = await res.blob();
    const cd = res.headers.get('Content-Disposition') ?? '';
    const match = cd.match(/filename="(.+?)"/);
    const filename = match ? match[1] : `tracking_ruta_${rid}.txt`;
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename; document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast('success', 'Descarga completa', filename);
  } catch (e: unknown) {
    showToast('error', 'Error de descarga', e instanceof Error ? e.message : String(e));
  }
}

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
  banForm.value = { ticket_asociado: '', servicio_afectado_id: '', servicio_protegido_id: '', motivo: '', usuario_ejecutor: '' };
  currentBanStep.value = 1;
  banProtMode.value = 'same';
  banSearchServicioInput.value = '';
  banRutas.value = [];
  banLoadingRutas.value = false;
  banRutasError.value = '';
  banSelectedRutaId.value = null;
  banConfirmChecked.value = false;
  banModalEl.value?.showModal();
}

function closeBanModal() {
  if (banLoading.value) return;
  banModalEl.value?.close();
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
    closeBanModal();
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
.infra-panel { padding: 16px; }
.infra-search-row { display: flex; gap: 8px; flex-wrap: wrap; }
.infra-search-row input { flex: 1; min-width: 220px; }
.infra-search-terms { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.infra-search-term {
  display: inline-flex; align-items: center; gap: 4px;
  background: rgba(59,130,246,.15); color: #60a5fa;
  border: 1px solid rgba(59,130,246,.3); border-radius: 14px;
  padding: 3px 10px 3px 10px; font-size: .82rem;
}
.infra-search-term-remove { background: none; border: none; cursor: pointer; color: inherit; padding: 0; line-height: 1; }
.infra-status { margin-top: 10px; font-size: .85rem; }
.infra-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; margin-top: 16px; }
.infra-empty { margin-top: 32px; text-align: center; color: var(--muted); }
.infra-loading { margin-top: 32px; text-align: center; color: var(--muted); }
.infra-camara-card { background: #1a1a1a; border: 1px solid var(--border); border-radius: 8px; padding: 14px; }
.infra-camara-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.infra-camara-estado { display: flex; align-items: center; gap: 6px; font-size: .85rem; }
.infra-estado-icon { width: 10px; height: 10px; border-radius: 50%; display: inline-block; background: #6b7280; }
.infra-estado-icon.libre { background: #22c55e; }
.infra-estado-icon.baneada { background: #ef4444; }
.infra-estado-icon.en_mantenimiento { background: #f59e0b; }
.infra-estado-icon.inaccesible { background: #9ca3af; }
.infra-camara-nombre { font-weight: 600; font-size: .9rem; color: var(--text); margin-bottom: 8px; }
.infra-camara-warning { font-size: .78rem; color: #f59e0b; margin-bottom: 6px; }
.infra-camara-servicios { display: flex; flex-wrap: wrap; gap: 6px; }
.infra-servicio-chip { padding: 3px 8px; border-radius: 12px; font-size: .78rem; color: #fff; display: inline-flex; align-items: center; gap: 4px; }
.infra-no-servicios { color: var(--muted); font-size: .82rem; }
.infra-edit-btn { font-size: .75rem; padding: 3px 8px; background: rgba(255,255,255,.07); border: 1px solid var(--border); border-radius: 6px; cursor: pointer; color: var(--text); }
.infra-ban-ticket { margin-top: 6px; font-size: .78rem; color: #ef4444; }
/* Modal */
.camera-state-modal, .tracking-detail-modal { position: fixed; inset: 0; margin: auto; border: 1px solid var(--border); border-radius: 10px; background: #1c1c1c; color: var(--text); padding: 24px; max-width: 520px; width: 95vw; max-height: 90vh; overflow-y: auto; }
.camera-state-modal::backdrop, .tracking-detail-modal::backdrop { background: rgba(0,0,0,.6); }
.camera-state-title-row { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.camera-state-meta-row { display: flex; gap: 16px; flex-wrap: wrap; font-size: .85rem; margin-bottom: 8px; color: var(--muted); }
.camera-state-badge { padding: 2px 8px; border-radius: 10px; font-size: .75rem; }
.camera-state-badge.ok { background: rgba(34,197,94,.15); color: #22c55e; }
.camera-state-badge.warning { background: rgba(245,158,11,.15); color: #f59e0b; }
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
.tracking-download-btn { font-size: .78rem; padding: 4px 10px; background: rgba(255,255,255,.07); border: 1px solid var(--border); border-radius: 6px; cursor: pointer; color: var(--text); }
.tracking-rutas-tabs { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.tracking-ruta-tab { padding: 5px 12px; border-radius: 14px; font-size: .8rem; border: 1px solid var(--border); background: none; cursor: pointer; color: var(--text); }
.tracking-ruta-tab.active { background: var(--tab-color, #3b82f6); color: #fff; border-color: transparent; }
.tracking-sequence { display: flex; flex-direction: column; gap: 6px; }
.tracking-item { display: flex; align-items: flex-start; gap: 8px; font-size: .85rem; padding: 6px 0; border-bottom: 1px solid var(--border); }
.tracking-punta { color: #60a5fa; }
.tracking-punta-label { font-size: .72rem; color: var(--muted); display: block; }
.tracking-cable { flex-direction: column; gap: 2px; }
.tracking-cable-name { font-weight: 600; }
.tracking-atenuacion { color: #f59e0b; font-size: .78rem; }
.tracking-empalme-id { color: var(--muted); font-size: .75rem; }
.tracking-loading, .tracking-error, .tracking-empty { padding: 16px; color: var(--muted); font-size: .85rem; }
.tracking-error { color: #ef4444; }
/* Toasts */
.toast-container { position: fixed; bottom: 24px; right: 24px; z-index: 9999; display: flex; flex-direction: column; gap: 8px; pointer-events: none; }
.toast { display: flex; align-items: flex-start; gap: 10px; background: #1e1e1e; border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; min-width: 260px; max-width: 380px; pointer-events: all; box-shadow: 0 4px 12px rgba(0,0,0,.4); }
.toast.success { border-left: 3px solid #22c55e; }
.toast.error { border-left: 3px solid #ef4444; }
.toast.warning { border-left: 3px solid #f59e0b; }
.toast.info { border-left: 3px solid #3b82f6; }
.toast-icon { font-size: 1rem; line-height: 1; }
.toast-content { flex: 1; }
.toast-title { font-weight: 600; font-size: .88rem; }
.toast-message { font-size: .82rem; color: var(--muted); margin-top: 2px; }
.toast-close { background: none; border: none; cursor: pointer; color: var(--muted); font-size: 1.1rem; padding: 0; }
.toast-anim-enter-active, .toast-anim-leave-active { transition: all .25s ease; }
.toast-anim-enter-from, .toast-anim-leave-to { opacity: 0; transform: translateX(24px); }

/* Estado icons — colores faltantes en la migración */
.infra-estado-icon.ocupada { background: #f59e0b; }
.infra-estado-icon.detectada { background: #9ca3af; }

/* Toolbar */
.infra-toolbar {
  display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap;
  gap: 10px; padding: 12px 0 16px; border-bottom: 1px solid var(--border); margin-bottom: 16px;
}
.infra-toolbar-title { margin: 0; font-size: 1.05rem; font-weight: 700; color: var(--text); }
.infra-toolbar-actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }

/* Zona Drag & Drop de upload tracking */
.upload-drop-zone {
  display: inline-flex; align-items: center; justify-content: center;
  padding: 7px 14px; border-radius: 8px; font-size: .88rem; font-weight: 500; cursor: pointer;
  user-select: none; transition: background .15s, border-color .15s;
  background: rgba(255,255,255,.06); color: var(--text);
  border: 1.5px dashed var(--border);
  min-height: 36px;
}
.upload-drop-zone:hover { background: rgba(255,255,255,.12); border-color: #60a5fa; }
.upload-drop-zone.drag-over {
  background: rgba(96,165,250,.12); border-color: #60a5fa;
  color: #60a5fa; outline: none;
}

/* Botones extra (modificadores de .btn global) */
.btn.danger { background: rgba(239,68,68,.15); color: #ef4444; border: 1px solid rgba(239,68,68,.3); }
.btn.danger:hover:not(:disabled) { background: rgba(239,68,68,.25); }
.btn.danger-subtle { background: none; color: #ef4444; border: 1px solid rgba(239,68,68,.2); }
.btn.danger-subtle:hover:not(:disabled) { background: rgba(239,68,68,.1); }
.btn.success { background: rgba(34,197,94,.15); color: #22c55e; border: 1px solid rgba(34,197,94,.3); }
.btn.success:hover:not(:disabled) { background: rgba(34,197,94,.25); }

/* Dropdown descargar */
.download-dropdown-wrapper { position: relative; }
.dropdown-caret { display: inline-block; transition: transform .2s; font-size: .75rem; margin-left: 2px; }
.dropdown-caret.open { transform: rotate(180deg); }
.download-dropdown-menu {
  position: absolute; top: calc(100% + 4px); right: 0; z-index: 200;
  min-width: 180px; margin: 0; padding: 4px 0; list-style: none;
  background: #1e1e1e; border: 1px solid var(--border); border-radius: 8px;
  box-shadow: 0 6px 18px rgba(0,0,0,.45);
}
.dropdown-item {
  padding: 9px 14px; font-size: .85rem; cursor: pointer;
  color: var(--text); display: flex; align-items: center; gap: 7px; white-space: nowrap;
}
.dropdown-item:hover { background: rgba(255,255,255,.07); }
.dropdown-divider { border: none; border-top: 1px solid var(--border); margin: 4px 0; }
.btn.warning { background: rgba(245,158,11,.15); color: #f59e0b; border: 1px solid rgba(245,158,11,.3); }
.btn.warning:hover:not(:disabled) { background: rgba(245,158,11,.25); }

/* Leyenda de estados — atajos de filtrado rápido */
.infra-legend { display: flex; flex-wrap: wrap; gap: 6px; margin: 12px 0 8px; }
.infra-legend-item {
  display: inline-flex; align-items: center; gap: 5px;
  background: none; border: 1px solid transparent; cursor: pointer;
  padding: 3px 10px; border-radius: 14px; font-size: .8rem;
  color: var(--muted); transition: background .15s, color .15s, border-color .15s;
}
.infra-legend-item:hover { background: rgba(255,255,255,.07); color: var(--text); }
.infra-legend-item.active { background: rgba(255,255,255,.10); color: var(--text); border-color: var(--border); }
.infra-legend-dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; flex-shrink: 0; }
.infra-legend-dot.libre { background: #22c55e; }
.infra-legend-dot.ocupada { background: #f59e0b; }
.infra-legend-dot.baneada { background: #ef4444; }
.infra-legend-dot.detectada { background: #9ca3af; }
/* Chip de filtro de estado activo */
.infra-state-filter-chip {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 3px 6px 3px 10px; border-radius: 14px; font-size: .82rem;
  background: rgba(96,165,250,.12); color: #60a5fa;
  border: 1px solid rgba(96,165,250,.3); margin-top: 8px;
}
.infra-state-filter-remove {
  background: none; border: none; cursor: pointer; color: #60a5fa;
  font-size: 1rem; padding: 0 2px; line-height: 1;
}
.infra-state-filter-remove:hover { color: var(--text); }

/* Modal genérico compartido */
.infra-generic-modal {
  position: fixed; inset: 0; margin: auto;
  border: 1px solid var(--border); border-radius: 10px; background: #1c1c1c;
  color: var(--text); padding: 0; max-width: 520px; width: 95vw; max-height: 90vh; overflow-y: auto;
}
.infra-generic-modal::backdrop { background: rgba(0,0,0,.6); }
.modal-inner { padding: 24px; display: flex; flex-direction: column; gap: 6px; }
.modal-header-row { display: flex; align-items: center; margin-bottom: 10px; }
.modal-title { margin: 0; font-size: 1rem; flex: 1; }
.modal-desc { margin: 0 0 6px; font-size: .83rem; color: var(--muted); }
.danger-text { color: #f59e0b; }
.req { color: #ef4444; }
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
.wizard-step-item.active .wizard-step-num { border-color: #60a5fa; background: rgba(96,165,250,.15); color: #60a5fa; }
.wizard-step-item.active .wizard-step-label { color: #60a5fa; font-weight: 600; }
.wizard-step-item.done .wizard-step-num { border-color: #22c55e; background: rgba(34,197,94,.15); color: #22c55e; }
.wizard-step-item.done .wizard-step-label { color: #22c55e; }
.wizard-step-connector { flex: 1; height: 1px; background: var(--border); margin: 0 6px; }

/* Paso 2 */
.ban-step2-affected {
  font-size: .84rem; color: var(--muted); padding: 6px 10px;
  background: rgba(255,255,255,.04); border-radius: 6px; margin-bottom: 10px;
}
.ban-prot-tabs { display: flex; gap: 0; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; margin-bottom: 10px; }
.ban-prot-tab {
  flex: 1; padding: 8px 10px; font-size: .82rem; cursor: pointer; text-align: center;
  background: transparent; color: var(--muted); border: none; transition: background .15s;
}
.ban-prot-tab:hover { background: rgba(255,255,255,.06); }
.ban-prot-tab.active { background: rgba(96,165,250,.12); color: #60a5fa; font-weight: 600; }
.ban-search-row { display: flex; gap: 8px; margin-bottom: 4px; }
.ban-search-row input { flex: 1; }
.ban-rutas-error { font-size: .83rem; color: #ef4444; padding: 6px 0; }
.ban-rutas-empty { font-size: .83rem; color: var(--muted); padding: 10px 0; text-align: center; }
.ban-ruta-grid { display: flex; flex-direction: column; gap: 6px; margin-top: 4px; }
.ban-ruta-card {
  display: flex; align-items: flex-start; gap: 10px; padding: 10px 12px;
  background: rgba(255,255,255,.04); border: 1.5px solid var(--border);
  border-radius: 8px; cursor: pointer; transition: border-color .15s, background .15s;
}
.ban-ruta-card:hover { background: rgba(255,255,255,.07); border-color: rgba(96,165,250,.4); }
.ban-ruta-card.selected { border-color: #60a5fa; background: rgba(96,165,250,.08); }
.ban-ruta-card.all-option { border-style: dashed; }
.ban-ruta-icon { font-size: 1.1rem; padding-top: 1px; flex-shrink: 0; }
.ban-ruta-nombre { font-size: .88rem; font-weight: 600; color: var(--text); }
.ban-ruta-meta { font-size: .78rem; color: var(--muted); margin-top: 2px; }
.ban-tracking-alert {
  margin-top: 6px; padding: 6px 8px; border-radius: 6px; font-size: .78rem;
  background: rgba(245,158,11,.12); color: #f59e0b; border: 1px solid rgba(245,158,11,.25);
}
.ban-tracking-alert-actions { display: flex; gap: 6px; margin-top: 6px; }
.btn.small { padding: 4px 10px; font-size: .78rem; }

/* Paso 3 */
.ban-summary-block {
  background: rgba(255,255,255,.04); border: 1px solid var(--border);
  border-radius: 8px; padding: 12px 14px; display: flex; flex-direction: column;
  gap: 6px; margin-bottom: 12px; font-size: .85rem;
}
.ban-summary-row { display: flex; gap: 8px; }
.ban-summary-label { color: var(--muted); min-width: 130px; flex-shrink: 0; font-size: .82rem; }
.ban-confirm-row {
  display: flex; align-items: flex-start; gap: 8px; font-size: .85rem;
  cursor: pointer; padding: 8px 10px; border-radius: 6px;
  background: rgba(239,68,68,.06); border: 1px solid rgba(239,68,68,.2);
}
.ban-confirm-row input[type=checkbox] { margin-top: 2px; flex-shrink: 0; }

/* Modal de resolución de tracking */
.tracking-resolve-modal { max-width: 580px; }
.upload-analyzing { padding: 16px 0; font-size: .88rem; color: var(--muted); }
.resolve-status-badge {
  display: inline-block; padding: 4px 12px; border-radius: 12px;
  font-size: .82rem; font-weight: 700; margin-bottom: 6px; background: rgba(255,255,255,.07);
}
.resolve-status-badge.status-new { background: rgba(59,130,246,.15); color: #60a5fa; }
.resolve-status-badge.status-identical { background: rgba(34,197,94,.15); color: #22c55e; }
.resolve-status-badge.status-conflict { background: rgba(245,158,11,.15); color: #f59e0b; }
.resolve-status-badge.status-potential_upgrade { background: rgba(168,85,247,.15); color: #c084fc; }
.resolve-status-badge.status-new_strand { background: rgba(168,85,247,.15); color: #c084fc; }
.resolve-status-badge.status-error { background: rgba(239,68,68,.15); color: #ef4444; }
.resolve-message { margin: 0 0 8px; font-size: .85rem; }
.resolve-svc-info { font-size: .83rem; color: var(--muted); margin-bottom: 8px; }
.resolve-hint { font-size: .85rem; color: var(--muted); margin: 4px 0 8px; }
.resolve-error { color: #ef4444; font-size: .85rem; margin: 8px 0; }
.resolve-rutas-list { display: flex; flex-direction: column; gap: 4px; margin: 6px 0; }
.resolve-ruta-item {
  display: flex; align-items: center; gap: 8px; font-size: .82rem;
  padding: 6px 8px; background: rgba(255,255,255,.04); border-radius: 6px;
}
.resolve-ruta-meta { font-size: .78rem; color: var(--muted); }
.resolve-select { width: 100%; margin: 4px 0 10px; }
.resolve-upgrade-info {
  font-size: .83rem; background: rgba(255,255,255,.04); border-radius: 6px;
  padding: 8px 10px; margin: 6px 0; display: flex; flex-direction: column; gap: 3px;
}
/* ─── Baneos Activos ─── */
.active-bans-btn { position: relative; }
.active-bans-badge {
  position: absolute; top: -6px; right: -6px;
  min-width: 18px; height: 18px; border-radius: 9px; padding: 0 4px;
  background: #ef4444; color: #fff; font-size: .72rem; font-weight: 700;
  display: inline-flex; align-items: center; justify-content: center; line-height: 1;
}
.active-bans-modal { max-width: 640px; }
.active-bans-loading, .active-bans-empty {
  padding: 20px 0; text-align: center; color: var(--muted); font-size: .88rem;
}
.active-bans-error { color: #ef4444; font-size: .85rem; padding: 8px 0; }
.active-bans-count { font-size: .8rem; color: var(--muted); margin-bottom: 10px; }
.active-bans-list { display: flex; flex-direction: column; gap: 10px; max-height: 60vh; overflow-y: auto; }
.active-ban-card {
  background: rgba(255,255,255,.04); border: 1px solid var(--border);
  border-radius: 8px; padding: 12px 14px; display: flex; flex-direction: column; gap: 6px;
}
.active-ban-card-header { display: flex; justify-content: space-between; align-items: flex-start; }
.active-ban-ticket { display: flex; flex-direction: column; gap: 2px; }
.active-ban-ticket-label { font-size: .72rem; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }
.active-ban-duracion {
  font-size: .78rem; font-weight: 600; color: #f59e0b;
  background: rgba(245,158,11,.1); padding: 2px 8px; border-radius: 10px;
  white-space: nowrap; align-self: flex-start;
}
.active-ban-servicios { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: .85rem; }
.active-ban-svc-item { display: flex; align-items: center; gap: 5px; }
.active-ban-svc-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.active-ban-svc-dot.afectado { background: #f59e0b; }
.active-ban-svc-dot.protegido { background: #ef4444; }
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
