// ventas.js
// Handles product search, cart UI, price autofill, stock validation and total calculation
document.addEventListener('DOMContentLoaded', function(){
  const search = document.getElementById('productoSearch');
  const suggestions = document.getElementById('productoSuggestions');
  const cart = document.getElementById('cart');
  const subtotalDisplay = document.getElementById('subtotalDisplay');
  const totalDisplay = document.getElementById('totalDisplay');
  const montoTotalInput = document.getElementById('monto_total');
  const descuentoInput = document.getElementById('descuento');

  let productosCache = [];
  let cartItems = [];

  async function loadProductos(){
    try{
      const res = await fetch('/ventas/api/productos', { credentials: 'same-origin' });
      if(!res.ok) throw new Error('error fetching productos');
      const d = await res.json(); productosCache = d.items || [];
    }catch(e){ console.error('load productos', e); }
  }
  // initial load
  loadProductos();

  function formatMoney(v){ return parseFloat(v||0).toFixed(2); }

  function normalizeText(s){
    return (s||'').toString().toLowerCase().replace(/[^a-z0-9\s]/g,' ').replace(/\s+/g,' ').trim();
  }

  function renderSuggestions(list){
    suggestions.innerHTML = '';
    if(!list.length){ suggestions.innerHTML = '<div class="list-group-item text-muted">No hay coincidencias</div>'; return }
    list.forEach(p=>{
      const el = document.createElement('button');
      el.type = 'button'; el.className = 'list-group-item list-group-item-action';
      el.textContent = `${p.nombre} — S/. ${formatMoney(p.precio)} • stock: ${p.stock}`;
      el.addEventListener('click', function(){ addToCart(p); suggestions.innerHTML = ''; search.value = ''; });
      suggestions.appendChild(el);
    });
  }

  function searchLocal(q){
    if(!q) { suggestions.innerHTML = ''; return; }
    const qnorm = normalizeText(q);
    const qTokens = qnorm.split(' ').filter(Boolean);
    if(qTokens.length === 0){ suggestions.innerHTML = ''; return }
    const res = productosCache.filter(p => {
      const nameNorm = normalizeText(p.nombre);
      const nameTokens = nameNorm.split(' ').filter(Boolean);
      // match if every query token is contained in some product token (prefix or substring)
      return qTokens.every(qt => nameTokens.some(nt => nt.indexOf(qt) !== -1 || nt.startsWith(qt)));
    });
    renderSuggestions(res.slice(0,20));
  }

  search.addEventListener('input', function(){
    const v = this.value.trim();
    if(v.length < 2){ suggestions.innerHTML = ''; return }
    // local search, fallback to remote if cache empty
    if(productosCache.length === 0) loadProductos().then(()=> searchLocal(v));
    else searchLocal(v);
  });

  function addToCart(product){
    // if already in cart, increment quantity
    let item = cartItems.find(c => c.producto.id === product.id);
    if(item){
      if(item.cantidad + 1 > product.stock){ alert('Stock insuficiente'); return }
      item.cantidad += 1; item.subtotal = item.cantidad * item.precio_unitario;
    } else {
      item = { producto: product, cantidad: 1, precio_unitario: parseFloat(product.precio||0), subtotal: parseFloat(product.precio||0) };
      cartItems.push(item);
    }
    renderCart();
  }

  function renderCart(){
    cart.innerHTML = '';
    if(cartItems.length === 0){ cart.innerHTML = '<div class="list-group-item text-muted">Añade productos desde la búsqueda</div>'; updateTotals(); return }
    cartItems.forEach((it, idx)=>{
      const div = document.createElement('div'); div.className = 'list-group-item d-flex align-items-center';
      div.innerHTML = `
        <div class="me-3">
          <strong>${it.producto.nombre}</strong>
          <div class="small text-muted">Stock: ${it.producto.stock}</div>
        </div>
        <div class="ms-auto d-flex align-items-center">
          <input type="number" min="1" value="${it.cantidad}" class="form-control form-control-sm me-2 qty-input" style="width:80px">
          <input type="text" readonly class="form-control form-control-sm me-2 price-input" value="${formatMoney(it.precio_unitario)}" style="width:100px; background:#f8f9fa">
          <div class="me-2">S/. <span class="subtotal-span">${formatMoney(it.subtotal)}</span></div>
          <button class="btn btn-sm btn-outline-danger btn-remove">Quitar</button>
        </div>
      `;
      // quantity change
      div.querySelector('.qty-input').addEventListener('change', function(e){
        let q = parseInt(this.value) || 1; if(q < 1) q = 1; if(q > it.producto.stock){ alert('Stock insuficiente'); q = it.producto.stock; this.value = q }
        it.cantidad = q; it.subtotal = it.cantidad * it.precio_unitario; renderCart();
      });
      // price is readonly by default; keep handler but prevent changes
      div.querySelector('.price-input').addEventListener('change', function(e){
        // ignore changes because price is not editable
        this.value = formatMoney(it.precio_unitario);
      });
      // remove
      div.querySelector('.btn-remove').addEventListener('click', function(){ cartItems.splice(idx,1); renderCart(); });
      cart.appendChild(div);
    });
    updateTotals();
  }

  function updateTotals(){
    const subtotal = cartItems.reduce((s,i)=> s + (i.subtotal||0), 0);
    subtotalDisplay.textContent = formatMoney(subtotal);
    const descuento = parseFloat(descuentoInput.value) || 0;
    const total = Math.max(0, subtotal - descuento);
    totalDisplay.textContent = formatMoney(total);
    montoTotalInput.value = formatMoney(total);
  }

  descuentoInput.addEventListener('input', updateTotals);

  // when clicking Save, show confirmation modal first
  document.getElementById('ventaForm').addEventListener('submit', async function(e){
    e.preventDefault();
    if(cartItems.length === 0){ alert('El carrito está vacío'); return }
    // build summary and show modal
    showConfirmModal();
  });

  // build and show confirm modal
  function showConfirmModal(){
    // build lines
    let lines = '';
    cartItems.forEach(it => {
      lines += `<li class="list-group-item d-flex justify-content-between"><div><strong>${it.producto.nombre}</strong><div class="small text-muted">Cant: ${it.cantidad}</div></div><div>S/. ${formatMoney(it.subtotal)}</div></li>`;
    });
    const subtotal = cartItems.reduce((s,i)=> s + (i.subtotal||0), 0);
    const descuento = parseFloat(descuentoInput.value) || 0;
    const total = Math.max(0, subtotal - descuento);
    const modalHtml = `
      <div class="modal fade" id="ventaConfirmModal" tabindex="-1">
        <div class="modal-dialog modal-dialog-centered modal-lg">
          <div class="modal-content shadow-lg">
            <div class="modal-header">
              <h5 class="modal-title">Confirmar venta</h5>
              <button class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
              <p class="text-muted">Revise el resumen de la venta. Por defecto la opción de <strong>Cerrar</strong> está seleccionada para evitar registrar ventas por error.</p>
              <ul class="list-group mb-3">${lines}</ul>
              <div class="d-flex justify-content-between"><div class="fw-semibold">Subtotal</div><div>S/. ${formatMoney(subtotal)}</div></div>
              <div class="d-flex justify-content-between"><div class="fw-semibold">Descuento</div><div>S/. ${formatMoney(descuento)}</div></div>
              <div class="d-flex justify-content-between"><div class="h5">Total</div><div class="h5">S/. ${formatMoney(total)}</div></div>

            </div>
            <div class="modal-footer">
              <button class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
              <button class="btn btn-danger" data-bs-dismiss="modal">Cerrar</button>
              <button class="btn btn-primary" id="confirmSaveBtn">Guardar venta</button>
            </div>
          </div>
        </div>
      </div>`;
    const wrapper = document.createElement('div'); wrapper.innerHTML = modalHtml; document.body.appendChild(wrapper);
    const modalEl = document.getElementById('ventaConfirmModal'); const m = new bootstrap.Modal(modalEl); m.show();
    // handle save: always submit when user clicks "Guardar venta"
    document.getElementById('confirmSaveBtn').addEventListener('click', function(){
      submitSaleForm();
      m.hide();
    });
    modalEl.addEventListener('hidden.bs.modal', function(){ wrapper.remove(); });
  }

  function submitSaleForm(){
    // validate stock server-side by reloading product stock and submit
    (async ()=>{
      await loadProductos();
      for(const it of cartItems){
        const prod = productosCache.find(p => p.id === it.producto.id);
        if(!prod){ alert('Producto no disponible: '+it.producto.nombre); return }
        if(it.cantidad > prod.stock){ alert('Stock insuficiente para '+it.producto.nombre); return }
      }

      const form = document.createElement('form'); form.method = 'post'; form.action = window.location.pathname;
      const cliente = document.querySelector('select[name="cliente_id"]').value;
      const metodo = document.querySelector('select[name="metodo_pago"]').value;
      const comentarios = document.querySelector('input[name="comentarios"]').value;
      form.appendChild(Object.assign(document.createElement('input'), { type:'hidden', name:'cliente_id', value: cliente }));
      form.appendChild(Object.assign(document.createElement('input'), { type:'hidden', name:'metodo_pago', value: metodo }));
      form.appendChild(Object.assign(document.createElement('input'), { type:'hidden', name:'monto_total', value: montoTotalInput.value }));
      form.appendChild(Object.assign(document.createElement('input'), { type:'hidden', name:'comentarios', value: comentarios }));
      form.appendChild(Object.assign(document.createElement('input'), { type:'hidden', name:'descuento', value: descuentoInput.value }));
      cartItems.forEach(it =>{
        form.appendChild(Object.assign(document.createElement('input'), { type:'hidden', name:'producto_id[]', value: it.producto.id }));
        form.appendChild(Object.assign(document.createElement('input'), { type:'hidden', name:'cantidad[]', value: it.cantidad }));
        form.appendChild(Object.assign(document.createElement('input'), { type:'hidden', name:'precio[]', value: it.precio_unitario }));
      });
      document.body.appendChild(form);
      form.submit();
    })();
  }

});
