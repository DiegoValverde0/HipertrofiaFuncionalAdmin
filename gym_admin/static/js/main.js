// Sistema de modales personalizado (Tailwind CSS)
window.ModalManager = {
  getModal: function(modalId) {
    return document.getElementById(modalId);
  },
  
  open: function(modalId) {
    const modal = this.getModal(modalId);
    if (modal) {
      modal.classList.remove('hidden');
    } else {
      console.error('Modal no encontrado:', modalId);
    }
  },
  
  close: function(modalId) {
    const modal = this.getModal(modalId);
    if (modal) {
      modal.classList.add('hidden');
    }
  },
  
  init: function() {
    // Cerrar modales al hacer click en botones confirm-modal-close
    document.querySelectorAll('.confirm-modal-close').forEach(btn => {
      if(btn.__modalBound) return;
      btn.__modalBound = true;
      btn.addEventListener('click', (e) => {
        const modalId = btn.dataset.modal;
        if (modalId) {
          this.close(modalId);
        }
      });
    });
    
    // Cerrar modal al hacer click fuera del contenedor
    ['confirmModal', 'confirmEditModal', 'confirmDiscardModal'].forEach(id => {
      const modal = this.getModal(id);
      if (modal && !modal.__bgBound) {
        modal.__bgBound = true;
        modal.addEventListener('click', (e) => {
          if (e.target === modal) {
            this.close(id);
          }
        });
      }
    });
  }
};

// Inicializar sistema de modales
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => window.ModalManager.init());
} else {
  window.ModalManager.init();
}

document.addEventListener('DOMContentLoaded', function(){
  document.body.addEventListener('click', function(e){
    var btn = e.target.closest('.btn-delete');
    if(btn){
      e.preventDefault();
      e.stopPropagation();
      var action = btn.dataset.action;
      var name = btn.dataset.name || 'este elemento';
      var msgEl = document.getElementById('confirmModalMessage');
      if(msgEl) msgEl.textContent = '¿Eliminar "' + name + '"? Esta acción no se puede deshacer.';
      var ok = document.getElementById('confirmOk');
      if(ok) ok.dataset.action = action;
      window.ModalManager.open('confirmModal');
    }
  }, true);

  document.getElementById('confirmOk')?.addEventListener('click', function(){
    window.ModalManager.close('confirmModal');
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
      e.stopPropagation(); // prevent HTMX or others from submitting immediately
      // store form to submit on confirm
      window.__formToSubmit = f;
      var name = f.dataset.name || f.querySelector('[name="nombre"]')?.value || f.querySelector('[name="id"]')?.value || 'este elemento';
      var msgEl = document.getElementById('confirmModalMessage');
      if(msgEl) msgEl.textContent = '¿Eliminar "' + name + '"? Esta acción no se puede deshacer.';
      var ok = document.getElementById('confirmOk');
      if(ok) ok.dataset.action = '';
      window.ModalManager.open('confirmModal');
    }
  }, true); // use capture phase

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
      var unreadCls = n.leido ? '' : 'bg-brand-50/50';
      var indicator = n.leido ? '<span class="inline-block h-2 w-2 rounded-full bg-slate-300 mt-1"></span>' : '<span class="relative flex h-3 w-3"><span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-brand-400 opacity-75"></span><span class="relative inline-flex rounded-full h-3 w-3 bg-brand-500"></span></span>';
      var btnHtml = n.leido ? '' : `<button class="btn-mark-read inline-flex items-center justify-center px-3 py-1.5 text-xs font-semibold text-brand-600 bg-brand-50 hover:bg-brand-100 rounded-md transition-colors sm:opacity-0 sm:group-hover:opacity-100 focus:opacity-100" data-notif-id="${n.id}">Leída</button>`;
      
      return `
        <div class="p-4 flex gap-4 transition-colors hover:bg-slate-50 cursor-pointer group notif-row border-b border-slate-100 last:border-0 ${unreadCls}" data-notif-id="${n.id}">
          <div class="shrink-0 mt-1">${indicator}</div>
          <div class="min-w-0 flex-1">
            <div class="flex items-center justify-between gap-2 mb-1">
              <p class="text-sm font-bold text-slate-900 truncate">${escapeHtml(n.tipo)}</p>
              <span class="text-[11px] text-slate-500 whitespace-nowrap">${d}</span>
            </div>
            <p class="text-sm text-slate-600 line-clamp-2">${escapeHtml(n.mensaje)}</p>
            <div class="mt-2 flex justify-end">${btnHtml}</div>
          </div>
        </div>`;
    }

    function renderNotifications(items){
      if(!listEl) return;
      if(!items || items.length===0){ 
        listEl.innerHTML = `
          <div class="text-center py-12">
            <div class="inline-flex items-center justify-center w-16 h-16 rounded-full bg-slate-100 text-slate-300 mb-4">
              <i class="ti ti-bell-off text-3xl"></i>
            </div>
            <p class="text-slate-600 font-semibold">Sin notificaciones</p>
            <p class="text-slate-500 text-sm mt-1">Estás al día por el momento.</p>
          </div>`;
        if(badge) badge.style.display='none'; 
        return; 
      }
      var unread = 0;
      var html = '<div class="divide-y divide-slate-100 -mx-4 -mt-4">';
      items.forEach(function(n){ if(!n.leido) unread += 1; html += buildItemHtml(n); });
      html += '</div>';
      listEl.innerHTML = html;

      if(badge){ if(unread>0){ badge.style.display='inline-block'; badge.textContent = unread; } else { badge.style.display='none'; } }

      // attach handlers for mark-read and view
      Array.from(listEl.querySelectorAll('.btn-mark-read')).forEach(function(btn){
        btn.addEventListener('click', async function(e){
          e.stopPropagation();
          e.preventDefault();
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
    function escapeHtml(s){ if(s===null || s===undefined) return ''; return String(s).replace(/[&<>"']/g, function(m){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]; }); }

    function showGenericNotifModal(detail){
      var html = `
        <div id="tailwindNotifDetailModal" class="fixed inset-0 z-[70] flex items-center justify-center p-4">
          <div class="absolute inset-0 bg-slate-900/50 backdrop-blur-sm transition-opacity" id="tailwindNotifOverlay"></div>
          <div class="bg-white rounded-2xl shadow-xl w-full max-w-md relative z-10 transform transition-all scale-100 opacity-100">
            <div class="flex items-center justify-between p-6 border-b border-slate-100">
              <h5 class="text-lg font-bold text-slate-900 flex items-center gap-2"><i class="ti ti-info-circle text-brand-600"></i> ${escapeHtml(detail.tipo)}</h5>
              <button type="button" class="text-slate-400 hover:text-slate-600 hover:bg-slate-100 p-1.5 rounded-lg transition-colors" onclick="document.getElementById('tailwindNotifDetailModal').remove()"><i class="ti ti-x text-lg"></i></button>
            </div>
            <div class="p-6">
              <p class="text-xs font-medium text-slate-400 mb-3">${new Date(detail.fecha).toLocaleString()}</p>
              <div class="text-slate-600 text-sm leading-relaxed">${escapeHtml(detail.mensaje)}</div>
            </div>
            <div class="p-6 border-t border-slate-50 bg-slate-50/50 rounded-b-2xl flex justify-end">
              <button class="px-4 py-2 bg-white border border-slate-200 text-slate-700 hover:bg-slate-50 hover:text-slate-900 rounded-lg text-sm font-medium transition-colors shadow-sm" onclick="document.getElementById('tailwindNotifDetailModal').remove()">Cerrar</button>
            </div>
          </div>
        </div>`;
      var wrapper = document.createElement('div'); wrapper.innerHTML = html; document.body.appendChild(wrapper);
      document.getElementById('tailwindNotifOverlay').addEventListener('click', function() {
        document.getElementById('tailwindNotifDetailModal').remove();
      });
    }

    // slide-over controls
    var notifBtn = document.getElementById('btn-notifications');
    var canvas = document.getElementById('notificationsCanvas');
    var overlay = document.getElementById('notif-overlay');
    var panel = document.getElementById('notif-panel');
    var closes = document.querySelectorAll('.notif-close');

    function openNotif(){
      if(canvas) {
        canvas.classList.remove('hidden', 'pointer-events-none');
        // trigger animation
        setTimeout(() => {
          overlay.classList.remove('opacity-0');
          panel.classList.remove('translate-x-full');
        }, 10);
        fetchAndRender();
      }
    }

    function closeNotif(){
      if(canvas) {
        overlay.classList.add('opacity-0');
        panel.classList.add('translate-x-full');
        setTimeout(() => {
          canvas.classList.add('hidden', 'pointer-events-none');
        }, 300);
      }
    }

    if(notifBtn) notifBtn.addEventListener('click', openNotif);
    if(overlay) overlay.addEventListener('click', closeNotif);
    closes.forEach(c => c.addEventListener('click', closeNotif));

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

    window.initFormSnapshots = function(container) {
      var root = container || document;
      var candidateForms = Array.from(root.querySelectorAll('form')).filter(function(f){
        var candidate = false;
        try{
          candidate = f.classList.contains('confirm-edit') || f.dataset.confirmEdit === '1' || (f.action && f.action.indexOf('/edit') !== -1);
        }catch(e){ candidate = false; }
        return candidate && formLooksLikeEdit(f);
      });
      candidateForms.forEach(function(f){
        try{
          if(!initialSnapshots.has(f)) {
            initialSnapshots.set(f, snapshotForm(f));
          }
        }catch(e){}
      });
    };
    
    // Initial call
    window.initFormSnapshots();

    document.body.addEventListener('submit', function(e){
      var f = e.target;
      if(!(f && f.tagName && f.tagName.toLowerCase() === 'form')) return;
      var candidate = false;
      try{
        candidate = f.classList.contains('confirm-edit') || f.dataset.confirmEdit === '1' || (f.action && f.action.indexOf('/edit') !== -1);
      }catch(err){ candidate = false; }
      
      if(candidate && formLooksLikeEdit(f)){
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
        e.stopPropagation(); // Stop other listeners (like modal-form.js)
        var recordId = f.querySelector('[name="id"]')?.value || f.dataset.recordId || '';
        var summaryEl = document.getElementById('confirm-edit-summary');
        if(summaryEl) summaryEl.innerHTML = buildDiffHtml(changes, recordId);
        // store form for final submit when user confirms
        window.__formToSubmit = f;
        window.ModalManager.open('confirmEditModal');
      }
    }, true); // use capture phase to run before modal-form.js

    // when user confirms edit, submit stored form
    document.getElementById('confirmEditOk')?.addEventListener('click', function(){
      if(window.__formToSubmit){
        var f = window.__formToSubmit;
        window.__formToSubmit = null;
        window.ModalManager.close('confirmEditModal');
        var isModalForm = f.closest('#form-modal');
        if(isModalForm && window.modalForm){
          window.modalForm.submitForm(f);
        } else {
          try{ if(window.__origFormSubmit && typeof window.__origFormSubmit === 'function'){ window.__origFormSubmit.apply(f); } else { f.submit(); } }catch(err){ console.error(err); }
        }
      }
    });
  })();
    function showBirthdayModal(list){
      var itemsHtml = '';
      if(!list || !list.length){ 
        itemsHtml = `
          <div class="text-center py-8">
            <div class="inline-flex items-center justify-center w-12 h-12 rounded-full bg-slate-100 text-slate-300 mb-3"><i class="ti ti-cake text-2xl"></i></div>
            <p class="text-sm font-medium text-slate-600">No hay cumpleañeros esta semana.</p>
          </div>`; 
      } else {
        itemsHtml = '<div class="divide-y divide-slate-100">';
        list.forEach(function(c){
          var wa = c.telefono ? `<a class="inline-flex items-center justify-center w-8 h-8 rounded-full bg-green-50 text-green-600 hover:bg-green-100 transition-colors" target="_blank" href="https://wa.me/591${String(c.telefono).replace(/[^0-9]/g,'')}?text=${encodeURIComponent('¡Feliz cumpleaños '+c.nombre_completo+'!')}"><i class="ti ti-brand-whatsapp text-lg"></i></a>` : '';
          itemsHtml += `
            <div class="py-3 flex items-center justify-between gap-4">
              <div class="min-w-0">
                <p class="text-sm font-bold text-slate-900 truncate">${escapeHtml(c.nombre_completo)}</p>
                <p class="text-xs text-slate-500">${escapeHtml(c.fecha_nacimiento)}</p>
              </div>
              <div class="shrink-0">${wa}</div>
            </div>`;
        });
        itemsHtml += '</div>';
      }
      var html = `
        <div id="tailwindBirthdayModal" class="fixed inset-0 z-[70] flex items-center justify-center p-4">
          <div class="absolute inset-0 bg-slate-900/50 backdrop-blur-sm transition-opacity" id="tailwindBirthdayOverlay"></div>
          <div class="bg-white rounded-2xl shadow-xl w-full max-w-md relative z-10 transform transition-all scale-100 opacity-100 flex flex-col max-h-[90vh]">
            <div class="flex items-center justify-between p-6 border-b border-slate-100 shrink-0">
              <h5 class="text-lg font-bold text-slate-900 flex items-center gap-2"><i class="ti ti-cake text-brand-600"></i> Cumpleañeros</h5>
              <button type="button" class="text-slate-400 hover:text-slate-600 hover:bg-slate-100 p-1.5 rounded-lg transition-colors" onclick="document.getElementById('tailwindBirthdayModal').remove()"><i class="ti ti-x text-lg"></i></button>
            </div>
            <div class="p-6 overflow-y-auto custom-scrollbar flex-1">
              ${itemsHtml}
            </div>
            <div class="p-6 border-t border-slate-50 bg-slate-50/50 rounded-b-2xl flex justify-end gap-3 shrink-0">
              <a href="/clientes?cumpleanos_week=1" class="px-4 py-2 bg-brand-600 text-white hover:bg-brand-700 rounded-lg text-sm font-medium transition-colors shadow-sm text-center">Ver todos</a>
              <button class="px-4 py-2 bg-white border border-slate-200 text-slate-700 hover:bg-slate-50 hover:text-slate-900 rounded-lg text-sm font-medium transition-colors shadow-sm" onclick="document.getElementById('tailwindBirthdayModal').remove()">Cerrar</button>
            </div>
          </div>
        </div>`;
      var wrapper = document.createElement('div'); wrapper.innerHTML = html; document.body.appendChild(wrapper);
      document.getElementById('tailwindBirthdayOverlay').addEventListener('click', function() {
        document.getElementById('tailwindBirthdayModal').remove();
      });
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

  document.body.addEventListener('click', function(e){
    var btn = e.target.closest('.btn-memb-marcar');
    if(!btn) return;
    e.preventDefault();
    e.stopPropagation();
    var action = btn.getAttribute('data-action');
    if(!action) return;
    btn.disabled = true;
    fetch(action, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    }).then(function(res){ return res.json().then(function(data){ return { ok: res.ok, data: data }; }); }).then(function(result){
      if(result.ok && result.data && result.data.success){
        var msg = result.data.message || 'Marcaje registrado';
        
        var finishAction = function() {
          if(typeof window._membLoadTable === 'function'){
            window._membLoadTable({});
          } else {
            window.location.reload();
          }
        };

        if (typeof Swal !== 'undefined') {
          Swal.fire({
            title: '¡Éxito!',
            text: msg,
            icon: 'success',
            timer: 2500,
            showConfirmButton: true
          }).then(finishAction);
        } else {
          alert(msg);
          finishAction();
        }
        return;
      }
      var errMsg = (result.data && result.data.message) ? result.data.message : 'No se pudo registrar el marcaje';
      if (typeof Swal !== 'undefined') {
        Swal.fire('Error', errMsg, 'error');
      } else {
        alert(errMsg);
      }
      btn.disabled = false;
    }).catch(function(err){
      console.error('Error registrando marcaje manual', err);
      if (typeof Swal !== 'undefined') {
        Swal.fire('Error', 'No se pudo registrar el marcaje', 'error');
      } else {
        alert('No se pudo registrar el marcaje');
      }
      btn.disabled = false;
    });
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