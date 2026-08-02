const artworks = document.querySelectorAll('.artwork');
if ('IntersectionObserver' in window) {
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (e.isIntersecting) {
        e.target.classList.add('is-in');
        io.unobserve(e.target);
      }
    }
  }, { threshold: 0.08, rootMargin: '0px 0px -20px 0px' });
  artworks.forEach((el) => io.observe(el));
} else {
  artworks.forEach((el) => el.classList.add('is-in'));
}

const lightbox = document.getElementById('lightbox');
const lightboxImg = lightbox && lightbox.querySelector('.lightbox__img');
const lightboxCaption = lightbox && lightbox.querySelector('.lightbox__caption');
const lightboxClose = lightbox && lightbox.querySelector('.lightbox__close');
const lightboxPrev = lightbox && lightbox.querySelector('.lightbox__nav--prev');
const lightboxNext = lightbox && lightbox.querySelector('.lightbox__nav--next');

const lightboxItems = [...document.querySelectorAll('[data-lightbox]')].map((btn) => ({
  src: btn.dataset.lightbox,
  caption: btn.dataset.caption || '',
}));
let lightboxIndex = -1;

function updateLightboxNav() {
  if (!lightboxPrev || !lightboxNext) return;
  const hasPrev = lightboxIndex > 0;
  const hasNext = lightboxIndex < lightboxItems.length - 1;
  lightboxPrev.hidden = !hasPrev;
  lightboxNext.hidden = !hasNext;
}

function showLightboxAt(index) {
  if (!lightbox || !lightboxImg || index < 0 || index >= lightboxItems.length) return;
  const item = lightboxItems[index];
  lightboxIndex = index;
  lightboxImg.src = item.src;
  lightboxImg.alt = item.caption;
  if (lightboxCaption) lightboxCaption.textContent = item.caption;
  lightbox.hidden = false;
  lightbox.setAttribute('aria-hidden', 'false');
  document.body.style.overflow = 'hidden';
  updateLightboxNav();
}

function openLightbox(src, caption) {
  const index = lightboxItems.findIndex((i) => i.src === src);
  showLightboxAt(index >= 0 ? index : 0);
}

function closeLightbox() {
  if (!lightbox) return;
  lightbox.hidden = true;
  lightbox.setAttribute('aria-hidden', 'true');
  lightboxIndex = -1;
  if (lightboxImg) lightboxImg.src = '';
  document.body.style.overflow = '';
  if (lightboxPrev) lightboxPrev.hidden = true;
  if (lightboxNext) lightboxNext.hidden = true;
}

function goLightboxPrev() {
  showLightboxAt(lightboxIndex - 1);
}

function goLightboxNext() {
  showLightboxAt(lightboxIndex + 1);
}

document.querySelectorAll('[data-lightbox]').forEach((btn) => {
  btn.addEventListener('click', () => {
    openLightbox(btn.dataset.lightbox, btn.dataset.caption || '');
  });
});

if (lightboxClose) lightboxClose.addEventListener('click', closeLightbox);
if (lightboxPrev) {
  lightboxPrev.addEventListener('click', (e) => {
    e.stopPropagation();
    goLightboxPrev();
  });
}
if (lightboxNext) {
  lightboxNext.addEventListener('click', (e) => {
    e.stopPropagation();
    goLightboxNext();
  });
}
if (lightbox) {
  lightbox.addEventListener('click', (e) => {
    if (e.target === lightbox) closeLightbox();
  });

  let touchStartX = 0;
  lightbox.addEventListener('touchstart', (e) => {
    touchStartX = e.changedTouches[0].screenX;
  }, { passive: true });
  lightbox.addEventListener('touchend', (e) => {
    if (lightbox.hidden) return;
    const deltaX = e.changedTouches[0].screenX - touchStartX;
    if (Math.abs(deltaX) < 50) return;
    if (deltaX > 0) goLightboxPrev();
    else goLightboxNext();
  }, { passive: true });
}
document.addEventListener('keydown', (e) => {
  if (!lightbox || lightbox.hidden) return;
  if (e.key === 'Escape') {
    closeLightbox();
  } else if (e.key === 'ArrowLeft') {
    e.preventDefault();
    goLightboxPrev();
  } else if (e.key === 'ArrowRight') {
    e.preventDefault();
    goLightboxNext();
  }
});
