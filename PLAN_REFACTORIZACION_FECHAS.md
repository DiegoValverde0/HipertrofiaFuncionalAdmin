# Plan de Acción: Refactorización de Manejo de Fechas en Membresías

## 📌 Visión General del Cambio

### Situación Actual (Problemática)
```
┌─────────────────────────────────────────────────────────────────┐
│                                                                  │
│  FRONTEND (JavaScript)                 BACKEND (Python)         │
│  ───────────────────────              ──────────────────────    │
│                                                                  │
│  User input fecha_inicio ──→  Browser calcula fecha_fin   │
│       ↓                        (new Date, setMonth)  ┐          │
│  periodoToEndDate()           │                       │        │
│  applyExtendDate()            └──→  Envía POST        │        │
│       ↓                            con fecha_inicio   │        │
│  Actualiza campo readonly                          │        │
│  fecha_fin visualmente            Backend RECALCULA   │        │
│                            fecha_fin (compute_end_date)        │
│                                     ↓                          │
│                            Guarda en BD                        │
│                                     ↓                          │
│                            ⚠️ PROBLEMA:                         │
│                            Dos cálculos diferentes               │
│                            pueden diferir!                      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Situación Propuesta (Centralizada)
```
┌─────────────────────────────────────────────────────────────────┐
│                                                                  │
│  FRONTEND (JavaScript)                 BACKEND (Python)         │
│  ───────────────────────              ──────────────────────    │
│                                                                  │
│  User input fecha_inicio              Recibe:                  │
│       ↓                                fecha_inicio,            │
│  Llama AJAX a                          plan_id, opcion         │
│  /preview-dates                             ↓                   │
│  {fecha_inicio, plan_id, opcion}     compute_end_date()       │
│       ↓                                     ↓                   │
│  Recibe JSON:                         Retorna JSON:           │
│  {fecha_inicio, fecha_fin,             {fecha_inicio,         │
│   dias, estado_preview}                 fecha_fin,             │
│       ↓                                  dias,                 │
│  Muestra preview visual                  estado}               │
│  sin cambiar inputs                      ↓                     │
│       ↓                             User confirma             │
│  User confirma POST                      ↓                     │
│       ↓                             Backend crea/actualiza      │
│  POST /create o /edit              con fechas VALIDADAS       │
│  con fecha_inicio                       ↓                      │
│       ↓                             Guarda en BD              │
│  Backend valida y                        ↓                      │
│  recalcula (asegura)               ✓ UN ÚNICO CÁLCULO          │
│       ↓                                  CONFIABLE              │
│  Retorna membresía creada                                      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Implementación Paso a Paso

### **PASO 1: Crear Endpoint de Preview (backend)**

**Archivo**: `gym_admin/services/membership_service.py`

Agregar función:
```python
def preview_membership_dates(fecha_inicio, plan_id, opcion='new', cliente_id=None):
    """
    Preview de fechas sin crear membresía.
    
    Args:
        fecha_inicio (date|str): Fecha de inicio propuesta
        plan_id (int): ID del plan
        opcion (str): 'new' o 'extend'
        cliente_id (int): Opcional, para opcion='extend', toma última fecha_fin
    
    Returns:
        dict: {
            'fecha_inicio': date,
            'fecha_fin': date,
            'dias_vigencia': int,
            'duracion_plan': str,
            'estado': 'valido' | 'error',
            'mensaje': str
        }
    """
    try:
        # Parsear fecha_inicio si viene como string
        if isinstance(fecha_inicio, str):
            fecha_inicio = datetime.strptime(fecha_inicio, "%Y-%m-%d").date()
        
        # Obtener plan
        plan = Plan.query.get(plan_id)
        if not plan or plan.estado != 'Activo':
            return {
                'estado': 'error',
                'mensaje': 'Plan no existe o está inactivo'
            }
        
        # Manejar opcion 'extend': obtener fecha_fin de última membresía activa
        if opcion == 'extend' and cliente_id:
            status = get_membership_status(cliente_id)
            if status.get('last_fecha_fin'):
                fecha_inicio = status['last_fecha_fin'] + timedelta(days=1)
                # Ajustar fin de semana
                if fecha_inicio.weekday() == 5:  # Sábado
                    fecha_inicio += timedelta(days=2)
                elif fecha_inicio.weekday() == 6:  # Domingo
                    fecha_inicio += timedelta(days=1)
        
        # Validar que fecha_inicio sea razonable
        if fecha_inicio < date.today() - timedelta(days=30):  # Pasado lejano
            return {
                'estado': 'warning',
                'mensaje': 'Fecha de inicio es más de 30 días en el pasado',
                'fecha_inicio': fecha_inicio,
                'fecha_fin': None
            }
        
        if fecha_inicio > date.today() + timedelta(days=365*5):  # Muy futuro
            return {
                'estado': 'warning',
                'mensaje': 'Fecha de inicio es muy lejana (>5 años)',
                'fecha_inicio': fecha_inicio,
                'fecha_fin': None
            }
        
        # Calcular fecha_fin
        fecha_fin = compute_end_date(fecha_inicio, plan.duracion)
        if not fecha_fin:
            return {
                'estado': 'error',
                'mensaje': 'No se pudo calcular fecha de fin'
            }
        
        # Calcular días de vigencia
        dias = (fecha_fin - fecha_inicio).days + 1  # +1 para incluir día 1
        
        return {
            'estado': 'valido',
            'fecha_inicio': fecha_inicio.isoformat(),
            'fecha_fin': fecha_fin.isoformat(),
            'dias_vigencia': dias,
            'duracion_plan': plan.duracion,
            'mensaje': None
        }
        
    except Exception as e:
        try:
            current_app.logger.exception(f"Error in preview_membership_dates: {e}")
        except:
            pass
        return {
            'estado': 'error',
            'mensaje': f'Error al procesar: {str(e)}'
        }
```

**Archivo**: `gym_admin/blueprints/membresias.py`

Agregar ruta:
```python
@membresias_bp.route("/preview-dates", methods=["GET"])
def preview_membership_dates():
    """API endpoint para preview de fechas sin crear membresía."""
    try:
        fecha_inicio = request.args.get("fecha_inicio", type=str)
        plan_id = request.args.get("plan_id", type=int)
        opcion = request.args.get("opcion", "new", type=str)
        cliente_id = request.args.get("cliente_id", type=int)
        
        if not fecha_inicio or not plan_id:
            return jsonify({'estado': 'error', 'mensaje': 'Parámetros requeridos'}), 400
        
        from ..services.membership_service import preview_membership_dates
        result = preview_membership_dates(
            fecha_inicio=fecha_inicio,
            plan_id=plan_id,
            opcion=opcion,
            cliente_id=cliente_id
        )
        
        return jsonify(result)
        
    except Exception as e:
        current_app.logger.exception(f"Error in preview_membership_dates endpoint: {e}")
        return jsonify({'estado': 'error', 'mensaje': str(e)}), 500
```

---

### **PASO 2: Modificar Frontend (template)**

**Archivo**: `gym_admin/templates/membresias/form.html`

**2.1 Remover función `periodoToEndDate()` y `computeClientFin()`**
(Líneas ~357-410)

Reemplazar con:
```javascript
// Nueva función: llamar al backend para preview
async function updateFechaFinPreview(force) {
  const inicioEl = document.getElementById('m-fecha-inicio');
  const finEl = document.getElementById('m-fecha-fin');
  const planSel = document.getElementById('plan_id');
  const opcionSel = document.querySelector('select[name="opcion"]');
  const clienteIdEl = document.getElementById('cliente_id');
  
  if (!inicioEl || !finEl || !planSel) return;
  
  const fechaInicio = inicioEl.value;
  const planId = planSel.value;
  const opcion = opcionSel?.value || 'new';
  const clienteId = clienteIdEl?.value;
  
  if (!fechaInicio || !planId) {
    finEl.value = '';
    return;
  }
  
  try {
    // Llamar a endpoint de preview
    const params = new URLSearchParams({
      fecha_inicio: fechaInicio,
      plan_id: planId,
      opcion: opcion,
      ...(clienteId && { cliente_id: clienteId })
    });
    
    const response = await fetch(`/membresias/preview-dates?${params}`, {
      credentials: 'same-origin'
    });
    
    if (!response.ok) {
      console.error('Error en preview:', response.status);
      return;
    }
    
    const data = await response.json();
    
    // Actualizar campo fecha_fin con el resultado
    if (data.estado === 'valido') {
      finEl.value = data.fecha_fin;
      // Si hay flatpickr, actualizar también
      if (window.flatpickr) {
        try {
          document.querySelector('#m-fecha-fin')._flatpickr.setDate(data.fecha_fin);
        } catch (e) {}
      }
      
      // Mostrar preview información
      showFechaPreview(data);
    } else if (data.estado === 'warning') {
      finEl.value = '';
      showFechaWarning(data.mensaje);
    } else {
      finEl.value = '';
      showFechaError(data.mensaje);
    }
    
  } catch (error) {
    console.error('Error fetching preview:', error);
    finEl.value = '';
  }
}

function showFechaPreview(data) {
  // Mostrar un badge o card con la información
  const container = document.getElementById('m-fecha-preview');
  if (container) {
    const diasTxt = data.dias_vigencia === 1 ? '1 día' : data.dias_vigencia + ' días';
    container.innerHTML = `
      <div class="alert alert-info" role="alert">
        <i class="ti ti-info-circle"></i>
        <strong>Vigencia:</strong> ${diasTxt} 
        (${data.fecha_inicio} a ${data.fecha_fin})
      </div>
    `;
  }
}

function showFechaWarning(msg) {
  const container = document.getElementById('m-fecha-preview');
  if (container) {
    container.innerHTML = `<div class="alert alert-warning">${msg}</div>`;
  }
}

function showFechaError(msg) {
  const container = document.getElementById('m-fecha-preview');
  if (container) {
    container.innerHTML = `<div class="alert alert-danger">${msg}</div>`;
  }
}

// Exponer función globalmente
window.updateFechaFinPreview = updateFechaFinPreview;
```

**2.2 Actualizar event listeners**
```javascript
// Después de que flatpickr esté cargado, reemplazar:

// OLD:
// flatpickr('#m-fecha-inicio', { 
//   ...fp_config, 
//   defaultDate: inicio.value || 'today', 
//   onChange: function(){ computeClientFin(true); }
// });

// NEW:
flatpickr('#m-fecha-inicio', { 
  ...fp_config, 
  defaultDate: inicio.value || 'today', 
  onChange: function(){ updateFechaFinPreview(true); }  // Llamar AJAX en lugar de calcular JS
});

// Listener para cambio de plan
planSel?.addEventListener('change', function(){ 
  updateFechaFinPreview(true);  // Recalcular preview
});

// Listener para cambio de opción (new/extend)
opcionSel?.addEventListener('change', function(){
  updateFechaFinPreview(true);  // Recalcular preview con nueva opción
});

// Compute inicial
setTimeout(function() { 
  updateFechaFinPreview(true); 
}, 200);
```

**2.3 Agregar contenedor para preview en HTML**

En el template HTML, después del campo `m-fecha-fin`, agregar:
```html
<div id="m-fecha-preview" class="mt-3"></div>
```

---

### **PASO 3: Actualizar Bluerint (reducir complejidad)**

**Archivo**: `gym_admin/blueprints/membresias.py`

Simplificar `create_membresia()`:
```python
@membresias_bp.route("/create", methods=["GET", "POST"])
def create_membresia():
    origin_cliente_id = request.args.get("cliente_id", type=int)
    cliente_id = origin_cliente_id or request.form.get("cliente_id", type=int)
    
    plans = Plan.query.filter(Plan.estado == "Activo").order_by(Plan.nombre).all()
    promos = Promocion.query.filter(Promocion.estado == "Activo").order_by(Promocion.nombre).all()
    
    if request.method == "POST":
        # Obtener datos del formulario
        cliente_id = origin_cliente_id or request.form.get("cliente_id", type=int)
        plan_id = request.form.get("plan_id", type=int)
        promocion_id = request.form.get("promocion_id", type=int) or None
        fecha_inicio_raw = request.form.get("fecha_inicio")
        fecha_fin_raw = request.form.get("fecha_fin")  # Solo para admins
        opcion = request.form.get("opcion") or "new"
        
        if not cliente_id or not plan_id:
            flash("Cliente y Plan son requeridos")
            return redirect(url_for("membresias.create_membresia"))
        
        # Validar cliente y plan
        cliente = Cliente.query.get(cliente_id)
        if not cliente:
            flash("Cliente no encontrado")
            return redirect(url_for("membresias.create_membresia"))
        
        plan = Plan.query.get(plan_id)
        if not plan or getattr(plan, "estado", None) != "Activo":
            flash("Plan no encontrado o inactivo")
            return redirect(request.referrer or url_for("membresias.create_membresia"))
        
        # Parsear fecha_inicio
        try:
            fecha_inicio = (
                datetime.strptime(fecha_inicio_raw, "%Y-%m-%d").date()
                if fecha_inicio_raw
                else date.today()
            )
        except Exception:
            fecha_inicio = date.today()
        
        # Manejar opción extend
        client_status = _client_membership_status(cliente)
        if opcion == "extend":
            if not cliente.membresias:
                flash("El cliente no posee membresía para extender")
                return redirect(request.referrer or url_for("membresias.create_membresia"))
            
            # Recalcular fecha_inicio si no se proporcionó explícitamente
            if not fecha_inicio_raw:
                last_valid_fecha_fin = client_status.get("last_fecha_fin")
                if last_valid_fecha_fin:
                    fecha_inicio = last_valid_fecha_fin + timedelta(days=1)
                    # Ajustar fin de semana
                    if fecha_inicio.weekday() == 5:
                        fecha_inicio += timedelta(days=2)
                    elif fecha_inicio.weekday() == 6:
                        fecha_inicio += timedelta(days=1)
        
        # CAMBIO CLAVE: Usar preview_membership_dates para obtener fecha_fin
        # (No calcular en el backend nuevamente, confirmar el preview del cliente)
        from ..services.membership_service import preview_membership_dates
        preview = preview_membership_dates(
            fecha_inicio=fecha_inicio,
            plan_id=plan_id,
            opcion=opcion,
            cliente_id=cliente_id
        )
        
        if preview['estado'] != 'valido':
            flash(f"Error en fechas: {preview.get('mensaje', 'Desconocido')}")
            return redirect(request.referrer or url_for("membresias.create_membresia"))
        
        fecha_fin = datetime.strptime(preview['fecha_fin'], "%Y-%m-%d").date()
        
        # ⚠️ Solo admins pueden sobrescribir fecha_fin
        if current_user and getattr(current_user, "rol_id", None) == 1:
            try:
                if fecha_fin_raw:
                    fecha_fin_override = datetime.strptime(fecha_fin_raw, "%Y-%m-%d").date()
                    # Validar que sea posterior a fecha_inicio
                    if fecha_fin_override > fecha_inicio:
                        fecha_fin = fecha_fin_override
                    else:
                        flash("Fecha fin manual debe ser posterior a fecha inicio")
                        return redirect(request.referrer or url_for("membresias.create_membresia"))
            except Exception:
                pass  # Ignorar si no se puede parsear, usar la calculada
        
        # Resto del código de creación (igual)
        # ...
```

---

### **PASO 4: Agregar Field `tipo_creacion` al Modelo**

**Archivo**: `gym_admin/models.py`

```python
class Membresia(db.Model):
    __tablename__ = "membresias"
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=False)
    sucursal_id = db.Column(db.Integer, db.ForeignKey("sucursales.id"), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey("planes.id"), nullable=False)
    promocion_id = db.Column(db.Integer, db.ForeignKey("promociones.id"), nullable=True)
    fecha_inicio = db.Column(db.Date, nullable=False)
    fecha_fin = db.Column(db.Date, nullable=False)
    estado_id = db.Column(db.Integer, db.ForeignKey("estados_membresias.id"))
    
    # NUEVO: Registrar si fue 'new' o 'extend'
    tipo_creacion = db.Column(
        db.String(10), 
        default='new',
        nullable=False,
        comment="'new' = nueva membresía, 'extend' = extensión de anterior"
    )
    
    pagos = db.relationship("Pago", backref="membresia", lazy=True)
    
    # ... resto de la clase
```

Generar migración:
```bash
flask db migrate -m "Add tipo_creacion to Membresia"
flask db upgrade
```

---

## 📊 Comparativa Antes/Después

| Aspecto | Antes | Después |
|--------|-------|---------|
| **Cálculo de fecha_fin** | JS + Python (DUPLICADO) | Solo Python (CENTRALIZADO) |
| **Zona horaria** | Riesgo de desfase ±1 día | UTC consistente en backend |
| **Opción extend** | 2 cálculos diferentes | 1 cálculo único en backend |
| **Preview antes de guardar** | No existe | Sí, AJAX en tiempo real |
| **Cambio de plan en edición** | No recalcula | ✓ Propone recalcular |
| **Auditoría de intención** | Imposible | Campo `tipo_creacion` |
| **Help text | Minimal | Contextual y claro |
| **Validación de rangos** | No existe | Avisos para fechas inválidas |
| **Confiabilidad** | 🟠 Media | 🟢 Alta |

---

## 🧪 Plan de Testing

### Unit Tests (Backend)
```python
# tests/services/test_membership_service.py

def test_preview_membership_dates_new():
    """Test cálculo de fecha_fin para nueva membresía."""
    # Plan mensual: 2024-01-01 + 1 mes = 2024-02-01
    result = preview_membership_dates(
        fecha_inicio='2024-01-01',
        plan_id=1,  # Mensual
        opcion='new'
    )
    assert result['estado'] == 'valido'
    assert result['fecha_fin'] == '2024-02-01'
    assert result['dias_vigencia'] == 32  # 31 días + día 1

def test_preview_membership_dates_extend():
    """Test cálculo para extensión."""
    # Cliente tiene membresía que vence 2024-02-01
    # Extensión debe empezar 2024-02-02
    result = preview_membership_dates(
        fecha_inicio='2024-02-01',  # La fecha_fin anterior
        plan_id=1,  # Mensual
        opcion='extend',
        cliente_id=1
    )
    assert result['estado'] == 'valido'
    assert result['fecha_inicio'] >= '2024-02-02'  # Ajustada si necesario

def test_preview_membership_dates_weekend_adjust():
    """Test ajuste de fin de semana."""
    # 2024-01-06 es sábado, debe ajustar a 2024-01-08 (lunes)
    result = preview_membership_dates(
        fecha_inicio='2024-01-01',
        plan_id=1,  # Dura 1 mes, caería en sábado
        opcion='new'
    )
    fecha_fin = datetime.strptime(result['fecha_fin'], '%Y-%m-%d')
    assert fecha_fin.weekday() not in [5, 6]  # No sábado ni domingo
```

### Integration Tests (Frontend + Backend)
```javascript
// test_membership_form.js

test('Preview actualiza cuando cambia fecha_inicio', async () => {
  const inicioInput = document.querySelector('#m-fecha-inicio');
  const finInput = document.querySelector('#m-fecha-fin');
  
  inicioInput.value = '2024-01-15';
  inicioInput.dispatchEvent(new Event('change'));
  
  await new Promise(resolve => setTimeout(resolve, 500));  // Esperar AJAX
  
  expect(finInput.value).toBe('2024-02-15');
});

test('Preview actualiza cuando cambia plan', async () => {
  const planSelect = document.querySelector('#plan_id');
  const finInput = document.querySelector('#m-fecha-fin');
  
  // Cambiar de plan mensual a anual
  planSelect.value = '3';  // Anual
  planSelect.dispatchEvent(new Event('change'));
  
  await new Promise(resolve => setTimeout(resolve, 500));
  
  expect(finInput.value).toMatch(/202[5-9]/);  // Año siguiente
});
```

---

## ✅ Checklist de Implementación

- [ ] **Paso 1: Backend**
  - [ ] Agregar `preview_membership_dates()` en `membership_service.py`
  - [ ] Agregar ruta `/preview-dates` en `membresias.py`
  - [ ] Testear con curl/Postman

- [ ] **Paso 2: Frontend**
  - [ ] Remover funciones `periodoToEndDate()` y `computeClientFin()`
  - [ ] Crear función `updateFechaFinPreview()` que llama AJAX
  - [ ] Actualizar event listeners (onChange de plan, opción, fecha)
  - [ ] Testear que preview funcione en navegador

- [ ] **Paso 3: Simplificar Blueprint**
  - [ ] Refactorizar `create_membresia()` para usar `preview_membership_dates()`
  - [ ] Remover cálculos duplicados
  - [ ] Testear creación desde UI

- [ ] **Paso 4: Modelo**
  - [ ] Agregar campo `tipo_creacion` a Membresia
  - [ ] Generar migración
  - [ ] Actualizar `create_membership()` para registrar tipo_creacion

- [ ] **Paso 5: QA**
  - [ ] Crear nueva membresía (new) → validar fechas
  - [ ] Extender membresía → validar fecha_inicio = next day
  - [ ] Admin: sobrescribir fecha_fin → debe funcionar
  - [ ] No-admin: campo readonly → no editable
  - [ ] Cambiar plan → preview recalcula
  - [ ] Fin de semana → ajusta a lunes

---

## 📚 Referencias y Recursos

- [Python `relativedelta` vs `timedelta`](https://dateutil.readthedocs.io/en/stable/relativedelta.html)
- [Zona horaria en JavaScript: `Date.UTC()`](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Date/UTC)
- [SQLAlchemy migrations con Alembic](https://alembic.sqlalchemy.org/en/latest/)
- [Validación de fecha en HTML5 `<input type="date">`](https://developer.mozilla.org/en-US/docs/Web/HTML/Element/input/date)
