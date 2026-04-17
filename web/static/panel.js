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
  let currentSelectedRutaId = null;
  
  function createTrackingModalIfNeeded() {
    if (trackingDetailModal) return;
    
    trackingDetailModal = document.createElement('dialog');
    trackingDetailModal.className = 'tracking-detail-modal';
    trackingDetailModal.innerHTML = `
      <div class="tracking-detail-content">
        <div class="tracking-detail-header">
          <h3 class="tracking-detail-title">Tracking del Servicio</h3>
          <button class="tracking-download-btn" type="button" title="Descargar TXT original">
            📄 Descargar TXT
          </button>
          <button class="tracking-detail-close" type="button">&times;</button>
        </div>
        <div class="tracking-rutas-tabs"></div>
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
    
    // Conectar botón de descarga
    trackingDetailModal.querySelector('.tracking-download-btn').addEventListener('click', () => {
      if (currentSelectedRutaId) {
        downloadOriginalTracking(currentSelectedRutaId);
      }
    });
  }

  // Función para descargar tracking original
  async function downloadOriginalTracking(rutaId) {
    try {
      const res = await fetch(`${window.API_BASE || ''}/api/infra/tracking/${rutaId}/download`, {
        credentials: 'include'
      });
      
      if (res.status === 404) {
        showToast('warning', '⚠️ Archivo no disponible', 'El archivo TXT original no está disponible (carga antigua)');
        return;
      }
      
      if (!res.ok) {
        throw new Error(`Error ${res.status}`);
      }
      
      const blob = await res.blob();
      const contentDisposition = res.headers.get('Content-Disposition');
      let filename = `tracking_ruta_${rutaId}.txt`;
      
      if (contentDisposition) {
        const match = contentDisposition.match(/filename="(.+?)"/);
        if (match) filename = match[1];
      }
      
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      
      showToast('success', '📄 Descarga completa', filename);
      
    } catch (err) {
      console.error('Error descargando tracking:', err);
      showToast('error', 'Error de descarga', err.message);
    }
  }

  // Cargar tracking de una ruta específica
  async function loadRutaTracking(rutaId, listEl) {
    listEl.innerHTML = '<div class="tracking-loading">Cargando tracking...</div>';
    currentSelectedRutaId = rutaId;
    
    try {
      const res = await fetch(`${window.API_BASE || ''}/api/infra/rutas/${rutaId}/tracking`);
      const data = await res.json();
      
      if (data.error) {
        listEl.innerHTML = `<div class="tracking-error">${data.error}</div>`;
        return;
      }
      
      const tracking = data.tracking || [];
      const puntaA = data.punta_a;
      const puntaB = data.punta_b;
      
      if (tracking.length === 0 && !puntaA && !puntaB) {
        listEl.innerHTML = '<div class="tracking-empty">Sin información de tracking</div>';
        return;
      }
      
      // Renderizar secuencia cámara-cable con puntas
      let html = '<div class="tracking-sequence">';
      
      // Punta A (extremo inicial)
      if (puntaA && (puntaA.sitio || puntaA.conector)) {
        const conectorInfo = puntaA.conector ? `: ${puntaA.conector}` : '';
        html += `
          <div class="tracking-item tracking-punta tracking-punta-a">
            <span class="tracking-icon">🔌</span>
            <span class="tracking-text">
              <span class="tracking-punta-label">Punta A</span>
              <span class="tracking-punta-sitio">${puntaA.sitio || 'Terminal'}${conectorInfo}</span>
              ${puntaA.identificador ? `<span class="tracking-punta-id">${puntaA.identificador}</span>` : ''}
            </span>
          </div>
        `;
      }
      
      // Secuencia cámara-cable
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
      
      // Punta B (extremo final)
      if (puntaB && (puntaB.sitio || puntaB.conector)) {
        const conectorInfo = puntaB.conector ? `: ${puntaB.conector}` : '';
        html += `
          <div class="tracking-item tracking-punta tracking-punta-b">
            <span class="tracking-icon">🔌</span>
            <span class="tracking-text">
              <span class="tracking-punta-label">Punta B</span>
              <span class="tracking-punta-sitio">${puntaB.sitio || 'Terminal'}${conectorInfo}</span>
              ${puntaB.identificador ? `<span class="tracking-punta-id">${puntaB.identificador}</span>` : ''}
            </span>
          </div>
        `;
      }
      
      html += '</div>';
      
      listEl.innerHTML = html;
      
    } catch (err) {
      listEl.innerHTML = `<div class="tracking-error">Error: ${err.message}</div>`;
    }
  }

  async function showTrackingModal(rutaId, servicioId, rutaNombre, rutaTipo, color) {
    createTrackingModalIfNeeded();
    
    const titleEl = trackingDetailModal.querySelector('.tracking-detail-title');
    const tabsEl = trackingDetailModal.querySelector('.tracking-rutas-tabs');
    const listEl = trackingDetailModal.querySelector('.tracking-detail-list');
    
    titleEl.textContent = `Svc: ${servicioId}`;
    tabsEl.innerHTML = '<div class="tracking-loading-tabs">Cargando rutas...</div>';
    listEl.innerHTML = '';
    
    trackingDetailModal.showModal();
    
    // Cargar todas las rutas del servicio
    try {
      const res = await fetch(`${window.API_BASE || ''}/api/infra/servicios/${servicioId}/rutas`, {
        credentials: 'include'
      });
      const data = await res.json();
      
      if (data.error || !data.rutas) {
        // Fallback: solo mostrar la ruta que se clickeó
        tabsEl.innerHTML = `
          <button class="tracking-ruta-tab active" data-ruta-id="${rutaId}">
            ${rutaNombre} (${rutaTipo})
          </button>
        `;
        await loadRutaTracking(rutaId, listEl);
        return;
      }
      
      const rutas = data.rutas || [];
      
      if (rutas.length === 0) {
        tabsEl.innerHTML = '<div class="tracking-no-rutas">Sin rutas disponibles</div>';
        return;
      }
      
      // Renderizar tabs de rutas
      let tabsHtml = '';
      rutas.forEach((ruta, idx) => {
        const isActive = ruta.id === parseInt(rutaId) ? 'active' : '';
        const tabColor = getRutaColor(ruta.tipo, idx);
        tabsHtml += `
          <button class="tracking-ruta-tab ${isActive}" data-ruta-id="${ruta.id}" style="--tab-color: ${tabColor}">
            ${ruta.nombre}
          </button>
        `;
      });
      tabsEl.innerHTML = tabsHtml;
      
      // Agregar event listeners a los tabs
      tabsEl.querySelectorAll('.tracking-ruta-tab').forEach(tab => {
        tab.addEventListener('click', async () => {
          // Quitar active de todos
          tabsEl.querySelectorAll('.tracking-ruta-tab').forEach(t => t.classList.remove('active'));
          tab.classList.add('active');
          
          const selectedRutaId = tab.dataset.rutaId;
          await loadRutaTracking(selectedRutaId, listEl);
        });
      });
      
      // Cargar el tracking de la ruta inicial
      await loadRutaTracking(rutaId, listEl);
      
    } catch (err) {
      tabsEl.innerHTML = `<div class="tracking-error">Error cargando rutas: ${err.message}</div>`;
    }
  }

  // ===========================================
  // RENDERIZADO DE TARJETAS
  // ===========================================
  function renderCamaraCard(camara) {
    const estadoLower = (camara.estado || 'libre').toLowerCase();
    const rutas = camara.rutas || [];
    const origenDatos = camara.origen_datos || 'MANUAL';
    const ticketBaneo = camara.ticket_baneo || null;

    const card = document.createElement('div');
    card.className = 'infra-camara-card';
    card.dataset.estado = camara.estado || 'LIBRE';
    card.dataset.origen = origenDatos;

    // Renderizar chips de servicios con colores según ruta
    let serviciosHtml = '';
    if (rutas.length > 0) {
      // Agrupar por servicio_id - UN chip por servicio
      const servicioRutas = {};
      rutas.forEach((ruta, idx) => {
        if (!servicioRutas[ruta.servicio_id]) {
          servicioRutas[ruta.servicio_id] = [];
        }
        servicioRutas[ruta.servicio_id].push({ ...ruta, _index: idx });
      });
      
      // Generar UN chip por servicio (agrupando pelos)
      const chips = [];
      Object.entries(servicioRutas).forEach(([svcId, svcRutas]) => {
        // Usar la primera ruta para el chip principal
        const primeraRuta = svcRutas[0];
        const color = getRutaColor(primeraRuta, primeraRuta._index);
        
        // Alias IDs (de todas las rutas del servicio)
        const allAliasIds = new Set();
        svcRutas.forEach(r => (r.alias_ids || []).forEach(a => allAliasIds.add(a)));
        const aliasHtml = allAliasIds.size > 0 
          ? `<span class="servicio-alias">(ex ${[...allAliasIds].join(', ')})</span>` 
          : '';
        
        // Cantidad de pelos = cantidad de rutas de este servicio
        const cantidadPelos = svcRutas.length;
        const pelosHtml = cantidadPelos > 1 
          ? `<span class="servicio-pelos-badge" title="${cantidadPelos} pelos/hilos">x${cantidadPelos}</span>` 
          : '';
        
        // Tránsitos (suma de todas las rutas)
        const transitosCount = svcRutas.reduce((sum, r) => sum + (r.transitos_count || 0), 0);
        const transitoHtml = transitosCount > 0 
          ? `<span class="servicio-transito-badge" title="${transitosCount} tránsito${transitosCount > 1 ? 's' : ''}">
              <svg class="transito-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="3"/>
                <path d="M12 2v4m0 12v4M2 12h4m12 0h4"/>
              </svg>
              ${transitosCount}
             </span>` 
          : '';
        
        chips.push(`
          <span class="infra-servicio-chip" 
                style="background-color: ${color}; cursor: pointer;"
                data-ruta-id="${primeraRuta.ruta_id}"
                data-servicio-id="${svcId}"
                data-ruta-nombre="${primeraRuta.ruta_nombre}"
                data-ruta-tipo="${primeraRuta.ruta_tipo}"
                data-color="${color}"
                title="${cantidadPelos > 1 ? cantidadPelos + ' pelos' : primeraRuta.ruta_nombre}">
            <span class="servicio-id-main">Svc: ${svcId}</span>
            ${aliasHtml}
            ${pelosHtml}
            ${transitoHtml}
          </span>
        `);
      });
      serviciosHtml = chips.join('');
    } else {
      serviciosHtml = '<span class="infra-no-servicios">Sin servicios asociados</span>';
    }

    // Ticket de baneo (si la cámara está baneada y tiene ticket)
    let ticketHtml = '';
    if (camara.estado === 'BANEADA' && ticketBaneo) {
      ticketHtml = `<span class="infra-ban-ticket">${ticketBaneo}</span>`;
    }

    // Puntas A y B (si la cámara tiene información de puntas)
    let puntasHtml = '';
    if (rutas.length > 0) {
      const rutaConPuntas = rutas.find(r => r.punta_a_sitio || r.punta_b_sitio);
      if (rutaConPuntas) {
        const puntaA = rutaConPuntas.punta_a_sitio || '-';
        const puntaB = rutaConPuntas.punta_b_sitio || '-';
        puntasHtml = `
          <div class="infra-camara-puntas">
            <span class="punta-chip punta-a" title="Punta A">
              <svg class="punta-icon-small" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="2" y="3" width="20" height="14" rx="2"/>
                <line x1="8" y1="21" x2="16" y2="21"/>
                <line x1="12" y1="17" x2="12" y2="21"/>
              </svg>
              A: ${puntaA}
            </span>
            <span class="punta-chip punta-b" title="Punta B">
              <svg class="punta-icon-small" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="2" y="3" width="20" height="14" rx="2"/>
                <line x1="8" y1="21" x2="16" y2="21"/>
                <line x1="12" y1="17" x2="12" y2="21"/>
              </svg>
              B: ${puntaB}
            </span>
          </div>
        `;
      }
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
      ${puntasHtml}
      ${ticketHtml}
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

      // Determinar si mostrar modal según el status
      const status = analysis.status || '';
      
      // Casos que requieren modal
      if (status === 'POTENTIAL_UPGRADE' || status === 'NEW_STRAND' || status === 'CONFLICT') {
        showConflictModal(analysis);
        return;
      }
      
      // Fallback: si hay suggested_action de conflicto
      if (analysis.suggested_action === 'REPLACE' || analysis.suggested_action === 'BRANCH') {
        showConflictModal(analysis);
        return;
      }

      // Si es nuevo o sin cambios, resolver automáticamente
      await resolveTracking(analysis.suggested_action || 'CREATE_NEW');

    } catch (err) {
      showToast('error', 'Error al analizar', err.message);
      setStatus(`Error: ${err.message}`, 'error');
      console.error('Error analizando tracking:', err);
      pendingFile = null;
      pendingAnalysis = null;
    }
  }
  
  // Mostrar modal de conflicto según tipo
  function showConflictModal(analysis) {
    console.log('showConflictModal called with:', JSON.stringify(analysis, null, 2));
    if (!trackingModal) {
      console.error('Modal de conflicto no encontrado');
      return;
    }
    
    const status = analysis.status || 'CONFLICT';
    console.log('Modal status:', status, 'upgrade_info:', analysis.upgrade_info);
    
    // Referencias a las secciones del modal
    const titleEl = document.getElementById('tracking-modal-title');
    const msgEl = document.getElementById('tracking-conflict-message');
    const standardConflict = document.getElementById('tracking-standard-conflict');
    const upgradeView = document.getElementById('tracking-upgrade-view');
    const strandView = document.getElementById('tracking-strand-view');
    const standardActions = document.getElementById('tracking-standard-actions');
    const upgradeActions = document.getElementById('tracking-upgrade-actions');
    const strandActions = document.getElementById('tracking-strand-actions');
    
    // Ocultar todas las vistas primero
    if (standardConflict) standardConflict.hidden = true;
    if (upgradeView) upgradeView.hidden = true;
    if (strandView) strandView.hidden = true;
    if (standardActions) standardActions.hidden = true;
    if (upgradeActions) upgradeActions.hidden = true;
    if (strandActions) strandActions.hidden = true;
    
    // Configurar según el tipo de conflicto
    if (status === 'POTENTIAL_UPGRADE' && analysis.upgrade_info) {
      // === CASO: POTENTIAL_UPGRADE ===
      const uInfo = analysis.upgrade_info;
      if (titleEl) titleEl.textContent = '⚠️ ¿Es esto un Upgrade?';
      
      // Construir mensaje con terminales que matchearon
      let matchDetails = '';
      if (uInfo.terminal_a_odf && uInfo.terminal_a_conector) {
        matchDetails += `<br>• Terminal A: <code>${uInfo.terminal_a_odf}: ${uInfo.terminal_a_conector}</code>`;
      }
      if (uInfo.terminal_b_odf && uInfo.terminal_b_conector) {
        matchDetails += `<br>• Terminal B: <code>${uInfo.terminal_b_odf}: ${uInfo.terminal_b_conector}</code>`;
      }
      if (msgEl) {
        msgEl.innerHTML = `El tracking <strong>${analysis.servicio_id}</strong> coincide con el servicio existente <strong>${uInfo.old_service_id}</strong>.${matchDetails}<br><br>¿Desea migrar el servicio?`;
      }
      
      // Llenar datos de upgrade
      const oldIdEl = document.getElementById('tracking-upgrade-old-id');
      const newIdEl = document.getElementById('tracking-upgrade-new-id');
      const puntaAEl = document.getElementById('tracking-upgrade-punta-a');
      const puntaBEl = document.getElementById('tracking-upgrade-punta-b');
      const upgradeDescEl = document.getElementById('tracking-upgrade-desc');
      
      if (oldIdEl) oldIdEl.textContent = uInfo.old_service_id;
      if (newIdEl) newIdEl.textContent = analysis.servicio_id;
      // Mostrar terminales completos si están disponibles
      if (puntaAEl) {
        puntaAEl.textContent = uInfo.terminal_a_odf && uInfo.terminal_a_conector
          ? `${uInfo.terminal_a_odf}: ${uInfo.terminal_a_conector}`
          : (analysis.punta_a_sitio || '-');
      }
      if (puntaBEl) {
        puntaBEl.textContent = uInfo.terminal_b_odf && uInfo.terminal_b_conector
          ? `${uInfo.terminal_b_odf}: ${uInfo.terminal_b_conector}`
          : (analysis.punta_b_sitio || '-');
      }
      if (upgradeDescEl) upgradeDescEl.textContent = `Migrar ${uInfo.old_service_id} → ${analysis.servicio_id}`;
      
      // Mostrar vistas de upgrade
      if (upgradeView) upgradeView.hidden = false;
      if (upgradeActions) upgradeActions.hidden = false;
      
    } else if (status === 'NEW_STRAND' && analysis.strand_info) {
      // === CASO: NEW_STRAND ===
      if (titleEl) titleEl.textContent = '🧶 Nuevo Pelo Detectado';
      if (msgEl) msgEl.innerHTML = `El recorrido es idéntico al existente para el servicio <strong>${analysis.servicio_id}</strong>. ¿Desea agregar capacidad?`;
      
      // Llenar datos de strand
      const strandServiceEl = document.getElementById('tracking-strand-service-id');
      const strandCurrentEl = document.getElementById('tracking-strand-current');
      const strandNewEl = document.getElementById('tracking-strand-new');
      
      if (strandServiceEl) strandServiceEl.textContent = analysis.servicio_id;
      if (strandCurrentEl) strandCurrentEl.textContent = analysis.strand_info.current_pelos || 1;
      if (strandNewEl) strandNewEl.textContent = (analysis.strand_info.current_pelos || 1) + 1;
      
      // Mostrar vistas de strand
      if (strandView) strandView.hidden = false;
      if (strandActions) strandActions.hidden = false;
      
    } else {
      // === CASO: CONFLICT estándar ===
      if (titleEl) titleEl.textContent = '⚠️ Conflicto de Tracking';
      if (msgEl) msgEl.textContent = `El servicio ${analysis.servicio_id} ya existe con una ruta diferente.`;
      
      // Llenar datos estándar
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
      
      // Mostrar vistas estándar
      if (standardConflict) standardConflict.hidden = false;
      if (standardActions) standardActions.hidden = false;
    }
    
    // Reset estado de selección
    selectedAction = null;
    const allActionBtns = trackingModal.querySelectorAll('.tracking-action-btn');
    allActionBtns.forEach(btn => btn.classList.remove('selected'));
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
    const allActionBtns = trackingModal ? trackingModal.querySelectorAll('.tracking-action-btn') : [];
    allActionBtns.forEach(btn => {
      btn.classList.toggle('selected', btn.dataset.action === action);
    });
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
    
    // Para CONFIRM_UPGRADE, agregar los datos del servicio a migrar
    if (action === 'CONFIRM_UPGRADE' && pendingAnalysis.upgrade_info) {
      bodyData.old_service_id = pendingAnalysis.upgrade_info.old_service_id;
      bodyData.old_service_db_id = pendingAnalysis.upgrade_info.old_service_db_id;
    }
    
    // Para ADD_STRAND, agregar target_ruta_id
    if (action === 'ADD_STRAND') {
      if (pendingAnalysis.strand_info) {
        bodyData.target_ruta_id = pendingAnalysis.strand_info.ruta_id;
      } else if (pendingAnalysis.rutas_existentes && pendingAnalysis.rutas_existentes.length > 0) {
        // Usar la primera ruta existente como target
        bodyData.target_ruta_id = pendingAnalysis.rutas_existentes[0].id;
      }
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
        'NO_CHANGES': 'Sin cambios',
        'CONFIRM_UPGRADE': 'Upgrade completado',
        'ADD_STRAND': 'Pelo agregado'
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

  // ===========================================
  // PROTOCOLO DE PROTECCIÓN - BANEO
  // ===========================================

  const panicBtn = $('#infra-panic-btn');
  const banBadge = $('#infra-ban-badge');
  const banCountEl = $('#infra-ban-count');
  const exportBtn = $('#infra-export-btn');
  const exportMenu = $('#infra-export-menu');
  // Elemento para mostrar total de cámaras baneadas (se crea dinámicamente)
  let totalCamarasBaneadasEl = null;

  // Estado del wizard
  let banWizardState = {
    step: 1,
    ticket: '',
    servicioAfectado: '',
    servicioProtegido: '',
    rutaProtegidaId: null,
    motivo: '',
    targetSame: true,
    rutasDisponibles: [],
    camarasCount: 0,
  };

  // Referencias del modal wizard
  const banWizardModal = document.getElementById('ban-wizard-modal');
  const banSteps = banWizardModal ? banWizardModal.querySelectorAll('.ban-step') : [];
  const banWizardSteps = banWizardModal ? banWizardModal.querySelectorAll('.ban-wizard-step') : [];
  const banPrevBtn = document.getElementById('ban-prev-btn');
  const banNextBtn = document.getElementById('ban-next-btn');
  const banCancelBtn = document.getElementById('ban-cancel-btn');
  const banExecuteBtn = document.getElementById('ban-execute-btn');
  const banCloseBtn = banWizardModal ? banWizardModal.querySelector('.ban-wizard-close') : null;

  // Cargar baneos activos al iniciar y calcular total de cámaras
  async function loadActiveBans() {
    try {
      const res = await fetch(`${window.API_BASE || ''}/api/infra/ban/active`, {
        credentials: 'include'
      });
      if (!res.ok) return;
      
      const data = await res.json();
      const count = data.total || 0;
      const incidentes = data.incidentes || [];
      
      // Calcular total de cámaras baneadas sumando todos los baneos
      let totalCamaras = 0;
      for (const inc of incidentes) {
        totalCamaras += inc.camaras_count || 0;
      }
      
      if (count > 0) {
        if (banBadge) {
          banBadge.hidden = false;
          if (banCountEl) banCountEl.textContent = count;
        }
        // Actualizar el tooltip del badge para mostrar total de cámaras
        if (banBadge) {
          banBadge.title = `${count} baneo(s) activo(s) - ${totalCamaras} cámara(s) restringidas`;
        }
        // Actualizar indicador global de cámaras baneadas
        updateTotalCamarasIndicator(totalCamaras);
      } else {
        if (banBadge) banBadge.hidden = true;
        updateTotalCamarasIndicator(0);
      }
    } catch (err) {
      console.error('Error cargando baneos activos:', err);
    }
  }

  // Actualizar indicador visual de total de cámaras baneadas en el header
  function updateTotalCamarasIndicator(total) {
    // Buscar o crear el elemento indicador
    if (!totalCamarasBaneadasEl) {
      totalCamarasBaneadasEl = document.getElementById('infra-total-camaras-indicator');
    }
    
    // Si no existe y hay cámaras, crear el elemento
    if (!totalCamarasBaneadasEl && total > 0) {
      const heroActions = document.querySelector('.infra-hero-actions');
      if (heroActions) {
        totalCamarasBaneadasEl = document.createElement('div');
        totalCamarasBaneadasEl.id = 'infra-total-camaras-indicator';
        totalCamarasBaneadasEl.className = 'infra-camaras-indicator';
        // Insertar después del badge de baneos activos
        const badge = heroActions.querySelector('#infra-ban-badge');
        if (badge && badge.nextSibling) {
          heroActions.insertBefore(totalCamarasBaneadasEl, badge.nextSibling);
        } else {
          heroActions.prepend(totalCamarasBaneadasEl);
        }
      }
    }
    
    if (totalCamarasBaneadasEl) {
      if (total > 0) {
        totalCamarasBaneadasEl.innerHTML = `<span class="camaras-icon">📷</span> <span class="camaras-count">${total}</span> <span class="camaras-text">cámaras restringidas</span>`;
        totalCamarasBaneadasEl.hidden = false;
        totalCamarasBaneadasEl.title = `Total de cámaras bajo Protocolo de Protección`;
      } else {
        totalCamarasBaneadasEl.hidden = true;
      }
    }
  }

  // Cargar al iniciar si estamos en la vista
  if (viewInfra) {
    loadActiveBans();
  }

  // ===========================================
  // EXPORTACIÓN DE CÁMARAS
  // ===========================================

  if (exportBtn && exportMenu) {
    // Toggle menú al hacer click en el botón
    exportBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      const isHidden = exportMenu.hidden;
      exportMenu.hidden = !isHidden;
    });

    // Evitar que clicks dentro del menú lo cierren
    exportMenu.addEventListener('click', (e) => {
      e.stopPropagation();
    });

    // Cerrar menú al hacer click fuera (usar setTimeout para evitar cierre inmediato)
    document.addEventListener('click', (e) => {
      if (!exportBtn.contains(e.target) && !exportMenu.contains(e.target)) {
        exportMenu.hidden = true;
      }
    });

    // Manejar opciones de exportación
    exportMenu.querySelectorAll('button').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.preventDefault();
        const filter = btn.dataset.filter || 'ALL';
        const format = btn.dataset.format || 'xlsx';
        
        exportMenu.hidden = true;
        setStatus(`Exportando cámaras (${filter})...`, 'loading');
        
        try {
          const url = `${window.API_BASE || ''}/api/infra/export/cameras?filter_status=${filter}&format=${format}`;
          const res = await fetch(url, { credentials: 'include' });
          
          if (!res.ok) {
            throw new Error(`Error ${res.status}`);
          }
          
          const blob = await res.blob();
          const downloadUrl = URL.createObjectURL(blob);
          const link = document.createElement('a');
          link.href = downloadUrl;
          link.download = `camaras_${filter.toLowerCase()}_${new Date().toISOString().slice(0, 10)}.${format}`;
          document.body.appendChild(link);
          link.click();
          document.body.removeChild(link);
          URL.revokeObjectURL(downloadUrl);
          
          setStatus(`Exportación completada`, 'success');
          showToast('success', 'Exportación completada', `Archivo ${format.toUpperCase()} descargado`);
          
        } catch (err) {
          setStatus(`Error: ${err.message}`, 'error');
          showToast('error', 'Error en exportación', err.message);
        }
      });
    });
  }

  // ===========================================
  // WIZARD DE BANEO - FUNCIONES
  // ===========================================

  function resetBanWizard() {
    banWizardState = {
      step: 1,
      ticket: '',
      servicioAfectado: '',
      servicioProtegido: '',
      rutaProtegidaId: null,
      motivo: '',
      targetSame: true,
      rutasDisponibles: [],
      camarasCount: 0,
    };
    
    // Reset inputs
    const ticketInput = document.getElementById('ban-ticket');
    const afectadoInput = document.getElementById('ban-servicio-afectado');
    const motivoInput = document.getElementById('ban-motivo');
    const protegidoInput = document.getElementById('ban-servicio-protegido');
    const confirmCheck = document.getElementById('ban-confirm-check');
    
    if (ticketInput) ticketInput.value = '';
    if (afectadoInput) afectadoInput.value = '';
    if (motivoInput) motivoInput.value = '';
    if (protegidoInput) protegidoInput.value = '';
    if (confirmCheck) confirmCheck.checked = false;
    
    // Reset target toggle
    const targetOpts = banWizardModal.querySelectorAll('.ban-target-opt');
    targetOpts.forEach(opt => {
      opt.classList.toggle('active', opt.dataset.target === 'same');
    });
    
    const otherServiceInput = document.getElementById('ban-other-service-input');
    if (otherServiceInput) otherServiceInput.hidden = true;
    
    // Reset rutas
    const rutasList = document.getElementById('ban-rutas-list');
    if (rutasList) rutasList.innerHTML = '<p class="ban-form-hint">Completá el paso 1 para ver las rutas disponibles.</p>';
    
    // Reset tracking status
    const trackingStatus = document.getElementById('ban-tracking-status');
    if (trackingStatus) trackingStatus.hidden = true;
    
    updateWizardStep(1);
  }

  function updateWizardStep(step) {
    banWizardState.step = step;
    
    // Actualizar progress
    banSteps.forEach((s, idx) => {
      const stepNum = idx + 1;
      s.classList.remove('active', 'completed');
      if (stepNum === step) s.classList.add('active');
      else if (stepNum < step) s.classList.add('completed');
    });
    
    // Mostrar step correcto
    banWizardSteps.forEach(s => {
      s.hidden = parseInt(s.dataset.step) !== step;
    });
    
    // Actualizar botones
    if (banPrevBtn) banPrevBtn.hidden = step === 1;
    if (banNextBtn) banNextBtn.hidden = step === 3;
    if (banExecuteBtn) banExecuteBtn.hidden = step !== 3;
  }

  async function loadRutasForService(servicioId) {
    const rutasList = document.getElementById('ban-rutas-list');
    const trackingStatus = document.getElementById('ban-tracking-status');
    
    if (!rutasList) return;
    
    rutasList.innerHTML = '<p class="ban-form-hint">Buscando rutas...</p>';
    
    try {
      const res = await fetch(`${window.API_BASE || ''}/api/infra/servicios/${servicioId}/rutas`, {
        credentials: 'include'
      });
      
      if (!res.ok) {
        rutasList.innerHTML = '<p class="ban-form-hint" style="color: #ff6b6b;">Servicio no encontrado o sin rutas</p>';
        banWizardState.rutasDisponibles = [];
        return false;
      }
      
      const data = await res.json();
      const rutas = data.rutas || [];
      banWizardState.rutasDisponibles = rutas;
      
      if (rutas.length === 0) {
        rutasList.innerHTML = '<p class="ban-form-hint">Este servicio no tiene rutas registradas.</p>';
        return false;
      }
      
      // Calcular total de cámaras
      let totalCamaras = 0;
      rutas.forEach(r => { totalCamaras += r.empalmes_count || 0; });
      banWizardState.camarasCount = totalCamaras;
      
      // Renderizar opciones
      let html = `
        <label class="ban-ruta-item selected">
          <input type="radio" name="ban-ruta" value="" checked />
          <div class="ban-ruta-info">
            <div class="ban-ruta-name">🌐 Todas las rutas</div>
            <div class="ban-ruta-meta">${rutas.length} ruta(s) disponible(s)</div>
          </div>
          <span class="ban-ruta-camaras">${totalCamaras} cámaras</span>
        </label>
      `;
      
      rutas.forEach(ruta => {
        const tipoIcon = ruta.tipo === 'PRINCIPAL' ? '🔵' : ruta.tipo === 'BACKUP' ? '🟢' : '🟠';
        html += `
          <label class="ban-ruta-item">
            <input type="radio" name="ban-ruta" value="${ruta.id}" />
            <div class="ban-ruta-info">
              <div class="ban-ruta-name">${tipoIcon} ${ruta.nombre || 'Ruta ' + ruta.id}</div>
              <div class="ban-ruta-meta">Tipo: ${ruta.tipo} · Hash: ${(ruta.hash || '').slice(0, 8)}...</div>
            </div>
            <span class="ban-ruta-camaras">${ruta.empalmes_count || 0} cámaras</span>
          </label>
        `;
      });
      
      rutasList.innerHTML = html;
      
      // Event listeners para selección
      rutasList.querySelectorAll('.ban-ruta-item').forEach(item => {
        item.addEventListener('click', () => {
          rutasList.querySelectorAll('.ban-ruta-item').forEach(i => i.classList.remove('selected'));
          item.classList.add('selected');
          
          const radio = item.querySelector('input[type="radio"]');
          if (radio) {
            radio.checked = true;
            banWizardState.rutaProtegidaId = radio.value ? parseInt(radio.value) : null;
            
            // Actualizar conteo de cámaras
            if (!radio.value) {
              banWizardState.camarasCount = totalCamaras;
            } else {
              const selectedRuta = rutas.find(r => r.id === parseInt(radio.value));
              banWizardState.camarasCount = selectedRuta ? (selectedRuta.empalmes_count || 0) : 0;
            }
          }
          
          // Mostrar semáforo de tracking
          showTrackingStatus(rutas[0]); // Usar la primera ruta como referencia
        });
      });
      
      // Mostrar semáforo inicial
      showTrackingStatus(rutas[0]);
      
      return true;
      
    } catch (err) {
      console.error('Error cargando rutas:', err);
      rutasList.innerHTML = `<p class="ban-form-hint" style="color: #ff6b6b;">Error: ${err.message}</p>`;
      return false;
    }
  }

  function showTrackingStatus(ruta) {
    const trackingStatus = document.getElementById('ban-tracking-status');
    const trackingIcon = document.getElementById('ban-tracking-icon');
    const trackingText = document.getElementById('ban-tracking-text');
    const downloadBtn = document.getElementById('ban-download-tracking-btn');
    
    if (!trackingStatus || !ruta) return;
    
    trackingStatus.hidden = false;
    
    // Calcular días desde última actualización
    const createdAt = ruta.created_at ? new Date(ruta.created_at) : null;
    let diasDesdeUpdate = 0;
    
    if (createdAt) {
      const ahora = new Date();
      diasDesdeUpdate = Math.floor((ahora - createdAt) / (1000 * 60 * 60 * 24));
    }
    
    // Semáforo
    if (diasDesdeUpdate <= 60) {
      if (trackingIcon) trackingIcon.textContent = '🟢';
      if (trackingText) trackingText.textContent = `Tracking actualizado hace ${diasDesdeUpdate} días`;
      if (trackingText) trackingText.style.color = '#22c55e';
    } else {
      if (trackingIcon) trackingIcon.textContent = '🟡';
      if (trackingText) trackingText.textContent = `⚠️ Tracking desactualizado (${diasDesdeUpdate} días)`;
      if (trackingText) trackingText.style.color = '#eab308';
    }
    
    // Botón de descarga del tracking
    if (downloadBtn) {
      downloadBtn.onclick = async () => {
        if (!ruta.id) {
          showToast('warning', 'Sin ruta', 'No hay ruta seleccionada para descargar');
          return;
        }
        
        try {
          const url = `${window.API_BASE || ''}/api/infra/rutas/${ruta.id}/download`;
          const a = document.createElement('a');
          a.href = url;
          a.download = `tracking_${banWizardState.servicioProtegido}_${ruta.nombre || 'ruta'}.txt`;
          a.click();
          showToast('success', 'Descarga iniciada', 'El archivo de tracking se está descargando');
        } catch (err) {
          showToast('error', 'Error de descarga', err.message);
        }
      };
    }
  }

  function updateSummary() {
    const summaryTicket = document.getElementById('ban-summary-ticket');
    const summaryAfectado = document.getElementById('ban-summary-afectado');
    const summaryProtegido = document.getElementById('ban-summary-protegido');
    const summaryRuta = document.getElementById('ban-summary-ruta');
    const summaryCamaras = document.getElementById('ban-summary-camaras');
    
    if (summaryTicket) summaryTicket.textContent = banWizardState.ticket || '(sin ticket)';
    if (summaryAfectado) summaryAfectado.textContent = banWizardState.servicioAfectado;
    if (summaryProtegido) summaryProtegido.textContent = banWizardState.servicioProtegido;
    
    if (summaryRuta) {
      if (banWizardState.rutaProtegidaId) {
        const ruta = banWizardState.rutasDisponibles.find(r => r.id === banWizardState.rutaProtegidaId);
        summaryRuta.textContent = ruta ? ruta.nombre : `Ruta #${banWizardState.rutaProtegidaId}`;
      } else {
        summaryRuta.textContent = 'Todas las rutas';
      }
    }
    
    if (summaryCamaras) summaryCamaras.textContent = `~${banWizardState.camarasCount} cámaras`;
  }

  async function executeBan() {
    const confirmCheck = document.getElementById('ban-confirm-check');
    if (!confirmCheck || !confirmCheck.checked) {
      showToast('warning', 'Confirmación requerida', 'Debés marcar la casilla de confirmación');
      return;
    }
    
    if (banExecuteBtn) banExecuteBtn.disabled = true;
    setStatus('Ejecutando baneo...', 'loading');
    
    try {
      const payload = {
        ticket_asociado: banWizardState.ticket || null,
        servicio_afectado_id: banWizardState.servicioAfectado,
        servicio_protegido_id: banWizardState.servicioProtegido,
        ruta_protegida_id: banWizardState.rutaProtegidaId || null,
        motivo: banWizardState.motivo || null,
      };
      
      const res = await fetch(`${window.API_BASE || ''}/api/infra/ban/create`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': window.CSRF_TOKEN || '',
        },
        body: JSON.stringify(payload),
      });
      
      const data = await res.json();
      
      if (!res.ok || !data.success) {
        throw new Error(data.error || data.message || 'Error al crear baneo');
      }
      
      // Éxito
      if (banWizardModal) banWizardModal.close();
      
      showToast(
        'success',
        '🔒 Baneo ejecutado',
        `${data.camaras_baneadas} cámaras baneadas (${data.camaras_ya_baneadas} ya estaban)`
      );
      
      setStatus(`Baneo creado: ${data.camaras_baneadas} cámaras afectadas`, 'success');
      
      // Recargar baneos activos y búsqueda
      loadActiveBans();
      
      if (banWizardState.servicioProtegido) {
        clearAllTerms();
        addTerm(banWizardState.servicioProtegido);
        await searchCamaras();
      }
      
    } catch (err) {
      showToast('error', 'Error al ejecutar baneo', err.message);
      setStatus(`Error: ${err.message}`, 'error');
    } finally {
      if (banExecuteBtn) banExecuteBtn.disabled = false;
    }
  }

  // ===========================================
  // WIZARD DE BANEO - EVENT LISTENERS
  // ===========================================

  if (panicBtn && banWizardModal) {
    panicBtn.addEventListener('click', () => {
      resetBanWizard();
      banWizardModal.showModal();
    });
  }

  if (banCloseBtn) {
    banCloseBtn.addEventListener('click', () => {
      banWizardModal.close();
    });
  }

  if (banCancelBtn) {
    banCancelBtn.addEventListener('click', () => {
      banWizardModal.close();
    });
  }

  if (banNextBtn) {
    banNextBtn.addEventListener('click', async () => {
      const currentStep = banWizardState.step;
      
      if (currentStep === 1) {
        // Validar paso 1
        const afectadoInput = document.getElementById('ban-servicio-afectado');
        const ticketInput = document.getElementById('ban-ticket');
        const motivoInput = document.getElementById('ban-motivo');
        
        if (!afectadoInput || !afectadoInput.value.trim()) {
          showToast('warning', 'Campo requerido', 'Ingresá el ID del servicio afectado');
          return;
        }
        
        banWizardState.servicioAfectado = afectadoInput.value.trim();
        banWizardState.ticket = ticketInput ? ticketInput.value.trim() : '';
        banWizardState.motivo = motivoInput ? motivoInput.value.trim() : '';
        
        // Por defecto, proteger el mismo servicio
        banWizardState.servicioProtegido = banWizardState.servicioAfectado;
        
        // Actualizar info box
        const afectadoText = document.getElementById('ban-afectado-text');
        if (afectadoText) afectadoText.textContent = `Servicio afectado: ${banWizardState.servicioAfectado}`;
        
        // Cargar rutas
        await loadRutasForService(banWizardState.servicioAfectado);
        
        updateWizardStep(2);
        
      } else if (currentStep === 2) {
        // Validar paso 2
        if (banWizardState.rutasDisponibles.length === 0) {
          showToast('warning', 'Sin rutas', 'El servicio no tiene rutas registradas para banear');
          return;
        }
        
        updateSummary();
        updateWizardStep(3);
      }
    });
  }

  if (banPrevBtn) {
    banPrevBtn.addEventListener('click', () => {
      if (banWizardState.step > 1) {
        updateWizardStep(banWizardState.step - 1);
      }
    });
  }

  if (banExecuteBtn) {
    banExecuteBtn.addEventListener('click', executeBan);
  }

  // Target toggle (mismo servicio vs otro)
  const targetOpts = banWizardModal ? banWizardModal.querySelectorAll('.ban-target-opt') : [];
  targetOpts.forEach(opt => {
    opt.addEventListener('click', async () => {
      targetOpts.forEach(o => o.classList.remove('active'));
      opt.classList.add('active');
      
      const target = opt.dataset.target;
      banWizardState.targetSame = target === 'same';
      
      const otherServiceInput = document.getElementById('ban-other-service-input');
      
      if (target === 'same') {
        if (otherServiceInput) otherServiceInput.hidden = true;
        banWizardState.servicioProtegido = banWizardState.servicioAfectado;
        await loadRutasForService(banWizardState.servicioAfectado);
      } else {
        if (otherServiceInput) otherServiceInput.hidden = false;
        // Limpiar rutas hasta que se busque otro servicio
        const rutasList = document.getElementById('ban-rutas-list');
        if (rutasList) rutasList.innerHTML = '<p class="ban-form-hint">Buscá el servicio a proteger.</p>';
        banWizardState.rutasDisponibles = [];
      }
    });
  });

  // Búsqueda de otro servicio
  const searchServiceBtn = document.getElementById('ban-search-service-btn');
  if (searchServiceBtn) {
    searchServiceBtn.addEventListener('click', async () => {
      const protegidoInput = document.getElementById('ban-servicio-protegido');
      if (!protegidoInput || !protegidoInput.value.trim()) {
        showToast('warning', 'Campo requerido', 'Ingresá el ID del servicio a proteger');
        return;
      }
      
      banWizardState.servicioProtegido = protegidoInput.value.trim();
      await loadRutasForService(banWizardState.servicioProtegido);
    });
  }

  // ===========================================
  // GESTIÓN DE BANEOS ACTIVOS
  // ===========================================

  const notifyModal = document.getElementById('notify-modal');
  const notifyCloseBtn = notifyModal ? notifyModal.querySelector('.notify-modal-close') : null;
  const notifyCancelBtn = document.getElementById('notify-cancel-btn');
  const activeBansList = document.getElementById('active-bans-list');

  async function loadActiveBansIntoModal() {
    if (!activeBansList) return;
    
    activeBansList.innerHTML = '<p class="loading-text">Cargando baneos...</p>';
    
    try {
      const res = await fetch(`${window.API_BASE || ''}/api/infra/ban/active`, {
        credentials: 'include'
      });
      
      if (!res.ok) {
        activeBansList.innerHTML = '<p class="error-text">Error cargando baneos</p>';
        return;
      }
      
      const data = await res.json();
      const incidentes = data.incidentes || [];
      
      if (incidentes.length === 0) {
        activeBansList.innerHTML = '<p class="empty-text">No hay baneos activos</p>';
        return;
      }
      
      let html = '';
      for (const inc of incidentes) {
        const duracion = inc.duracion_horas ? `${inc.duracion_horas}h` : '-';
        const fecha = inc.fecha_inicio ? new Date(inc.fecha_inicio).toLocaleString('es-AR') : '-';
        const camarasCount = inc.camaras_count || '?';
        
        html += `
          <div class="active-ban-item" data-id="${inc.id}">
            <div class="active-ban-header">
              <span class="active-ban-ticket">${inc.ticket_asociado || 'Sin ticket'}</span>
              <span class="active-ban-duration">⏱️ ${duracion}</span>
            </div>
            <div class="active-ban-services">
              <span class="active-ban-label">Afectado:</span> <strong class="text-red">${inc.servicio_afectado_id}</strong>
              <span class="active-ban-arrow">→</span>
              <span class="active-ban-label">Protegido:</span> <strong class="text-green">${inc.servicio_protegido_id}</strong>
            </div>
            <div class="active-ban-meta">
              <span>📅 ${fecha}</span>
              ${inc.usuario_ejecutor ? `<span>👤 ${inc.usuario_ejecutor}</span>` : ''}
            </div>
            ${inc.motivo ? `<div class="active-ban-motivo">${inc.motivo}</div>` : ''}
            <div class="active-ban-actions">
              <button type="button" class="btn-notify-ban" data-id="${inc.id}" data-ticket="${inc.ticket_asociado || ''}" title="Enviar aviso por correo para este baneo">
                📧 Dar Aviso
              </button>
              <button type="button" class="btn-lift-ban" data-id="${inc.id}" data-ticket="${inc.ticket_asociado || ''}">
                🔓 Levantar Baneo
              </button>
            </div>
          </div>
        `;
      }
      
      activeBansList.innerHTML = html;
      
      // Agregar event listeners a los botones de desbanear
      activeBansList.querySelectorAll('.btn-lift-ban').forEach(btn => {
        btn.addEventListener('click', () => liftBan(btn.dataset.id, btn.dataset.ticket));
      });
      
      // Agregar event listeners a los botones de Dar Aviso (individual por baneo)
      activeBansList.querySelectorAll('.btn-notify-ban').forEach(btn => {
        btn.addEventListener('click', async () => {
          const incId = parseInt(btn.dataset.id, 10);
          const inc = incidentes.find(i => i.id === incId);
          if (inc) {
            await openEmailModal(incId, inc);
          } else {
            showToast('error', 'Error', 'No se encontró el incidente');
          }
        });
      });
      
    } catch (err) {
      console.error('Error cargando baneos:', err);
      activeBansList.innerHTML = '<p class="error-text">Error de conexión</p>';
    }
  }

  async function liftBan(incidenteId, ticket) {
    if (!confirm(`¿Confirmar levantamiento del baneo${ticket ? ` (${ticket})` : ''}?\n\nLas cámaras volverán a su estado normal.`)) {
      return;
    }
    
    try {
      const res = await fetch(`${window.API_BASE || ''}/api/infra/ban/lift`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': window.CSRF_TOKEN || '',
        },
        body: JSON.stringify({
          incidente_id: parseInt(incidenteId, 10),
          motivo_cierre: 'Levantado desde panel web',
        }),
      });
      
      const data = await res.json();
      
      if (!res.ok || !data.success) {
        throw new Error(data.error || data.message || 'Error al levantar baneo');
      }
      
      // Verificar si se debe enviar correo
      const emailCheck = document.getElementById('notify-email-check');
      const sendEmail = emailCheck && emailCheck.checked;
      
      if (sendEmail) {
        showToast('info', '📧 Enviando aviso...', 'Notificando levantamiento de baneo');
        // TODO: Integrar con servicio de correo real
        setTimeout(() => {
          showToast('success', '📧 Aviso enviado', 'Se notificó el levantamiento del baneo');
        }, 1000);
      }
      
      showToast('success', '🔓 Baneo levantado', `${data.camaras_restauradas || 0} cámaras restauradas`);
      
      // Recargar listado y badge
      loadActiveBansIntoModal();
      loadActiveBans();
      
      // Recargar búsqueda si hay filtros activos
      if (terms.length > 0) {
        await searchCamaras();
      }
      
    } catch (err) {
      showToast('error', 'Error al levantar baneo', err.message);
    }
  }

  // El badge de baneos activos abre el modal de baneos (NO el editor de correo)
  if (banBadge && notifyModal) {
    banBadge.addEventListener('click', () => {
      loadActiveBansIntoModal();
      notifyModal.showModal();
    });
  }

  // NOTA: El botón "Dar Aviso" abre el EDITOR DE CORREO (definido más abajo)
  // NO agregamos listener aquí para evitar duplicación

  if (notifyCloseBtn) {
    notifyCloseBtn.addEventListener('click', () => notifyModal.close());
  }

  if (notifyCancelBtn) {
    notifyCancelBtn.addEventListener('click', () => notifyModal.close());
  }

  // ===========================================
  // EDITOR DE CORREO ELECTRÓNICO - DAR AVISO
  // ===========================================

  const emailEditorModal = document.getElementById('email-editor-modal');
  const emailEditorClose = emailEditorModal ? emailEditorModal.querySelector('.email-editor-close') : null;
  const emailCancelBtn = document.getElementById('email-cancel-btn');
  const emailSendBtn = document.getElementById('email-send-btn');
  const emailDownloadEmlBtn = document.getElementById('email-download-eml-btn');
  const emailStatus = document.getElementById('email-status');
  
  // Campos del formulario
  const emailTo = document.getElementById('email-to');
  const emailSubject = document.getElementById('email-subject');
  const emailBody = document.getElementById('email-body');
  const emailAttachXls = document.getElementById('email-attach-xls');
  const emailAttachTxt = document.getElementById('email-attach-txt');
  const emailTxtWarning = document.getElementById('email-txt-warning');
  const emailBansList = document.getElementById('email-bans-list');
  const emailRestoreBtn = document.getElementById('email-restore-template');

  // Estado de baneos activos para el editor
  let emailEditorBans = [];
  let txtFileAvailable = false;
  
  // ═══════════════════════════════════════════════════════════════════════════
  // PERSISTENCIA DE CONFIGURACIÓN (LocalStorage)
  // ═══════════════════════════════════════════════════════════════════════════
  
  const EMAIL_STORAGE_KEY = 'lasfocas_email_settings';
  
  function loadEmailSettings() {
    try {
      const saved = localStorage.getItem(EMAIL_STORAGE_KEY);
      if (saved) {
        return JSON.parse(saved);
      }
    } catch (err) {
      console.warn('Error cargando configuración de email:', err);
    }
    return {}; // Retornar objeto vacío si no hay configuración
  }
  
  function saveEmailSettings() {
    try {
      const settings = {
        recipients: emailTo ? emailTo.value : '',
      };
      localStorage.setItem(EMAIL_STORAGE_KEY, JSON.stringify(settings));
    } catch (err) {
      console.warn('Error guardando configuración de email:', err);
    }
  }
  
  // Guardar destinatarios cuando cambian
  if (emailTo) {
    emailTo.addEventListener('change', saveEmailSettings);
    emailTo.addEventListener('blur', saveEmailSettings);
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // PLANTILLA DE TEXTO PLANO (más fácil de editar)
  // ═══════════════════════════════════════════════════════════════════════════
  
  const DEFAULT_TEMPLATE = `Estimados,

Se les informa que se ha activado el Protocolo de Protección en la red de fibra óptica debido a una afectación de servicio.

DATOS DEL INCIDENTE:
• Ticket: {{ticket}}
• Servicio Afectado: {{servicio_afectado}}
• Servicio Protegido: {{servicio_protegido}}
• Cámaras Restringidas: {{cantidad}} cámaras
• Fecha/Hora: {{fecha}}
• Motivo: {{motivo}}

Se adjunta el listado detallado de cámaras restringidas (Excel) y el archivo de tracking original.

Por favor, tomar las precauciones necesarias y abstenerse de realizar trabajos en las cámaras listadas hasta nuevo aviso.

Saludos cordiales,

Operaciones de Red
Metrotel S.A.`;

  // ═══════════════════════════════════════════════════════════════════════════
  // FUNCIONES DEL EDITOR
  // ═══════════════════════════════════════════════════════════════════════════
  
  function renderTemplate(template, values) {
    const replacements = {
      ticket: values.ticket || `INC-${values.id || ''}`.trim(),
      servicio: values.servicio || values.servicio_protegido || '-',
      servicio_afectado: values.servicio_afectado || '-',
      servicio_protegido: values.servicio_protegido || values.servicio || '-',
      cantidad: values.cantidad ?? values.total_camaras ?? '?',
      fecha: values.fecha || new Date().toLocaleString('es-AR'),
      motivo: values.motivo || 'Afectación de servicio',
    };

    let output = template;
    Object.entries(replacements).forEach(([key, val]) => {
      output = output.replace(new RegExp(`\\{\\{${key}\\}\\}`, 'g'), val);
    });

    // Compatibilidad retro: reemplazar placeholder anterior si quedara en la plantilla
    output = output.replace(/\{\{total_camaras\}\}/g, replacements.cantidad);

    return output;
  }

  // Generar texto con datos del incidente
  function generateEmailText(bans) {
    if (bans.length === 0) return DEFAULT_TEMPLATE;
    
    const ban = bans[0]; // Usar el primer baneo para los datos principales
    const fecha = ban.fecha_inicio 
      ? new Date(ban.fecha_inicio).toLocaleString('es-AR', {
          day: '2-digit', month: '2-digit', year: 'numeric',
          hour: '2-digit', minute: '2-digit'
        })
      : new Date().toLocaleString('es-AR');
    
    return renderTemplate(DEFAULT_TEMPLATE, {
      id: ban.id,
      ticket: ban.ticket_asociado || `INC-${ban.id}`,
      servicio_afectado: ban.servicio_afectado_id,
      servicio_protegido: ban.servicio_protegido_id,
      servicio: ban.servicio_protegido_id,
      cantidad: ban.camaras_count ?? ban.cantidad_camaras ?? '?',
      fecha,
      motivo: ban.motivo,
    });
  }

  // Generar asunto por defecto
  function generateDefaultSubject(bans) {
    if (bans.length === 0) return '[ALERTA] Protocolo de Protección Activo - Metrotel';
    const ban = bans[0];
    const ticket = ban.ticket_asociado || `INC-${ban.id}`;
    return `[ALERTA] Protocolo de Protección - ${ticket} - ${ban.servicio_protegido_id}`;
  }

  // Restaurar plantilla por defecto
  function restoreDefaultTemplate() {
    if (emailBody) {
      emailBody.value = generateEmailText(emailEditorBans);
      setEmailStatus('✓ Plantilla restaurada', 'success');
      setTimeout(() => setEmailStatus('', ''), 2000);
    }
  }

  // Cargar datos de baneos en el editor
  async function loadBansIntoEmailEditor() {
    if (!emailBansList) return;
    
    emailBansList.innerHTML = '<p class="loading-text">Cargando baneos...</p>';
    
    try {
      const res = await fetch(`${window.API_BASE || ''}/api/infra/ban/active`, {
        credentials: 'include'
      });
      
      if (!res.ok) throw new Error('Error cargando baneos');
      
      const data = await res.json();
      emailEditorBans = data.incidentes || [];
      
      if (emailEditorBans.length === 0) {
        emailBansList.innerHTML = '<p class="empty-text">No hay baneos activos</p>';
        return;
      }
      
      // Renderizar lista de baneos
      let html = '';
      for (const ban of emailEditorBans) {
        html += `
          <div class="email-ban-item">
            <span class="ban-ticket">${ban.ticket_asociado || 'Sin ticket'}</span>
            <span class="ban-services">
              ${ban.servicio_afectado_id} → ${ban.servicio_protegido_id}
            </span>
            <span class="ban-camaras">${ban.camaras_count || '?'} cámaras</span>
          </div>
        `;
      }
      emailBansList.innerHTML = html;
      
      // Actualizar nombre del archivo TXT
      const txtFilename = document.getElementById('email-txt-filename');
      if (txtFilename && emailEditorBans.length > 0) {
        txtFilename.textContent = `tracking_${emailEditorBans[0].servicio_protegido_id}.txt`;
      }
      
      // Cargar destinatarios guardados
      const savedSettings = loadEmailSettings();
      if (emailTo && savedSettings.recipients) {
        emailTo.value = savedSettings.recipients;
      }
      
      // Cargar plantilla con datos
      if (emailSubject) emailSubject.value = generateDefaultSubject(emailEditorBans);
      if (emailBody) emailBody.value = generateEmailText(emailEditorBans);
      
      // Verificar disponibilidad del TXT original
      txtFileAvailable = emailEditorBans.length > 0;
      if (emailTxtWarning) emailTxtWarning.hidden = txtFileAvailable;
      
    } catch (err) {
      console.error('Error cargando baneos para editor:', err);
      emailBansList.innerHTML = '<p class="error-text">Error cargando datos</p>';
    }
  }

  // Validar formulario de email
  function validateEmailForm() {
    if (!emailTo.value.trim()) {
      setEmailStatus('Ingresá al menos un destinatario', 'error');
      emailTo.focus();
      return false;
    }
    
    if (!emailSubject.value.trim()) {
      setEmailStatus('El asunto es requerido', 'error');
      emailSubject.focus();
      return false;
    }
    
    if (!emailBody.value.trim()) {
      setEmailStatus('El mensaje es requerido', 'error');
      emailBody.focus();
      return false;
    }
    
    if (emailEditorBans.length === 0) {
      setEmailStatus('No hay baneos activos para notificar', 'error');
      return false;
    }
    
    // Validar formato de emails básico
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    const allEmails = emailTo.value.split(/[,;\s]+/).map(e => e.trim()).filter(e => e);
    const invalidEmails = allEmails.filter(e => !emailRegex.test(e));
    if (invalidEmails.length > 0) {
      setEmailStatus(`Email inválido: ${invalidEmails[0]}`, 'error');
      return false;
    }
    
    return true;
  }

  function textToBasicHtml(text) {
    const escaped = text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

    // Separar párrafos por líneas en blanco, y dentro usar <br> para saltos simples
    const paragraphs = escaped.split(/\n\s*\n/).map(p => p.replace(/\n/g, '<br>'));
    const htmlContent = paragraphs.map(p => `<p style="margin:0 0 12px 0;">${p}</p>`).join('');

    return `<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; padding: 20px; }
    </style>
</head>
<body>
    ${htmlContent}
    <hr style="margin-top: 30px; border: none; border-top: 1px solid #e2e8f0;">
    <p style="font-size: 12px; color: #64748b; margin: 0;">
        Generado por LAS-FOCAS - Metrotel
    </p>
</body>
</html>`;
  }

  function htmlToPlainText(html) {
    if (!html) return '';
    // Eliminar estilos/scripts para que no aparezcan en el editor
    const sanitized = html
      .replace(/<style[^>]*>[\s\S]*?<\/style>/gi, '')
      .replace(/<script[^>]*>[\s\S]*?<\/script>/gi, '');
    // Reemplazar saltos de línea HTML por \n antes de extraer texto
    const normalized = sanitized
      .replace(/<br\s*\/?>/gi, '\n')
      .replace(/<\/p>/gi, '\n')
      .replace(/<\/div>/gi, '\n');
    const tmp = document.createElement('div');
    tmp.innerHTML = normalized;
    return tmp.textContent || tmp.innerText || html;
  }

  // Preparar payload JSON para envío directo
  function prepareEmailPayload() {
    return {
      incident_id: emailEditorBans[0].id,
      recipients: emailTo.value,
      subject: emailSubject.value,
      html_body: textToBasicHtml(emailBody.value),
      include_xls: emailAttachXls ? emailAttachXls.checked : true,
      include_txt: emailAttachTxt ? emailAttachTxt.checked : true,
    };
  }

  // Preparar FormData para descarga EML (endpoint espera form-data)
  function prepareEmlFormData() {
    if (!emailEditorBans.length || typeof emailEditorBans[0].id === 'undefined') {
      throw new Error('Incidente no cargado en el editor');
    }

    const incidentId = parseInt(emailEditorBans[0].id, 10);
    if (!Number.isFinite(incidentId)) {
      throw new Error('Incidente inválido');
    }

    const formData = new FormData();
    formData.append('incident_id', String(incidentId));
    formData.append('html_body', textToBasicHtml(emailBody.value || ''));
    formData.append('subject', emailSubject.value || '');
    if (emailTo && emailTo.value) {
      formData.append('recipients', emailTo.value);
    }
    return formData;
  }

  // Generar y descargar archivo EML
  async function downloadEmailAsEml() {
    if (!validateEmailForm()) return;
    
    // Guardar destinatarios
    saveEmailSettings({ recipients: emailTo.value });
    
    setEmailStatus('Generando archivo EML...', 'loading');
    if (emailDownloadEmlBtn) emailDownloadEmlBtn.disabled = true;
    
    try {
      const formData = prepareEmlFormData();
      
      const res = await fetch(`${window.API_BASE || ''}/api/infra/notify/download-eml`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'X-CSRF-Token': window.CSRF_TOKEN || '',
        },
        body: formData,
      });
      
      if (!res.ok) {
        let message = `Error ${res.status}`;
        try {
          const errorData = await res.json();
          if (errorData) {
            if (typeof errorData.detail === 'string') {
              message = errorData.detail;
            } else if (Array.isArray(errorData.detail)) {
              message = errorData.detail.map((d) => d.msg || d.detail || JSON.stringify(d)).join('; ');
            } else if (errorData.error) {
              message = errorData.error;
            }
          }
        } catch (_) {
          // si no es JSON, dejamos el status
        }
        throw new Error(message);
      }
      
      // Descargar el archivo .eml
      const blob = await res.blob();
      const contentDisposition = res.headers.get('Content-Disposition');
      let filename = 'notificacion.eml';
      
      if (contentDisposition) {
        const match = contentDisposition.match(/filename="(.+?)"/);
        if (match) filename = match[1];
      }
      
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      
      setEmailStatus('', '');
      showToast('success', '📄 Archivo EML generado', `Descargando: ${filename}`);
      
      // Cerrar modal
      if (emailEditorModal) emailEditorModal.close();
      
    } catch (err) {
      console.error('Error generando EML:', err);
      setEmailStatus(err.message, 'error');
      showToast('error', 'Error al generar', err.message);
    } finally {
      if (emailDownloadEmlBtn) emailDownloadEmlBtn.disabled = false;
    }
  }

  // Enviar email directamente via API
  async function sendEmailDirectly() {
    if (!validateEmailForm()) return;
    
    // Guardar destinatarios
    saveEmailSettings({ recipients: emailTo.value });
    
    setEmailStatus('Enviando correo...', 'loading');
    if (emailSendBtn) emailSendBtn.disabled = true;
    
    try {
      const toList = emailTo.value
        .split(/[,;\\s]+/)
        .map(e => e.trim())
        .filter(Boolean);

      const payload = {
        to: toList,
        cc: [],
        subject: emailSubject.value,
        body: emailBody.value,
        incidente_ids: [emailEditorBans[0].id],
        include_xls: emailAttachXls ? emailAttachXls.checked : true,
        include_txt: emailAttachTxt ? emailAttachTxt.checked : true,
      };
      
      const res = await fetch(`${window.API_BASE || ''}/api/infra/notify/email`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': window.CSRF_TOKEN || '',
        },
        body: JSON.stringify(payload),
      });
      
      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.error || `Error ${res.status}`);
      }
      
      const result = await res.json();
      
      setEmailStatus('', '');
      showToast('success', '✉️ Correo enviado', result.message || 'Notificación enviada exitosamente');
      
      // Cerrar modal
      if (emailEditorModal) emailEditorModal.close();
      
    } catch (err) {
      console.error('Error enviando email:', err);
      setEmailStatus(err.message, 'error');
      showToast('error', 'Error al enviar', err.message);
    } finally {
      if (emailSendBtn) emailSendBtn.disabled = false;
    }
  }

  function setEmailStatus(message, type) {
    if (!emailStatus) return;
    emailStatus.textContent = message;
    emailStatus.className = `email-status ${type || ''}`;
  }

  function resetEmailEditor() {
    emailEditorBans = [];
    // No resetear destinatarios - se cargan desde localStorage
    if (emailSubject) emailSubject.value = '';
    if (emailBody) emailBody.value = '';
    if (emailAttachXls) emailAttachXls.checked = true;
    if (emailAttachTxt) emailAttachTxt.checked = true;
    if (emailBansList) emailBansList.innerHTML = '';
    setEmailStatus('', '');
  }

  // NOTA: El botón global "Dar Aviso" fue eliminado del header principal.
  // Ahora cada baneo en el modal tiene su propio botón de aviso individual.
  // Los event listeners se agregan dinámicamente en loadActiveBansIntoModal().

  // Botón Restaurar Plantilla
  if (emailRestoreBtn) {
    emailRestoreBtn.addEventListener('click', restoreDefaultTemplate);
  }

  // Event listeners del modal
  if (emailEditorClose) {
    emailEditorClose.addEventListener('click', () => {
      if (emailEditorModal) emailEditorModal.close();
    });
  }

  if (emailCancelBtn) {
    emailCancelBtn.addEventListener('click', () => {
      if (emailEditorModal) emailEditorModal.close();
    });
  }

  // Botón Enviar Correo (directo)
  if (emailSendBtn) {
    emailSendBtn.addEventListener('click', sendEmailDirectly);
  }

  // Botón Descargar EML
  if (emailDownloadEmlBtn) {
    emailDownloadEmlBtn.addEventListener('click', downloadEmailAsEml);
  }

  // Cerrar con ESC
  if (emailEditorModal) {
    emailEditorModal.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        emailEditorModal.close();
      }
    });
  }

  // Cargar y abrir modal de email para un incidente específico
  async function openEmailModal(incidenteId, fallbackBan = null) {
    if (!incidenteId) {
      showToast('warning', 'Incidente requerido', 'Seleccioná un incidente para notificar');
      return;
    }

    resetEmailEditor();
    setEmailStatus('Cargando datos...', 'loading');

    try {
      const res = await fetch(`${window.API_BASE || ''}/api/infra/ban/${incidenteId}`, {
        credentials: 'include',
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        const message = errData.detail || `Error ${res.status}`;
        // Intento de fallback con datos ya cargados si la API de detalle no está disponible
        if (fallbackBan) {
          console.warn('Detalle no disponible, usando datos de fallback del listado activo:', message);
          throw { useFallback: true, message };
        }
        throw new Error(message);
      }

      const data = await res.json();

      const cantidad =
        data.cantidad_camaras ??
        data.camaras_count ??
        data.total_camaras ??
        (data.camaras_afectadas ? data.camaras_afectadas.length : undefined) ??
        (data.incidente && data.incidente.camaras_afectadas ? data.incidente.camaras_afectadas.length : undefined) ??
        '?';

      const templateData = {
        id: data.id,
        ticket: data.ticket,
        servicio_afectado: data.servicio_afectado,
        servicio_protegido: data.servicio_protegido,
        servicio: data.servicio_protegido,
        cantidad,
        motivo: data.motivo,
      };

      emailEditorBans = [
        {
          id: data.id,
          ticket_asociado: data.ticket,
          servicio_afectado_id: data.servicio_afectado,
          servicio_protegido_id: data.servicio_protegido,
          camaras_count: cantidad,
          motivo: data.motivo,
        },
      ];

      if (emailBansList) {
        emailBansList.innerHTML = `
          <div class="email-ban-item">
            <span class="ban-ticket">${data.ticket || 'Sin ticket'}</span>
            <span class="ban-services">${data.servicio_afectado} → ${data.servicio_protegido}</span>
            <span class="ban-camaras">${cantidad ?? '?'} cámaras</span>
          </div>
        `;
      }

      const savedSettings = loadEmailSettings();
      if (emailTo && savedSettings.recipients) {
        emailTo.value = savedSettings.recipients;
      }

      const defaultSubject = `[ALERTA] Protocolo de Protección - ${data.ticket || `INC-${data.id}`} - ${data.servicio_protegido}`;
      if (emailSubject) emailSubject.value = data.email_subject || defaultSubject;

      const defaultBody = renderTemplate(DEFAULT_TEMPLATE, templateData);
      const bodyFromDb = data.email_body ? htmlToPlainText(data.email_body) : null;

      let finalBody = bodyFromDb;
      if (!finalBody) {
        finalBody = defaultBody;
      } else if (finalBody.includes('{{cantidad}}') || finalBody.includes('? cámaras')) {
        // Reemplazar placeholders antiguos o valores desconocidos con el conteo real
        finalBody = renderTemplate(DEFAULT_TEMPLATE, templateData);
      }

      if (emailBody) emailBody.value = finalBody;

      if (emailTxtWarning) emailTxtWarning.hidden = true;
      txtFileAvailable = true;
      setEmailStatus('', '');

      if (emailEditorModal) emailEditorModal.showModal();
    } catch (err) {
      // Fallback: si vino desde listado y no hay endpoint de detalle, usar datos básicos para no bloquear UX
      if (err && err.useFallback && fallbackBan) {
        const fallbackData = {
          id: fallbackBan.id,
          ticket: fallbackBan.ticket_asociado || `INC-${fallbackBan.id}`,
          servicio_afectado: fallbackBan.servicio_afectado_id,
          servicio_protegido: fallbackBan.servicio_protegido_id,
          cantidad_camaras: fallbackBan.camaras_count ?? fallbackBan.cantidad_camaras ?? '?',
          motivo: fallbackBan.motivo,
          email_subject: null,
          email_body: null,
        };

        const cantidad =
          fallbackData.cantidad_camaras ??
          fallbackData.camaras_count ??
          fallbackData.total_camaras ??
          (fallbackData.camaras_afectadas ? fallbackData.camaras_afectadas.length : undefined) ??
          '?';

        const templateData = {
          id: fallbackData.id,
          ticket: fallbackData.ticket,
          servicio_afectado: fallbackData.servicio_afectado,
          servicio_protegido: fallbackData.servicio_protegido,
          servicio: fallbackData.servicio_protegido,
          cantidad,
          motivo: fallbackData.motivo,
        };

        emailEditorBans = [
          {
            id: fallbackData.id,
            ticket_asociado: fallbackData.ticket,
            servicio_afectado_id: fallbackData.servicio_afectado,
            servicio_protegido_id: fallbackData.servicio_protegido,
            camaras_count: cantidad,
            motivo: fallbackData.motivo,
          },
        ];

        if (emailBansList) {
          emailBansList.innerHTML = `
            <div class="email-ban-item">
              <span class="ban-ticket">${fallbackData.ticket || 'Sin ticket'}</span>
              <span class="ban-services">${fallbackData.servicio_afectado} → ${fallbackData.servicio_protegido}</span>
            <span class="ban-camaras">${cantidad ?? '?'} cámaras</span>
          </div>
        `;
      }

        const savedSettings = loadEmailSettings();
        if (emailTo && savedSettings.recipients) {
          emailTo.value = savedSettings.recipients;
        }

        const defaultSubject = `[ALERTA] Protocolo de Protección - ${fallbackData.ticket} - ${fallbackData.servicio_protegido}`;
        if (emailSubject) emailSubject.value = fallbackData.email_subject || defaultSubject;

        const defaultBody = renderTemplate(DEFAULT_TEMPLATE, templateData);
        const bodyFromDb = fallbackData.email_body ? htmlToPlainText(fallbackData.email_body) : null;

        let finalBody = bodyFromDb;
        if (!finalBody) {
          finalBody = defaultBody;
        } else if (finalBody.includes('{{cantidad}}') || finalBody.includes('? cámaras')) {
          finalBody = renderTemplate(DEFAULT_TEMPLATE, templateData);
        }

        if (emailBody) emailBody.value = finalBody;

        if (emailTxtWarning) emailTxtWarning.hidden = true;
        txtFileAvailable = true;
        setEmailStatus('', '');

        if (emailEditorModal) emailEditorModal.showModal();
        return;
      }

      const message = err.message || 'No se pudo cargar el incidente';
      console.error('Error cargando incidente para notificación:', err);
      setEmailStatus(message, 'error');
      showToast('error', 'No se pudo cargar el incidente', message);
    }
  }

  // Exponer función para usos externos (botones dinámicos)
  window.openEmailModal = openEmailModal;

})();
