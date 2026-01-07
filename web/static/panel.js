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
