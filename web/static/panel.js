//
// Nombre de archivo: panel.js
// Ubicación de archivo: web/static/panel.js
// Descripción: Lógica de tabs/secciones y dropzones para el Panel
//

(function(){
  const $$ = (sel, root=document) => Array.from(root.querySelectorAll(sel));
  const $ = (sel, root=document) => root.querySelector(sel);

  // Tabs
  const chips = $$('.actions .chip');
  const views = $$('.view');
  function showView(name){
    chips.forEach(c => c.classList.toggle('active', c.dataset.view===name));
    views.forEach(v => v.classList.toggle('active', v.id === `view-${name}`));
  }
  chips.forEach(ch => {
    if (ch.tagName === 'A') return;
    ch.addEventListener('click', () => showView(ch.dataset.view));
  });
  showView('chat'); // default

  // Dropzone helper (click-to-browse + drag/drop)
  function wireDropzone(zoneId, inputId){
    const zone = document.getElementById(zoneId);
    const input = document.getElementById(inputId);
    if (!zone || !input) return;
    // Ocultar input nativo si no está oculto
    input.style.position = 'absolute';
    input.style.left = '-9999px';
    // Abrir selector sólo cuando clickeamos la zona (y no el input)
    zone.addEventListener('click', (e) => {
      if (zone.classList.contains('disabled')) return;
      if (e.target === input) return; // no duplicar
      input.click();
    });
    // Drag & Drop
    zone.addEventListener('dragover', e => {
      e.preventDefault();
      if (zone.classList.contains('disabled')) return;
      zone.classList.add('drag');
    });
    zone.addEventListener('dragleave', () => zone.classList.remove('drag'));
    zone.addEventListener('drop', e => {
      e.preventDefault();
      zone.classList.remove('drag');
      if (zone.classList.contains('disabled')) return;
      if(e.dataTransfer.files && e.dataTransfer.files.length){
        input.files = e.dataTransfer.files;
        const name = e.dataTransfer.files[0].name;
        const label = zone.querySelector('span');
        if (label) label.textContent = `Seleccionado: ${name}`;
      }
    });
    // Reflejar selección
    input.addEventListener('change', () => {
      if (input.files && input.files.length){
        const label = zone.querySelector('span');
        if (label) label.textContent = `Seleccionado: ${input.files[0].name}`;
      }
    });
  }
  wireDropzone('rep-drop', 'rep-file');
  wireDropzone('fo-drop', 'fo-file');
  wireDropzone('ciena-drop', 'ciena-file');

  // Comparador VLAN
  const vlanEls = {
    textA: document.getElementById('vlan-text-a'),
    textB: document.getElementById('vlan-text-b'),
    status: document.getElementById('vlan-status'),
    onlyA: document.getElementById('vlan-only-a'),
    onlyB: document.getElementById('vlan-only-b'),
    common: document.getElementById('vlan-common'),
    onlyACount: document.getElementById('vlan-only-a-count'),
    onlyBCount: document.getElementById('vlan-only-b-count'),
    commonCount: document.getElementById('vlan-common-count'),
  };

  const vlanCompareBtn = document.getElementById('vlan-compare');
  const vlanClearBtn = document.getElementById('vlan-clear');

  function setVlanStatus(message, variant='info', isBusy=false){
    if (!vlanEls.status) return;
    const variants = {
      info: 'result-box info',
      success: 'result-box success',
      error: 'result-box error',
      muted: 'result-box muted'
    };
    vlanEls.status.className = variants[variant] || variants.info;
    vlanEls.status.textContent = message;
    if (isBusy) {
      vlanEls.status.setAttribute('aria-busy', 'true');
    } else {
      vlanEls.status.removeAttribute('aria-busy');
    }
  }

  function setVlanCount(el, value){
    if (el) el.textContent = value;
  }

  function renderVlanList(target, values){
    if (!target) return;
    target.innerHTML = '';
    if (!values || !values.length){
      target.classList.add('empty');
      target.textContent = target.dataset.empty || 'Sin datos';
      return;
    }
    target.classList.remove('empty');
    const sortedValues = [...values]
      .map((val) => Number(val))
      .filter((val) => Number.isFinite(val))
      .sort((a, b) => a - b);
    sortedValues.forEach((val) => {
      const pill = document.createElement('span');
      pill.className = 'vlan-pill';
      pill.textContent = val;
      target.appendChild(pill);
    });
  }

  function resetVlanResults(){
    renderVlanList(vlanEls.onlyA, []);
    renderVlanList(vlanEls.onlyB, []);
    renderVlanList(vlanEls.common, []);
    setVlanCount(vlanEls.onlyACount, 0);
    setVlanCount(vlanEls.onlyBCount, 0);
    setVlanCount(vlanEls.commonCount, 0);
  }

  if (vlanEls.onlyA || vlanEls.onlyB || vlanEls.common){
    resetVlanResults();
  }

  async function handleVlanCompare(){
    if (!vlanEls.textA || !vlanEls.textB){
      return;
    }
    const textA = vlanEls.textA.value.trim();
    const textB = vlanEls.textB.value.trim();
    if (!textA || !textB){
      resetVlanResults();
      setVlanStatus('Pegá configuraciones en ambos campos.', 'error');
      return;
    }
    setVlanStatus('Comparando configuraciones...', 'info', true);
    const payload = { text_a: textA, text_b: textB };
    if (window.CSRF_TOKEN){
      payload.csrf_token = window.CSRF_TOKEN;
    }
    try {
      const res = await fetch('/api/tools/compare-vlans', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok){
        throw new Error(data.error || 'Error comparando VLANs');
      }
      renderVlanList(vlanEls.onlyA, data.only_a || []);
      renderVlanList(vlanEls.onlyB, data.only_b || []);
      renderVlanList(vlanEls.common, data.common || []);
      setVlanCount(vlanEls.onlyACount, data.only_a ? data.only_a.length : 0);
      setVlanCount(vlanEls.onlyBCount, data.only_b ? data.only_b.length : 0);
      setVlanCount(vlanEls.commonCount, data.common ? data.common.length : 0);
      const totalA = data.total_a ?? (data.vlans_a ? data.vlans_a.length : 0);
      const totalB = data.total_b ?? (data.vlans_b ? data.vlans_b.length : 0);
      setVlanStatus(`Totales: A ${totalA} · B ${totalB} · Coincidencias ${data.common ? data.common.length : 0}`, 'success');
    } catch (err){
      resetVlanResults();
      setVlanStatus(err.message, 'error');
    }
  }

  if (vlanCompareBtn){
    vlanCompareBtn.addEventListener('click', handleVlanCompare);
  }
  if (vlanClearBtn){
    vlanClearBtn.addEventListener('click', () => {
      if (vlanEls.textA) vlanEls.textA.value = '';
      if (vlanEls.textB) vlanEls.textB.value = '';
      resetVlanResults();
      setVlanStatus('Ingresá dos configuraciones de interfaz trunk para comenzar.', 'muted');
    });
  }

  // Repetitividad
  const repBtn = document.getElementById('rep-run');
  const repUseDb = document.getElementById('rep-use-db');
  const repWithGeo = document.getElementById('rep-with-geo');
  const repDrop = document.getElementById('rep-drop');
  const repFile = document.getElementById('rep-file');

  function updateRepDrop(){
    if (!repDrop) return;
    const label = repDrop.querySelector('span');
    if (repUseDb && repUseDb.checked){
      repDrop.classList.add('disabled');
      repDrop.setAttribute('aria-disabled', 'true');
      if (label) label.textContent = 'Usando datos desde la base (archivo opcional)';
      if (repFile) repFile.value = '';
    } else {
      repDrop.classList.remove('disabled');
      repDrop.removeAttribute('aria-disabled');
      if (label) label.textContent = 'Arrastrá el .xlsx acá o hacé click';
    }
  }
  if (repUseDb){
    repUseDb.addEventListener('change', updateRepDrop);
    updateRepDrop();
  }

  if (repBtn) {
    repBtn.addEventListener('click', async () => {
      const out = document.getElementById('rep-result');
      const mes = document.getElementById('rep-mes');
      const anio = document.getElementById('rep-anio');
      const pdf = document.getElementById('rep-pdf');
      const useDb = repUseDb && repUseDb.checked;
      if (!useDb && repFile && !repFile.files.length){
        out.textContent = 'Seleccioná un archivo';
        out.className='result-box error';
        return;
      }
      const data = new FormData();
      if (repFile && repFile.files.length && !useDb){
        data.append('file', repFile.files[0]);
      }
      data.append('mes', mes.value);
      data.append('anio', anio.value);
      data.append('include_pdf', pdf && pdf.checked ? 'true' : 'false');
      data.append('with_geo', repWithGeo && repWithGeo.checked ? 'true' : 'false');
      data.append('use_db', useDb ? 'true' : 'false');
      if (window.CSRF_TOKEN) data.append('csrf_token', window.CSRF_TOKEN);
      out.textContent = 'Procesando...'; out.className='result-box info';
      try {
        const res = await fetch('/api/flows/repetitividad', { method:'POST', body:data, credentials:'include'});
        const j = await res.json();
        if (!res.ok) throw new Error(j.error || 'Error');
        const links = [];
        if (j.docx) links.push(`<a href="${j.docx}" target="_blank">DOCX</a>`);
        if (j.pdf) links.push(`<a href="${j.pdf}" target="_blank">PDF</a>`);
        const mapImages = Array.isArray(j.map_images) ? j.map_images : [];
        mapImages.forEach((url, idx) => {
          const label = mapImages.length > 1 ? `Mapa PNG ${idx + 1}` : 'Mapa PNG';
          links.push(`<a href="${url}" target="_blank">${label}</a>`);
        });
        out.innerHTML = 'Listo: ' + (links.join(' · ') || 'sin archivos');
        out.className='result-box success';
      } catch (e) {
        out.textContent = 'Error: ' + e.message; out.className='result-box error';
      }
    });
  }

  // FO (WIP)
  const foBtn = document.getElementById('fo-run');
  if (foBtn) {
    foBtn.addEventListener('click', async () => {
      const out = document.getElementById('fo-result');
      out.textContent = 'No implementado aún';
      out.className='result-box info';
    });
  }
})();

// --- Chat HTTP básico (envío + adjuntos) ---
(function(){
  const $ = (sel, root=document) => root.querySelector(sel);
  const log = $('#chat-log');
  const status = $('#chat-status');
  const form = $('#chat-form');
  const input = $('#chat-input');
  const drop = $('#chat-dropzone');
  const attachBtn = $('#chat-attachment-browse');
  const attachInput = $('#chat-attachment-input');
  const chips = $('#chat-attachments');
  if (!form || !input) return; // chat no presente

  function appendMsg(text, role='user'){
    const div = document.createElement('div');
    div.className = `msg ${role}`;
    div.textContent = text;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
  }

  async function sendMessage(text){
    const body = new URLSearchParams();
    body.set('text', text);
    if (window.CSRF_TOKEN) body.set('csrf_token', window.CSRF_TOKEN);
    status.textContent = 'Enviando...';
    try {
      const res = await fetch('/api/chat/message', { method: 'POST', body, credentials: 'include', headers:{ 'Accept':'application/json' }});
      const j = await res.json();
      if (!res.ok) throw new Error(j.error || 'Error');
      appendMsg(j.reply || '(sin respuesta)', 'assistant');
      status.textContent = '';
    } catch (e){
      status.textContent = `Error: ${e.message}`;
      status.className = 'chat-status error';
    }
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    appendMsg(text, 'user');
    input.value = '';
    await sendMessage(text);
  });

  // Adjuntos: abrir selector y subir 1 a 1
  if (attachBtn && attachInput){
    attachBtn.addEventListener('click', () => attachInput.click());
    attachInput.addEventListener('change', async () => {
      const files = Array.from(attachInput.files || []);
      for (const f of files){
        const fd = new FormData();
        fd.append('file', f);
        if (window.CSRF_TOKEN) fd.append('csrf_token', window.CSRF_TOKEN);
        try {
          status.textContent = `Subiendo ${f.name}...`;
          const res = await fetch('/api/chat/uploads', { method:'POST', body:fd, credentials:'include' });
          const j = await res.json();
          if (!res.ok) throw new Error(j.error || 'Error');
          // chip visual
          const chip = document.createElement('span');
          chip.className = 'attachment-chip';
          chip.innerHTML = `<span>${j.name}</span><button class="remove-attachment" title="Quitar">×</button>`;
          chip.querySelector('button').addEventListener('click', () => chip.remove());
          chips.classList.add('active');
          chips.appendChild(chip);
          status.textContent = '';
        } catch(e){
          status.textContent = `Error subiendo ${f.name}: ${e.message}`;
          status.className = 'chat-status error';
        }
      }
      attachInput.value = '';
    });
  }

  // Soporte drop en zona de chat
  if (drop && attachInput){
    drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('dragging'); });
    drop.addEventListener('dragleave', () => drop.classList.remove('dragging'));
    drop.addEventListener('drop', (e) => {
      e.preventDefault(); drop.classList.remove('dragging');
      if (e.dataTransfer.files && e.dataTransfer.files.length){
        attachInput.files = e.dataTransfer.files; // dispara change y sube
        const event = new Event('change');
        attachInput.dispatchEvent(event);
      }
    });
  }

  // Alarmas Ciena
  const cienaBtn = document.getElementById('ciena-run');
  if (cienaBtn) {
    cienaBtn.addEventListener('click', async () => {
      const out = document.getElementById('ciena-result');
      const fileInput = document.getElementById('ciena-file');
      
      if (!fileInput.files.length) {
        out.textContent = 'Seleccioná un archivo CSV';
        out.className = 'result-box error';
        return;
      }
      
      const data = new FormData();
      data.append('file', fileInput.files[0]);
      if (window.CSRF_TOKEN) {
        data.append('csrf_token', window.CSRF_TOKEN);
      }
      
      out.textContent = 'Procesando...';
      out.className = 'result-box info';
      
      try {
        const res = await fetch('/api/tools/alarmas-ciena', {
          method: 'POST',
          body: data,
          credentials: 'include'
        });
        
        if (!res.ok) {
          // Intentar obtener mensaje de error del JSON
          let errMsg = 'Error al procesar el archivo';
          try {
            const errData = await res.json();
            if (errData.error) errMsg = errData.error;
            else if (errData.detail) errMsg = errData.detail;
          } catch {}
          throw new Error(errMsg);
        }
        
        // Obtener información del archivo desde los headers
        const formato = res.headers.get('X-Formato-Detectado') || 'desconocido';
        const filas = res.headers.get('X-Filas-Procesadas') || '?';
        const columnas = res.headers.get('X-Columnas') || '?';
        
        // Obtener el blob Excel de la respuesta
        const blob = await res.blob();
        
        // Crear un link temporal para descargarlo
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = fileInput.files[0].name.replace(/\.csv$/i, '') + '_procesado.xlsx';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
        
        out.textContent = `✔ Archivo convertido (formato: ${formato}, ${filas} filas, ${columnas} columnas). La descarga debería haber comenzado.`;
        out.className = 'result-box success';
        
      } catch (e) {
        out.textContent = 'Error: ' + e.message;
        out.className = 'result-box error';
      }
    });
  }
})();

// --- Infraestructura / Cámaras Dashboard ---
(function(){
  const $ = (sel, root=document) => root.querySelector(sel);
  const $$ = (sel, root=document) => Array.from(root.querySelectorAll(sel));

  // Elementos del DOM - Smart Search (texto libre)
  const searchInput = $('#infra-search-input');
  const addTermBtn = $('#infra-add-term');
  const searchTermsContainer = $('#infra-search-terms');
  const searchBtn = $('#infra-search-btn');
  const quickFilterChips = $$('.infra-quick-chip');

  // Elementos del DOM - Upload y resultados
  const uploadZone = $('#infra-drop');
  const fileInput = $('#infra-file');
  const statusEl = $('#infra-status');
  const gridEl = $('#infra-grid');
  const loadingEl = $('#infra-loading');
  const emptyEl = $('#infra-empty');

  if (!searchInput || !gridEl) return; // Vista infra no presente

  // Estado de términos de búsqueda activos
  let searchTerms = [];
  let hasSearched = false;

  // ===========================================
  // TOAST NOTIFICATIONS
  // ===========================================
  function showToast(type, title, message, duration = 5000) {
    const container = $('#toast-container');
    if (!container) return;

    const icons = {
      success: '✓',
      error: '✗',
      warning: '⚠',
      info: 'ℹ'
    };

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `
      <span class="toast-icon">${icons[type] || 'ℹ'}</span>
      <div class="toast-content">
        <div class="toast-title">${title}</div>
        ${message ? `<div class="toast-message">${message}</div>` : ''}
      </div>
      <button class="toast-close" aria-label="Cerrar">×</button>
    `;

    const closeBtn = toast.querySelector('.toast-close');
    const closeToast = () => {
      toast.classList.add('closing');
      setTimeout(() => toast.remove(), 250);
    };

    closeBtn.addEventListener('click', closeToast);
    container.appendChild(toast);

    if (duration > 0) {
      setTimeout(closeToast, duration);
    }
  }

  // ===========================================
  // STATUS HELPERS
  // ===========================================
  function setStatus(text, variant = 'muted') {
    if (!statusEl) return;
    statusEl.textContent = text || '';
    statusEl.className = `infra-status ${variant}`;
  }

  function showLoading(show) {
    if (loadingEl) loadingEl.hidden = !show;
    if (gridEl) gridEl.style.display = show ? 'none' : '';
    if (emptyEl) emptyEl.hidden = true;
  }

  function showEmpty(show) {
    if (emptyEl) emptyEl.hidden = !show;
    if (gridEl) gridEl.style.display = show ? 'none' : '';
    if (loadingEl) loadingEl.hidden = true;
  }

  function showInitialState() {
    // Estado inicial: mostrar empty state con mensaje de bienvenida
    if (loadingEl) loadingEl.hidden = true;
    if (gridEl) gridEl.style.display = 'none';
    if (emptyEl) emptyEl.hidden = false;
    setStatus('');
  }

  // ===========================================
  // COLORES DE RUTAS SEGÚN TIPO/ORDEN
  // ===========================================
  const RUTA_COLORS = {
    PRINCIPAL: '#3B82F6',  // Azul (actual)
    BACKUP: '#37BC7D',     // Verde (Camino 2/Secundario)
    ALTERNATIVA: '#F54927', // Naranja/Rojo (Camino 3)
    CUARTO: '#E61876',     // Rosa (Camino 4+)
  };

  function getRutaColor(ruta, index) {
    // Primero por tipo explícito
    if (ruta.ruta_tipo === 'PRINCIPAL') return RUTA_COLORS.PRINCIPAL;
    if (ruta.ruta_tipo === 'BACKUP') return RUTA_COLORS.BACKUP;
    if (ruta.ruta_tipo === 'ALTERNATIVA') return RUTA_COLORS.ALTERNATIVA;
    
    // Por nombre
    const nombre = (ruta.ruta_nombre || '').toLowerCase();
    if (nombre.includes('principal') || nombre === 'camino 1') return RUTA_COLORS.PRINCIPAL;
    if (nombre.includes('backup') || nombre.includes('secundario') || nombre === 'camino 2') return RUTA_COLORS.BACKUP;
    if (nombre === 'camino 3' || nombre.includes('alternativ')) return RUTA_COLORS.ALTERNATIVA;
    if (nombre === 'camino 4') return RUTA_COLORS.CUARTO;
    
    // Por índice (fallback)
    const colors = [RUTA_COLORS.PRINCIPAL, RUTA_COLORS.BACKUP, RUTA_COLORS.ALTERNATIVA, RUTA_COLORS.CUARTO];
    return colors[index % colors.length];
  }

  // ===========================================
  // MODAL DE TRACKING
  // ===========================================
  let trackingDetailModal = null;
  
  function createTrackingModalIfNeeded() {
    if (trackingDetailModal) return;
    
    trackingDetailModal = document.createElement('dialog');
    trackingDetailModal.className = 'tracking-detail-modal';
    trackingDetailModal.innerHTML = `
      <div class="tracking-detail-content">
        <div class="tracking-detail-header">
          <h3 class="tracking-detail-title">Tracking del Servicio</h3>
          <button class="tracking-detail-close" type="button">&times;</button>
        </div>
        <div class="tracking-detail-info"></div>
        <div class="tracking-detail-list"></div>
      </div>
    `;
    document.body.appendChild(trackingDetailModal);
    
    // Cerrar con click en X
    trackingDetailModal.querySelector('.tracking-detail-close').addEventListener('click', () => {
      trackingDetailModal.close();
    });
    
    // Cerrar con click fuera
    trackingDetailModal.addEventListener('click', (e) => {
      if (e.target === trackingDetailModal) trackingDetailModal.close();
    });
  }

  async function showTrackingModal(rutaId, servicioId, rutaNombre, rutaTipo, color) {
    createTrackingModalIfNeeded();
    
    const titleEl = trackingDetailModal.querySelector('.tracking-detail-title');
    const infoEl = trackingDetailModal.querySelector('.tracking-detail-info');
    const listEl = trackingDetailModal.querySelector('.tracking-detail-list');
    
    titleEl.textContent = `Svc: ${servicioId}`;
    infoEl.innerHTML = `
      <span class="tracking-ruta-badge" style="background-color: ${color}">
        ${rutaNombre} (${rutaTipo})
      </span>
    `;
    listEl.innerHTML = '<div class="tracking-loading">Cargando tracking...</div>';
    
    trackingDetailModal.showModal();
    
    try {
      const res = await fetch(`${window.API_BASE || ''}/api/infra/rutas/${rutaId}/tracking`);
      const data = await res.json();
      
      if (data.error) {
        listEl.innerHTML = `<div class="tracking-error">${data.error}</div>`;
        return;
      }
      
      const tracking = data.tracking || [];
      if (tracking.length === 0) {
        listEl.innerHTML = '<div class="tracking-empty">Sin información de tracking</div>';
        return;
      }
      
      // Renderizar secuencia cámara-cable
      let html = '<div class="tracking-sequence">';
      tracking.forEach((item, idx) => {
        if (item.tipo === 'camara') {
          html += `
            <div class="tracking-item tracking-camara">
              <span class="tracking-icon">📍</span>
              <span class="tracking-text">${item.descripcion || 'Cámara'}</span>
              ${item.empalme_id ? `<span class="tracking-empalme-id">#${item.empalme_id}</span>` : ''}
            </div>
          `;
        } else if (item.tipo === 'cable') {
          html += `
            <div class="tracking-item tracking-cable">
              <span class="tracking-cable-line"></span>
              <span class="tracking-cable-info">
                <span class="tracking-cable-name">${item.nombre || 'Cable'}</span>
                ${item.atenuacion_db != null ? `<span class="tracking-atenuacion">${item.atenuacion_db} dB</span>` : ''}
              </span>
            </div>
          `;
        }
      });
      html += '</div>';
      
      listEl.innerHTML = html;
      
    } catch (err) {
      listEl.innerHTML = `<div class="tracking-error">Error: ${err.message}</div>`;
    }
  }

  // ===========================================
  // RENDERIZADO DE TARJETAS
  // ===========================================
  function renderCamaraCard(camara) {
    const estadoLower = (camara.estado || 'libre').toLowerCase();
    const rutas = camara.rutas || [];
    const origenDatos = camara.origen_datos || 'MANUAL';

    const card = document.createElement('div');
    card.className = 'infra-camara-card';
    card.dataset.estado = camara.estado || 'LIBRE';
    card.dataset.origen = origenDatos;

    // Renderizar chips de servicios con colores según ruta
    let serviciosHtml = '';
    if (rutas.length > 0) {
      // Agrupar por servicio_id para ordenar
      const servicioRutas = {};
      rutas.forEach((ruta, idx) => {
        if (!servicioRutas[ruta.servicio_id]) {
          servicioRutas[ruta.servicio_id] = [];
        }
        servicioRutas[ruta.servicio_id].push({ ...ruta, _index: idx });
      });
      
      // Generar chips
      const chips = [];
      Object.entries(servicioRutas).forEach(([svcId, svcRutas]) => {
        svcRutas.forEach((ruta) => {
          const color = getRutaColor(ruta, ruta._index);
          chips.push(`
            <span class="infra-servicio-chip" 
                  style="background-color: ${color}; cursor: pointer;"
                  data-ruta-id="${ruta.ruta_id}"
                  data-servicio-id="${ruta.servicio_id}"
                  data-ruta-nombre="${ruta.ruta_nombre}"
                  data-ruta-tipo="${ruta.ruta_tipo}"
                  data-color="${color}"
                  title="${ruta.ruta_nombre} (${ruta.ruta_tipo})">
              Svc: ${svcId}
            </span>
          `);
        });
      });
      serviciosHtml = chips.join('');
    } else {
      serviciosHtml = '<span class="infra-no-servicios">Sin servicios asociados</span>';
    }

    let metaHtml = '';
    const metaItems = [];
    if (camara.id) {
      metaItems.push(`<span class="infra-meta-item"><span>ID:</span> ${camara.id}</span>`);
    }
    if (camara.latitud && camara.longitud) {
      metaItems.push(`<span class="infra-meta-item"><span>📍</span> ${camara.latitud.toFixed(4)}, ${camara.longitud.toFixed(4)}</span>`);
    }
    if (origenDatos && origenDatos !== 'MANUAL') {
      metaItems.push(`<span class="infra-meta-item"><span>Origen:</span> ${origenDatos}</span>`);
    }
    if (metaItems.length > 0) {
      metaHtml = `<div class="infra-camara-meta">${metaItems.join('')}</div>`;
    }

    card.innerHTML = `
      <div class="infra-camara-header">
        <div class="infra-camara-estado">
          <span class="infra-estado-icon ${estadoLower}"></span>
          <span class="infra-estado-text">${camara.estado || 'LIBRE'}</span>
        </div>
        ${camara.fontine_id ? `<span class="infra-camara-id">${camara.fontine_id}</span>` : ''}
      </div>
      <div class="infra-camara-nombre">${camara.nombre || camara.direccion || 'Sin nombre'}</div>
      <div class="infra-camara-servicios">${serviciosHtml}</div>
      ${metaHtml}
    `;

    // Agregar event listeners a los chips
    card.querySelectorAll('.infra-servicio-chip[data-ruta-id]').forEach(chip => {
      chip.addEventListener('click', (e) => {
        e.stopPropagation();
        const rutaId = chip.dataset.rutaId;
        const servicioId = chip.dataset.servicioId;
        const rutaNombre = chip.dataset.rutaNombre;
        const rutaTipo = chip.dataset.rutaTipo;
        const color = chip.dataset.color;
        showTrackingModal(rutaId, servicioId, rutaNombre, rutaTipo, color);
      });
    });

    return card;
  }

  function renderCamaras(camaras) {
    gridEl.innerHTML = '';
    
    if (!camaras || camaras.length === 0) {
      showEmpty(true);
      return;
    }

    showEmpty(false);
    camaras.forEach(camara => {
      gridEl.appendChild(renderCamaraCard(camara));
    });
  }

  // ===========================================
  // SEARCH TERMS MANAGEMENT (Smart Search)
  // ===========================================
  function addTerm(value) {
    if (!value || !value.trim()) return false;

    const trimmedValue = value.trim();

    // Evitar duplicados exactos (case-insensitive)
    const exists = searchTerms.some(t => t.toLowerCase() === trimmedValue.toLowerCase());
    if (exists) {
      showToast('warning', 'Término duplicado', 'Este término ya está activo');
      return false;
    }

    searchTerms.push(trimmedValue);
    renderSearchTerms();
    return true;
  }

  function removeTerm(index) {
    if (index >= 0 && index < searchTerms.length) {
      searchTerms.splice(index, 1);
      renderSearchTerms();
    }
  }

  function clearAllTerms() {
    searchTerms = [];
    renderSearchTerms();
  }

  function renderSearchTerms() {
    if (!searchTermsContainer) return;
    searchTermsContainer.innerHTML = '';

    searchTerms.forEach((term, index) => {
      const tag = document.createElement('span');
      tag.className = 'infra-search-term';
      tag.innerHTML = `
        <span class="infra-search-term-value">${term}</span>
        <button class="infra-search-term-remove" title="Eliminar término" data-index="${index}">×</button>
      `;

      const removeBtn = tag.querySelector('.infra-search-term-remove');
      removeBtn.addEventListener('click', () => removeTerm(index));

      searchTermsContainer.appendChild(tag);
    });
  }

  // ===========================================
  // API: SMART SEARCH (POST /api/infra/smart-search)
  // ===========================================
  async function searchCamaras() {
    hasSearched = true;
    showLoading(true);
    setStatus('Buscando con ' + searchTerms.length + ' término' + (searchTerms.length !== 1 ? 's' : '') + '...', 'loading');

    const payload = {
      terms: searchTerms,
      limit: 100,
      offset: 0
    };

    try {
      const url = `${window.API_BASE || ''}/api/infra/smart-search`;
      const res = await fetch(url, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || errData.error || `Error ${res.status}`);
      }

      const data = await res.json();
      const camaras = data.camaras || [];

      showLoading(false);
      renderCamaras(camaras);

      const count = camaras.length;
      const total = data.total || count;
      if (count > 0) {
        const statusText = total > count 
          ? `Mostrando ${count} de ${total} cámaras (${searchTerms.length} término${searchTerms.length !== 1 ? 's' : ''} AND)`
          : `${count} cámara${count !== 1 ? 's' : ''} encontrada${count !== 1 ? 's' : ''}`;
        setStatus(statusText, 'success');
      } else {
        setStatus('Sin resultados para estos términos', 'muted');
      }

    } catch (err) {
      showLoading(false);
      showEmpty(true);
      setStatus(`Error: ${err.message}`, 'error');
      console.error('Error buscando cámaras:', err);
    }
  }

  // ===========================================
  // API: UPLOAD DE TRACKING (Flujo de 2 pasos)
  // ===========================================
  
  // Estado del modal de conflicto
  let pendingAnalysis = null;
  let pendingFile = null;
  let selectedAction = null;
  
  // Referencias al modal (solo inicializar cuando existe)
  const trackingModal = document.getElementById('tracking-conflict-modal');
  const trackingConfirmBtn = document.getElementById('tracking-confirm-btn');
  const trackingCancelBtn = document.getElementById('tracking-cancel-btn');
  const trackingCloseBtn = trackingModal ? trackingModal.querySelector('.tracking-modal-close') : null;
  const trackingActionBtns = trackingModal ? trackingModal.querySelectorAll('.tracking-action-btn') : [];
  const trackingBranchOptions = document.getElementById('tracking-branch-options');
  
  // Función principal de upload
  async function uploadTracking(file) {
    if (!file) return;

    // Validar extensión
    if (!file.name.toLowerCase().endsWith('.txt')) {
      showToast('error', 'Archivo inválido', 'Solo se aceptan archivos .txt');
      return;
    }

    setStatus('Analizando tracking...', 'loading');
    pendingFile = file;

    const formData = new FormData();
    formData.append('file', file);
    if (window.CSRF_TOKEN) {
      formData.append('csrf_token', window.CSRF_TOKEN);
    }

    try {
      // Paso 1: Analizar
      const analyzeUrl = `${window.API_BASE || ''}/api/infra/trackings/analyze`;
      const res = await fetch(analyzeUrl, {
        method: 'POST',
        body: formData,
        credentials: 'include'
      });

      const analysis = await res.json();

      if (!res.ok) {
        throw new Error(analysis.detail || analysis.error || `Error ${res.status}`);
      }

      pendingAnalysis = analysis;

      // Si hay conflicto (servicio existente con diferente hash), mostrar modal
      if (analysis.suggested_action === 'REPLACE' || analysis.suggested_action === 'BRANCH') {
        showConflictModal(analysis);
        return;
      }

      // Si es nuevo o sin cambios, resolver automáticamente
      await resolveTracking(analysis.suggested_action);

    } catch (err) {
      showToast('error', 'Error al analizar', err.message);
      setStatus(`Error: ${err.message}`, 'error');
      console.error('Error analizando tracking:', err);
      pendingFile = null;
      pendingAnalysis = null;
    }
  }
  
  // Mostrar modal de conflicto
  function showConflictModal(analysis) {
    if (!trackingModal) {
      console.error('Modal de conflicto no encontrado');
      return;
    }
    
    // Llenar datos del modal
    const msgEl = document.getElementById('tracking-conflict-message');
    if (msgEl) msgEl.textContent = `El servicio ${analysis.servicio_id} ya existe con una ruta diferente.`;
    
    const filenameEl = document.getElementById('tracking-new-filename');
    if (filenameEl) filenameEl.textContent = pendingFile?.name || '-';
    
    const servicioEl = document.getElementById('tracking-new-servicio');
    if (servicioEl) servicioEl.textContent = analysis.servicio_id || '-';
    
    const empalmesEl = document.getElementById('tracking-new-empalmes');
    if (empalmesEl) empalmesEl.textContent = analysis.empalmes_nuevos || '-';
    
    // Info de ruta existente
    const existingRoute = analysis.rutas_existentes?.[0];
    const rutaEl = document.getElementById('tracking-existing-ruta');
    if (rutaEl) rutaEl.textContent = existingRoute?.nombre || 'Principal';
    
    const existingEmpalmesEl = document.getElementById('tracking-existing-empalmes');
    if (existingEmpalmesEl) existingEmpalmesEl.textContent = existingRoute?.empalmes_count || '-';
    
    const diffEl = document.getElementById('tracking-diff-count');
    if (diffEl) diffEl.textContent = analysis.hash_match ? '0 (idéntico)' : 'Contenido diferente';
    
    // Reset estado
    selectedAction = null;
    if (trackingActionBtns) {
      trackingActionBtns.forEach(btn => btn.classList.remove('selected'));
    }
    if (trackingConfirmBtn) trackingConfirmBtn.disabled = true;
    if (trackingBranchOptions) trackingBranchOptions.setAttribute('hidden', '');
    
    trackingModal.showModal();
  }
  
  // Cerrar modal
  function closeConflictModal() {
    if (trackingModal) trackingModal.close();
    pendingAnalysis = null;
    pendingFile = null;
    selectedAction = null;
    setStatus('Operación cancelada', 'muted');
  }
  
  // Seleccionar acción en el modal
  function selectAction(action) {
    selectedAction = action;
    if (trackingActionBtns) {
      trackingActionBtns.forEach(btn => {
        btn.classList.toggle('selected', btn.dataset.action === action);
      });
    }
    if (trackingConfirmBtn) trackingConfirmBtn.disabled = false;
    
    // Mostrar opciones de branch si corresponde
    if (action === 'BRANCH' && trackingBranchOptions) {
      trackingBranchOptions.removeAttribute('hidden');
      // Sugerir nombre basado en el archivo
      const nombreInput = document.getElementById('tracking-ruta-nombre');
      if (nombreInput && pendingFile) {
        const suggestedName = pendingFile.name.replace(/\.txt$/i, '').replace(/^\d+\s*/, '');
        nombreInput.value = suggestedName || 'Camino 2';
      }
    } else if (trackingBranchOptions) {
      trackingBranchOptions.setAttribute('hidden', '');
    }
  }
  
  // Resolver tracking (Paso 2)
  async function resolveTracking(action) {
    if (!pendingFile || !pendingAnalysis) {
      showToast('error', 'Error interno', 'No hay análisis pendiente');
      return;
    }
    
    setStatus('Procesando tracking...', 'loading');
    if (trackingModal) trackingModal.close();

    // Leer contenido del archivo
    const fileContent = await pendingFile.text();
    
    // Construir body JSON
    const bodyData = {
      action: action,
      content: fileContent,
      filename: pendingFile.name,
    };
    
    // Para REPLACE/MERGE_APPEND, usar la primera ruta existente como target
    if ((action === 'REPLACE' || action === 'MERGE_APPEND') && pendingAnalysis.rutas_existentes?.length > 0) {
      bodyData.target_ruta_id = pendingAnalysis.rutas_existentes[0].id;
    }
    
    // Para BRANCH, agregar nombre y tipo
    if (action === 'BRANCH') {
      const nombreRuta = document.getElementById('tracking-ruta-nombre')?.value || 'Camino 2';
      const tipoRuta = document.getElementById('tracking-ruta-tipo')?.value || 'ALTERNATIVA';
      bodyData.new_ruta_name = nombreRuta;
      bodyData.new_ruta_tipo = tipoRuta;
    }

    try {
      const resolveUrl = `${window.API_BASE || ''}/api/infra/trackings/resolve`;
      const res = await fetch(resolveUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': window.CSRF_TOKEN || '',
        },
        body: JSON.stringify(bodyData),
        credentials: 'include'
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || data.error || `Error ${res.status}`);
      }

      // Toast de éxito
      const actionLabels = {
        'CREATE_NEW': 'Servicio creado',
        'REPLACE': 'Ruta actualizada',
        'MERGE_APPEND': 'Cámaras agregadas',
        'BRANCH': 'Camino disjunto creado',
        'SKIP': 'Sin cambios',
        'NO_CHANGES': 'Sin cambios'
      };
      
      const msg = [
        data.camaras_nuevas > 0 ? `${data.camaras_nuevas} cámara${data.camaras_nuevas !== 1 ? 's' : ''} nueva${data.camaras_nuevas !== 1 ? 's' : ''}` : '',
        data.empalmes_asociados > 0 ? `${data.empalmes_asociados} empalme${data.empalmes_asociados !== 1 ? 's' : ''}` : ''
      ].filter(Boolean).join(', ');

      showToast(
        'success',
        actionLabels[data.action] || 'Tracking procesado',
        `Servicio ${data.servicio_id}: ${msg || data.message || 'OK'}`
      );

      setStatus(data.message || 'Tracking procesado correctamente', 'success');

      // Agregar filtro con el servicio recién subido y buscar
      if (data.servicio_id) {
        clearAllTerms();
        addTerm(data.servicio_id);
        await searchCamaras();
      }

    } catch (err) {
      showToast('error', 'Error al procesar', err.message);
      setStatus(`Error: ${err.message}`, 'error');
      console.error('Error resolviendo tracking:', err);
    } finally {
      pendingFile = null;
      pendingAnalysis = null;
      selectedAction = null;
    }
  }
  
  // Event listeners del modal (solo si existe)
  if (trackingCloseBtn) {
    trackingCloseBtn.addEventListener('click', closeConflictModal);
  }
  if (trackingCancelBtn) {
    trackingCancelBtn.addEventListener('click', closeConflictModal);
  }
  if (trackingConfirmBtn) {
    trackingConfirmBtn.addEventListener('click', () => {
      if (selectedAction) {
        resolveTracking(selectedAction);
      }
    });
  }
  if (trackingActionBtns && trackingActionBtns.length > 0) {
    trackingActionBtns.forEach(btn => {
      btn.addEventListener('click', () => selectAction(btn.dataset.action));
    });
  }
  
  // Cerrar modal con Escape
  if (trackingModal) {
    trackingModal.addEventListener('cancel', (e) => {
      e.preventDefault();
      closeConflictModal();
    });
  }

  // ===========================================
  // LIMPIAR SERVICIO (Eliminar asociaciones)
  // ===========================================
  const clearServiceBtn = document.getElementById('infra-clear-service-btn');
  
  async function clearServiceEmpalmes() {
    // Pedir el ID del servicio
    const servicioId = prompt('Ingresá el ID del servicio a limpiar (ej: 52547):');
    if (!servicioId || !servicioId.trim()) {
      return;
    }
    
    // Confirmar
    const confirmed = confirm(`¿Estás seguro de eliminar TODAS las asociaciones del servicio ${servicioId}?\n\nEsta acción no se puede deshacer.`);
    if (!confirmed) {
      return;
    }
    
    setStatus(`Limpiando servicio ${servicioId}...`, 'loading');
    
    try {
      const url = `${window.API_BASE || ''}/api/infra/servicios/${servicioId}/empalmes`;
      const res = await fetch(url, {
        method: 'DELETE',
        credentials: 'include',
        headers: {
          'Accept': 'application/json',
          'X-CSRF-Token': window.CSRF_TOKEN || '',
        }
      });
      
      const data = await res.json();
      
      if (!res.ok) {
        throw new Error(data.detail || data.error || `Error ${res.status}`);
      }
      
      showToast(
        'success',
        'Servicio limpiado',
        `${data.empalmes_legacy_eliminados} asociaciones y ${data.rutas_eliminadas} rutas eliminadas`
      );
      
      setStatus(data.message || 'Servicio limpiado correctamente', 'success');
      
      // Si hay términos de búsqueda activos, refrescar
      if (searchTerms.length > 0) {
        await searchCamaras();
      }
      
    } catch (err) {
      showToast('error', 'Error al limpiar', err.message);
      setStatus(`Error: ${err.message}`, 'error');
      console.error('Error limpiando servicio:', err);
    }
  }
  
  if (clearServiceBtn) {
    clearServiceBtn.addEventListener('click', clearServiceEmpalmes);
  }

  // ===========================================
  // EVENT LISTENERS
  // ===========================================

  // Agregar término con botón +
  addTermBtn.addEventListener('click', () => {
    const value = searchInput.value;
    
    if (addTerm(value)) {
      searchInput.value = '';
      searchInput.focus();
    }
  });

  // Enter en input de búsqueda → agregar término
  searchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      const value = searchInput.value;
      
      if (addTerm(value)) {
        searchInput.value = '';
      }
    }
  });

  // Botón de búsqueda
  searchBtn.addEventListener('click', () => {
    searchCamaras();
  });

  // Quick filter chips (atajos para agregar términos)
  quickFilterChips.forEach(chip => {
    chip.addEventListener('click', () => {
      const value = chip.dataset.term || chip.dataset.filterValue;
      
      if (value) {
        addTerm(value);
        // Ejecutar búsqueda inmediatamente
        searchCamaras();
      }
    });
  });

  // Upload zone: click
  uploadZone.addEventListener('click', (e) => {
    if (e.target === fileInput) return;
    fileInput.click();
  });

  // Upload zone: drag & drop
  uploadZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    uploadZone.classList.add('drag');
  });

  uploadZone.addEventListener('dragleave', () => {
    uploadZone.classList.remove('drag');
  });

  uploadZone.addEventListener('drop', (e) => {
    e.preventDefault();
    uploadZone.classList.remove('drag');
    
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0];
      uploadTracking(file);
    }
  });

  // File input change
  fileInput.addEventListener('change', () => {
    if (fileInput.files && fileInput.files.length > 0) {
      uploadTracking(fileInput.files[0]);
      fileInput.value = ''; // Reset para permitir subir el mismo archivo de nuevo
    }
  });

  // Mostrar estado inicial cuando se activa la vista
  const viewInfra = $('#view-infra');
  if (viewInfra) {
    const observer = new MutationObserver((mutations) => {
      mutations.forEach((mutation) => {
        if (mutation.type === 'attributes' && mutation.attributeName === 'class') {
          if (viewInfra.classList.contains('active') && !hasSearched) {
            // Primera vez que se muestra la vista, mostrar estado inicial
            showInitialState();
          }
        }
      });
    });
    observer.observe(viewInfra, { attributes: true });
    
    // Si ya está activa al cargar
    if (viewInfra.classList.contains('active')) {
      showInitialState();
    }
  }
})();
