const shots = document.querySelectorAll('.shot');
if ('IntersectionObserver' in window) {
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (e.isIntersecting) {
        e.target.classList.add('is-in');
        io.unobserve(e.target);
      }
    }
  }, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });
  shots.forEach((el) => io.observe(el));
} else {
  shots.forEach((el) => el.classList.add('is-in'));
}
