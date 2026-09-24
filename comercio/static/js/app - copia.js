/* ===== Utilidades ===== */
const $ = id => document.getElementById(id);

let SESION_ACTIVA = false; // Se actualiza al cargar

function toast(msg, ms = 2800) {
  const el = $('toast');
  if (!el) return;
  el.textContent = msg;
  el.classList.remove('hidden');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.add('hidden'), ms);
}

async function api(url, method = 'GET', body = null) {
  const opts = { method, headers: { 'Content-Type': 'application/json' }, credentials: 'include' };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(url, opts);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Error en la petición');
  return data;
}

function escapeHtml(str) {
  const d = document.createElement('div');
  d.appendChild(document.createTextNode(str || ''));
  return d.innerHTML;
}

function timeAgo(fechaStr) {
  const diff = Date.now() - new Date(fechaStr).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1)  return 'ahora';
  if (m < 60) return `hace ${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `hace ${h}h`;
  const d = Math.floor(h / 24);
  if (d < 7)  return `hace ${d}d`;
  return new Date(fechaStr).toLocaleDateString('es-MX', { day:'2-digit', month:'short' });
}

/* ===== Modal login requerido ===== */
function pedirLogin() {
  const overlay = $('modal-login-req');
  if (overlay) overlay.classList.add('open');
}

function cerrarModalLogin(e) {
  if (e && e.target !== $('modal-login-req')) return;
  $('modal-login-req')?.classList.remove('open');
}

/* ===== Verificar sesión ===== */
async function verificarSesion() {
  try {
    await api('/api/auth/yo');
    SESION_ACTIVA = true;
    // Mostrar fab de publicar, ocultar fab de login
    $('fab-pub')  && ($('fab-pub').style.display   = 'flex');
    $('fab-login') && ($('fab-login').style.display = 'none');
    $('visitor-banner') && ($('visitor-banner').style.display = 'none');
    // Mostrar links de perfil/mensajes/notifs en navbar
    actualizarBadge();
    setInterval(actualizarBadge, 30000);
  } catch (_) {
    SESION_ACTIVA = false;
    // Mostrar fab de login, ocultar fab de publicar
    $('fab-pub')   && ($('fab-pub').style.display  = 'none');
    $('fab-login') && ($('fab-login').style.display = 'flex');
    $('visitor-banner') && ($('visitor-banner').style.display = 'flex');
    // Ocultar links que requieren sesión en navbar
    document.querySelectorAll('.nav-auth').forEach(el => el.style.display = 'none');
  }
}

/* ===== Feed ===== */
async function cargarPublicaciones() {
  const feed = $('feed');
  if (!feed) return;
  feed.innerHTML = `<div class="spinner-feed"><span></span><span></span><span></span></div>`;
  try {
    const pubs = await api('/api/publicaciones?limite=30');
    if (!pubs.length) {
      feed.innerHTML = `<div class="empty">
        <div class="empty-icon">🏪</div>
        <p>Aún no hay publicaciones.<br>¡Sé el primero en vender algo!</p>
      </div>`;
      return;
    }
    feed.innerHTML = '';
    pubs.forEach((p, i) => {
      const el = document.createElement('div');
      el.innerHTML = renderPub(p);
      el.firstElementChild.style.animationDelay = `${i * 0.05}s`;
      feed.appendChild(el.firstElementChild);
    });
  } catch (e) {
    feed.innerHTML = `<div class="empty"><p>Error al cargar: ${e.message}</p></div>`;
  }
}

function renderPub(p) {
  const imgs = p.imagenes || [];
  const vids = p.videos   || [];
  let imgsHtml = '';
  if (vids.length) {
    imgsHtml = `<div class="card-video-wrap">
      <video src="/static/${vids[0]}" controls playsinline preload="metadata" class="card-video"></video>
    </div>`;
  } else if (imgs.length) {
    const cls = `n${Math.min(imgs.length, 3)}`;
    imgsHtml = `<div class="card-imagenes ${cls}">
      ${imgs.slice(0,3).map(img =>
        `<img src="/static/${img}" loading="lazy" class="img-lightbox" data-src="/static/${img}" style="cursor:zoom-in" />`
      ).join('')}
    </div>`;
  }

  const avatarHtml = p.autor_foto
    ? `<img src="/static/${p.autor_foto}" class="avatar" />`
    : `<div class="avatar">👤</div>`;

  return `
    <div class="card ${p.destacada ? 'card-destacada' : ''}" id="pub-${p.id}">
      <div class="card-header">
        ${avatarHtml}
        <div class="card-meta">
          <div class="card-autor">${escapeHtml(p.autor || p.telefono)}</div>
          <div class="card-fecha">
            ${p.comunidad ? `<span class="card-comunidad">📍 ${escapeHtml(p.comunidad)}</span> · ` : ''}${timeAgo(p.fecha)}
          </div>
        </div>
        ${p.destacada ? '<span class="badge-destacada">⭐ Destacado</span>' : ''}
        <span class="card-badge">🏷 Venta</span>
      </div>
      <div class="card-contenido" style="cursor:pointer" onclick="location.href='/publicacion/${p.id}'">${escapeHtml(p.contenido)}</div>
      ${p.precio ? `<div class="card-precio">$${escapeHtml(String(p.precio))}</div>` : ''}
      ${imgsHtml}
      <div class="card-acciones">
        <button class="btn-accion" id="like-btn-${p.id}" onclick="reaccionar(${p.id})">
          <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <path d="M20.84 4.61a5.5 5.5 0 00-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 00-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 000-7.78z"/>
          </svg>
          <span id="likes-${p.id}">${p.total_likes}</span>
        </button>
        <button class="btn-accion" onclick="toggleComentarios(${p.id})">
          <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>
          </svg>
          <span id="coms-count-${p.id}">${p.total_comentarios}</span>
        </button>
        <button class="btn-accion btn-wa" onclick="contactarWA('${p.tel_autor || p.telefono}', ${p.id}, \`${escapeHtml(p.contenido).slice(0,60)}\`)">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
            <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347z"/>
            <path d="M12 0C5.373 0 0 5.373 0 12c0 2.123.554 4.118 1.528 5.847L.057 23.882l6.198-1.448A11.945 11.945 0 0012 24c6.627 0 12-5.373 12-12S18.627 0 12 0zm0 21.894a9.878 9.878 0 01-5.031-1.378l-.361-.214-3.681.861.878-3.596-.235-.369A9.865 9.865 0 012.106 12C2.106 6.58 6.58 2.106 12 2.106c5.421 0 9.894 4.474 9.894 9.894 0 5.421-4.473 9.894-9.894 9.894z"/>
          </svg>
          Contactar
        </button>
      </div>
      <div class="comentarios-box" id="coms-${p.id}"></div>
    </div>`;
}

/* ===== Modal nueva publicación ===== */
async function abrirModal() {
  if (!SESION_ACTIVA) { pedirLogin(); return; }
  $('modal-overlay').classList.add('open');
  setTimeout(() => $('nuevo-contenido')?.focus(), 300);
  try {
    const data = await api('/api/auth/puntos');
    const restantes = 2 - data.pubs_hoy;
    const ind = $('modal-limit-ind');
    if (ind) {
      ind.textContent = restantes > 0
        ? `Puedes publicar ${restantes} vez${restantes > 1 ? 'es' : ''} más hoy`
        : '⏳ Llegaste al límite de hoy';
      ind.style.color = restantes > 0 ? 'var(--success)' : 'var(--error)';
    }
  } catch(_) {}
}

function cerrarModal(e) {
  if (e && e.target !== $('modal-overlay')) return;
  $('modal-overlay').classList.remove('open');
  $('nuevo-contenido').value = '';
  $('preview-imgs').innerHTML = '';
  $('nuevo-imgs').value = '';
  if ($('nuevo-vid'))    $('nuevo-vid').value = '';
  if ($('nuevo-precio')) $('nuevo-precio').value = '';
}

function previewMedia(input, tipo) {
  const wrap = $('preview-imgs');
  if (tipo === 'video') {
    wrap.innerHTML = '';
    const file = input.files[0];
    if (!file) return;
    const MAX_VID = 100 * 1024 * 1024;
    if (file.size > MAX_VID) {
      toast(`⚠️ El video supera el límite de 100 MB (pesa ${(file.size/1024/1024).toFixed(1)} MB)`);
      input.value = ''; return;
    }
    const url = URL.createObjectURL(file);
    const vid = document.createElement('video');
    vid.src = url; vid.controls = true;
    vid.style.cssText = 'width:100%;border-radius:8px;max-height:180px;margin-top:.5rem';
    wrap.appendChild(vid);
  } else {
    wrap.innerHTML = '';
    const MAX_IMG = 10 * 1024 * 1024;
    Array.from(input.files).slice(0, 4).forEach(file => {
      if (file.size > MAX_IMG) {
        toast(`⚠️ "${file.name}" supera el límite de 10 MB`);
        input.value = ''; return;
      }
      const reader = new FileReader();
      reader.onload = e => {
        const img = document.createElement('img');
        img.src = e.target.result;
        wrap.appendChild(img);
      };
      reader.readAsDataURL(file);
    });
  }
}

async function publicar() {
  if (!SESION_ACTIVA) { pedirLogin(); return; }
  const textarea  = $('nuevo-contenido');
  const contenido = textarea?.value.trim();
  if (!contenido) { toast('✏️ Escribe algo primero'); return; }

  const btn = $('btn-pub');
  btn.classList.add('loading'); btn.disabled = true;

  const precio   = $('nuevo-precio')?.value.trim();
  const formData = new FormData();
  formData.append('contenido', contenido);
  if (precio) formData.append('precio', precio);

  const imgs = $('nuevo-imgs');
  if (imgs?.files.length) Array.from(imgs.files).forEach(f => formData.append('imagenes', f));
  const vid = $('nuevo-vid');
  if (vid?.files.length) formData.append('videos', vid.files[0]);

  try {
    await fetch('/api/publicaciones', { method: 'POST', body: formData, credentials: 'include' });
    cerrarModal();
    toast('✅ Publicación creada');
    cargarPublicaciones();
  } catch (e) {
    toast('Error: ' + e.message);
  } finally {
    btn.classList.remove('loading'); btn.disabled = false;
  }
}

/* ===== Likes ===== */
async function reaccionar(pubId) {
  if (!SESION_ACTIVA) { pedirLogin(); return; }
  try {
    const res = await api('/api/likes', 'POST', { publicacion_id: pubId, reaccion: 'like' });
    const el  = $(`likes-${pubId}`);
    const btn = $(`like-btn-${pubId}`);
    if (el) {
      const n = parseInt(el.textContent) || 0;
      el.textContent = res.accion === 'quitado' ? Math.max(0, n - 1) : n + 1;
    }
    btn?.classList.toggle('liked', res.accion !== 'quitado');
  } catch (e) {
    toast(e.message);
  }
}

/* ===== Comentarios ===== */
async function toggleComentarios(pubId) {
  const box = $(`coms-${pubId}`);
  if (!box) return;
  const open = box.classList.toggle('open');
  if (open && !box.dataset.loaded) await cargarComentarios(pubId);
}

async function cargarComentarios(pubId) {
  const box = $(`coms-${pubId}`);
  box.innerHTML = `<div class="spinner-feed"><span></span><span></span><span></span></div>`;
  try {
    const coms = await api(`/api/comentarios/${pubId}`);
    box.dataset.loaded = '1';

    const inputHtml = SESION_ACTIVA
      ? `<div class="com-input-row">
           <input id="com-input-${pubId}" type="text" placeholder="Escribe un comentario..."
                  onkeydown="if(event.key==='Enter') enviarComentario(${pubId})"/>
           <button class="com-send" onclick="enviarComentario(${pubId})">Enviar</button>
         </div>`
      : `<button class="com-login-btn" onclick="pedirLogin()">
           Inicia sesión para comentar
         </button>`;

    box.innerHTML = `
      <div style="padding:.75rem 0;border-top:1px solid #f1f5f9">
        ${coms.length ? coms.map(c => `
          <div class="comentario-item">
            <div class="com-avatar">👤</div>
            <div class="com-body">
              <div class="com-autor">${escapeHtml(c.autor || c.telefono)}</div>
              <div class="com-texto">${escapeHtml(c.comentario)}</div>
              <div class="com-fecha">${timeAgo(c.fecha)}</div>
            </div>
          </div>`).join('')
          : '<p style="color:var(--muted);font-size:.82rem;margin-bottom:.5rem">Sin comentarios aún</p>'}
        ${inputHtml}
      </div>`;
  } catch(e) {
    box.innerHTML = `<p style="color:var(--error);font-size:.82rem">${e.message}</p>`;
  }
}

async function enviarComentario(pubId) {
  if (!SESION_ACTIVA) { pedirLogin(); return; }
  const input = $(`com-input-${pubId}`);
  const texto = input?.value.trim();
  if (!texto) return;
  input.disabled = true;
  try {
    await api('/api/comentarios', 'POST', { publicacion_id: pubId, comentario: texto });
    const box = $(`coms-${pubId}`);
    delete box.dataset.loaded;
    await cargarComentarios(pubId);
    const cnt = $(`coms-count-${pubId}`);
    if (cnt) cnt.textContent = parseInt(cnt.textContent || 0) + 1;
  } catch(e) {
    toast(e.message);
  } finally {
    input.disabled = false;
    input?.focus();
  }
}

/* ===== WhatsApp ===== */
function contactarWA(telefono, pubId, descripcion) {
  let tel = telefono.replace(/[\s\-\(\)]/g, '');
  if (tel.startsWith('0')) tel = '52' + tel.slice(1);
  else if (!tel.startsWith('52') && tel.length === 10) tel = '52' + tel;
  const url = location.origin + '/publicacion/' + pubId;
  const msg = encodeURIComponent(`Hola! Vi tu publicación en Ventas Locales José Azueta:\n*${descripcion}*\n${url}\n\n¿Sigue disponible?`);
  window.open(`https://wa.me/${tel}?text=${msg}`, '_blank');
}

/* ===== Compartir ===== */
function compartir(pubId) {
  const url = `${location.origin}/publicacion/${pubId}`;
  if (navigator.share) {
    navigator.share({ title: 'Ventas Locales José Azueta', url });
  } else {
    navigator.clipboard.writeText(url).then(() => toast('🔗 Enlace copiado'));
  }
}

/* ===== Lightbox ===== */
function verImagen(src) {
  const lb = document.createElement('div');
  lb.className = 'lightbox';
  lb.innerHTML = `
    <img src="${src}" />
    <button onclick="this.parentElement.remove()"
      style="position:absolute;top:1rem;right:1rem;background:rgba(0,0,0,.6);
             border:none;border-radius:50%;color:#fff;width:36px;height:36px;
             font-size:1.1rem;cursor:pointer;display:flex;align-items:center;justify-content:center">✕</button>`;
  lb.onclick = e => { if (e.target === lb) lb.remove(); };
  document.body.appendChild(lb);
}
window.abrirLightbox = verImagen;

document.addEventListener('click', e => {
  const img = e.target.closest('.img-lightbox');
  if (img) verImagen(img.dataset.src || img.src);
});

/* ===== Badge notificaciones ===== */
async function actualizarBadge() {
  if (!SESION_ACTIVA) return;
  try {
    const data  = await api('/api/notificaciones/no-leidas');
    const badge = $('notif-count');
    if (badge) {
      if (data.no_leidas > 0) {
        badge.textContent = data.no_leidas > 9 ? '9+' : data.no_leidas;
        badge.style.display = 'flex';
      } else {
        badge.style.display = 'none';
      }
    }
  } catch (_) {}
}

/* ===== Escape key ===== */
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    $('modal-overlay')?.classList.remove('open');
    $('modal-login-req')?.classList.remove('open');
  }
});

/* ===== Init ===== */
document.addEventListener('DOMContentLoaded', async () => {
  await verificarSesion();
  cargarPublicaciones();
});
