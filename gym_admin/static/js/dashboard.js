// ═══════════════════════════════════════════════════════════════════
// DASHBOARD PREMIUM JS – Hipertrofia Funcional
// Light Mode · Animated counters · Gradient charts · HTMX-compatible
// ═══════════════════════════════════════════════════════════════════

// ─── Color Palette (Light Mode) ───
var DASH = {
  blue:    { main: '#3b82f6', light: '#93c5fd', dark: '#2563eb' },
  emerald: { main: '#10b981', light: '#6ee7b7', dark: '#059669' },
  rose:    { main: '#f43f5e', light: '#fda4af', dark: '#e11d48' },
  amber:   { main: '#f59e0b', light: '#fcd34d', dark: '#d97706' },
  violet:  { main: '#8b5cf6', light: '#c4b5fd', dark: '#7c3aed' },
  sky:     { main: '#0ea5e9', light: '#7dd3fc', dark: '#0284c7' },
  text:    '#0f172a',
  muted:   '#64748b',
  grid:    'rgba(0,0,0,0.04)',
  border:  'rgba(0,0,0,0.06)',
};

// ─── Track chart instances for cleanup ───
window._dashCharts = window._dashCharts || {};

function destroyDashChart(key) {
  if (window._dashCharts[key]) {
    try { window._dashCharts[key].destroy(); } catch(e) {}
    window._dashCharts[key] = null;
  }
}

function destroyAllDashCharts() {
  Object.keys(window._dashCharts).forEach(destroyDashChart);
}

// ─── Animated Number Counter ───
function animateCounter(element, target, duration) {
  if (!element) return;
  duration = duration || 1200;
  var start = 0;
  var startTime = performance.now();

  element.innerHTML = '0';

  function update(currentTime) {
    var elapsed = currentTime - startTime;
    var progress = Math.min(elapsed / duration, 1);
    // Ease-out cubic
    var eased = 1 - Math.pow(1 - progress, 3);
    var current = Math.round(start + (target - start) * eased);
    element.textContent = current.toLocaleString('es-BO');
    if (progress < 1) {
      requestAnimationFrame(update);
    }
  }

  requestAnimationFrame(update);
}

// ─── Helper: Create gradient fill ───
function createGradient(ctx, colorMain) {
  var gradient = ctx.createLinearGradient(0, 0, 0, ctx.canvas.height);
  gradient.addColorStop(0, colorMain + '30');
  gradient.addColorStop(0.6, colorMain + '0a');
  gradient.addColorStop(1, colorMain + '00');
  return gradient;
}

// ─── Helper: Format currency ───
function formatBs(val) {
  return 'Bs ' + Number(val).toLocaleString('es-BO', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

// ═══════════════════════════════════════════════════════════════════
// MAIN INIT FUNCTION (callable multiple times for HTMX navigation)
// ═══════════════════════════════════════════════════════════════════
function initDashboard() {

  // ─── Configure Chart.js defaults ───
  if (typeof Chart !== 'undefined') {
    Chart.defaults.color = DASH.muted;
    Chart.defaults.borderColor = DASH.grid;
    Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
    Chart.defaults.font.size = 12;
    Chart.defaults.plugins.tooltip.backgroundColor = 'rgba(15, 23, 42, 0.92)';
    Chart.defaults.plugins.tooltip.titleColor = '#f1f5f9';
    Chart.defaults.plugins.tooltip.bodyColor = '#cbd5e1';
    Chart.defaults.plugins.tooltip.borderColor = 'rgba(255,255,255,0.1)';
    Chart.defaults.plugins.tooltip.borderWidth = 1;
    Chart.defaults.plugins.tooltip.cornerRadius = 12;
    Chart.defaults.plugins.tooltip.padding = { top: 10, right: 14, bottom: 10, left: 14 };
    Chart.defaults.plugins.tooltip.displayColors = true;
    Chart.defaults.plugins.tooltip.boxPadding = 4;
    Chart.defaults.plugins.legend.labels.usePointStyle = true;
    Chart.defaults.plugins.legend.labels.pointStyle = 'circle';
    Chart.defaults.plugins.legend.labels.padding = 20;
  }

  // Destroy any previous chart instances from a prior load
  destroyAllDashCharts();

  // Guard: make sure we're actually on the dashboard page
  if (!document.getElementById('chart-financials')) return;

  // ─── 1. Financial Chart (Ingresos vs Egresos) ───
  function loadFinancials(includeCafeteria) {
    var url = '/api/financials/monthly' + (includeCafeteria ? '?include_cafeteria=1' : '');
    fetch(url).then(function(res){ return res.json(); }).then(function(data){
      var canvas = document.getElementById('chart-financials');
      if (!canvas) return;
      var ctx = canvas.getContext('2d');

      destroyDashChart('financials');

      // Format month labels
      var months = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];
      var formattedLabels = data.labels.map(function(l){
        var parts = l.split('-');
        return months[parseInt(parts[1]) - 1] + ' ' + parts[0].slice(2);
      });

      var gradIngresos = createGradient(ctx, DASH.emerald.main);
      var gradEgresos = createGradient(ctx, DASH.rose.main);

      window._dashCharts.financials = new Chart(ctx, {
        type: 'line',
        data: {
          labels: formattedLabels,
          datasets: [
            {
              label: 'Ingresos',
              data: data.ingresos,
              borderColor: DASH.emerald.main,
              backgroundColor: gradIngresos,
              borderWidth: 2.5,
              tension: 0.4,
              fill: true,
              pointRadius: 0,
              pointHoverRadius: 6,
              pointHoverBackgroundColor: DASH.emerald.main,
              pointHoverBorderColor: '#fff',
              pointHoverBorderWidth: 2,
            },
            {
              label: 'Egresos',
              data: data.egresos,
              borderColor: DASH.rose.main,
              backgroundColor: gradEgresos,
              borderWidth: 2.5,
              tension: 0.4,
              fill: true,
              pointRadius: 0,
              pointHoverRadius: 6,
              pointHoverBackgroundColor: DASH.rose.main,
              pointHoverBorderColor: '#fff',
              pointHoverBorderWidth: 2,
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            legend: {
              position: 'top',
              align: 'end',
              labels: { boxWidth: 8, boxHeight: 8 }
            },
            tooltip: {
              callbacks: {
                label: function(ctx) {
                  return ctx.dataset.label + ': ' + formatBs(ctx.parsed.y);
                }
              }
            }
          },
          scales: {
            x: {
              grid: { display: false },
              ticks: { font: { size: 11 }, color: '#94a3b8' }
            },
            y: {
              grid: { color: DASH.grid },
              border: { display: false },
              ticks: {
                font: { size: 11 },
                color: '#94a3b8',
                callback: function(value) {
                  if (value >= 1000) return (value / 1000).toFixed(0) + 'k';
                  return value;
                }
              }
            }
          },
          animation: { duration: 1200, easing: 'easeOutQuart' }
        }
      });
    }).catch(function(e){ console.error('loadFinancials', e); });
  }

  loadFinancials(false);

  // Wire the cafeteria toggle
  var toggle = document.getElementById('toggleIncludeCafeteria');
  if (toggle) {
    // Remove old listeners by cloning
    var newToggle = toggle.cloneNode(true);
    toggle.parentNode.replaceChild(newToggle, toggle);
    newToggle.checked = false;
    newToggle.addEventListener('change', function(){ loadFinancials(this.checked); });
  }

  // ─── 2. Client Summary Cards ───
  fetch('/api/clients/summary').then(function(r){ return r.json(); }).then(function(d){
    animateCounter(document.getElementById('card-total-clients'), d.total);
    animateCounter(document.getElementById('card-active-clients'), d.activos);
    animateCounter(document.getElementById('card-inactive-clients'), d.inactivos);

    // Update progress bar
    var ratio = d.total > 0 ? Math.round((d.activos / d.total) * 100) : 0;
    var progressEl = document.getElementById('active-progress');
    var ratioText = document.getElementById('active-ratio-text');
    if (progressEl) {
      setTimeout(function(){ progressEl.style.width = ratio + '%'; }, 500);
    }
    if (ratioText) {
      ratioText.textContent = ratio + '% del total';
    }
  }).catch(function(){});

  // ─── 3. Birthdays List ───
  fetch('/api/clients/birthdays').then(function(r){ return r.json(); }).then(function(list){
    var container = document.getElementById('birthdays-list');
    if (!container) return;
    container.innerHTML = '';

    if (!list.length) {
      container.innerHTML = '<div class="dash-list-empty"><i class="ti ti-mood-smile"></i><p>No hay cumpleañeros esta semana</p></div>';
      return;
    }

    list.forEach(function(c){
      var phone = c.telefono || '';
      var waNumber = phone ? phone.replace(/[^0-9]/g, '') : '';
      var waHref = waNumber
        ? 'https://wa.me/591' + waNumber + '?text=' + encodeURIComponent('¡Feliz cumpleaños! 🎂 Te deseamos un gran día desde Hipertrofia Funcional.')
        : null;

      var waBtn = waHref
        ? '<a class="dash-wa-btn" href="' + waHref + '" target="_blank" title="Felicitar por WhatsApp" onclick="event.stopPropagation()"><i class="ti ti-brand-whatsapp"></i></a>'
        : '';

      var div = document.createElement('div');
      div.className = 'dash-list-item';
      div.innerHTML = '<div class="min-w-0"><div class="dash-list-item-name truncate">' + c.nombre + '</div><div class="dash-list-item-meta">' + c.fecha_nacimiento + ' • ' + (phone || 'Sin teléfono') + '</div></div><div class="flex items-center gap-2">' + waBtn + '<span class="text-lg">🎂</span></div>';
      div.addEventListener('click', function(e) {
        if (e.target.closest('a')) return;
        window.location.href = '/clientes?cumpleanos_week=1&cliente_id=' + c.id;
      });
      container.appendChild(div);
    });
  }).catch(function(){});

  // ─── 4. Expiring Memberships ───
  fetch('/api/members/expiring?days=7').then(function(r){ return r.json(); }).then(function(payload){
    var count = payload && payload.count ? payload.count : 0;
    var items = payload && payload.items ? payload.items : [];

    var countEl = document.getElementById('members-expiring-count');
    if (countEl) countEl.textContent = count;

    var listEl = document.getElementById('members-expiring-list');
    if (!listEl) return;
    listEl.innerHTML = '';

    if (!items.length) {
      listEl.innerHTML = '<div class="dash-list-empty"><i class="ti ti-shield-check"></i><p>No hay membresías por vencer</p></div>';
      return;
    }

    items.forEach(function(m){
      var daysText = (m.days_left !== null && m.days_left !== undefined) ? m.days_left + ' días' : '';
      var urgencyClass = 'amber';
      if (m.days_left !== null && m.days_left <= 2) urgencyClass = 'rose';

      var div = document.createElement('div');
      div.className = 'dash-list-item';
      div.innerHTML = '<div class="min-w-0"><div class="dash-list-item-name truncate">' + m.nombre + '</div><div class="dash-list-item-meta">' + (m.telefono ? m.telefono + ' • ' : '') + (m.fecha_fin || '') + '</div></div><span class="dash-badge ' + urgencyClass + '"><i class="ti ti-clock text-[10px]"></i> ' + (daysText || 'Pronto') + '</span>';
      div.addEventListener('click', function(e) {
        e.stopPropagation();
        window.location.href = '/clientes?expiring=7&cliente_id=' + (m.cliente_id || '');
      });
      listEl.appendChild(div);
    });
  }).catch(function(){});

  // ─── 5. Overview (Doughnut Chart) ───
  fetch('/api/overview').then(function(r){ return r.json(); }).then(function(d){
    try {
      var canvas = document.getElementById('chart-status-pie');
      if (!canvas) return;
      var ctx = canvas.getContext('2d');

      var total = (d.activos || 0) + (d.inactivos || 0);
      if (total === 0) return;

      destroyDashChart('pie');

      window._dashCharts.pie = new Chart(ctx, {
        type: 'doughnut',
        data: {
          labels: ['Activos', 'Inactivos'],
          datasets: [{
            data: [d.activos || 0, d.inactivos || 0],
            backgroundColor: [DASH.emerald.main, DASH.rose.light],
            borderColor: ['rgba(16,185,129,0.2)', 'rgba(244,63,94,0.2)'],
            borderWidth: 2,
            hoverBackgroundColor: [DASH.emerald.dark, DASH.rose.main],
            hoverBorderColor: [DASH.emerald.main, DASH.rose.dark],
            hoverBorderWidth: 3,
            spacing: 3,
            borderRadius: 6,
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          cutout: '68%',
          plugins: {
            legend: {
              position: 'bottom',
              labels: { padding: 16, boxWidth: 10, boxHeight: 10, color: '#475569' }
            },
            tooltip: {
              callbacks: {
                label: function(ctx) {
                  var val = ctx.parsed;
                  var pct = total > 0 ? Math.round((val / total) * 100) : 0;
                  return ctx.label + ': ' + val + ' (' + pct + '%)';
                }
              }
            }
          },
          animation: { animateRotate: true, duration: 1500, easing: 'easeOutQuart' }
        },
        plugins: [{
          id: 'centerText',
          beforeDraw: function(chart) {
            var width = chart.width;
            var height = chart.height;
            var cCtx = chart.ctx;
            cCtx.restore();

            var fontSize = (height / 8).toFixed(0);
            cCtx.font = '800 ' + fontSize + 'px Inter, system-ui, sans-serif';
            cCtx.textBaseline = 'middle';
            cCtx.textAlign = 'center';
            cCtx.fillStyle = '#0f172a';
            cCtx.fillText(total.toLocaleString('es-BO'), width / 2, height / 2 - 6);

            cCtx.font = '500 ' + (fontSize * 0.45).toFixed(0) + 'px Inter, system-ui, sans-serif';
            cCtx.fillStyle = DASH.muted;
            cCtx.fillText('Total', width / 2, height / 2 + parseInt(fontSize) * 0.6);
            cCtx.save();
          }
        }]
      });
    } catch(e) { console.error('pie', e); }
  }).catch(function(){});

  // ─── 6. Plans Bar Chart ───
  fetch('/api/planes/populares').then(function(r){ return r.json(); }).then(function(d){
    var items = d && d.items ? d.items : [];
    if (!items.length) return;

    try {
      var canvas = document.getElementById('chart-plans-bar');
      if (!canvas) return;
      var ctx = canvas.getContext('2d');

      var labels = items.map(function(x){ return x.nombre; });
      var data = items.map(function(x){ return x.count; });

      var colors = [
        DASH.blue.main, DASH.emerald.main, DASH.violet.main,
        DASH.amber.main, DASH.sky.main, DASH.rose.main,
        DASH.blue.light, DASH.emerald.light
      ];
      var hoverColors = [
        DASH.blue.dark, DASH.emerald.dark, DASH.violet.dark,
        DASH.amber.dark, DASH.sky.dark, DASH.rose.dark,
        DASH.blue.main, DASH.emerald.main
      ];

      destroyDashChart('plans');

      window._dashCharts.plans = new Chart(ctx, {
        type: 'bar',
        data: {
          labels: labels,
          datasets: [{
            label: 'Membresías',
            data: data,
            backgroundColor: labels.map(function(_, i){ return colors[i % colors.length]; }),
            hoverBackgroundColor: labels.map(function(_, i){ return hoverColors[i % hoverColors.length]; }),
            borderRadius: 8,
            borderSkipped: false,
            barPercentage: 0.6,
            categoryPercentage: 0.7,
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          indexAxis: 'y',
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                label: function(ctx) {
                  return ctx.parsed.x + ' membresías';
                }
              }
            }
          },
          scales: {
            x: {
              grid: { color: DASH.grid },
              border: { display: false },
              ticks: { font: { size: 11 }, color: '#94a3b8', stepSize: 1 }
            },
            y: {
              grid: { display: false },
              ticks: { font: { size: 12, weight: '600' }, color: '#334155' }
            }
          },
          animation: {
            duration: 1200,
            easing: 'easeOutQuart',
            delay: function(context) {
              return context.dataIndex * 100;
            }
          }
        }
      });
    } catch(e) { console.error('plans bar', e); }
  }).catch(function(){});

  // ─── 7. Active Promotions ───
  fetch('/api/promociones/activas').then(function(r){ return r.json(); }).then(function(d){
    var container = document.getElementById('promotions-list');
    if (!container) return;
    container.innerHTML = '';

    var items = d && d.items ? d.items : [];

    if (!items.length) {
      container.innerHTML = '<div class="dash-list-empty"><i class="ti ti-speakerphone-off"></i><p>No hay promociones activas</p></div>';
      return;
    }

    items.forEach(function(p){
      var div = document.createElement('div');
      div.className = 'dash-promo-item';

      var discountBadge = p.descuento
        ? '<span class="dash-badge emerald"><i class="ti ti-discount-2 text-[10px]"></i> ' + p.descuento + '%</span>'
        : '';

      var dateInfo = p.fecha_fin ? 'Hasta ' + p.fecha_fin : '';

      div.innerHTML = '<div class="flex items-start justify-between gap-3"><div class="min-w-0"><div class="text-sm font-semibold text-slate-800 truncate">' + p.nombre + '</div><div class="text-xs text-slate-500 mt-1 line-clamp-1">' + (p.descripcion || '') + (dateInfo ? ' • ' + dateInfo : '') + '</div></div>' + discountBadge + '</div>';
      container.appendChild(div);
    });
  }).catch(function(){});
}

// ═══════════════════════════════════════════════════════════════════
// AUTO-INIT: Works on both full page load AND HTMX content swap
// ═══════════════════════════════════════════════════════════════════
(function() {
  // Run immediately if DOM is already loaded (HTMX swap scenario)
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initDashboard);
  } else {
    // DOM already loaded (HTMX swap or late script execution)
    initDashboard();
  }
})();
