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

function openLightbox(src, caption) {
  if (!lightbox || !lightboxImg) return;
  lightboxImg.src = src;
  lightboxImg.alt = caption || '';
  if (lightboxCaption) lightboxCaption.textContent = caption || '';
  lightbox.hidden = false;
  lightbox.setAttribute('aria-hidden', 'false');
  document.body.style.overflow = 'hidden';
}

function closeLightbox() {
  if (!lightbox) return;
  lightbox.hidden = true;
  lightbox.setAttribute('aria-hidden', 'true');
  if (lightboxImg) lightboxImg.src = '';
  document.body.style.overflow = '';
}

document.querySelectorAll('[data-lightbox]').forEach((btn) => {
  btn.addEventListener('click', () => {
    openLightbox(btn.dataset.lightbox, btn.dataset.caption || '');
  });
});

if (lightboxClose) lightboxClose.addEventListener('click', closeLightbox);
if (lightbox) {
  lightbox.addEventListener('click', (e) => {
    if (e.target === lightbox) closeLightbox();
  });
}
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && lightbox && !lightbox.hidden) closeLightbox();
});
