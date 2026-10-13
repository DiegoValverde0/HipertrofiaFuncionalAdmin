/**
 * Sistema de Modales para Formularios
 * Maneja apertura, cierre, AJAX y detección de cambios
 */

class ModalForm {
  constructor(options = {}) {
    this.modalId = options.modalId || 'form-modal';
    this.formContainerId = options.formContainerId || 'form-container';
    this.closeCallback = options.closeCallback || null;
    this.saveCallback = options.saveCallback || null;
    this.isOpen = false;
    this.isDirty = false;
    this.isSubmitting = false;
    this.pendingClose = false;

    this.init();
  }

  init() {
    this.modal = document.getElementById(this.modalId);
    this.formContainer = document.getElementById(this.formContainerId);
    this.overlay = this.modal?.querySelector('[data-modal-overlay]');
    this.closeBtn = this.modal?.querySelector('[data-modal-close]');

    if (!this.modal) return;

    // Event listeners
    this.closeBtn?.addEventListener('click', () => this.close());
    this.overlay?.addEventListener('click', () => this.close());

    // Tecla Escape para cerrar
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && this.isOpen) {
        this.close();
      }
    });

    // Detectar cambios en inputs
    this.modal.addEventListener('input', () => {
      if (!this.isSubmitting) this.isDirty = true;
    });
    this.modal.addEventListener('change', () => {
      if (!this.isSubmitting) this.isDirty = true;
    });

    // Submit de formularios vía AJAX
    this.modal.addEventListener('submit', (e) => {
      if (e.target.closest('form')) {
        e.preventDefault();
        this.submitForm(e.target);
      }
    });

    // Discard confirmation modal handler
    this.discardModalEl = document.getElementById('confirmDiscardModal');
    this.discardConfirmBtn = document.getElementById('confirmDiscardOk');
    this.discardCancelBtn = document.getElementById('confirmDiscardCancel');

    if (this.discardConfirmBtn && !this.discardConfirmBtn.__discardBound) {
      this.discardConfirmBtn.addEventListener('click', () => {
        this.pendingClose = false;
        this._hideDiscardModal();
        this.close(true);
      });
      this.discardConfirmBtn.__discardBound = true;
    }

    if (this.discardCancelBtn && !this.discardCancelBtn.__discardBound) {
      this.discardCancelBtn.addEventListener('click', () => {
        this.pendingClose = false;
      });
      this.discardCancelBtn.__discardBound = true;
    }

    // CRITICAL: Listen for the Bootstrap modal 'hidden' event to reset pendingClose
    // This covers cases like clicking backdrop, pressing Escape on the discard modal,
    // or clicking the X button — all of which dismiss without clicking "Cancel"
    if (this.discardModalEl && !this.discardModalEl.__discardHiddenBound) {
      this.discardModalEl.addEventListener('hidden.bs.modal', () => {
        this.pendingClose = false;
      });
      this.discardModalEl.__discardHiddenBound = true;
    }
  }

  _hideDiscardModal() {
    if (!this.discardModalEl) return;
    try {
      window.ModalManager.close('confirmDiscardModal');
    } catch (e) {}
  }

  async executeScripts(container){
    // Ejecuta scripts inline y externos encontrados dentro del contenedor
    const scripts = Array.from(container.querySelectorAll('script'));
    // Ejecutar en orden: los externos esperan a cargar, los inline se insertan en el mismo contenedor
    for(const s of scripts){
      try{
        if(s.src){
          await new Promise((resolve, reject)=>{
            const tag = document.createElement('script');
            tag.src = s.src;
            tag.async = false;
            tag.onload = resolve; tag.onerror = reject;
            document.head.appendChild(tag);
          });
        } else {
          const inline = document.createElement('script');
          inline.type = s.type || 'text/javascript';
          inline.textContent = s.textContent || s.innerHTML || '';
          // Insertar el script inline dentro del contenedor para mantener el mismo contexto DOM
          container.appendChild(inline);
        }
      } catch(e){ console.error('Error ejecutando script', e); }
      // remover el script original del contenedor para evitar duplicados en re-aperturas
      try{ if(s.parentNode) s.parentNode.removeChild(s); }catch(e){}
    }
  }

  async open(url, mode = 'create') {
    // Cancelar un cierre en curso: su limpieza diferida borraría el formulario nuevo
    if (this._closeTimer) {
      clearTimeout(this._closeTimer);
      this._closeTimer = null;
    }
    try {
      // Obtener formulario via AJAX
      const response = await fetch(url, {
        method: 'GET',
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
      });

      if (!response.ok) throw new Error('Error cargando formulario');

      const html = await response.text();
      this.formContainer.innerHTML = html;

      // Ejecutar scripts incluidos en el HTML inyectado (inline & externals)
      try { await this.executeScripts(this.formContainer); } catch(e){ console.error('Error ejecutando scripts del formulario:', e); }

      // Inicializar snapshots para confirmación de edición
      if (typeof window.initFormSnapshots === 'function') {
        window.initFormSnapshots(this.formContainer);
      }

      // Reset state
      this.isDirty = false;
      this.isSubmitting = false;
      this.pendingClose = false;

      // Mostrar modal con animación
      this.modal.classList.remove('hidden');
      this.modal.classList.add('flex');
      
      // Trigger animación
      setTimeout(() => {
        this.modal.style.opacity = '1';
      }, 10);

      this.isOpen = true;

      // Focus al primer input
      const firstInput = this.modal.querySelector('input:not([type="hidden"]), textarea, select');
      firstInput?.focus();
    } catch (error) {
      console.error('Error abriendo modal:', error);
      alert('Error cargando el formulario');
    }
  }

  async submitForm(form) {
    if (this.isSubmitting) return;

    this.isSubmitting = true;
    const submitBtn = form.querySelector('button[type="submit"]');
    const originalText = submitBtn?.textContent;

    try {
      // Mostrar loading
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Guardando...';
      }

      // Enviar via AJAX
      const formData = new FormData(form);
      const actionUrl = form.action || form.getAttribute('data-action');
      
      if (!actionUrl) {
        throw new Error('No se especificó URL de acción para el formulario');
      }

      const response = await fetch(actionUrl, {
        method: form.method.toUpperCase(),
        body: formData,
        headers: {
          'X-Requested-With': 'XMLHttpRequest'
        }
      });

      const contentType = response.headers.get('content-type');
      let data;

      // Verificar si la respuesta es JSON
      if (contentType && contentType.includes('application/json')) {
        data = await response.json();
      } else {
        // Si no es JSON, mostrar error detallado
        const text = await response.text();
        console.error('Respuesta no-JSON:', text);
        throw new Error(`Error del servidor: ${response.status} ${response.statusText}`);
      }

      if (data.success) {
        this.isDirty = false;
        
        // Mostrar éxito
        this.showMessage('success', data.message || 'Guardado exitosamente');
        
        setTimeout(() => {
          this.close(true);
          if (this.saveCallback) {
            this.saveCallback(data);
          }
        }, 500);
      } else {
        // Mostrar errores
        this.showMessage('error', data.message || 'Error al guardar');
        
        // Mostrar errores de validación si existen
        if (data.errors) {
          this.showValidationErrors(data.errors);
        }
      }
    } catch (error) {
      console.error('Error enviando formulario:', error);
      this.showMessage('error', `Error: ${error.message}`);
    } finally {
      this.isSubmitting = false;
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = originalText;
      }
    }
  }

  showMessage(type, message) {
    const alertDiv = document.createElement('div');
    alertDiv.className = `
      fixed top-4 right-4 px-4 py-3 rounded-lg text-sm font-medium
      ${type === 'success' 
        ? 'bg-emerald-50 text-emerald-800 border border-emerald-200' 
        : 'bg-red-50 text-red-800 border border-red-200'}
      z-50 animate-in fade-in slide-in-from-top-2 duration-300
    `;
    alertDiv.textContent = message;

    document.body.appendChild(alertDiv);

    setTimeout(() => {
      alertDiv.remove();
    }, 4000);
  }

  showValidationErrors(errors) {
    // Limpiar errores previos
    this.modal.querySelectorAll('[data-error-msg]').forEach(el => el.textContent = '');

    // Mostrar nuevos errores
    Object.entries(errors).forEach(([field, messages]) => {
      const errorEl = this.modal.querySelector(`[data-error-msg="${field}"]`);
      const fieldGroup = this.modal.querySelector(`[name="${field}"]`)?.closest('[data-field]');
      
      if (errorEl) {
        errorEl.textContent = Array.isArray(messages) ? messages[0] : messages;
      }
      
      if (fieldGroup) {
        fieldGroup.classList.add('has-error');
      }
    });
  }

  close(skipConfirm = false) {
    if (this.isOpen && this.isDirty && !skipConfirm) {
      this.showDiscardConfirm();
      return;
    }

    // Animación de cierre
    this.modal.style.opacity = '0';

    this._closeTimer = setTimeout(() => {
      this._closeTimer = null;
      this.modal.classList.add('hidden');
      this.modal.classList.remove('flex');
      this.formContainer.innerHTML = '';
      this.isOpen = false;
      this.isDirty = false;
      this.pendingClose = false;

      if (this.closeCallback) {
        this.closeCallback();
      }
    }, 300);
  }

  showDiscardConfirm() {
    if (!this.discardModalEl) {
      // Fallback if modal is missing
      if (!confirm('¿Descartar cambios sin guardar?')) return;
      this.close(true);
      return;
    }
    if (this.pendingClose) return;
    this.pendingClose = true;
    try {
      window.ModalManager.open('confirmDiscardModal');
    } catch (e) {
      // Fallback if bootstrap is not available
      this.pendingClose = false;
      if (!confirm('¿Descartar cambios sin guardar?')) return;
      this.close(true);
    }
  }
}

// Inicializar globalmente
let modalForm = null;

document.addEventListener('DOMContentLoaded', () => {
  modalForm = new ModalForm({
    modalId: 'form-modal',
    formContainerId: 'form-container'
  });
});
