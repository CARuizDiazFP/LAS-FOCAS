//
// Nombre de archivo: sla.js
// Ubicación de archivo: web/static/sla.js
// Descripción: Interacciones de la vista minimalista para generar informes SLA
//

(function(){
  const form = document.getElementById('sla-form');
  if (!form) return;

  const dropzone = document.getElementById('sla-drop');
  const input = document.getElementById('sla-files');
  const flash = document.getElementById('sla-flash');
  const results = document.getElementById('sla-results');
  const mes = document.getElementById('sla-mes');
  const anio = document.getElementById('sla-anio');
  const pdf = document.getElementById('sla-pdf');
  const useDb = document.getElementById('sla-use-db');

  function setFlash(message, mode='info'){
    if (!flash) return;
    const classes = {
      info: 'result-box info',
      success: 'result-box success',
      error: 'result-box error',
    };
    flash.textContent = message;
    flash.className = classes[mode] || classes.info;
  }

  function clearResults(){
    if (!results) return;
    results.innerHTML = '';
  }

  function renderResults(reportPaths){
    if (!results) return;
    results.innerHTML = '';
    if (!reportPaths || typeof reportPaths !== 'object'){
      return;
    }
    const entries = Object.entries(reportPaths).filter(([, href]) => typeof href === 'string' && href);
    if (!entries.length){
      return;
    }
    entries.forEach(([kind, href]) => {
      const anchor = document.createElement('a');
      anchor.href = href;
      anchor.target = '_blank';
      anchor.rel = 'noopener';
      anchor.className = 'btn subtle';
      anchor.textContent = kind.toUpperCase();
      results.appendChild(anchor);
    });
  }

  function updateDropLabel(files){
    if (!dropzone) return;
    const label = dropzone.querySelector('span');
    if (!label) return;
    if (!files || !files.length){
      label.textContent = 'Soltá hasta dos archivos .xlsx o hacé click para seleccionarlos';
      return;
    }
    if (files.length === 1){
      label.textContent = `Falta adjuntar el segundo archivo (actual: ${files[0].name})`;
      return;
    }
    if (files.length === 2){
      label.textContent = `${files[0].name} + ${files[1].name}`;
      return;
    }
    label.textContent = `${files.length} archivos seleccionados`;  // fallback defensivo
  }

  function updateDropzoneState(){
    if (!dropzone) return;
    if (useDb && useDb.checked){
      dropzone.classList.add('disabled');
      dropzone.setAttribute('aria-disabled', 'true');
      updateDropLabel([]);
      if (input) input.value = '';
    } else {
      dropzone.classList.remove('disabled');
      dropzone.removeAttribute('aria-disabled');
      updateDropLabel(input ? Array.from(input.files || []) : []);
    }
  }

  if (useDb){
    useDb.addEventListener('change', () => {
      updateDropzoneState();
      clearResults();
    });
    updateDropzoneState();
  }

  if (dropzone && input){
    dropzone.addEventListener('click', (event) => {
      if (dropzone.classList.contains('disabled')) return;
      if (event.target === input) return;
      input.click();
    });
    dropzone.addEventListener('dragover', (event) => {
      event.preventDefault();
      if (dropzone.classList.contains('disabled')) return;
      dropzone.classList.add('drag');
    });
    dropzone.addEventListener('dragleave', () => dropzone.classList.remove('drag'));
    dropzone.addEventListener('drop', (event) => {
      event.preventDefault();
      dropzone.classList.remove('drag');
      if (dropzone.classList.contains('disabled')) return;
      const files = Array.from(event.dataTransfer.files || []);
      if (!files.length) return;
      input.files = event.dataTransfer.files;
      updateDropLabel(files);
    });
    input.addEventListener('change', () => {
      const files = Array.from(input.files || []);
      updateDropLabel(files);
      clearResults();
    });
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    clearResults();

    const useDbChecked = useDb ? useDb.checked : false;
    const files = input ? Array.from(input.files || []) : [];

    if (!useDbChecked){
      if (files.length !== 2){
        setFlash('Debés adjuntar dos archivos: Servicios Fuera de SLA y Reclamos SLA.', 'error');
        return;
      }
    }

    if (!mes.value || !anio.value){
      setFlash('Indicá mes y año válidos.', 'error');
      return;
    }

    const endpoint = form.getAttribute('action') || '/api/reports/sla';
    const mesValor = mes.value.trim();
    const anioValor = anio.value.trim();

    const formData = new FormData();
    formData.append('mes', mesValor);
    formData.append('anio', anioValor);
    formData.append('periodo_mes', mesValor);
    formData.append('periodo_anio', anioValor);
    formData.append('pdf_enabled', pdf && pdf.checked ? 'true' : 'false');
    formData.append('use_db', useDbChecked ? 'true' : 'false');
    if (!useDbChecked){
      files.forEach((file) => formData.append('files', file, file.name));
    }
    if (window.CSRF_TOKEN){
      formData.append('csrf_token', window.CSRF_TOKEN);
    }

    setFlash('Procesando informe...', 'info');

    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        body: formData,
        credentials: 'include',
      });
      const contentType = response.headers.get('content-type') || '';
      let data = {};
      if (contentType.includes('application/json')){
        data = await response.json().catch(() => ({}));
      } else {
        const textPayload = await response.text();
        if (!response.ok){
          throw new Error(textPayload || `Error ${response.status}: ${response.statusText}`);
        }
      }

      if (!response.ok || !data || data.ok === false){
        const rawError = data && (data.error ?? data.detail ?? data.message);
        const normalizedError = typeof rawError === 'string'
          ? rawError
          : rawError ? JSON.stringify(rawError) : `Error ${response.status}: ${response.statusText}`;
        throw new Error(normalizedError || 'No se pudo generar el informe');
      }
      setFlash(data.message || 'Informe SLA generado correctamente.', 'success');
      renderResults(data.report_paths);
    } catch (error) {
      const message = error && error.message ? error.message : String(error);
      setFlash(`Error: ${message}`, 'error');
      clearResults();
    }
  });
})();
