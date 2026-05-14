document.addEventListener('DOMContentLoaded', function(){
  // Confirm delete buttons (delegated)
  document.body.addEventListener('click', function(e){
    if(e.target.closest('.btn-delete')){
      e.preventDefault();
      var btn = e.target.closest('.btn-delete');
      var action = btn.dataset.action;
      var name = btn.dataset.name || 'este elemento';
      var modal = document.getElementById('confirmModal');
      modal.querySelector('.modal-body').textContent = '¿Eliminar "'+name+'"? Esta acción no se puede deshacer.';
      var ok = modal.querySelector('#confirmOk');
      ok.dataset.action = action;
      var m = new bootstrap.Modal(modal);
      m.show();
    }
  });

  document.getElementById('confirmOk')?.addEventListener('click', function(){
    var action = this.dataset.action;
    // If a form was stored for submission, submit it using the original submit to avoid re-interception
    if(window.__formToSubmit){
      try{
        if(window.__origFormSubmit && typeof window.__origFormSubmit === 'function'){
          window.__origFormSubmit.apply(window.__formToSubmit);
        } else {
          window.__formToSubmit.submit();
        }
      }catch(e){ console.error(e); }
      window.__formToSubmit = null;
      return;
    }
    // else if an action url is provided, POST to it
    if(action){
      var form = document.createElement('form');
      form.method = 'post';
      form.action = action;
      document.body.appendChild(form);
      form.submit();
    }
  });

  // --- Enhanced deletion confirmation for forms and links ---
  // Intercept forms that want delete confirmation: class 'confirm-delete-form' or data-confirm-delete
  document.body.addEventListener('submit', function(e){
    var f = e.target;
    if(!(f && f.tagName && f.tagName.toLowerCase() === 'form')) return;
    if(f.classList.contains('confirm-delete-form') || f.dataset.confirmDelete === '1'){
      e.preventDefault();
      // store form to submit on confirm
      window.__formToSubmit = f;
      var name = f.dataset.name || f.querySelector('[name="nombre"]')?.value || f.querySelector('[name="id"]')?.value || 'este elemento';
      var modal = document.getElementById('confirmModal');
      modal.querySelector('.modal-body').textContent = '¿Eliminar "'+name+'"? Esta acción no se puede deshacer.';
      modal.querySelector('#confirmOk').dataset.action = '';
      var m = new bootstrap.Modal(modal);
      m.show();
    }
  });

  // Toasts from window.FLASH_MESSAGES
  if(Array.isArray(window.FLASH_MESSAGES)){
    window.FLASH_MESSAGES.forEach(function(m){
      var t = document.createElement('div');
      t.className = 'toast align-items-center text-bg-primary border-0';
      t.setAttribute('role','alert');
      t.innerHTML = '<div class="d-flex"><div class="toast-body">'+m+'</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button></div>';
      document.getElementById('toast-container').appendChild(t);
      new bootstrap.Toast(t).show();
    });
  }

  // flatpickr init (if present)
  if(window.flatpickr){
    // fecha de nacimiento (misma configuración original)
    if(document.querySelector('#fecha_nacimiento') && !document.querySelector('#fecha_nacimiento')._flatpickr){
      flatpickr('#fecha_nacimiento', {dateFormat:'Y-m-d', maxDate: new Date()});
    }
    // membresías: usar el mismo estilo de calendario (dateFormat) pero permitir fechas futuras
    if(document.querySelector('#m-fecha-inicio') && !document.querySelector('#m-fecha-inicio')._flatpickr){
      flatpickr('#m-fecha-inicio', {dateFormat:'Y-m-d'});
    }
    if(document.querySelector('#m-fecha-fin') && !document.querySelector('#m-fecha-fin')._flatpickr){
      flatpickr('#m-fecha-fin', {dateFormat:'Y-m-d'});
    }
  }

  // Live search and per-page for clientes is now handled in clientes/list.html
  // These references are only used for export/print buttons
  var perPageEl = document.getElementById('per-page');
  var exportBtn = document.getElementById('export-csv');
  var printBtn = document.getElementById('print-view');
  // clients/gastos have their own buttons with unique IDs
  var exportClientsBtn = document.getElementById('export-clients-csv');
  var printClientsBtn = document.getElementById('print-clients-view');
  var exportGastosBtn = document.getElementById('export-gastos-csv');
  var printGastosBtn = document.getElementById('print-gastos-view');
  // Search and per-page for clientes, membresias, ventas and productos are now handled
  // in their respective list.html templates with centralized filter state.

  // export/print for clients (use unique buttons)
  exportClientsBtn?.addEventListener('click', function(e){
    e.preventDefault();
    var url = new URL('/clientes/export.csv', window.location.origin);
    var cur = new URL(window.location.href);
    cur.searchParams.forEach(function(v,k){ url.searchParams.set(k,v); });
    window.location.href = url.toString();
  });
  printClientsBtn?.addEventListener('click', function(e){
    e.preventDefault();
    var url = new URL('/clientes/print', window.location.origin);
    var cur = new URL(window.location.href);
    cur.searchParams.forEach(function(v,k){ url.searchParams.set(k,v); });
    window.open(url.toString(), '_blank');
  });

  // export/print for gastos (use POST to include current filters - handled later in gastos section)
  exportGastosBtn?.addEventListener('click', function(e){
    // delegate to gastos code which already handles POST in page; trigger click on element with id 'export-csv' inside gastos form if present
    e.preventDefault();
    var ev = new Event('click');
    // if there is a local export button in gastos filters, use it; otherwise submit form
    var gf = document.getElementById('gastos-filters');
    if(gf){
      // trigger the existing handler via the same id used previously
      var btn = document.getElementById('export-csv');
      if(btn) btn.dispatchEvent(ev);
      else {
        // fallback: serialize and POST
        var params = (function(){ var data={}; Array.from(gf.elements).forEach(function(el){ if(!el.name) return; if((el.type==='checkbox' || el.type==='radio') && !el.checked) return; data[el.name]=el.value; }); return data; })();
        var form = document.createElement('form'); form.method='post'; form.action='/gastos/export.csv'; Object.keys(params).forEach(function(k){ var i=document.createElement('input'); i.type='hidden'; i.name=k; i.value=params[k]; form.appendChild(i); }); document.body.appendChild(form); form.submit();
      }
    }
  });
  printGastosBtn?.addEventListener('click', function(e){
    e.preventDefault();
    var gf = document.getElementById('gastos-filters');
    if(gf){
      var params = (function(){ var data={}; Array.from(gf.elements).forEach(function(el){ if(!el.name) return; if((el.type==='checkbox' || el.type==='radio') && !el.checked) return; data[el.name]=el.value; }); return data; })();
      var form = document.createElement('form'); form.method='post'; form.action='/gastos/print'; form.target='_blank'; Object.keys(params).forEach(function(k){ var i=document.createElement('input'); i.type='hidden'; i.name=k; i.value=params[k]; form.appendChild(i); }); document.body.appendChild(form); form.submit();
    }
  });

  // --- notifications: poll and populate offcanvas ---
  (function(){
    var badge = document.getElementById('notif-badge');
    var listEl = document.getElementById('notifications-list');

    function buildItemHtml(n){
      var d = new Date(n.fecha).toLocaleString();
      var unreadCls = n.leido ? ' text-muted' : '';
      return `
        <div class="list-group-item d-flex justify-content-between align-items-start p-3 notif-row${unreadCls}" data-notif-id="${n.id}">
          <div>
            <div class="small text-muted">${d}</div>
            <div class="fw-semibold">${n.tipo}</div>
            <div class="small text-truncate" style="max-width:42ch">${n.mensaje}</div>
          </div>
          <div class="btns">
            ${n.leido ? '' : `<button class="btn btn-sm btn-outline-primary btn-mark-read" data-notif-id="${n.id}">Marcar leída</button>`}
          </div>
        </div>`;
    }

    function renderNotifications(items){
      if(!listEl) return;
      if(!items || items.length===0){ listEl.innerHTML = '<p class="text-muted">Sin notificaciones por el momento.</p>'; if(badge) badge.style.display='none'; return; }
      var unread = 0;
      var html = '<div class="list-group">';
      items.forEach(function(n){ if(!n.leido) unread += 1; html += buildItemHtml(n); });
      html += '</div>';
      listEl.innerHTML = html;

      if(badge){ if(unread>0){ badge.style.display='inline-block'; badge.textContent = unread; } else { badge.style.display='none'; } }

      // attach handlers for mark-read and view
      Array.from(listEl.querySelectorAll('.btn-mark-read')).forEach(function(btn){
        btn.addEventListener('click', async function(e){
          e.stopPropagation();
          var nid = this.getAttribute('data-notif-id');
          try{
            await fetch('/notificaciones/api/mark_read/' + nid, { method: 'POST', credentials: 'same-origin' });
            // refresh both list and unread count
            await fetchAndRender();
          }catch(err){ console.error('mark read failed', err); }
        });
      });

      // make clicking the whole notification row open the detail
      Array.from(listEl.querySelectorAll('.notif-row')).forEach(function(row){
        row.addEventListener('click', async function(e){
          // avoid reacting when clicking mark-read button specifically
          if(e.target.closest('.btn-mark-read')) return;
          var nid = this.getAttribute('data-notif-id');
          try{
            // mark as read first
            await fetch('/notificaciones/api/mark_read/' + nid, { method: 'POST', credentials: 'same-origin' });
          }catch(err){ /* ignore */ }
          try{
            var res = await fetch('/notificaciones/api/detail/' + nid, { credentials: 'same-origin' });
            if(!res.ok) throw new Error('detail fetch failed');
            var detail = await res.json();
            if(detail.tipo === 'cumpleanos'){
              var r2 = await fetch('/notificaciones/api/birthdays', { credentials: 'same-origin' });
              if(r2.ok){ var bd = await r2.json(); showBirthdayModal(bd); }
            } else {
              showGenericNotifModal(detail);
            }
          }catch(err){ console.error('Error showing detail', err); }
          // refresh list after displaying
          await fetchAndRender();
        });
      });
    }

    async function fetchAndRender(){
      try{
        var res = await fetch('/notificaciones/api/list', { credentials: 'same-origin' });
        if(!res.ok) throw new Error('fetch failed');
        var data = await res.json();
        renderNotifications(data);
      }catch(e){ console.error('Error fetching notifications', e); }
    }

    // nicer modal builders
    function showGenericNotifModal(detail){
      var html = `
        <div class="modal fade" id="notifDetailModal" tabindex="-1">
          <div class="modal-dialog modal-dialog-centered">
            <div class="modal-content shadow-lg border-0">
              <div class="modal-header bg-light">
                <h5 class="modal-title">${detail.tipo}</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
              </div>
              <div class="modal-body">
                <p class="small text-muted">${new Date(detail.fecha).toLocaleString()}</p>
                <div>${detail.mensaje}</div>
              </div>
              <div class="modal-footer">
                <button class="btn btn-secondary" data-bs-dismiss="modal">Cerrar</button>
              </div>
            </div>
          </div>
        </div>`;
      var wrapper = document.createElement('div'); wrapper.innerHTML = html; document.body.appendChild(wrapper);
      var modalEl = document.getElementById('notifDetailModal'); var m = new bootstrap.Modal(modalEl); m.show();
      modalEl.addEventListener('hidden.bs.modal', function(){ wrapper.remove(); });

  // --- Confirm-on-edit feature ---
  (function(){
    // map to store initial snapshots
    var initialSnapshots = new WeakMap();
    // helper to read form values (only meaningful fields)
    function snapshotForm(form){
      var data = {};
      Array.from(form.elements).forEach(function(el){
        if(!el.name) return;
        if(el.type === 'checkbox') data[el.name] = el.checked ? '1' : '0';
        else if(el.type === 'radio') { if(el.checked) data[el.name] = el.value; }
        else data[el.name] = el.value;
      });
      return data;
    }

    function buildDiffHtml(changes, recordId){
      if(!changes || changes.length===0) return '<div class="text-muted">No hay cambios detectados.</div>';
      var html = '';
      if(recordId) html += '<p><strong>ID:</strong> ' + recordId + '</p>';
      html += '<div class="table-responsive"><table class="table table-sm"><thead><tr><th>Campo</th><th>Anterior</th><th>Nuevo</th></tr></thead><tbody>';
      changes.forEach(function(c){ html += '<tr><td>' + escapeHtml(c.field) + '</td><td>' + escapeHtml(c.old) + '</td><td>' + escapeHtml(c.new) + '</td></tr>'; });
      html += '</tbody></table></div>';
      return html;
    }

    function escapeHtml(s){ if(s===null || s===undefined) return ''; return String(s).replace(/[&<>"']/g, function(m){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]; }); }

    // helper: determine if a form corresponds to an existing record (edit)
    function formLooksLikeEdit(f){
      try{
        // explicit data-record-id or hidden input named id with a value
        if(f.dataset && f.dataset.recordId) return true;
        var idel = f.querySelector('[name="id"][type="hidden"], [name="id"]');
        if(idel && idel.value && idel.value.toString().trim() !== '') return true;
        // action containing '/edit' (conservative: word boundary)
        if(f.action && /\/edit(\/|$|\?)/.test(f.action)) return true;
      }catch(e){}
      return false;
    }

    // collect candidate forms: only forms that look like an edit (not create)
    var forms = Array.from(document.querySelectorAll('form')).filter(function(f){
      var candidate = false;
      try{
        candidate = f.classList.contains('confirm-edit') || f.dataset.confirmEdit === '1' || (f.action && f.action.indexOf('/edit') !== -1);
      }catch(e){ candidate = false; }
      // only require confirmation for forms that represent an edit of an existing record
      return candidate && formLooksLikeEdit(f);
    });

    // Override HTMLFormElement.submit to catch programmatic submits for confirm-edit forms
    try{
    if(!HTMLFormElement.prototype.__submit_wrapped){
      var _origSubmit = HTMLFormElement.prototype.submit;
      try{ window.__origFormSubmit = _origSubmit; }catch(e){}
      HTMLFormElement.prototype.submit = function(){
          try{
            var f = this;
          // only require confirm if form looks like an edit (avoid asking on creates)
          var isConfirm = (f.classList && (f.classList.contains('confirm-edit') || f.dataset.confirmEdit === '1' || (f.action && f.action.indexOf('/edit') !== -1))) && formLooksLikeEdit(f);
            if(!isConfirm){
              return _origSubmit.apply(f, arguments);
            }
            // compute diffs similar to submit handler
            var before = initialSnapshots.get(f) || snapshotForm(f) || {};
            var after = snapshotForm(f) || {};
            var changes = [];
            Object.keys(after).forEach(function(k){
              var a = after[k] === undefined ? '' : after[k];
              var b = before[k] === undefined ? '' : before[k];
              if(a !== b){
                if(k.toLowerCase().indexOf('csrf') === 0) return;
                if(k.toLowerCase().indexOf('token') !== -1) return;
                changes.push({ field: k, old: b, new: a });
              }
            });
            if(changes.length === 0){
              return _origSubmit.apply(f, arguments);
            }
            // store and show modal
            window.__formToSubmit = f;
            var recordId = f.querySelector('[name="id"]')?.value || f.dataset.recordId || '';
            var summaryEl = document.getElementById('confirm-edit-summary');
            if(summaryEl) summaryEl.innerHTML = buildDiffHtml(changes, recordId);
            var emodal = document.getElementById('confirmEditModal');
            var m = new bootstrap.Modal(emodal);
            m.show();
            return; // do not submit now
          }catch(e){ console.error('submit override error', e); return _origSubmit.apply(this, arguments); }
        };
        HTMLFormElement.prototype.__submit_wrapped = true;
      }
    }catch(e){ console.error('Could not override form submit', e); }

    forms.forEach(function(f){
      try{
        initialSnapshots.set(f, snapshotForm(f));
        f.addEventListener('submit', function(e){
          // on submit, compare snapshots
          var before = initialSnapshots.get(f) || {};
          var after = snapshotForm(f);
          var changes = [];
          Object.keys(after).forEach(function(k){
            var a = after[k] === undefined ? '' : after[k];
            var b = before[k] === undefined ? '' : before[k];
            if(a !== b){
              // only show if meaningful (ignore CSRF, timestamps, meta fields)
              if(k.toLowerCase().indexOf('csrf') === 0) return;
              if(k.toLowerCase().indexOf('token') !== -1) return;
              changes.push({ field: k, old: b, new: a });
            }
          });
          if(changes.length === 0){
            // no changes: proceed
            return true;
          }
          // prevent submit and show modal with summary
          e.preventDefault();
          var recordId = f.querySelector('[name="id"]')?.value || f.dataset.recordId || '';
          var summaryEl = document.getElementById('confirm-edit-summary');
          if(summaryEl) summaryEl.innerHTML = buildDiffHtml(changes, recordId);
          // store form for final submit when user confirms
          window.__formToSubmit = f;
          var emodal = document.getElementById('confirmEditModal');
          var m = new bootstrap.Modal(emodal);
          m.show();
        });
      }catch(e){ console.error('confirm-edit init error', e); }
    });

    // when user confirms edit, submit stored form
    document.getElementById('confirmEditOk')?.addEventListener('click', function(){
      if(window.__formToSubmit){
        try{ if(window.__origFormSubmit && typeof window.__origFormSubmit === 'function'){ window.__origFormSubmit.apply(window.__formToSubmit); } else { window.__formToSubmit.submit(); } }catch(e){ console.error(e); }
        window.__formToSubmit = null;
      }
    });
  })();
    }

    function showBirthdayModal(list){
      var itemsHtml = '';
      if(!list || !list.length){ itemsHtml = '<p class="text-muted">No hay cumpleañeros esta semana.</p>'; }
      else{
        itemsHtml = '<div class="list-group">';
        list.forEach(function(c){
          var wa = c.telefono ? `<a class="btn btn-sm btn-success me-2" target="_blank" href="https://wa.me/591${String(c.telefono).replace(/[^0-9]/g,'')}?text=${encodeURIComponent('¡Feliz cumpleaños '+c.nombre_completo+'!')}"><i class="bi bi-whatsapp"></i></a>` : '';
          itemsHtml += `<div class="list-group-item d-flex justify-content-between align-items-center"><div><strong>${c.nombre_completo}</strong><div class="small text-muted">${c.fecha_nacimiento}</div></div><div>${wa}</div></div>`;
        });
        itemsHtml += '</div>';
      }
      var html = `
        <div class="modal fade" id="notifDetailModal" tabindex="-1">
          <div class="modal-dialog modal-dialog-scrollable modal-lg">
            <div class="modal-content shadow-lg border-0">
              <div class="modal-header bg-light">
                <h5 class="modal-title">Cumpleañeros de la semana</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
              </div>
              <div class="modal-body p-0">
                ${itemsHtml}
              </div>
              <div class="modal-footer">
                <a class="btn btn-primary" href="/clientes?cumpleanos_week=1">Ver todos</a>
                <button class="btn btn-secondary" data-bs-dismiss="modal">Cerrar</button>
              </div>
            </div>
          </div>
        </div>`;
      var wrapper = document.createElement('div'); wrapper.innerHTML = html; document.body.appendChild(wrapper);
      var modalEl = document.getElementById('notifDetailModal'); var m = new bootstrap.Modal(modalEl); m.show();
      modalEl.addEventListener('hidden.bs.modal', function(){ wrapper.remove(); });
    }

  // Delegated handler: abrir modal de detalle de membresía
  document.body.addEventListener('click', function(e){
    var btn = e.target.closest('.btn-memb-detalle');
    if(!btn) return;
    e.preventDefault();
    var id = btn.getAttribute('data-id');
    if(!id) return;
    // fetch fragment and append to body
    fetch('/membresias/'+encodeURIComponent(id)+'/detail', { credentials: 'same-origin' }).then(function(res){ return res.text(); }).then(function(html){
      try{
        // remove any existing detail modal to avoid duplicates
        var existing = document.getElementById('membDetailModal'); if(existing){ existing.closest('.memb-detail-wrapper')?.remove(); }
        // insert into a wrapper and append
        var wrapper = document.createElement('div'); wrapper.className = 'memb-detail-wrapper';
        wrapper.innerHTML = html;
        document.body.appendChild(wrapper);
        // find modal element and show it via bootstrap API (scripts inside inserted HTML won't run reliably)
        var modalEl = wrapper.querySelector('#membDetailModal');
        if(modalEl){
          try{
            var modalInstance = new bootstrap.Modal(modalEl);
            modalInstance.show();
            // remove wrapper when modal is hidden
            modalEl.addEventListener('hidden.bs.modal', function(){ try{ wrapper.remove(); }catch(e){} });
          }catch(e){ console.error('Error mostrando modal de detalle', e); }
        } else {
          console.error('Modal element not found in detail HTML');
        }
      }catch(e){ console.error('Error mostrando detalle membresía', e); }
    }).catch(function(err){ console.error('Error cargando detalle', err); });
  });

    // Delegated handler: Enviar comprobante por WhatsApp desde el modal
    document.body.addEventListener('click', function(e){
      var btn = e.target.closest('#membDetailWhatsapp');
      if(!btn) return;
      try{
        // find enclosing modal
        var modal = document.getElementById('membDetailModal');
        if(!modal) {
          // maybe the modal is inside a wrapper
          modal = document.querySelector('.memb-detail-wrapper #membDetailModal') || document.getElementById('membDetailModal');
        }
  var phone = modal?.getAttribute('data-phone') || '';
  // the modal now exposes a tokenized print-ready URL in data-print-url
  var printPath = modal?.getAttribute('data-print-url') || '';
  var fullPrintUrl = (printPath && printPath.indexOf('http') === 0) ? printPath : (window.location.origin + printPath);
        // sanitize phone: keep digits only
        var cleaned = (phone || '').toString().replace(/[^0-9]/g,'');
        if(!cleaned){ alert('Número de teléfono del cliente no disponible para enviar por WhatsApp'); return; }
        // build message with link to the PDF (note: for local servers, WhatsApp recipient may not be able to access the URL)
  var text = 'Hola, le envío el comprobante de membresía. Puede ver e imprimir el comprobante aquí: ' + fullPrintUrl;
  var waUrl = 'https://wa.me/' + cleaned + '?text=' + encodeURIComponent(text);
        window.open(waUrl, '_blank');
      }catch(err){ console.error('Error preparando WhatsApp', err); alert('No se pudo abrir WhatsApp'); }
    });

    var btn = document.getElementById('btn-notifications');
    if(btn){
      btn.addEventListener('click', function(){
        var el = document.getElementById('notificationsCanvas');
        var off = new bootstrap.Offcanvas(el);
        off.show();
        fetchAndRender();
      });
    }
    fetchAndRender();
    // poll every 30 seconds to keep UI in sync
    setInterval(fetchAndRender, 30*1000);
  })();

});
// fin
// --- Gastos: filtros en tiempo real ---
document.addEventListener('DOMContentLoaded', function(){
  var gastosForm = document.getElementById('gastos-filters');
  if(!gastosForm) return;

  var timerG = null;
  function serializeForm(frm){
    var data = {};
    Array.from(frm.elements).forEach(function(el){
      if(!el.name) return;
      if((el.type === 'checkbox' || el.type === 'radio') && !el.checked) return;
      data[el.name] = el.value;
    });
    return data;
  }

  function loadGastosTable(params){
    var url = new URL('/gastos/table', window.location.origin);
    try{ var cur = new URL(window.location.href); cur.searchParams.forEach(function(v,k){ url.searchParams.set(k,v); }); }catch(e){}
    for(var k in params) if(params[k] !== undefined && params[k] !== null && params[k] !== '') url.searchParams.set(k, params[k]);
    fetch(url.toString(), { credentials: 'same-origin' }).then(function(r){ return r.text(); }).then(function(html){
      var cont = document.getElementById('gastos-table');
      if(cont) cont.innerHTML = html;
    });
  }

  // enable/disable custom date inputs
  function toggleCustomDates(){
    var periodo = gastosForm.querySelector('select[name="periodo"]').value;
    var desde = gastosForm.querySelector('input[name="fecha_desde"]');
    var hasta = gastosForm.querySelector('input[name="fecha_hasta"]');
    if(periodo === 'custom'){
      desde.removeAttribute('disabled');
      hasta.removeAttribute('disabled');
    } else {
      desde.setAttribute('disabled','disabled');
      hasta.setAttribute('disabled','disabled');
    }
  }

  // initial toggle
  toggleCustomDates();

  gastosForm.addEventListener('input', function(e){
    if(e.target.name === 'periodo'){
      toggleCustomDates();
    }
    clearTimeout(timerG);
    timerG = setTimeout(function(){
      var params = serializeForm(gastosForm);
      // reset to page 1 when filters change
      params.page = 1;
      loadGastosTable(params);
    }, 300);
  });

  // delegate pagination clicks inside gastos-table
  document.body.addEventListener('click', function(e){
    var a = e.target.closest('#gastos-table .pagination a.page-link');
    if(a){
      e.preventDefault();
      try{
        var href = a.getAttribute('href') || '';
        var u = new URL(href, window.location.origin);
        var page = u.searchParams.get('page') || 1;
        var params = serializeForm(gastosForm);
        params.page = page;
        loadGastosTable(params);
      }catch(err){ window.location.href = a.href; }
    }
  });

  // export and print buttons (use current filters)
  var exp = document.getElementById('export-csv');
  var pr = document.getElementById('print-view');
  function postTo(url, params, target){
    var form = document.createElement('form');
    form.method = 'post';
    form.action = url;
    if(target) form.target = target;
    Object.keys(params).forEach(function(k){ var i = document.createElement('input'); i.type='hidden'; i.name=k; i.value=params[k]; form.appendChild(i); });
    document.body.appendChild(form);
    form.submit();
  }
  exp?.addEventListener('click', function(e){ e.preventDefault(); var params = serializeForm(gastosForm); postTo('/gastos/export.csv', params, null); });
  pr?.addEventListener('click', function(e){ e.preventDefault(); var params = serializeForm(gastosForm); postTo('/gastos/print', params, '_blank'); });
});